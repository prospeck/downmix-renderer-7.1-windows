from __future__ import annotations

import unittest

from downmix_renderer.devices import AudioDevice
from downmix_renderer.presets import (
    PRESET_SCHEMA_VERSION,
    load_presets,
    match_preset_for_output,
    preset_from_current,
    update_preset_from_current,
)


def fake_output(name: str = "Speakers (Qudelix-5K USB DAC 48KHz)") -> AudioDevice:
    return AudioDevice(
        id=18,
        name=name,
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.01,
    )


def fake_realtek_output() -> AudioDevice:
    return AudioDevice(
        id=21,
        name="Speakers (Realtek(R) Audio)",
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.01,
    )


def fake_duplicate_output(device_id: int, endpoint_id: str) -> AudioDevice:
    return AudioDevice(
        id=device_id,
        name="Speakers (USB Audio Device)",
        hostapi="Windows WASAPI",
        max_input_channels=0,
        max_output_channels=2,
        default_samplerate=48000,
        default_low_input_latency=0.0,
        default_low_output_latency=0.003,
        default_high_input_latency=0.0,
        default_high_output_latency=0.01,
        native_endpoint_id=endpoint_id,
        native_direction="output",
        native_is_default=False,
    )


def fake_input() -> AudioDevice:
    return AudioDevice(
        id=24,
        name="CABLE Output (VB-Audio Virtual Cable)",
        hostapi="Windows WASAPI",
        max_input_channels=16,
        max_output_channels=0,
        default_samplerate=48000,
        default_low_input_latency=0.003,
        default_low_output_latency=0.0,
        default_high_input_latency=0.01,
        default_high_output_latency=0.0,
    )


class PresetTests(unittest.TestCase):
    def test_no_presets_are_created_without_v2_schema(self) -> None:
        self.assertEqual(load_presets({}, [fake_input(), fake_output()]), [])

    def test_v2_presets_are_loaded_only_when_user_saved(self) -> None:
        preset = preset_from_current("Qudelix", fake_input(), fake_output(), -7, 0.42, "windows_7_1")
        settings = {"preset_schema_version": PRESET_SCHEMA_VERSION, "presets": [preset.to_dict()]}
        loaded = load_presets(settings, [fake_input(), fake_output()])
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].preamp_db, -7)
        self.assertAlmostEqual(loaded[0].user_volume, 0.42)
        self.assertFalse(loaded[0].surround_fill_enabled)
        self.assertFalse(loaded[0].upmix_9_1_6_enabled)
        self.assertFalse(loaded[0].channel_sanity_enabled)
        self.assertEqual(loaded[0].audio_stability, "ultra")
        self.assertFalse(loaded[0].lr_swap_enabled)
        self.assertFalse(loaded[0].global_peq_enabled)
        self.assertEqual(loaded[0].global_peq_text, "")
        self.assertFalse(loaded[0].speaker_eq_enabled)
        self.assertEqual(loaded[0].speaker_eq_text, "")
        self.assertEqual(loaded[0].trim_left_db, 0.0)
        self.assertEqual(loaded[0].trim_right_db, 0.0)
        self.assertEqual(loaded[0].sample_rate_mode, "auto")

    def test_v2_presets_still_load_after_peq_schema_upgrade(self) -> None:
        settings = {
            "preset_schema_version": 2,
            "presets": [
                {
                    "id": "legacy",
                    "name": "Legacy",
                    "preamp_db": -4,
                    "channel_config": "windows_7_1",
                }
            ],
        }

        loaded = load_presets(settings, [fake_input(), fake_output()])

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "Legacy")
        self.assertEqual(loaded[0].preamp_db, -4)
        self.assertFalse(loaded[0].global_peq_enabled)
        self.assertEqual(loaded[0].trim_left_db, 0.0)
        self.assertEqual(loaded[0].trim_right_db, 0.0)

    def test_trim_values_are_serialized_and_clamped(self) -> None:
        preset = preset_from_current(
            "Trimmed",
            fake_input(),
            fake_output(),
            -7,
            1.0,
            "windows_7_1",
            trim_left_db=-2.5,
            trim_right_db=-99.0,
        )

        payload = preset.to_dict()
        self.assertEqual(payload["trim_left_db"], -2.5)
        self.assertEqual(payload["trim_right_db"], -24.0)

        loaded = load_presets(
            {
                "preset_schema_version": PRESET_SCHEMA_VERSION,
                "presets": [
                    {**payload, "trim_left_db": 4.0, "trim_right_db": "bad"},
                ],
            },
            [fake_input(), fake_output()],
        )

        self.assertEqual(loaded[0].trim_left_db, 0.0)
        self.assertEqual(loaded[0].trim_right_db, 0.0)

    def test_update_overwrites_all_audio_parameters(self) -> None:
        preset = preset_from_current("Daily", fake_input(), fake_output(), -14, 1.0, "windows_7_1")
        update_preset_from_current(
            preset,
            fake_input(),
            fake_output("Speakers (Realtek(R) Audio)"),
            -3,
            0.6,
            "sharur_9_1_6",
            surround_fill_enabled=False,
            upmix_9_1_6_enabled=True,
            channel_sanity_enabled=False,
            audio_stability="low_latency",
            lr_swap_enabled=True,
            global_peq_enabled=True,
            global_peq_text="Preamp: -3 dB",
            speaker_eq_enabled=True,
            speaker_eq_text="CH:0\nPreamp: -6 dB",
            trim_left_db=-2.5,
            trim_right_db=-6.0,
            sample_rate_mode="192000",
        )
        self.assertEqual(preset.preamp_db, -3)
        self.assertAlmostEqual(preset.user_volume, 0.6)
        self.assertEqual(preset.channel_config, "sharur_9_1_6")
        self.assertFalse(preset.surround_fill_enabled)
        self.assertTrue(preset.upmix_9_1_6_enabled)
        self.assertFalse(preset.channel_sanity_enabled)
        self.assertEqual(preset.audio_stability, "raw")
        self.assertIn("Realtek", str(preset.output_device))
        self.assertTrue(preset.lr_swap_enabled)
        self.assertTrue(preset.global_peq_enabled)
        self.assertEqual(preset.global_peq_text, "Preamp: -3 dB")
        self.assertTrue(preset.speaker_eq_enabled)
        self.assertEqual(preset.speaker_eq_text, "CH:0\nPreamp: -6 dB")
        self.assertEqual(preset.trim_left_db, -2.5)
        self.assertEqual(preset.trim_right_db, -6.0)
        self.assertEqual(preset.sample_rate_mode, "192000")

    def test_sample_rate_mode_is_serialized_and_normalized(self) -> None:
        preset = preset_from_current(
            "192K",
            fake_input(),
            fake_output(),
            -14,
            1.0,
            "windows_7_1",
            sample_rate_mode="192000",
        )

        payload = preset.to_dict()
        self.assertEqual(payload["sample_rate_mode"], "192000")

        loaded = load_presets(
            {
                "preset_schema_version": PRESET_SCHEMA_VERSION,
                "presets": [
                    {**payload, "sample_rate_mode": "96 kHz"},
                    {**payload, "id": "bad", "sample_rate_mode": "384000"},
                ],
            },
            [fake_input(), fake_output()],
        )

        self.assertEqual(loaded[0].sample_rate_mode, "96000")
        self.assertEqual(loaded[1].sample_rate_mode, "auto")

    def test_legacy_preset_audio_stability_values_are_migrated(self) -> None:
        settings = {
            "preset_schema_version": PRESET_SCHEMA_VERSION,
            "presets": [
                {"id": "p1", "name": "Normal", "audio_stability": "normal"},
                {"id": "p2", "name": "Balanced", "audio_stability": "balanced"},
                {"id": "p3", "name": "Low", "audio_stability": "low_latency"},
            ],
        }

        loaded = load_presets(settings, [fake_input(), fake_output()])

        self.assertEqual([preset.audio_stability for preset in loaded], ["ultra", "ultra", "raw"])

    def test_removed_output_preset_does_not_match_generic_speakers_keyword(self) -> None:
        qudelix = preset_from_current("Qudelix", fake_input(), fake_output(), -14, 1.0, "windows_7_1")
        realtek = fake_realtek_output()

        self.assertIsNone(match_preset_for_output([qudelix], realtek, [fake_input(), realtek]))

    def test_available_output_preset_wins_after_another_output_is_removed(self) -> None:
        qudelix = preset_from_current("Qudelix", fake_input(), fake_output(), -14, 1.0, "windows_7_1")
        speakers = preset_from_current("Speakers", fake_input(), fake_realtek_output(), -10, 0.8, "windows_7_1")
        realtek = fake_realtek_output()

        matched = match_preset_for_output([qudelix, speakers], realtek, [fake_input(), realtek])

        self.assertIs(matched, speakers)

    def test_endpoint_identity_prevents_same_name_output_cross_match(self) -> None:
        output_a = fake_duplicate_output(31, "{0.0.0.00000000}.A")
        output_b = fake_duplicate_output(32, "{0.0.0.00000000}.B")
        preset = preset_from_current("USB A", fake_input(), output_a, -8, 1.0, "windows_7_1")

        matched = match_preset_for_output([preset], output_b, [fake_input(), output_a, output_b])

        self.assertIsNone(matched)

    def test_device_identity_persists_native_endpoint_fields(self) -> None:
        output = fake_duplicate_output(31, "{0.0.0.00000000}.A")

        identity = output.identity("output")

        self.assertEqual(identity["native_endpoint_id"], "{0.0.0.00000000}.A")
        self.assertEqual(identity["native_direction"], "output")
        self.assertIs(identity["native_is_default"], False)


if __name__ == "__main__":
    unittest.main()
