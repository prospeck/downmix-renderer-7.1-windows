from __future__ import annotations

import ctypes
import os
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VolumeState:
    scalar: float
    muted: bool
    available: bool
    source: str
    detail: str = ""


class VolumeFollower(Protocol):
    def get_state(self) -> VolumeState:
        ...

    def set_output_endpoint_id(self, endpoint_id: str | None) -> None:
        ...

    def close(self) -> None:
        ...


class NullVolumeFollower:
    def __init__(self, detail: str = "Volume follow unavailable") -> None:
        self.detail = detail

    def get_state(self) -> VolumeState:
        return VolumeState(1.0, False, False, "none", self.detail)

    def set_output_endpoint_id(self, endpoint_id: str | None) -> None:
        return None

    def close(self) -> None:
        return None


class PycawVolumeFollower:
    def __init__(self) -> None:
        self._endpoint = None
        self._create_endpoint()

    def get_state(self) -> VolumeState:
        try:
            return self._read_state()
        except Exception:
            self._create_endpoint()
            return self._read_state()

    def set_output_endpoint_id(self, endpoint_id: str | None) -> None:
        return None

    def close(self) -> None:
        self._endpoint = None

    def _create_endpoint(self) -> None:
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        self._endpoint = cast(interface, POINTER(IAudioEndpointVolume))

    def _read_state(self) -> VolumeState:
        scalar = float(self._endpoint.GetMasterVolumeLevelScalar())
        muted = bool(self._endpoint.GetMute())
        return VolumeState(_clamp_scalar(scalar), muted, True, "pycaw", "Default render endpoint")


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, value: str) -> None:
        super().__init__()
        parsed = uuid.UUID(value)
        fields = parsed.fields
        self.Data1 = fields[0]
        self.Data2 = fields[1]
        self.Data3 = fields[2]
        data4 = parsed.bytes[8:]
        self.Data4[:] = data4


class WindowsEndpointVolumeFollower:
    CLSCTX_ALL = 0x17
    E_RENDER = 0
    E_MULTIMEDIA = 1
    RPC_E_CHANGED_MODE = 0x80010106

    CLSID_MMDEVICE_ENUMERATOR = _GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
    IID_IMMDEVICE_ENUMERATOR = _GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    IID_IAUDIO_ENDPOINT_VOLUME = _GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows endpoint volume is only available on Windows")

        self._ole32 = ctypes.WinDLL("ole32")
        self._initialized_com = False
        self._enumerator = ctypes.c_void_p()
        self._device = ctypes.c_void_p()
        self._endpoint = ctypes.c_void_p()
        self._target_endpoint_id = ""
        self._endpoint_detail = "Default render endpoint"

        hr = self._ole32.CoInitializeEx(None, 0)
        unsigned_hr = int(hr) & 0xFFFFFFFF
        if hr == 0:
            self._initialized_com = True
        elif unsigned_hr != self.RPC_E_CHANGED_MODE:
            self._check_hr(hr, "CoInitializeEx")

        self._create_endpoint()

    def set_output_endpoint_id(self, endpoint_id: str | None) -> None:
        target = str(endpoint_id or "").strip()
        if target == self._target_endpoint_id:
            return
        self._target_endpoint_id = target
        self._release_endpoint_objects()
        try:
            self._create_endpoint()
        except Exception:
            pass

    def get_state(self) -> VolumeState:
        try:
            return self._read_state()
        except Exception as exc:
            first_error = str(exc)
            try:
                self._release_endpoint_objects()
                self._create_endpoint()
                return self._read_state()
            except Exception as refresh_exc:
                detail = f"{first_error}; refresh failed: {refresh_exc}"
                return VolumeState(1.0, False, False, "windows-coreaudio", detail)

    def _read_state(self) -> VolumeState:
        try:
            scalar = ctypes.c_float()
            muted = ctypes.c_int()
            get_scalar = self._call_endpoint(9, ctypes.HRESULT, ctypes.POINTER(ctypes.c_float))
            get_mute = self._call_endpoint(15, ctypes.HRESULT, ctypes.POINTER(ctypes.c_int))
            hr = get_scalar(
                self._endpoint,
                ctypes.byref(scalar),
            )
            self._check_hr(hr, "IAudioEndpointVolume.GetMasterVolumeLevelScalar")
            hr = get_mute(
                self._endpoint,
                ctypes.byref(muted),
            )
            self._check_hr(hr, "IAudioEndpointVolume.GetMute")
            return VolumeState(
                _clamp_scalar(float(scalar.value)),
                bool(muted.value),
                True,
                "windows-coreaudio",
                self._endpoint_detail,
            )
        except Exception as exc:
            raise exc

    def close(self) -> None:
        self._release_endpoint_objects()
        if self._initialized_com:
            self._ole32.CoUninitialize()
            self._initialized_com = False

    def _release_endpoint_objects(self) -> None:
        for pointer in (self._endpoint, self._device, self._enumerator):
            if pointer:
                try:
                    self._release(pointer)
                except Exception:
                    pass
        self._endpoint = ctypes.c_void_p()
        self._device = ctypes.c_void_p()
        self._enumerator = ctypes.c_void_p()

    def _create_endpoint(self) -> None:
        hr = self._ole32.CoCreateInstance(
            ctypes.byref(self.CLSID_MMDEVICE_ENUMERATOR),
            None,
            self.CLSCTX_ALL,
            ctypes.byref(self.IID_IMMDEVICE_ENUMERATOR),
            ctypes.byref(self._enumerator),
        )
        self._check_hr(hr, "CoCreateInstance(IMMDeviceEnumerator)")

        selected_error = ""
        if self._target_endpoint_id:
            try:
                get_device = self._method(
                    self._enumerator,
                    5,
                    ctypes.HRESULT,
                    ctypes.c_wchar_p,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                hr = get_device(
                    self._enumerator,
                    ctypes.c_wchar_p(self._target_endpoint_id),
                    ctypes.byref(self._device),
                )
                self._check_hr(hr, "IMMDeviceEnumerator.GetDevice")
                self._endpoint_detail = "Selected output endpoint"
            except Exception as exc:
                selected_error = str(exc)
                if self._device:
                    try:
                        self._release(self._device)
                    except Exception:
                        pass
                self._device = ctypes.c_void_p()

        if not self._device:
            self._create_default_render_device()
            self._endpoint_detail = "Default render endpoint"
            if selected_error:
                self._endpoint_detail = f"{self._endpoint_detail}; selected unavailable: {selected_error}"

        activate = self._method(
            self._device,
            3,
            ctypes.HRESULT,
            ctypes.POINTER(_GUID),
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = activate(
            self._device,
            ctypes.byref(self.IID_IAUDIO_ENDPOINT_VOLUME),
            self.CLSCTX_ALL,
            None,
            ctypes.byref(self._endpoint),
        )
        self._check_hr(hr, "IMMDevice.Activate(IAudioEndpointVolume)")

    def _create_default_render_device(self) -> None:
        get_default = self._method(
            self._enumerator,
            4,
            ctypes.HRESULT,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = get_default(
            self._enumerator,
            self.E_RENDER,
            self.E_MULTIMEDIA,
            ctypes.byref(self._device),
        )
        self._check_hr(hr, "IMMDeviceEnumerator.GetDefaultAudioEndpoint")

    def _call_endpoint(self, index: int, restype: object, *argtypes: object):
        return self._method(self._endpoint, index, restype, *argtypes)

    @staticmethod
    def _method(pointer: ctypes.c_void_p, index: int, restype: object, *argtypes: object):
        vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return prototype(vtable[index])

    def _release(self, pointer: ctypes.c_void_p) -> None:
        release = self._method(pointer, 2, ctypes.c_ulong)
        release(pointer)

    @staticmethod
    def _check_hr(hr: int, context: str) -> None:
        if hr < 0:
            raise OSError(f"{context} failed with HRESULT 0x{ctypes.c_ulong(hr).value:08X}")


def create_volume_follower() -> VolumeFollower:
    if os.name != "nt":
        return NullVolumeFollower("Non-Windows platform")

    try:
        return WindowsEndpointVolumeFollower()
    except Exception:
        pass

    try:
        return PycawVolumeFollower()
    except Exception as exc:
        return NullVolumeFollower(str(exc))


def _clamp_scalar(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
