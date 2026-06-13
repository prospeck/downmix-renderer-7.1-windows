from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .constants import MAX_INPUT_CHANNELS, OUTPUT_CHANNELS
from .dsp import DspSnapshot
from .peq import PeqCascade, PeqRuntimeConfig


DLL_NAME = "downmix_renderer_native.dll"


class NativeBackendUnavailable(RuntimeError):
    pass


class _NativeDspSnapshot(ctypes.Structure):
    _fields_ = [
        ("channel_levels", ctypes.c_float * MAX_INPUT_CHANNELS),
        ("channel_rms", ctypes.c_float * MAX_INPUT_CHANNELS),
        ("raw_channel_levels", ctypes.c_float * MAX_INPUT_CHANNELS),
        ("raw_channel_rms", ctypes.c_float * MAX_INPUT_CHANNELS),
        ("left_meter", ctypes.c_float),
        ("right_meter", ctypes.c_float),
        ("preamp_db", ctypes.c_float),
        ("trim_left_db", ctypes.c_float),
        ("trim_right_db", ctypes.c_float),
        ("limiter_gain", ctypes.c_float),
        ("clipping", ctypes.c_int32),
        ("user_volume", ctypes.c_float),
        ("master_volume", ctypes.c_float),
        ("master_muted", ctypes.c_int32),
        ("surround_fill_enabled", ctypes.c_int32),
        ("surround_fill_active", ctypes.c_int32),
        ("upmix_9_1_6_enabled", ctypes.c_int32),
        ("upmix_9_1_6_active", ctypes.c_int32),
        ("channel_sanity_enabled", ctypes.c_int32),
        ("channel_sanity_active", ctypes.c_int32),
    ]


class _NativeEngineSnapshot(ctypes.Structure):
    _fields_ = [
        ("running", ctypes.c_int32),
        ("input_channels", ctypes.c_int32),
        ("callback_status_count", ctypes.c_int32),
        ("dsp_error_count", ctypes.c_int32),
        ("cpu_load", ctypes.c_float),
        ("input_latency", ctypes.c_float),
        ("output_latency", ctypes.c_float),
        ("has_latency", ctypes.c_int32),
        ("status", ctypes.c_char * 256),
        ("route", ctypes.c_char * 512),
        ("callback_status", ctypes.c_char * 256),
        ("stream_profile", ctypes.c_char * 32),
        ("dsp", _NativeDspSnapshot),
    ]


class _NativeDeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("endpoint_id", ctypes.c_char * 512),
        ("name", ctypes.c_char * 256),
        ("direction", ctypes.c_int32),
        ("is_default", ctypes.c_int32),
        ("max_input_channels", ctypes.c_int32),
        ("max_output_channels", ctypes.c_int32),
        ("default_samplerate", ctypes.c_int32),
        ("ambiguous", ctypes.c_int32),
    ]


@dataclass(frozen=True)
class NativeEngineRuntime:
    running: bool
    status: str
    input_channels: int
    route: str
    callback_status: str
    callback_status_count: int
    dsp_error_count: int
    cpu_load: float
    stream_latency: tuple[float, float] | None
    stream_profile: str
    dsp: DspSnapshot


def native_backend_path() -> Path:
    candidates: list[Path] = []
    module_dir = Path(__file__).resolve().parent
    candidates.append(module_dir / DLL_NAME)
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "downmix_renderer" / DLL_NAME)
        candidates.append(Path(frozen_root) / DLL_NAME)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def native_backend_available() -> bool:
    return native_backend_path().exists()


def native_device_descriptors() -> list[dict[str, object]]:
    if os.name != "nt" or not native_backend_available():
        return []
    dll = ctypes.CDLL(str(native_backend_path()))
    try:
        enumerate_devices = dll.downmix_native_enumerate_devices
    except AttributeError:
        return []
    enumerate_devices.argtypes = [
        ctypes.POINTER(_NativeDeviceDescriptor),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    enumerate_devices.restype = ctypes.c_int32

    count = ctypes.c_uint32(0)
    if not enumerate_devices(None, 0, ctypes.byref(count)) and count.value == 0:
        return []
    if count.value == 0:
        return []

    array_type = _NativeDeviceDescriptor * count.value
    raw_devices = array_type()
    written = ctypes.c_uint32(count.value)
    if not enumerate_devices(raw_devices, count.value, ctypes.byref(written)):
        return []

    descriptors: list[dict[str, object]] = []
    for index in range(min(count.value, written.value)):
        raw = raw_devices[index]
        descriptors.append(
            {
                "endpoint_id": _decode(raw.endpoint_id),
                "name": _decode(raw.name),
                "direction": "input" if int(raw.direction) == 1 else "output",
                "is_default": bool(raw.is_default),
                "max_input_channels": int(raw.max_input_channels),
                "max_output_channels": int(raw.max_output_channels),
                "default_samplerate": int(raw.default_samplerate),
                "ambiguous": bool(raw.ambiguous),
            }
        )
    return descriptors


def _device_name(device: Any) -> str:
    if isinstance(device, str):
        return device
    return str(getattr(device, "name", "") or "")


def _device_endpoint(device: Any) -> str:
    return str(getattr(device, "native_endpoint_id", "") or "")


def _encode(value: str) -> bytes:
    return value.encode("utf-8", errors="replace")


class NativeAudioBackend:
    def __init__(self) -> None:
        if os.name != "nt":
            raise NativeBackendUnavailable("Native audio backend is Windows-only")
        path = native_backend_path()
        if not path.exists():
            raise NativeBackendUnavailable(f"Native audio DLL not found: {path}")
        self._dll = ctypes.CDLL(str(path))
        self._bind()
        self._handle = self._dll.downmix_native_create()
        if not self._handle:
            raise NativeBackendUnavailable("Native audio backend could not be created")
        self.processor = NativeDownmixProcessor(self)

    def start(self, input_device: Any, output_device: Any, profile: str, block_size: int, sample_rate: int) -> None:
        if getattr(self, "_has_endpoint_start", False):
            ok = self._dll.downmix_native_start_endpoints(
                self._handle,
                _encode(_device_endpoint(input_device)),
                _encode(_device_name(input_device)),
                _encode(_device_endpoint(output_device)),
                _encode(_device_name(output_device)),
                profile.encode("ascii", errors="replace"),
                int(block_size),
                int(sample_rate),
            )
        else:
            ok = self._dll.downmix_native_start(
                self._handle,
                _encode(_device_name(input_device)),
                _encode(_device_name(output_device)),
                profile.encode("ascii", errors="replace"),
                int(block_size),
                int(sample_rate),
            )
        if not ok:
            raise RuntimeError(self.last_error() or "Unable to start native audio backend")

    def stop(self) -> None:
        if self._handle:
            self._dll.downmix_native_stop(self._handle)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            self._dll.downmix_native_destroy(handle)

    def snapshot(self) -> NativeEngineRuntime:
        raw = _NativeEngineSnapshot()
        self._dll.downmix_native_snapshot(self._handle, ctypes.byref(raw))
        stream_latency = (
            (float(raw.input_latency), float(raw.output_latency)) if raw.has_latency else None
        )
        return NativeEngineRuntime(
            running=bool(raw.running),
            status=_decode(raw.status),
            input_channels=int(raw.input_channels),
            route=_decode(raw.route) or "No route",
            callback_status=_decode(raw.callback_status),
            callback_status_count=int(raw.callback_status_count),
            dsp_error_count=int(raw.dsp_error_count),
            cpu_load=float(raw.cpu_load),
            stream_latency=stream_latency,
            stream_profile=_decode(raw.stream_profile) or "ultra",
            dsp=_dsp_snapshot(raw.dsp),
        )

    def last_error(self) -> str:
        buffer = ctypes.create_string_buffer(1024)
        self._dll.downmix_native_last_error(self._handle, buffer, len(buffer))
        return _decode(buffer.value)

    def reset_runtime_state(self) -> None:
        self._dll.downmix_native_reset_runtime_state(self._handle)

    def set_preamp_db(self, db_value: float) -> None:
        self._dll.downmix_native_set_preamp_db(self._handle, float(db_value))

    def set_master_volume(self, scalar: float, muted: bool = False) -> None:
        self._dll.downmix_native_set_master_volume(self._handle, float(scalar), int(bool(muted)))

    def set_user_volume(self, scalar: float) -> None:
        self._dll.downmix_native_set_user_volume(self._handle, float(scalar))

    def set_sample_rate(self, sample_rate: int) -> None:
        if not getattr(self, "_has_sample_rate", False):
            return
        self._dll.downmix_native_set_sample_rate(self._handle, int(sample_rate))

    def set_channel_trim_db(self, left_db: float, right_db: float) -> None:
        if not getattr(self, "_has_channel_trim", False):
            return
        self._dll.downmix_native_set_channel_trim_db(self._handle, float(left_db), float(right_db))

    def set_surround_fill_enabled(self, enabled: bool) -> None:
        self._dll.downmix_native_set_surround_fill_enabled(self._handle, int(bool(enabled)))

    def set_upmix_9_1_6_enabled(self, enabled: bool) -> None:
        self._dll.downmix_native_set_upmix_916_enabled(self._handle, int(bool(enabled)))

    def set_channel_sanity_enabled(self, enabled: bool) -> None:
        self._dll.downmix_native_set_channel_sanity_enabled(self._handle, int(bool(enabled)))

    def set_monitor_layout(self, layout_id: str) -> None:
        value = 1 if layout_id == "sharur_9_1_6" else 0
        self._dll.downmix_native_set_monitor_layout(self._handle, value)

    def set_input_layout(self, layout_id: str) -> None:
        value = 1 if layout_id == "sharur_9_1_6" else 0
        self._dll.downmix_native_set_input_layout(self._handle, value)

    def set_peq_config(self, config: PeqRuntimeConfig) -> None:
        if not getattr(self, "_has_peq_config", False):
            return
        global_coeffs = _coeff_array(config.global_cascade)
        left_coeffs = _coeff_array(config.speaker_left)
        right_coeffs = _coeff_array(config.speaker_right)
        self._dll.downmix_native_set_peq_config(
            self._handle,
            int(config.global_cascade.enabled),
            global_coeffs,
            len(config.global_cascade.biquads),
            float(config.global_cascade.preamp_db),
            int(config.speaker_enabled),
            left_coeffs,
            len(config.speaker_left.biquads),
            float(config.speaker_left.preamp_db),
            right_coeffs,
            len(config.speaker_right.biquads),
            float(config.speaker_right.preamp_db),
            int(config.lr_swap_enabled),
        )

    def _bind(self) -> None:
        self._dll.downmix_native_create.restype = ctypes.c_void_p
        self._dll.downmix_native_destroy.argtypes = [ctypes.c_void_p]
        self._dll.downmix_native_start.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        self._dll.downmix_native_start.restype = ctypes.c_int32
        try:
            self._dll.downmix_native_start_endpoints.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            self._dll.downmix_native_start_endpoints.restype = ctypes.c_int32
            self._has_endpoint_start = True
        except AttributeError:
            self._has_endpoint_start = False
        self._dll.downmix_native_stop.argtypes = [ctypes.c_void_p]
        self._dll.downmix_native_snapshot.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_NativeEngineSnapshot),
        ]
        self._dll.downmix_native_last_error.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self._dll.downmix_native_set_preamp_db.argtypes = [ctypes.c_void_p, ctypes.c_float]
        self._dll.downmix_native_set_user_volume.argtypes = [ctypes.c_void_p, ctypes.c_float]
        try:
            self._dll.downmix_native_set_sample_rate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            self._has_sample_rate = True
        except AttributeError:
            self._has_sample_rate = False
        try:
            self._dll.downmix_native_set_channel_trim_db.argtypes = [
                ctypes.c_void_p,
                ctypes.c_float,
                ctypes.c_float,
            ]
            self._has_channel_trim = True
        except AttributeError:
            self._has_channel_trim = False
        self._dll.downmix_native_set_master_volume.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_int32,
        ]
        self._dll.downmix_native_set_surround_fill_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self._dll.downmix_native_set_upmix_916_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self._dll.downmix_native_set_channel_sanity_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self._dll.downmix_native_set_monitor_layout.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self._dll.downmix_native_set_input_layout.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self._dll.downmix_native_reset_runtime_state.argtypes = [ctypes.c_void_p]
        try:
            self._dll.downmix_native_set_peq_config.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int32,
                ctypes.POINTER(ctypes.c_double),
                ctypes.c_uint32,
                ctypes.c_double,
                ctypes.c_int32,
                ctypes.POINTER(ctypes.c_double),
                ctypes.c_uint32,
                ctypes.c_double,
                ctypes.POINTER(ctypes.c_double),
                ctypes.c_uint32,
                ctypes.c_double,
                ctypes.c_int32,
            ]
            self._has_peq_config = True
        except AttributeError:
            self._has_peq_config = False
        self._dll.downmix_native_process_float32.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_uint32,
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_float),
        ]
        self._dll.downmix_native_process_float32.restype = ctypes.c_int32

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class NativeDownmixProcessor:
    def __init__(self, backend: NativeAudioBackend) -> None:
        self._backend = backend

    def set_preamp_db(self, db_value: float) -> None:
        self._backend.set_preamp_db(db_value)

    def set_master_volume(self, scalar: float, muted: bool = False) -> None:
        self._backend.set_master_volume(scalar, muted)

    def set_user_volume(self, scalar: float) -> None:
        self._backend.set_user_volume(scalar)

    def set_sample_rate(self, sample_rate: int) -> None:
        self._backend.set_sample_rate(sample_rate)

    def set_channel_trim_db(self, left_db: float, right_db: float) -> None:
        self._backend.set_channel_trim_db(left_db, right_db)

    def set_surround_fill_enabled(self, enabled: bool) -> None:
        self._backend.set_surround_fill_enabled(enabled)

    def set_upmix_9_1_6_enabled(self, enabled: bool) -> None:
        self._backend.set_upmix_9_1_6_enabled(enabled)

    def set_channel_sanity_enabled(self, enabled: bool) -> None:
        self._backend.set_channel_sanity_enabled(enabled)

    def set_monitor_layout(self, layout_id: str) -> None:
        self._backend.set_monitor_layout(layout_id)

    def set_input_layout(self, layout_id: str) -> None:
        self._backend.set_input_layout(layout_id)

    def set_peq_config(self, config: PeqRuntimeConfig) -> None:
        self._backend.set_peq_config(config)

    def reset_limiter(self) -> None:
        self.reset_runtime_state()

    def reset_runtime_state(self) -> None:
        self._backend.reset_runtime_state()

    def snapshot(self) -> DspSnapshot:
        return self._backend.snapshot().dsp

    def process(self, indata: np.ndarray, outdata: np.ndarray | None = None) -> np.ndarray:
        samples = np.ascontiguousarray(indata, dtype=np.float32)
        if samples.ndim != 2:
            raise ValueError("indata must be a frames x channels array")
        frames, channels = samples.shape
        if outdata is None:
            rendered = np.zeros((frames, OUTPUT_CHANNELS), dtype=np.float32)
        else:
            if outdata.shape[0] != frames or outdata.shape[1] < OUTPUT_CHANNELS:
                raise ValueError("outdata must match frames and have at least 2 channels")
            if outdata.dtype != np.float32 or not outdata.flags.c_contiguous:
                raise ValueError("outdata must be a contiguous float32 array")
            if outdata.shape[1] > OUTPUT_CHANNELS:
                outdata.fill(0.0)
            rendered = outdata[:, :OUTPUT_CHANNELS]
        ok = self._backend._dll.downmix_native_process_float32(
            self._backend._handle,
            samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            frames,
            channels,
            rendered.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        )
        if not ok:
            raise RuntimeError("Native DSP processing failed")
        return rendered


def _decode(value: bytes | ctypes.Array[ctypes.c_char]) -> str:
    raw = bytes(value)
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _array(values: ctypes.Array[ctypes.c_float]) -> np.ndarray:
    return np.array(list(values), dtype=np.float32)


def _coeff_array(cascade: PeqCascade) -> ctypes.Array[ctypes.c_double]:
    values: list[float] = []
    for coeff in cascade.biquads:
        values.extend(coeff.as_tuple())
    if not values:
        values = [0.0]
    array_type = ctypes.c_double * len(values)
    return array_type(*values)


def _dsp_snapshot(raw: _NativeDspSnapshot) -> DspSnapshot:
    return DspSnapshot(
        channel_levels=_array(raw.channel_levels),
        channel_rms=_array(raw.channel_rms),
        raw_channel_levels=_array(raw.raw_channel_levels),
        raw_channel_rms=_array(raw.raw_channel_rms),
        left_meter=float(raw.left_meter),
        right_meter=float(raw.right_meter),
        preamp_db=float(raw.preamp_db),
        trim_left_db=float(raw.trim_left_db),
        trim_right_db=float(raw.trim_right_db),
        limiter_gain=float(raw.limiter_gain),
        clipping=bool(raw.clipping),
        user_volume=float(raw.user_volume),
        master_volume=float(raw.master_volume),
        master_muted=bool(raw.master_muted),
        surround_fill_enabled=bool(raw.surround_fill_enabled),
        surround_fill_active=bool(raw.surround_fill_active),
        upmix_9_1_6_enabled=bool(raw.upmix_9_1_6_enabled),
        upmix_9_1_6_active=bool(raw.upmix_9_1_6_active),
        channel_sanity_enabled=bool(raw.channel_sanity_enabled),
        channel_sanity_active=bool(raw.channel_sanity_active),
    )
