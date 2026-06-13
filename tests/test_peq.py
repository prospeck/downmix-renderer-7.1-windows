from __future__ import annotations

import unittest

from downmix_renderer.peq import MAX_GAIN_DB, MIN_Q, build_runtime_config


class PeqParserTests(unittest.TestCase):
    def test_equalizer_apo_user_peq_import_compiles_supported_filters(self) -> None:
        text = """
        Preamp: -5.5 dB
        Filter 1: ON PK Fc 105 Hz Gain 3.0 dB Q 1.20
        Filter 2: ON LSHELF Fc 80 Hz Gain -2.0 dB Q 0.70
        Filter 3: ON HPF Fc 20 Hz Q 0.707
        """

        config, report = build_runtime_config(
            global_text=text,
            global_enabled=True,
            speaker_text="",
            speaker_enabled=False,
            lr_swap_enabled=False,
            sample_rate=48000,
        )

        self.assertFalse(report.warnings)
        self.assertEqual(report.global_filter_count, 3)
        self.assertEqual(len(config.global_cascade.biquads), 3)
        self.assertAlmostEqual(config.global_cascade.preamp_db, -5.5)
        self.assertTrue(config.global_cascade.active)

    def test_malformed_lines_do_not_invalidate_valid_filters(self) -> None:
        text = """
        Filter 1: ON PK Fc 1000 Hz Gain 2 dB Q 1
        Filter 2: ON PK Fc nope Gain 2 dB Q 1
        Include: something-unsupported.txt
        Filter 3: OFF PK Fc 500 Hz Gain 12 dB Q 1
        """

        config, report = build_runtime_config(
            global_text=text,
            global_enabled=True,
            speaker_text="",
            speaker_enabled=False,
            lr_swap_enabled=False,
            sample_rate=48000,
        )

        self.assertEqual(report.global_filter_count, 1)
        self.assertEqual(len(config.global_cascade.biquads), 1)
        self.assertGreaterEqual(len(report.warnings), 1)

    def test_qudelix_speaker_mapping_flips_when_swap_is_enabled(self) -> None:
        text = """
        CH:0
        Preamp: -6 dB
        Filter 1: ON PK Fc 100 Hz Gain 1 dB Q 1
        CH:1
        Preamp: -12 dB
        Filter 1: ON PK Fc 1000 Hz Gain -1 dB Q 1
        """

        normal, _ = build_runtime_config(
            global_text="",
            global_enabled=False,
            speaker_text=text,
            speaker_enabled=True,
            lr_swap_enabled=False,
            sample_rate=48000,
        )
        swapped, _ = build_runtime_config(
            global_text="",
            global_enabled=False,
            speaker_text=text,
            speaker_enabled=True,
            lr_swap_enabled=True,
            sample_rate=48000,
        )

        self.assertAlmostEqual(normal.speaker_left.preamp_db, -6.0)
        self.assertAlmostEqual(normal.speaker_right.preamp_db, -12.0)
        self.assertAlmostEqual(swapped.speaker_left.preamp_db, -12.0)
        self.assertAlmostEqual(swapped.speaker_right.preamp_db, -6.0)

    def test_equalizer_apo_channel_numbers_remain_one_based(self) -> None:
        text = """
        Channel: 1
        Preamp: -3 dB
        Channel: 2
        Preamp: -9 dB
        """

        config, _ = build_runtime_config(
            global_text="",
            global_enabled=False,
            speaker_text=text,
            speaker_enabled=True,
            lr_swap_enabled=False,
            sample_rate=48000,
        )

        self.assertAlmostEqual(config.speaker_left.preamp_db, -3.0)
        self.assertAlmostEqual(config.speaker_right.preamp_db, -9.0)

    def test_filter_values_are_safely_clamped_before_compile(self) -> None:
        text = "Filter 1: ON PK Fc 999999 Hz Gain 80 dB Q 0.001"

        config, report = build_runtime_config(
            global_text=text,
            global_enabled=True,
            speaker_text="",
            speaker_enabled=False,
            lr_swap_enabled=False,
            sample_rate=48000,
        )

        self.assertFalse(report.warnings)
        self.assertEqual(config.global_cascade.filters[0].gain_db, MAX_GAIN_DB)
        self.assertEqual(config.global_cascade.filters[0].q, MIN_Q)
        self.assertEqual(len(config.global_cascade.biquads), 1)


if __name__ == "__main__":
    unittest.main()
