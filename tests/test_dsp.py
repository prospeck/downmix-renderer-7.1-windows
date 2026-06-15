from __future__ import annotations

import unittest

import numpy as np

from downmix_renderer.constants import MAX_INPUT_CHANNELS
from downmix_renderer.constants import CHANNEL_LAYOUTS
from downmix_renderer.dsp import (
    DRY_DELAY_SAMPLES,
    LFE_CHANNEL_INDEX,
    LFE_LOWPASS_CUTOFF_HZ,
    DownmixProcessor,
    _BUTTERWORTH_Q_VALUES,
    db_to_linear,
    estimate_lfe_filter_delay,
)
from downmix_renderer.layouts import SHARUR_9_1_6_LAYOUT, WINDOWS_7_1_LAYOUT, Speaker
from downmix_renderer.matrix import (
    MATRIX,
    MATRIX_LITERAL,
    SHARUR_916_STEREO_MATRIX_LITERAL,
    WINDOWS_71_STEREO_MATRIX_LITERAL,
)
from downmix_renderer.peq import build_runtime_config
from downmix_renderer.routing import fold_sharur_9_1_6_to_windows_7_1


EXPECTED_SHARUR_MATRIX = (
    (1.0, 0.0),
    (0.0, 1.0),
    (0.70710678, 0.70710678),
    (2.26464431, 2.26464431),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (1.0, 0.0),
    (0.0, 1.0),
)


class MatrixTests(unittest.TestCase):
    def test_matrix_literal_matches_exact_sharur_values(self) -> None:
        self.assertEqual(MATRIX_LITERAL, EXPECTED_SHARUR_MATRIX)

    def test_matrix_shape_and_dtype(self) -> None:
        self.assertEqual(MATRIX.shape, (16, 2))
        self.assertEqual(MATRIX.dtype, np.float64)

    def test_separate_windows_and_sharur_matrices_lock_lfe_coefficient(self) -> None:
        self.assertEqual(SHARUR_916_STEREO_MATRIX_LITERAL[3], (2.26464431, 2.26464431))
        self.assertEqual(WINDOWS_71_STEREO_MATRIX_LITERAL[3], (2.26464431, 2.26464431))
        self.assertEqual(len(WINDOWS_71_STEREO_MATRIX_LITERAL), 8)
        self.assertEqual(len(SHARUR_916_STEREO_MATRIX_LITERAL), 16)

    def test_windows_7_1_layout_uses_first_eight_stream_channels(self) -> None:
        layout = CHANNEL_LAYOUTS["windows_7_1"]
        self.assertEqual(tuple(layout["indices"]), tuple(range(8)))
        self.assertEqual(tuple(layout["names"]), ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"))

    def test_sharur_layout_keeps_blc_brc_before_sl_sr(self) -> None:
        self.assertEqual(SHARUR_9_1_6_LAYOUT.index_of(Speaker.BLC), 6)
        self.assertEqual(SHARUR_9_1_6_LAYOUT.index_of(Speaker.BRC), 7)
        self.assertEqual(SHARUR_9_1_6_LAYOUT.index_of(Speaker.SL), 8)
        self.assertEqual(SHARUR_9_1_6_LAYOUT.index_of(Speaker.SR), 9)
        self.assertEqual(WINDOWS_7_1_LAYOUT.index_of(Speaker.SL), 6)
        self.assertEqual(WINDOWS_7_1_LAYOUT.index_of(Speaker.SR), 7)


class DspTests(unittest.TestCase):
    def test_sharur_tuned_filter_and_delay_constants_are_locked(self) -> None:
        self.assertEqual(DRY_DELAY_SAMPLES, 172)
        self.assertEqual(LFE_LOWPASS_CUTOFF_HZ, 125.0)
        self.assertEqual(_BUTTERWORTH_Q_VALUES, (0.541196100146197, 1.3065629648763766))

    def test_smaller_variable_blocks_reuse_preallocated_scratch(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        large = np.zeros((513, MAX_INPUT_CHANNELS), dtype=np.float32)
        small = np.zeros((128, MAX_INPUT_CHANNELS), dtype=np.float32)

        processor.process(large)
        input_buffer = processor._input16
        stereo_buffer = processor._stereo
        processor.process(small)

        self.assertIs(processor._input16, input_buffer)
        self.assertIs(processor._stereo, stereo_buffer)

    def test_front_left_maps_to_left_only(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.25
        out = processor.process(data)
        np.testing.assert_allclose(out[:DRY_DELAY_SAMPLES, 0], 0.0, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.25, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[:, 1], 0.0, rtol=0, atol=1e-7)

    def test_center_maps_to_both_channels_with_exact_sharur_coefficient(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 2] = 0.5
        out = processor.process(data)
        expected = 0.5 * 0.70710678
        np.testing.assert_allclose(out[:DRY_DELAY_SAMPLES], 0.0, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], expected, rtol=0, atol=1e-6)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], expected, rtol=0, atol=1e-6)

    def test_preamp_is_applied_before_output(self) -> None:
        processor = DownmixProcessor(preamp_db=-6)
        data = np.zeros((DRY_DELAY_SAMPLES + 4, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.5
        out = processor.process(data)
        expected = 0.5 * db_to_linear(-6)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], expected, rtol=0, atol=1e-6)

    def test_channel_trim_attenuates_independent_final_channels(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_channel_trim_db(-2.5, -6.0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.5
        data[:, 1] = 0.25

        out = processor.process(data)
        snapshot = processor.snapshot()

        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.5 * db_to_linear(-2.5), rtol=0, atol=1e-6)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], 0.25 * db_to_linear(-6.0), rtol=0, atol=1e-6)
        self.assertEqual(snapshot.trim_left_db, -2.5)
        self.assertEqual(snapshot.trim_right_db, -6.0)

    def test_channel_trim_clamps_without_gain_boost_or_inversion(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.5
        data[:, 1] = 0.25

        processor.set_channel_trim_db(3.0, -99.0)
        out = processor.process(data)

        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.5, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], 0.25 * db_to_linear(-24.0), rtol=0, atol=1e-6)
        self.assertEqual(processor.snapshot().trim_left_db, 0.0)
        self.assertEqual(processor.snapshot().trim_right_db, -24.0)

    def test_channel_trim_runs_before_limiter(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_channel_trim_db(-6.0, -6.0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 1.5
        data[:, 1] = 1.5

        out = processor.process(data)
        snapshot = processor.snapshot()

        expected = 1.5 * db_to_linear(-6.0)
        self.assertFalse(snapshot.clipping)
        self.assertAlmostEqual(snapshot.limiter_gain, 1.0, places=7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:], expected, rtol=0, atol=1e-6)

    def test_global_peq_preamp_runs_after_master_preamp(self) -> None:
        processor = DownmixProcessor(preamp_db=-6)
        config, _ = build_runtime_config(
            global_text="Preamp: -3 dB",
            global_enabled=True,
            speaker_text="",
            speaker_enabled=False,
            lr_swap_enabled=False,
            sample_rate=48000,
        )
        processor.set_peq_config(config)
        data = np.zeros((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.5

        out = processor.process(data)

        expected = 0.5 * db_to_linear(-6) * db_to_linear(-3)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], expected, rtol=0, atol=1e-6)
        np.testing.assert_allclose(out[:, 1], 0.0, rtol=0, atol=1e-7)

    def test_lr_swap_is_physical_stereo_output_swap(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        config, _ = build_runtime_config(
            global_text="",
            global_enabled=False,
            speaker_text="",
            speaker_enabled=False,
            lr_swap_enabled=True,
            sample_rate=48000,
        )
        processor.set_peq_config(config)
        data = np.zeros((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.25

        out = processor.process(data)

        np.testing.assert_allclose(out[:, 0], 0.0, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], 0.25, rtol=0, atol=1e-7)

    def test_speaker_eq_mapping_follows_swap_state(self) -> None:
        speaker_text = """
        CH:0
        Preamp: -6 dB
        CH:1
        Preamp: -12 dB
        """
        data = np.zeros((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.4
        data[:, 1] = 0.2

        normal = DownmixProcessor(preamp_db=0)
        normal_config, _ = build_runtime_config(
            global_text="",
            global_enabled=False,
            speaker_text=speaker_text,
            speaker_enabled=True,
            lr_swap_enabled=False,
            sample_rate=48000,
        )
        normal.set_peq_config(normal_config)
        normal_out = normal.process(data)

        swapped = DownmixProcessor(preamp_db=0)
        swapped_config, _ = build_runtime_config(
            global_text="",
            global_enabled=False,
            speaker_text=speaker_text,
            speaker_enabled=True,
            lr_swap_enabled=True,
            sample_rate=48000,
        )
        swapped.set_peq_config(swapped_config)
        swapped_out = swapped.process(data)

        np.testing.assert_allclose(normal_out[DRY_DELAY_SAMPLES:, 0], 0.4 * db_to_linear(-6), rtol=0, atol=1e-6)
        np.testing.assert_allclose(normal_out[DRY_DELAY_SAMPLES:, 1], 0.2 * db_to_linear(-12), rtol=0, atol=1e-6)
        np.testing.assert_allclose(swapped_out[DRY_DELAY_SAMPLES:, 0], 0.2 * db_to_linear(-12), rtol=0, atol=1e-6)
        np.testing.assert_allclose(swapped_out[DRY_DELAY_SAMPLES:, 1], 0.4 * db_to_linear(-6), rtol=0, atol=1e-6)

    def test_fewer_channels_are_padded(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 4, 2), dtype=np.float32)
        data[:, 0] = 0.2
        data[:, 1] = 0.3
        out = processor.process(data)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.2, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], 0.3, rtol=0, atol=1e-7)

    def test_master_volume_and_mute_are_separate_from_preamp(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_master_volume(0.25, muted=False)
        data = np.zeros((DRY_DELAY_SAMPLES + 4, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.8
        out = processor.process(data)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.2, rtol=0, atol=1e-6)

        processor.set_master_volume(1.0, muted=True)
        out = processor.process(data)
        np.testing.assert_allclose(out, 0.0, rtol=0, atol=1e-7)

    def test_lfe_is_low_pass_filtered_and_not_dry_delayed(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, LFE_CHANNEL_INDEX] = 1.0
        out = processor.process(data)
        self.assertGreater(float(out[0, 0]), 0.0)
        self.assertLess(float(out[0, 0]), MATRIX_LITERAL[LFE_CHANNEL_INDEX][0] * 0.001)
        np.testing.assert_allclose(out[:, 0], out[:, 1], rtol=0, atol=1e-7)

    def test_dry_delay_persists_across_blocks(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        first = np.zeros((100, MAX_INPUT_CHANNELS), dtype=np.float32)
        second = np.zeros((100, MAX_INPUT_CHANNELS), dtype=np.float32)
        first[:, 0] = 0.5

        out_first = processor.process(first)
        out_second = processor.process(second)

        np.testing.assert_allclose(out_first, 0.0, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out_second[:72], 0.0, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out_second[72:, 0], 0.5, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out_second[72:, 1], 0.0, rtol=0, atol=1e-7)

    def test_dry_delay_scales_with_selected_sample_rate(self) -> None:
        processor = DownmixProcessor(preamp_db=0, sample_rate=192000)
        scaled_delay = DRY_DELAY_SAMPLES * 4
        data = np.zeros((scaled_delay + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[0, 0] = 1.0

        out = processor.process(data)

        self.assertEqual(float(out[scaled_delay - 1, 0]), 0.0)
        self.assertGreater(float(out[scaled_delay, 0]), 0.99)

    def test_lfe_filter_state_persists_across_blocks(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        first = np.zeros((100, MAX_INPUT_CHANNELS), dtype=np.float32)
        second = np.zeros((16, MAX_INPUT_CHANNELS), dtype=np.float32)
        first[:, LFE_CHANNEL_INDEX] = 1.0

        processor.process(first)
        out_second = processor.process(second)

        self.assertGreater(float(np.max(np.abs(out_second))), 0.0)

    def test_runtime_reset_clears_delay_and_filter_state(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.5
        data[:, LFE_CHANNEL_INDEX] = 1.0
        processor.process(data)

        processor.reset_runtime_state()
        out = processor.process(np.zeros((16, MAX_INPUT_CHANNELS), dtype=np.float32))

        np.testing.assert_allclose(out, 0.0, rtol=0, atol=1e-8)

    def test_snapshot_reports_raw_channel_peak_and_rms(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 6] = 0.25
        data[:, 7] = 0.5
        processor.process(data)
        snapshot = processor.snapshot()

        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.25, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[7]), 0.5, places=7)
        self.assertAlmostEqual(float(snapshot.channel_rms[6]), 0.25, places=7)
        self.assertAlmostEqual(float(snapshot.channel_rms[7]), 0.5, places=7)

    def test_default_optional_dsp_is_off_and_matches_sharur_baseline(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.20
        data[:, 1] = -0.15
        data[:, 4] = 0.40
        data[:, 5] = -0.30
        data[:, 6] = 0.25
        data[:, 7] = -0.10

        out = processor.process(data)
        snapshot = processor.snapshot()

        self.assertFalse(snapshot.surround_fill_enabled)
        self.assertFalse(snapshot.surround_fill_active)
        self.assertFalse(snapshot.upmix_9_1_6_enabled)
        self.assertFalse(snapshot.upmix_9_1_6_active)
        self.assertFalse(snapshot.channel_sanity_enabled)
        self.assertFalse(snapshot.channel_sanity_active)
        np.testing.assert_allclose(snapshot.channel_levels, snapshot.raw_channel_levels, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[:DRY_DELAY_SAMPLES], 0.0, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.85, rtol=0, atol=1e-7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], -0.55, rtol=0, atol=1e-7)

    def test_surround_fill_splits_5_1_bed_into_7_1_without_boosting_output(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_surround_fill_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 4] = 0.8
        data[:, 5] = 0.6

        out = processor.process(data)
        snapshot = processor.snapshot()

        self.assertTrue(snapshot.surround_fill_enabled)
        self.assertTrue(snapshot.surround_fill_active)
        self.assertAlmostEqual(float(snapshot.raw_channel_levels[4]), 0.8, places=7)
        self.assertAlmostEqual(float(snapshot.raw_channel_levels[6]), 0.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[4]), 0.4, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.4, places=7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.8, rtol=0, atol=1e-6)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 1], 0.6, rtol=0, atol=1e-6)

    def test_surround_fill_can_be_disabled_for_exact_raw_mapping(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_surround_fill_enabled(False)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 4] = 0.8

        out = processor.process(data)
        snapshot = processor.snapshot()

        self.assertFalse(snapshot.surround_fill_enabled)
        self.assertFalse(snapshot.surround_fill_active)
        self.assertAlmostEqual(float(snapshot.channel_levels[4]), 0.8, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.0, places=7)
        np.testing.assert_allclose(out[DRY_DELAY_SAMPLES:, 0], 0.8, rtol=0, atol=1e-6)

    def test_channel_sanity_guard_suppresses_front_correlated_channel_fill(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_channel_sanity_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.4
        data[:, 1] = -0.3
        data[:, 2] = 0.4
        data[:, 4] = 0.4
        data[:, 6] = -0.3

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertTrue(snapshot.channel_sanity_enabled)
        self.assertTrue(snapshot.channel_sanity_active)
        self.assertAlmostEqual(float(snapshot.raw_channel_levels[4]), 0.4, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[4]), 0.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.0, places=7)

    def test_9_1_6_upmix_is_disabled_by_default(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.4
        data[:, 1] = -0.25

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertFalse(snapshot.upmix_9_1_6_enabled)
        self.assertFalse(snapshot.upmix_9_1_6_active)
        self.assertEqual(int(np.count_nonzero(snapshot.channel_levels[8:] > 1e-4)), 0)

    def test_9_1_6_upmix_generates_decorrelated_surround_and_height_field(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        processor.set_upmix_9_1_6_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = np.linspace(-0.35, 0.35, data.shape[0], dtype=np.float32)
        data[:, 1] = np.linspace(0.22, -0.22, data.shape[0], dtype=np.float32)

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertTrue(snapshot.upmix_9_1_6_enabled)
        self.assertTrue(snapshot.upmix_9_1_6_active)
        self.assertGreater(float(snapshot.channel_levels[6]), 0.001)
        self.assertGreater(float(snapshot.channel_levels[10]), 0.001)
        self.assertFalse(np.allclose(snapshot.channel_levels[8:16], snapshot.raw_channel_levels[8:16]))

    def test_windows_sl_maps_to_sharur_sl_not_blc_with_upmix_off(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 6] = 1.0

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertAlmostEqual(float(snapshot.channel_levels[8]), 1.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[7]), 0.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[9]), 0.0, places=7)

    def test_windows_sr_maps_to_sharur_sr_not_brc_with_upmix_off(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 7] = 1.0

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertAlmostEqual(float(snapshot.channel_levels[9]), 1.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[7]), 0.0, places=7)
        self.assertAlmostEqual(float(snapshot.channel_levels[8]), 0.0, places=7)

    def test_windows_sl_is_preserved_at_sharur_index_8_with_upmix_on(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        processor.set_upmix_9_1_6_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 128, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 6] = np.linspace(0.1, 0.9, data.shape[0], dtype=np.float32)

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertGreater(float(snapshot.channel_levels[8]), 0.89)
        self.assertLess(float(snapshot.channel_levels[7]), 0.6)
        self.assertAlmostEqual(float(snapshot.channel_levels[9]), 0.0, places=7)

    def test_windows_sr_is_preserved_at_sharur_index_9_with_upmix_on(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        processor.set_upmix_9_1_6_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 128, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 7] = np.linspace(0.1, 0.9, data.shape[0], dtype=np.float32)

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertGreater(float(snapshot.channel_levels[9]), 0.89)
        self.assertLess(float(snapshot.channel_levels[6]), 0.6)
        self.assertAlmostEqual(float(snapshot.channel_levels[8]), 0.0, places=7)

    def test_real_sharur_blc_is_not_overwritten_by_upmix(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        processor.set_input_layout("sharur_9_1_6")
        processor.set_upmix_9_1_6_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 6] = 0.7

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertFalse(snapshot.upmix_9_1_6_active)
        self.assertAlmostEqual(float(snapshot.channel_levels[6]), 0.7, places=7)

    def test_real_sharur_tfl_is_not_overwritten_by_upmix(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        processor.set_input_layout("sharur_9_1_6")
        processor.set_upmix_9_1_6_enabled(True)
        data = np.zeros((DRY_DELAY_SAMPLES + 8, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 10] = 0.6

        processor.process(data)
        snapshot = processor.snapshot()

        self.assertFalse(snapshot.upmix_9_1_6_active)
        self.assertAlmostEqual(float(snapshot.channel_levels[10]), 0.6, places=7)

    def test_sharur_to_windows_7_1_fold_routes_by_label(self) -> None:
        bus = np.zeros((4, MAX_INPUT_CHANNELS), dtype=np.float32)
        bus[:, 8] = 1.0
        out = fold_sharur_9_1_6_to_windows_7_1(bus)
        self.assertAlmostEqual(float(out[0, 6]), 1.0, places=7)
        self.assertAlmostEqual(float(out[0, 7]), 0.0, places=7)

        bus.fill(0.0)
        bus[:, 6] = 1.0
        out = fold_sharur_9_1_6_to_windows_7_1(bus)
        self.assertAlmostEqual(float(out[0, 4]), 0.5, places=7)
        self.assertAlmostEqual(float(out[0, 6]), 0.0, places=7)

    def test_generated_height_mono_sum_does_not_cancel(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_monitor_layout("sharur_9_1_6")
        processor.set_upmix_9_1_6_enabled(True)
        frames = 2048
        x = np.linspace(0.0, 1.0, frames, dtype=np.float32)
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = np.sin(2 * np.pi * 431 * x) * 0.35
        data[:, 1] = np.cos(2 * np.pi * 389 * x) * 0.30
        data[:, 4] = np.sin(2 * np.pi * 211 * x) * 0.25
        data[:, 5] = np.cos(2 * np.pi * 257 * x) * 0.22
        data[:, 6] = np.sin(2 * np.pi * 173 * x) * 0.20
        data[:, 7] = np.cos(2 * np.pi * 197 * x) * 0.18

        processor.process(data)
        bus = processor._render16[:frames]

        for left, right in ((10, 11), (12, 13), (14, 15)):
            stereo_level = max(float(np.sqrt(np.mean(bus[:, left] ** 2))), float(np.sqrt(np.mean(bus[:, right] ** 2))))
            mono_level = float(np.sqrt(np.mean((bus[:, left] + bus[:, right]) ** 2)))
            self.assertGreater(mono_level, stereo_level * 0.10)

    def test_lfe_delay_debug_uses_locked_filter_without_replacing_live_processing(self) -> None:
        report = estimate_lfe_filter_delay()
        self.assertEqual(report["sample_rate"], 48000.0)
        self.assertEqual(report["expected_dry_delay_samples"], 172.0)
        self.assertIn("measured_peak_samples", report)
        self.assertIn("measured_energy_centroid_samples", report)

    def test_limiter_never_outputs_above_full_scale_on_hot_blocks(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.ones((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        out = processor.process(data)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0 + 1e-6)
        self.assertTrue(processor.snapshot().clipping)

    def test_sound_enhancer_lifts_quiet_material_without_clipping(self) -> None:
        dry = DownmixProcessor(preamp_db=0)
        enhanced = DownmixProcessor(preamp_db=0)
        enhanced.set_sound_enhancer_enabled(True)

        frames = DRY_DELAY_SAMPLES + 512
        phase = np.linspace(0.0, 8.0 * np.pi, frames, dtype=np.float64)
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = (0.055 * np.sin(phase)).astype(np.float32)
        data[:, 1] = (0.055 * np.sin(phase + 0.4)).astype(np.float32)

        dry_out = dry.process(data)
        enhanced_out = enhanced.process(data)
        dry_rms = float(np.sqrt(np.mean(np.square(dry_out))))
        enhanced_rms = float(np.sqrt(np.mean(np.square(enhanced_out))))
        snapshot = enhanced.snapshot()

        self.assertTrue(snapshot.sound_enhancer_enabled)
        self.assertGreater(enhanced_rms, dry_rms * 1.9)
        self.assertLessEqual(float(np.max(np.abs(enhanced_out))), 0.8914 + 1e-6)
        self.assertFalse(snapshot.clipping)
        self.assertTrue(np.all(np.isfinite(enhanced_out)))

    def test_sound_enhancer_safely_limits_hot_material(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_sound_enhancer_enabled(True)
        data = np.ones((DRY_DELAY_SAMPLES + 64, MAX_INPUT_CHANNELS), dtype=np.float32) * 0.9

        out = processor.process(data)
        snapshot = processor.snapshot()

        self.assertLessEqual(float(np.max(np.abs(out))), 0.8914 + 1e-6)
        self.assertTrue(snapshot.sound_enhancer_enabled)
        self.assertLess(snapshot.sound_enhancer_gain, 1.0)
        self.assertTrue(snapshot.clipping)

    def test_sound_enhancer_limits_inter_sample_peak_estimate(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        processor.set_sound_enhancer_enabled(True)
        frames = DRY_DELAY_SAMPLES + 96
        data = np.zeros((frames, MAX_INPUT_CHANNELS), dtype=np.float32)
        pattern = np.array([0.86956584, -0.8674835, -0.8719893, 0.7874929], dtype=np.float32)
        repeated = np.resize(pattern, frames)
        data[:, 0] = repeated
        data[:, 1] = -repeated

        out = processor.process(data)
        snapshot = processor.snapshot()

        self.assertLessEqual(float(np.max(np.abs(out))), 0.8914 + 1e-6)
        self.assertLessEqual(
            processor._estimate_true_peak_stereo(out, out.shape[0]),
            0.8914 + 1e-6,
        )
        self.assertTrue(snapshot.clipping)
        self.assertTrue(np.all(np.isfinite(out)))

    def test_sound_enhancer_can_be_disabled_without_changing_baseline_output(self) -> None:
        baseline = DownmixProcessor(preamp_db=0)
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 64, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[:, 0] = 0.12
        data[:, 1] = -0.11

        baseline.process(data)
        processor.set_sound_enhancer_enabled(True)
        processor.process(data)
        processor.set_sound_enhancer_enabled(False)
        enhanced_then_disabled = processor.process(data)
        baseline_out = baseline.process(data)

        np.testing.assert_allclose(enhanced_then_disabled, baseline_out, rtol=0, atol=1e-7)
        snapshot = processor.snapshot()
        self.assertFalse(snapshot.sound_enhancer_enabled)
        self.assertAlmostEqual(snapshot.sound_enhancer_gain, 1.0, places=7)

    def test_non_finite_input_is_silently_sanitized(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.zeros((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        data[0, 0] = np.nan
        data[1, 1] = np.inf
        data[2, 3] = -np.inf
        data[:, 4] = 0.25

        out = processor.process(data)
        snapshot = processor.snapshot()

        self.assertTrue(np.all(np.isfinite(out)))
        self.assertTrue(np.all(np.isfinite(snapshot.raw_channel_levels)))
        self.assertTrue(np.all(np.isfinite(snapshot.channel_levels)))
        self.assertTrue(np.isfinite(snapshot.limiter_gain))


if __name__ == "__main__":
    unittest.main()
