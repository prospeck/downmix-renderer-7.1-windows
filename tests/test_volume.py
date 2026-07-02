from __future__ import annotations

import unittest

from downmix_renderer.volume import WindowsEndpointVolumeFollower


class WindowsEndpointVolumeFollowerTests(unittest.TestCase):
    def test_prepare_output_endpoint_sets_selected_endpoint_to_full_volume(self) -> None:
        class FakeFollower(WindowsEndpointVolumeFollower):
            def __init__(self) -> None:
                self.events: list[tuple[object, ...]] = []

            def _create_enumerator(self):
                self.events.append(("create_enumerator",))
                return "enumerator"

            def _device_for_endpoint_id(self, enumerator, endpoint_id: str):
                self.events.append(("get_device", enumerator, endpoint_id))
                return "device"

            def _activate_endpoint_volume(self, device):
                self.events.append(("activate", device))
                return "endpoint"

            def _set_endpoint_volume(self, endpoint, scalar: float, muted: bool) -> None:
                self.events.append(("set_volume", endpoint, scalar, muted))

            def _release(self, pointer) -> None:
                self.events.append(("release", pointer))

        follower = FakeFollower()
        follower.prepare_output_endpoint("{output-endpoint}")

        self.assertEqual(
            follower.events,
            [
                ("create_enumerator",),
                ("get_device", "enumerator", "{output-endpoint}"),
                ("activate", "device"),
                ("set_volume", "endpoint", 1.0, False),
                ("release", "endpoint"),
                ("release", "device"),
                ("release", "enumerator"),
            ],
        )

    def test_prepare_output_endpoint_ignores_missing_endpoint_identity(self) -> None:
        class FakeFollower(WindowsEndpointVolumeFollower):
            def __init__(self) -> None:
                self.created = False

            def _create_enumerator(self):
                self.created = True
                return "enumerator"

        follower = FakeFollower()
        follower.prepare_output_endpoint("")

        self.assertFalse(follower.created)


if __name__ == "__main__":
    unittest.main()
