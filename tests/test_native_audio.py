from __future__ import annotations

import unittest

from downmix_renderer.devices import AudioDevice
from downmix_renderer.native_audio import NativeAudioBackend


def fake_device(mode: str, endpoint_id: str | None) -> AudioDevice:
    return AudioDevice(
        id=1 if mode == "input" else 2,
        name=f"{mode.title()} Device",
        hostapi="Windows WASAPI",
        max_input_channels=16 if mode == "input" else 0,
        max_output_channels=0 if mode == "input" else 2,
        default_samplerate=48000,
        default_low_input_latency=0.003 if mode == "input" else 0.0,
        default_low_output_latency=0.0 if mode == "input" else 0.003,
        default_high_input_latency=0.010 if mode == "input" else 0.0,
        default_high_output_latency=0.0 if mode == "input" else 0.010,
        native_endpoint_id=endpoint_id,
        native_direction=mode,
    )


class NativeAudioBindingTests(unittest.TestCase):
    def test_start_uses_endpoint_identity_when_export_is_available(self) -> None:
        calls: list[tuple[object, ...]] = []

        class FakeDll:
            def downmix_native_start_endpoints(self, *args: object) -> int:
                calls.append(args)
                return 1

            def downmix_native_start(self, *args: object) -> int:
                self.fail("legacy name-only start should not be used")

        backend = object.__new__(NativeAudioBackend)
        backend._handle = object()
        backend._dll = FakeDll()
        backend._has_endpoint_start = True

        backend.start(
            fake_device("input", "{input-endpoint}"),
            fake_device("output", "{output-endpoint}"),
            "ultra",
            128,
            192000,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], b"{input-endpoint}")
        self.assertEqual(calls[0][2], b"Input Device")
        self.assertEqual(calls[0][3], b"{output-endpoint}")
        self.assertEqual(calls[0][4], b"Output Device")
        self.assertEqual(calls[0][7], 192000)


if __name__ == "__main__":
    unittest.main()
