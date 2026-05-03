from __future__ import annotations

import unittest

import numpy as np

from downmix_renderer.constants import MAX_INPUT_CHANNELS
from downmix_renderer.constants import CHANNEL_LAYOUTS
from downmix_renderer.dsp import DRY_DELAY_SAMPLES, LFE_CHANNEL_INDEX, DownmixProcessor, db_to_linear
from downmix_renderer.matrix import MATRIX, MATRIX_LITERAL


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

    def test_windows_7_1_layout_uses_first_eight_stream_channels(self) -> None:
        layout = CHANNEL_LAYOUTS["windows_7_1"]
        self.assertEqual(tuple(layout["indices"]), tuple(range(8)))
        self.assertEqual(tuple(layout["names"]), ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"))


class DspTests(unittest.TestCase):
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

    def test_limiter_never_outputs_above_full_scale_on_hot_blocks(self) -> None:
        processor = DownmixProcessor(preamp_db=0)
        data = np.ones((DRY_DELAY_SAMPLES + 16, MAX_INPUT_CHANNELS), dtype=np.float32)
        out = processor.process(data)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0 + 1e-6)
        self.assertTrue(processor.snapshot().clipping)


if __name__ == "__main__":
    unittest.main()
