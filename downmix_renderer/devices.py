from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import sounddevice as sd

WASAPI_HOSTAPI = "Windows WASAPI"


@dataclass(frozen=True)
class AudioDevice:
    id: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: int
    default_low_input_latency: float
    default_low_output_latency: float
    default_high_input_latency: float
    default_high_output_latency: float
    native_endpoint_id: str | None = None
    native_direction: str | None = None
    native_is_default: bool = False
    native_ambiguous: bool = False

    @property
    def input_label(self) -> str:
        return (
            f"{self.name} | {self.hostapi} | "
            f"{self.max_input_channels}ch in | {self.default_samplerate} Hz"
        )

    @property
    def output_label(self) -> str:
        return (
            f"{self.name} | {self.hostapi} | "
            f"{self.max_output_channels}ch out | {self.default_samplerate} Hz"
        )

    def identity(self, mode: str) -> dict[str, object]:
        identity = {
            "id": self.id,
            "name": self.name,
            "hostapi": self.hostapi,
            "mode": mode,
            "max_input_channels": self.max_input_channels,
            "max_output_channels": self.max_output_channels,
            "default_samplerate": self.default_samplerate,
        }
        if self.native_endpoint_id:
            identity["native_endpoint_id"] = self.native_endpoint_id
            identity["native_direction"] = self.native_direction or mode
            identity["native_is_default"] = self.native_is_default
        if self.native_ambiguous:
            identity["native_ambiguous"] = True
        return identity

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def list_devices(force_refresh: bool = False) -> list[AudioDevice]:
    if force_refresh:
        _refresh_portaudio_inventory()
    raw_devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    devices: list[AudioDevice] = []

    native_by_key = _native_descriptor_index()

    for device_id, dev in enumerate(raw_devices):
        hostapi = hostapis[dev["hostapi"]]["name"]
        name = str(dev["name"])
        max_input_channels = int(dev["max_input_channels"])
        max_output_channels = int(dev["max_output_channels"])
        direction = "input" if max_input_channels >= max_output_channels else "output"
        descriptor = native_by_key.get((name, direction))
        devices.append(
            AudioDevice(
                id=device_id,
                name=name,
                hostapi=str(hostapi),
                max_input_channels=max_input_channels,
                max_output_channels=max_output_channels,
                default_samplerate=int(dev["default_samplerate"]),
                default_low_input_latency=float(dev["default_low_input_latency"]),
                default_low_output_latency=float(dev["default_low_output_latency"]),
                default_high_input_latency=float(dev["default_high_input_latency"]),
                default_high_output_latency=float(dev["default_high_output_latency"]),
                native_endpoint_id=descriptor.get("endpoint_id") if descriptor else None,
                native_direction=descriptor.get("direction") if descriptor else None,
                native_is_default=bool(descriptor.get("is_default")) if descriptor else False,
                native_ambiguous=bool(descriptor.get("ambiguous")) if descriptor else False,
            )
        )
    return devices


def _native_descriptor_index() -> dict[tuple[str, str], dict[str, object]]:
    try:
        from .native_audio import native_device_descriptors

        descriptors = native_device_descriptors()
    except Exception:
        return {}

    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for descriptor in descriptors:
        name = str(descriptor.get("name") or "")
        direction = str(descriptor.get("direction") or "")
        endpoint_id = str(descriptor.get("endpoint_id") or "")
        if not name or direction not in {"input", "output"} or not endpoint_id:
            continue
        grouped.setdefault((name, direction), []).append(descriptor)

    indexed: dict[tuple[str, str], dict[str, object]] = {}
    for key, matches in grouped.items():
        if len(matches) == 1:
            indexed[key] = matches[0]
        else:
            indexed[key] = {**matches[0], "endpoint_id": None, "ambiguous": True}
    return indexed


def _refresh_portaudio_inventory() -> None:
    terminate = getattr(sd, "_terminate", None)
    initialize = getattr(sd, "_initialize", None)
    if not callable(terminate) or not callable(initialize):
        return
    try:
        terminate()
        initialize()
    except Exception:
        pass


def input_devices(devices: Iterable[AudioDevice]) -> list[AudioDevice]:
    return [dev for dev in devices if dev.max_input_channels >= 2]


def output_devices(devices: Iterable[AudioDevice]) -> list[AudioDevice]:
    return [dev for dev in devices if dev.max_output_channels >= 2]


def wasapi_devices(devices: Iterable[AudioDevice]) -> list[AudioDevice]:
    return [dev for dev in devices if dev.hostapi == WASAPI_HOSTAPI]


def _is_vb_cable_name(name: str) -> bool:
    name = name.casefold().replace("-", " ")
    is_vb_virtual_cable = "vb audio virtual cable" in name or "vb-audio virtual cable" in name
    is_renamed_16ch_cable = "cable" in name and ("16 channel" in name or "16ch" in name)
    return is_vb_virtual_cable or is_renamed_16ch_cable


def _is_16_channel_vb_cable(device: AudioDevice, mode: str) -> bool:
    channels = device.max_input_channels if mode == "input" else device.max_output_channels
    return channels >= 16 and _is_vb_cable_name(device.name)


def _renderer_sort_key(device: AudioDevice, mode: str) -> tuple[bool, bool, int]:
    return (
        not _is_16_channel_vb_cable(device, mode),
        device.hostapi != WASAPI_HOSTAPI,
        device.id,
    )


def renderer_input_devices(devices: Iterable[AudioDevice]) -> list[AudioDevice]:
    inputs = [dev for dev in wasapi_devices(devices) if dev.max_input_channels >= 16]
    return sorted(inputs, key=lambda dev: _renderer_sort_key(dev, "input"))


def renderer_output_devices(devices: Iterable[AudioDevice]) -> list[AudioDevice]:
    return [dev for dev in wasapi_devices(devices) if dev.max_output_channels >= 2]


def find_saved_device(
    devices: Iterable[AudioDevice],
    saved: dict[str, object] | int | None,
    mode: str,
) -> AudioDevice | None:
    if saved is None:
        return None

    candidates = list(renderer_input_devices(devices) if mode == "input" else renderer_output_devices(devices))

    if isinstance(saved, int):
        return next((dev for dev in candidates if dev.id == saved), None)

    saved_name = str(saved.get("name", ""))
    saved_hostapi = str(saved.get("hostapi", ""))
    saved_sr = int(saved.get("default_samplerate", 0) or 0)
    saved_id = saved.get("id")
    saved_endpoint = str(saved.get("native_endpoint_id") or "")

    if saved_endpoint:
        endpoint_match = next((dev for dev in candidates if dev.native_endpoint_id == saved_endpoint), None)
        if endpoint_match is not None:
            return endpoint_match

    exact = [
        dev
        for dev in candidates
        if dev.name == saved_name
        and dev.hostapi == saved_hostapi
        and (saved_sr == 0 or dev.default_samplerate == saved_sr)
    ]
    if exact:
        return exact[0]

    name_host = [dev for dev in candidates if dev.name == saved_name and dev.hostapi == saved_hostapi]
    if name_host:
        return name_host[0]

    if isinstance(saved_id, int):
        saved_id_match = next((dev for dev in candidates if dev.id == saved_id), None)
        if saved_id_match is not None:
            return saved_id_match

    if mode == "input":
        saved_channels = int(saved.get("max_input_channels", 0) or 0)
        if saved_channels >= 16 and _is_vb_cable_name(saved_name):
            return next((dev for dev in candidates if _is_16_channel_vb_cable(dev, mode)), None)

    return None


def preferred_input(devices: Iterable[AudioDevice]) -> AudioDevice | None:
    inputs = renderer_input_devices(devices)
    ranked = sorted(
        inputs,
        key=lambda dev: (
            not _is_16_channel_vb_cable(dev, "input"),
            dev.hostapi != WASAPI_HOSTAPI,
            dev.max_input_channels < 16,
            dev.default_samplerate != 48000,
            dev.id,
        ),
    )
    return ranked[0] if ranked else None


def preferred_output(devices: Iterable[AudioDevice]) -> AudioDevice | None:
    outputs = renderer_output_devices(devices)
    if not outputs:
        return None

    dac_keywords = ("qudelix", "dac", "speakers")
    ranked = sorted(
        outputs,
        key=lambda dev: (
            not any(keyword in dev.name.lower() for keyword in dac_keywords),
            "Windows WASAPI" not in dev.hostapi,
            dev.max_output_channels < 2,
            dev.id,
        ),
    )
    return ranked[0]


def default_wasapi_output(devices: Iterable[AudioDevice]) -> AudioDevice | None:
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return None

    default_id: int | None = None
    for hostapi in hostapis:
        if hostapi.get("name") == WASAPI_HOSTAPI:
            raw_id = hostapi.get("default_output_device", -1)
            if isinstance(raw_id, int) and raw_id >= 0:
                default_id = raw_id
            break
    if default_id is None:
        return None
    return next((dev for dev in devices if dev.id == default_id), None)


def check_format_support(device_id: int, mode: str, channels: int, samplerate: int) -> tuple[bool, str]:
    try:
        if mode == "input":
            sd.check_input_settings(
                device=device_id,
                channels=channels,
                samplerate=samplerate,
                dtype="float32",
            )
        elif mode == "output":
            sd.check_output_settings(
                device=device_id,
                channels=channels,
                samplerate=samplerate,
                dtype="float32",
            )
        else:
            raise ValueError("mode must be input or output")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    return True, "OK"
