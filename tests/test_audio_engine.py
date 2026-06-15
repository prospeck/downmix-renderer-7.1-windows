from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from downmix_renderer.audio_engine import (
    LOW_LATENCY_BLOCK_SIZE,
    ULTRA_BLOCK_SIZE,
    AudioEngine,
    OutputKeepAwake,
    _normalize_sample_rate_mode,
    _normalize_stream_profile,
    _profile_start_candidates,
    _resolve_sample_rate,
    _scaled_stream_block_size,
    _stream_settings,
)
from downmix_renderer.constants import MAX_INPUT_CHANNELS, OUTPUT_CHANNELS, SAMPLE_RATE
from downmix_renderer.devices import AudioDevice
from downmix_renderer.dsp import DspSnapshot
from downmix_renderer.native_audio import NativeBackendUnavailable


def fake_device(mode: str, endpoint_id: str | None = None, samplerate: int = 48000) -> AudioDevice:
    return AudioDevice(
        id=1 if mode == "input" else 2,
        name="Device",
        hostapi="Windows WASAPI",
        max_input_channels=16 if mode == "input" else 0,
        max_output_channels=0 if mode == "input" else 2,
        default_samplerate=samplerate,
        default_low_input_latency=0.003 if mode == "input" else 0.0,
        default_low_output_latency=0.0 if mode == "input" else 0.003,
        default_high_input_latency=0.010 if mode == "input" else 0.0,
        default_high_output_latency=0.0 if mode == "input" else 0.010,
        native_endpoint_id=endpoint_id,
        native_direction=mode,
    )


class AudioEngineSettingsTests(unittest.TestCase):
    def test_raw_stream_kwargs_use_low_latency_path(self) -> None:
        opened: list[dict[str, object]] = []

        class FakeStream:
            def __init__(self, **kwargs) -> None:
                opened.append(kwargs)
                self.cpu_load = 0.0
                self.latency = (0.0, 0.0)

            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        with patch("downmix_renderer.audio_engine.sd.Stream", FakeStream):
            engine = AudioEngine(backend="python")
            engine.start(fake_device("input"), fake_device("output"), "raw")
            snapshot = engine.snapshot()
            engine.close()

        self.assertEqual(len(opened), 1)
        kwargs = opened[0]
        self.assertEqual(kwargs["samplerate"], SAMPLE_RATE)
        self.assertEqual(kwargs["blocksize"], LOW_LATENCY_BLOCK_SIZE)
        self.assertEqual(kwargs["channels"], (MAX_INPUT_CHANNELS, OUTPUT_CHANNELS))
        self.assertEqual(kwargs["device"], (1, 2))
        self.assertEqual(kwargs["dtype"], "float32")
        self.assertEqual(kwargs["latency"], "low")
        self.assertIn("callback", kwargs)
        self.assertNotIn("clip_off", kwargs)
        self.assertNotIn("dither_off", kwargs)
        self.assertEqual(snapshot.stream_profile, "raw")

    def test_manual_sample_rate_mode_is_used_for_python_stream(self) -> None:
        opened: list[dict[str, object]] = []

        class FakeStream:
            def __init__(self, **kwargs) -> None:
                opened.append(kwargs)
                self.cpu_load = 0.0
                self.latency = (0.0, 0.0)

            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        with patch("downmix_renderer.audio_engine.sd.Stream", FakeStream):
            engine = AudioEngine(backend="python")
            engine.start(fake_device("input"), fake_device("output"), "raw", sample_rate_mode="192000")
            snapshot = engine.snapshot()
            engine.close()

        self.assertEqual(opened[0]["samplerate"], 192000)
        self.assertEqual(opened[0]["blocksize"], 1024)
        self.assertEqual(snapshot.sample_rate, 192000)
        self.assertEqual(snapshot.sample_rate_mode, "192000")

    def test_auto_sample_rate_prefers_selected_input_default_rate(self) -> None:
        input_device = fake_device("input", samplerate=192000)
        output_device = fake_device("output", samplerate=96000)

        self.assertEqual(_normalize_sample_rate_mode("96 kHz"), "96000")
        self.assertEqual(_normalize_sample_rate_mode("bad"), "auto")
        self.assertEqual(_resolve_sample_rate("auto", input_device, output_device), 192000)
        self.assertEqual(_resolve_sample_rate("96000", input_device, output_device), 96000)

    def test_fixed_mode_stream_settings(self) -> None:
        self.assertEqual(_stream_settings("normal"), (ULTRA_BLOCK_SIZE, "low"))
        self.assertEqual(_stream_settings("balanced"), (ULTRA_BLOCK_SIZE, "low"))
        self.assertEqual(_stream_settings("low_latency"), (LOW_LATENCY_BLOCK_SIZE, "low"))
        self.assertEqual(_stream_settings("raw"), (LOW_LATENCY_BLOCK_SIZE, "low"))
        self.assertEqual(_stream_settings("ultra"), (ULTRA_BLOCK_SIZE, "low"))

    def test_stream_block_size_scales_with_sample_rate_to_preserve_time_budget(self) -> None:
        self.assertEqual(_scaled_stream_block_size(ULTRA_BLOCK_SIZE, 48000), 128)
        self.assertEqual(_scaled_stream_block_size(ULTRA_BLOCK_SIZE, 96000), 256)
        self.assertEqual(_scaled_stream_block_size(ULTRA_BLOCK_SIZE, 192000), 512)
        self.assertEqual(_stream_settings("ultra", 192000), (512, "low"))
        self.assertEqual(_stream_settings("raw", 192000), (1024, "low"))

    def test_old_profile_names_are_migrated_to_safe_modes(self) -> None:
        self.assertEqual(_normalize_stream_profile("legacy_low"), "raw")
        self.assertEqual(_normalize_stream_profile("low_latency"), "raw")
        self.assertEqual(_normalize_stream_profile("low"), "raw")
        self.assertEqual(_normalize_stream_profile("raw_mode"), "raw")
        self.assertEqual(_normalize_stream_profile("balanced"), "ultra")
        self.assertEqual(_normalize_stream_profile("normal"), "ultra")
        self.assertEqual(_normalize_stream_profile("ultra_mode"), "ultra")
        self.assertEqual(_normalize_stream_profile("safe"), "ultra")
        self.assertEqual(_normalize_stream_profile("stable"), "ultra")

    def test_start_candidates_use_ultra_to_raw_only(self) -> None:
        self.assertEqual(_profile_start_candidates("low_latency"), ("raw",))
        self.assertEqual(_profile_start_candidates("raw"), ("raw",))
        self.assertEqual(_profile_start_candidates("balanced"), ("ultra", "raw"))
        self.assertEqual(_profile_start_candidates("ultra"), ("ultra", "raw"))
        self.assertEqual(_profile_start_candidates("normal"), ("ultra", "raw"))

    def test_ultra_start_falls_back_to_raw_when_stream_cannot_open(self) -> None:
        opened_blocks: list[int] = []

        class FakeStream:
            def __init__(self, **kwargs) -> None:
                opened_blocks.append(int(kwargs["blocksize"]))
                if len(opened_blocks) == 1:
                    raise RuntimeError("device rejected low buffers")
                self.cpu_load = 0.0
                self.latency = kwargs["latency"]

            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        with patch("downmix_renderer.audio_engine.sd.Stream", FakeStream):
            engine = AudioEngine(backend="python")
            engine.start(fake_device("input"), fake_device("output"), "ultra")
            snapshot = engine.snapshot()
            engine.close()

        self.assertEqual(opened_blocks, [ULTRA_BLOCK_SIZE, LOW_LATENCY_BLOCK_SIZE])
        self.assertEqual(snapshot.stream_profile, "raw")
        self.assertTrue(snapshot.running)

    def test_raw_start_does_not_fall_back_to_removed_modes(self) -> None:
        opened_blocks: list[int] = []

        class FakeStream:
            def __init__(self, **kwargs) -> None:
                opened_blocks.append(int(kwargs["blocksize"]))
                raise RuntimeError("raw device rejected")

            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        with patch("downmix_renderer.audio_engine.sd.Stream", FakeStream):
            engine = AudioEngine(backend="python")
            with self.assertRaisesRegex(RuntimeError, "Unable to start WASAPI stream"):
                engine.start(fake_device("input"), fake_device("output"), "raw")
            engine.close()

        self.assertEqual(opened_blocks, [LOW_LATENCY_BLOCK_SIZE])

    def test_python_callback_updates_liveness_counters(self) -> None:
        class FakeProcessor:
            def set_master_volume(self, scalar: float, muted: bool = False) -> None:
                return None

            def process(self, indata, outdata) -> None:
                outdata.fill(0.0)

            def snapshot(self) -> DspSnapshot:
                zeros = np.zeros(MAX_INPUT_CHANNELS, dtype=np.float32)
                return DspSnapshot(
                    channel_levels=zeros,
                    channel_rms=zeros,
                    raw_channel_levels=zeros,
                    raw_channel_rms=zeros,
                    left_meter=0.0,
                    right_meter=0.0,
                    preamp_db=-14.0,
                    trim_left_db=0.0,
                    trim_right_db=0.0,
                    limiter_gain=1.0,
                    clipping=False,
                    user_volume=1.0,
                    master_volume=1.0,
                    master_muted=False,
                    surround_fill_enabled=False,
                    surround_fill_active=False,
                    upmix_9_1_6_enabled=False,
                    upmix_9_1_6_active=False,
                    channel_sanity_enabled=False,
                    channel_sanity_active=False,
                    sound_enhancer_enabled=False,
                    sound_enhancer_gain=1.0,
                )

        engine = AudioEngine(processor=FakeProcessor(), backend="python")
        indata = np.zeros((128, MAX_INPUT_CHANNELS), dtype=np.float32)
        outdata = np.ones((128, OUTPUT_CHANNELS), dtype=np.float32)

        engine._callback(indata, outdata, 128, None, None)
        snapshot = engine.snapshot()
        engine.close()

        self.assertEqual(snapshot.callback_invocation_count, 1)
        self.assertEqual(snapshot.processed_frame_count, 128)
        self.assertFalse(snapshot.mmcss_registered)
        self.assertTrue(np.all(outdata == 0.0))

    def test_native_backend_start_receives_full_device_descriptors(self) -> None:
        calls: list[tuple[AudioDevice, AudioDevice, str, int, int]] = []

        class FakeProcessor:
            def reset_runtime_state(self) -> None:
                return None

        class FakeNativeBackend:
            def __init__(self) -> None:
                self.processor = FakeProcessor()

            def start(
                self,
                input_device: AudioDevice,
                output_device: AudioDevice,
                stream_profile: str,
                block_size: int,
                sample_rate: int,
            ) -> None:
                calls.append((input_device, output_device, stream_profile, block_size, sample_rate))

            def stop(self) -> None:
                return None

            def close(self) -> None:
                return None

        engine = AudioEngine(backend="python")
        fake_native = FakeNativeBackend()
        engine._native_backend = fake_native
        engine.processor = fake_native.processor
        input_device = fake_device("input", endpoint_id="{input-endpoint}")
        output_device = fake_device("output", endpoint_id="{output-endpoint}")

        engine.start(input_device, output_device, "ultra", sample_rate_mode="192000")
        engine.close()

        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], input_device)
        self.assertIs(calls[0][1], output_device)
        self.assertEqual(calls[0][2], "ultra")
        self.assertEqual(calls[0][3], 512)
        self.assertEqual(calls[0][4], 192000)

    def test_missing_native_backend_falls_back_to_python_processor(self) -> None:
        with patch(
            "downmix_renderer.audio_engine.NativeAudioBackend",
            side_effect=NativeBackendUnavailable("missing dll"),
        ):
            engine = AudioEngine()
            try:
                self.assertIsNone(engine._native_backend)
                self.assertFalse(engine.uses_native_backend)
            finally:
                engine.close()

    def test_keep_output_awake_uses_silent_output_stream_only_while_renderer_is_stopped(self) -> None:
        keep_streams: list[object] = []
        render_streams: list[object] = []

        class FakeOutputStream:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs
                self.started = False
                self.stopped = False
                keep_streams.append(self)

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.stopped = True

            def close(self) -> None:
                return None

        class FakeStream:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs
                self.cpu_load = 0.0
                self.latency = (0.0, 0.0)
                self.started = False
                self.stopped = False
                render_streams.append(self)

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.stopped = True

            def close(self) -> None:
                return None

        with (
            patch("downmix_renderer.audio_engine.sd.OutputStream", FakeOutputStream),
            patch("downmix_renderer.audio_engine.sd.Stream", FakeStream),
        ):
            engine = AudioEngine(backend="python")
            engine.set_keep_output_awake(True, fake_device("output"))
            self.assertTrue(engine.keep_awake.active)
            self.assertEqual(keep_streams[0].kwargs["device"], 2)
            self.assertEqual(keep_streams[0].kwargs["channels"], OUTPUT_CHANNELS)

            engine.start(fake_device("input"), fake_device("output"), "ultra")
            self.assertFalse(engine.keep_awake.active)
            self.assertTrue(keep_streams[0].stopped)
            self.assertTrue(render_streams[0].started)

            engine.stop()
            self.assertFalse(engine.snapshot().running)
            self.assertTrue(engine.keep_awake.active)
            self.assertEqual(len(keep_streams), 2)
            engine.close()

    def test_keep_awake_callback_only_fills_zeros(self) -> None:
        keep_awake = OutputKeepAwake()

        class Buffer:
            def __init__(self) -> None:
                self.value: float | None = None

            def fill(self, value: float) -> None:
                self.value = value

        buffer = Buffer()
        keep_awake._callback(buffer, 128, None, None)

        self.assertEqual(buffer.value, 0.0)

    def test_keep_awake_records_start_error_without_raising(self) -> None:
        keep_awake = OutputKeepAwake()

        class FailingOutputStream:
            def __init__(self, **kwargs) -> None:
                raise RuntimeError("output unavailable")

        with patch("downmix_renderer.audio_engine.sd.OutputStream", FailingOutputStream):
            keep_awake.set_enabled(True, fake_device("output"), renderer_running=False)

        self.assertFalse(keep_awake.active)
        self.assertIn("output unavailable", keep_awake.last_error)


if __name__ == "__main__":
    unittest.main()
