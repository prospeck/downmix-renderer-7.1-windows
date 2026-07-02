from __future__ import annotations

import os
import unittest

import numpy as np

from downmix_renderer.constants import MAX_INPUT_CHANNELS, SAMPLE_RATE
from downmix_renderer.dsp import DRY_DELAY_SAMPLES, DownmixProcessor
from downmix_renderer.native_audio import NativeAudioBackend, NativeBackendUnavailable, native_backend_available
from downmix_renderer.peq import build_runtime_config


@unittest.skipUnless(os.name == "nt" and native_backend_available(), "native backend is unavailable")
class NativeDspTrimTests(unittest.TestCase):
    def make_backend(self) -> NativeAudioBackend:
        try:
            backend = NativeAudioBackend()
        except NativeBackendUnavailable as exc:
            self.skipTest(str(exc))
        except OSError as exc:
            self.skipTest(str(exc))
        self.addCleanup(backend.close)
        if not getattr(backend, "_has_channel_trim", False):
            self.skipTest("native trim API is not exported")
        return backend

    def assert_native_matches_python(
        self,
        backend: NativeAudioBackend,
        python: DownmixProcessor,
        data: np.ndarray,
        *,
        atol: float = 2e-5,
    ) -> None:
        native_out = backend.processor.process(data)
        python_out = python.process(data)
        np.testing.assert_allclose(native_out, python_out, rtol=0, atol=atol)

    def test_native_trim_matches_python_reference(self) -> None:
        backend = self.make_backend()
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)

        native.set_preamp_db(0)
        native.set_channel_trim_db(-2.5, -6.0)
        python.set_channel_trim_db(-2.5, -6.0)

        data = np.zeros((DRY_DELAY_SAMPLES + 32, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.5
        data[:, 1] = 0.25

        native_out = native.process(data)
        python_out = python.process(data)

        np.testing.assert_allclose(native_out, python_out, rtol=0, atol=2e-6)
        snapshot = native.snapshot()
        self.assertAlmostEqual(snapshot.trim_left_db, -2.5, places=5)
        self.assertAlmostEqual(snapshot.trim_right_db, -6.0, places=5)

    def test_native_peq_and_lr_swap_match_python_reference(self) -> None:
        backend = self.make_backend()
        if not getattr(backend, "_has_peq_config", False):
            self.skipTest("native PEQ API is not exported")
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)
        config, _ = build_runtime_config(
            global_text="Preamp: -3 dB\nFilter 1: ON PK Fc 1000 Hz Gain 3 dB Q 0.7",
            global_enabled=True,
            speaker_text="CH:0\nPreamp: -6 dB\nCH:1\nPreamp: -2 dB",
            speaker_enabled=True,
            lr_swap_enabled=True,
            sample_rate=SAMPLE_RATE,
        )

        native.set_preamp_db(0)
        python.set_preamp_db(0)
        native.set_peq_config(config)
        python.set_peq_config(config)

        data = np.zeros((DRY_DELAY_SAMPLES + 512, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = np.linspace(-0.25, 0.25, data.shape[0], dtype=np.float32)
        data[:, 1] = 0.125

        self.assert_native_matches_python(backend, python, data)

    def test_native_limiter_matches_python_reference(self) -> None:
        backend = self.make_backend()
        native = backend.processor
        python = DownmixProcessor(preamp_db=12)

        native.set_preamp_db(12)
        data = np.zeros((DRY_DELAY_SAMPLES + 128, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 1.0
        data[:, 1] = 1.0

        self.assert_native_matches_python(backend, python, data)
        self.assertLess(native.snapshot().limiter_gain, 1.0)

    def test_native_sound_enhancer_matches_python_reference(self) -> None:
        backend = self.make_backend()
        self.assertTrue(getattr(backend, "_has_sound_enhancer", False))
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)

        native.set_preamp_db(0)
        native.set_sound_enhancer_enabled(True)
        python.set_sound_enhancer_enabled(True)

        frames = DRY_DELAY_SAMPLES + 512
        phase = np.linspace(0.0, 8.0 * np.pi, frames, dtype=np.float64)
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = (0.06 * np.sin(phase)).astype(np.float32)
        data[:, 1] = (0.06 * np.sin(phase + 0.25)).astype(np.float32)

        self.assert_native_matches_python(backend, python, data, atol=3e-5)
        self.assertTrue(native.snapshot().sound_enhancer_enabled)
        self.assertLessEqual(float(np.max(np.abs(native.process(data)))), 0.8914 + 1e-6)

    def test_native_sound_enhancer_matches_python_true_peak_guard(self) -> None:
        backend = self.make_backend()
        self.assertTrue(getattr(backend, "_has_sound_enhancer", False))
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)

        native.set_preamp_db(0)
        native.set_sound_enhancer_enabled(True)
        python.set_sound_enhancer_enabled(True)

        frames = DRY_DELAY_SAMPLES + 96
        pattern = np.array([0.86956584, -0.8674835, -0.8719893, 0.7874929], dtype=np.float32)
        repeated = np.resize(pattern, frames)
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = repeated
        data[:, 1] = -repeated

        native_out = native.process(data)
        python_out = python.process(data)

        np.testing.assert_allclose(native_out, python_out, rtol=0, atol=4e-5)
        self.assertLessEqual(
            python._estimate_true_peak_stereo(native_out, native_out.shape[0]),
            0.8914 + 1e-6,
        )
        self.assertTrue(native.snapshot().clipping)

    def test_native_sample_rate_matches_python_reference(self) -> None:
        backend = self.make_backend()
        if not getattr(backend, "_has_sample_rate", False):
            self.skipTest("native sample-rate API is not exported")
        native = backend.processor
        python = DownmixProcessor(preamp_db=0, sample_rate=192000)
        scaled_delay = DRY_DELAY_SAMPLES * 4

        native.set_preamp_db(0)
        native.set_sample_rate(192000)
        data = np.zeros((scaled_delay + 128, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[0, 0] = 1.0

        native_out = native.process(data)
        python_out = python.process(data)
        np.testing.assert_allclose(native_out, python_out, rtol=0, atol=2e-5)
        self.assertEqual(float(native_out[scaled_delay - 1, 0]), 0.0)
        self.assertGreater(float(native_out[scaled_delay, 0]), 0.99)

    def test_native_non_finite_input_is_sanitized(self) -> None:
        backend = self.make_backend()
        native = backend.processor
        native.set_preamp_db(0)
        data = np.zeros((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[0, 0] = np.nan
        data[1, 1] = np.inf
        data[2, 3] = -np.inf
        data[:, 4] = 0.25

        out = native.process(data)
        snapshot = native.snapshot()

        self.assertTrue(np.all(np.isfinite(out)))
        self.assertTrue(np.all(np.isfinite(snapshot.raw_channel_levels)))
        self.assertTrue(np.all(np.isfinite(snapshot.channel_levels)))
        self.assertTrue(np.isfinite(snapshot.limiter_gain))

    def test_native_layout_mapping_and_upmix_match_python_reference(self) -> None:
        backend = self.make_backend()
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)

        native.set_preamp_db(0)
        native.set_input_layout("windows_7_1")
        native.set_monitor_layout("sharur_9_1_6")
        native.set_upmix_9_1_6_enabled(True)
        python.set_input_layout("windows_7_1")
        python.set_monitor_layout("sharur_9_1_6")
        python.set_upmix_9_1_6_enabled(True)

        data = np.zeros((DRY_DELAY_SAMPLES + 256, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.3
        data[:, 1] = -0.2
        data[:, 6] = 0.1
        data[:, 7] = -0.1

        self.assert_native_matches_python(backend, python, data, atol=4e-5)
        self.assertTrue(native.snapshot().upmix_9_1_6_enabled)

    def test_native_9_1_6_upmix_side_fill_matches_python_reference(self) -> None:
        backend = self.make_backend()
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)

        native.set_preamp_db(0)
        native.set_input_layout("windows_7_1")
        native.set_monitor_layout("sharur_9_1_6")
        native.set_upmix_9_1_6_enabled(True)
        python.set_input_layout("windows_7_1")
        python.set_monitor_layout("sharur_9_1_6")
        python.set_upmix_9_1_6_enabled(True)

        frames = DRY_DELAY_SAMPLES + 512
        phase = np.linspace(0.0, 8.0 * np.pi, frames, dtype=np.float64)
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 4] = (0.32 * np.sin(phase)).astype(np.float32)
        data[:, 5] = (0.27 * np.sin(phase + 0.8)).astype(np.float32)

        self.assert_native_matches_python(backend, python, data, atol=4e-5)
        snapshot = native.snapshot()
        self.assertTrue(snapshot.upmix_9_1_6_active)
        self.assertGreater(float(snapshot.channel_levels[8]), 0.02)
        self.assertGreater(float(snapshot.channel_levels[9]), 0.02)

    def test_native_9_1_6_upmix_center_only_gate_matches_python_reference(self) -> None:
        backend = self.make_backend()
        native = backend.processor
        python = DownmixProcessor(preamp_db=0)

        native.set_preamp_db(0)
        native.set_input_layout("windows_7_1")
        native.set_monitor_layout("sharur_9_1_6")
        native.set_upmix_9_1_6_enabled(True)
        python.set_input_layout("windows_7_1")
        python.set_monitor_layout("sharur_9_1_6")
        python.set_upmix_9_1_6_enabled(True)

        frames = DRY_DELAY_SAMPLES + 512
        phase = np.linspace(0.0, 8.0 * np.pi, frames, dtype=np.float64)
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 2] = (0.40 * np.sin(phase)).astype(np.float32)

        self.assert_native_matches_python(backend, python, data, atol=4e-5)
        snapshot = native.snapshot()
        self.assertFalse(snapshot.upmix_9_1_6_active)
        self.assertLessEqual(float(np.max(snapshot.channel_levels[6:16])), 1e-4)


if __name__ == "__main__":
    unittest.main()
