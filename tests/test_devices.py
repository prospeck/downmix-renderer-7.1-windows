from __future__ import annotations

import unittest
from unittest import mock

from downmix_renderer import devices
from downmix_renderer.constants import SAMPLE_RATE


class DeviceInventoryTests(unittest.TestCase):
    def test_duplex_native_endpoints_are_mode_specific(self) -> None:
        raw_device = {
            "name": "USB Duplex",
            "hostapi": 0,
            "max_input_channels": 2,
            "max_output_channels": 2,
            "default_samplerate": SAMPLE_RATE,
            "default_low_input_latency": 0.003,
            "default_low_output_latency": 0.003,
            "default_high_input_latency": 0.010,
            "default_high_output_latency": 0.010,
        }
        native_index = {
            ("USB Duplex", "input"): {
                "endpoint_id": "{input-endpoint}",
                "direction": "input",
                "is_default": False,
            },
            ("USB Duplex", "output"): {
                "endpoint_id": "{output-endpoint}",
                "direction": "output",
                "is_default": True,
            },
        }

        with (
            mock.patch.object(devices.sd, "query_devices", return_value=[raw_device]),
            mock.patch.object(devices.sd, "query_hostapis", return_value=[{"name": devices.WASAPI_HOSTAPI}]),
            mock.patch.object(devices, "_native_descriptor_index", return_value=native_index),
        ):
            listed = devices.list_devices()

        self.assertEqual(len(listed), 1)
        device = listed[0]
        self.assertEqual(device.native_endpoint_for("input"), "{input-endpoint}")
        self.assertEqual(device.native_endpoint_for("output"), "{output-endpoint}")
        self.assertEqual(device.identity("input")["native_endpoint_id"], "{input-endpoint}")
        self.assertEqual(device.identity("output")["native_endpoint_id"], "{output-endpoint}")

        output_match = devices.find_saved_device(
            listed,
            {"native_endpoint_id": "{output-endpoint}", "name": "USB Duplex", "hostapi": devices.WASAPI_HOSTAPI},
            "output",
        )

        self.assertIs(output_match, device)

    def test_default_wasapi_output_prefers_native_default_over_stale_portaudio_default(self) -> None:
        stale_portaudio_default = devices.AudioDevice(
            id=10,
            name="Speakers (Old Default)",
            hostapi=devices.WASAPI_HOSTAPI,
            max_input_channels=0,
            max_output_channels=2,
            default_samplerate=SAMPLE_RATE,
            default_low_input_latency=0.0,
            default_low_output_latency=0.003,
            default_high_input_latency=0.0,
            default_high_output_latency=0.010,
            native_endpoint_id="{old}",
            native_direction="output",
            native_is_default=False,
        )
        current_native_default = devices.AudioDevice(
            id=11,
            name="CABLE Input (VB-Audio Virtual Cable)",
            hostapi=devices.WASAPI_HOSTAPI,
            max_input_channels=0,
            max_output_channels=16,
            default_samplerate=SAMPLE_RATE,
            default_low_input_latency=0.0,
            default_low_output_latency=0.003,
            default_high_input_latency=0.0,
            default_high_output_latency=0.010,
            native_endpoint_id="{current}",
            native_direction="output",
            native_is_default=True,
        )

        with mock.patch.object(
            devices.sd,
            "query_hostapis",
            return_value=[{"name": devices.WASAPI_HOSTAPI, "default_output_device": stale_portaudio_default.id}],
        ):
            selected = devices.default_wasapi_output([stale_portaudio_default, current_native_default])

        self.assertIs(selected, current_native_default)


if __name__ == "__main__":
    unittest.main()
