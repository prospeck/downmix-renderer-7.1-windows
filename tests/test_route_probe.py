from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from downmix_renderer import route_probe
from downmix_renderer.constants import OUTPUT_CHANNELS, SAMPLE_RATE
from downmix_renderer.devices import AudioDevice
from downmix_renderer.route_probe import _front_correlations, _looks_like_windows_channel_fill


class RouteProbeTests(unittest.TestCase):
    def test_output_format_checks_use_stereo_output_channel_count(self) -> None:
        devices = [
            AudioDevice(
                id=7,
                name="Laptop Speakers",
                hostapi="Windows WASAPI",
                max_input_channels=0,
                max_output_channels=2,
                default_samplerate=SAMPLE_RATE,
                default_low_input_latency=0.0,
                default_low_output_latency=0.01,
                default_high_input_latency=0.0,
                default_high_output_latency=0.04,
            )
        ]
        calls: list[tuple[int, str, int, int]] = []

        def fake_check(device_id: int, mode: str, channels: int, samplerate: int) -> tuple[bool, str]:
            calls.append((device_id, mode, channels, samplerate))
            return True, "ok"

        with mock.patch.object(route_probe, "check_format_support", side_effect=fake_check):
            checks = route_probe.format_checks(devices)

        self.assertEqual(calls, [(7, "output", OUTPUT_CHANNELS, SAMPLE_RATE)])
        self.assertEqual(checks[0].channels, OUTPUT_CHANNELS)

    def test_detects_front_correlated_channel_fill(self) -> None:
        square_sum = np.array([10.0, 8.0, 9.0, 0.0, 10.0] + [0.0] * 11, dtype=np.float64)
        cross_sum = np.zeros((16, 2), dtype=np.float64)
        cross_sum[0, 0] = 10.0
        cross_sum[1, 1] = 8.0
        cross_sum[2, 0] = np.sqrt(9.0 * 10.0)
        cross_sum[4, 0] = 10.0

        correlations = _front_correlations(square_sum, cross_sum)

        self.assertTrue(
            _looks_like_windows_channel_fill(
                active_channels=[1, 2, 3, 5],
                rms=np.sqrt(square_sum / 100.0),
                front_correlations=correlations,
                threshold=1e-4,
            )
        )

    def test_does_not_flag_independent_surround_activity_as_fill(self) -> None:
        rms = np.array([0.3, 0.25, 0.1, 0.0, 0.15] + [0.0] * 11, dtype=np.float64)
        correlations = [1.0, 1.0, 0.2, 0.0, 0.1] + [0.0] * 11

        self.assertFalse(
            _looks_like_windows_channel_fill(
                active_channels=[1, 2, 3, 5],
                rms=rms,
                front_correlations=correlations,
                threshold=1e-4,
            )
        )


if __name__ == "__main__":
    unittest.main()
