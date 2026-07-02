from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Lock
from time import monotonic

import sounddevice as sd

from .constants import BLOCK_SIZE, MAX_INPUT_CHANNELS, OUTPUT_CHANNELS, SAMPLE_RATE
from .devices import AudioDevice, WASAPI_HOSTAPI
from .dsp import DownmixProcessor, DspSnapshot
from .native_audio import NativeAudioBackend, NativeBackendUnavailable
from .sample_rates import (
    DEFAULT_SAMPLE_RATE_MODE,
    normalize_sample_rate_mode,
    resolve_sample_rate,
)
from .volume import VolumeFollower, VolumeState, create_volume_follower


@dataclass(frozen=True)
class EngineSnapshot:
    running: bool
    status: str
    input_device: AudioDevice | None
    output_device: AudioDevice | None
    input_channels: int
    route: str
    callback_status: str
    callback_status_count: int
    callback_status_time: float
    dsp_error_count: int
    callback_invocation_count: int
    processed_frame_count: int
    xrun_count: int
    mmcss_registered: bool
    cpu_load: float
    stream_latency: tuple[float, float] | None
    stream_profile: str
    sample_rate: int
    sample_rate_mode: str
    volume: VolumeState
    dsp: DspSnapshot


class OutputKeepAwake:
    def __init__(self) -> None:
        self._enabled = False
        self._stream: sd.OutputStream | None = None
        self._device_id: int | None = None
        self._sample_rate = SAMPLE_RATE
        self._stream_sample_rate = SAMPLE_RATE
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active(self) -> bool:
        return self._stream is not None

    @property
    def last_error(self) -> str:
        return self._last_error

    def set_enabled(
        self,
        enabled: bool,
        output_device: AudioDevice | None,
        renderer_running: bool,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._enabled = bool(enabled)
        self._sample_rate = int(sample_rate)
        if not self._enabled or renderer_running:
            self.stop()
            return
        self.update_output_device(output_device, renderer_running=False, sample_rate=self._sample_rate)

    def update_output_device(
        self,
        output_device: AudioDevice | None,
        renderer_running: bool,
        sample_rate: int | None = None,
    ) -> None:
        if sample_rate is not None:
            self._sample_rate = int(sample_rate)
        if renderer_running or not self._enabled or output_device is None:
            self.stop()
            return
        if self._stream is not None and self._device_id == output_device.id and self._stream_sample_rate == self._sample_rate:
            return
        self.stop()
        stream: sd.OutputStream | None = None
        try:
            stream = sd.OutputStream(
                samplerate=self._sample_rate,
                blocksize=BLOCK_SIZE,
                channels=OUTPUT_CHANNELS,
                device=output_device.id,
                dtype="float32",
                latency="low",
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            self._last_error = str(exc)
            if stream is not None:
                _safe_close_stream(stream)
            return
        self._stream = stream
        self._device_id = output_device.id
        self._stream_sample_rate = self._sample_rate
        self._last_error = ""

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        self._device_id = None
        self._stream_sample_rate = self._sample_rate
        if stream is not None:
            _safe_close_stream(stream)

    def close(self) -> None:
        self._enabled = False
        self._last_error = ""
        self.stop()

    def _callback(self, outdata, frames, time, status) -> None:
        outdata.fill(0.0)


STREAM_PROFILES = {
    "ultra": "ULTRA Mode",
    "raw": "RAW Mode",
}
DEFAULT_STREAM_PROFILE = "ultra"
LOW_LATENCY_BLOCK_SIZE = BLOCK_SIZE
ULTRA_BLOCK_SIZE = 128
_PROFILE_ALIASES = {
    "legacy_low": "raw",
    "low_latency": "raw",
    "low": "raw",
    "raw_mode": "raw",
    "ultra_mode": "ultra",
    "normal": "ultra",
    "balanced": "ultra",
    "safe": "ultra",
    "stable": "ultra",
}
_PROFILE_FALLBACKS = {
    "ultra": ("ultra", "raw"),
    "raw": ("raw",),
}


class AudioEngine:
    def __init__(
        self,
        processor: DownmixProcessor | None = None,
        volume_follower: VolumeFollower | None = None,
        backend: str | None = None,
    ) -> None:
        self._native_backend: NativeAudioBackend | None = None
        backend_mode = (backend or os.environ.get("DOWNMIX_RENDERER_AUDIO_BACKEND") or "native").casefold()
        if processor is not None or backend_mode in {"python", "legacy"}:
            self.processor = processor or DownmixProcessor()
        else:
            try:
                self._native_backend = NativeAudioBackend()
                self.processor = self._native_backend.processor
            except (NativeBackendUnavailable, OSError):
                self._native_backend = None
                self.processor = DownmixProcessor()
        self.volume_follower = volume_follower or create_volume_follower()
        self._stream: sd.Stream | None = None
        self._state_lock = Lock()
        self._running = False
        self._status = "Stopped"
        self._input_device: AudioDevice | None = None
        self._output_device: AudioDevice | None = None
        self._input_channels = 0
        self._route = "No route"
        self._callback_status = ""
        self._callback_status_count = 0
        self._callback_status_time = 0.0
        self._dsp_error_count = 0
        self._callback_invocation_count = 0
        self._processed_frame_count = 0
        self._xrun_count = 0
        self._stream_profile = DEFAULT_STREAM_PROFILE
        self._sample_rate_mode = DEFAULT_SAMPLE_RATE_MODE
        self._sample_rate = SAMPLE_RATE
        self._volume_state = self.volume_follower.get_state()
        self._last_volume_poll = monotonic()
        self._volume_poll_interval = 0.04
        self.keep_awake = OutputKeepAwake()
        self.processor.set_master_volume(self._volume_state.scalar, self._volume_state.muted)

    def start(
        self,
        input_device: AudioDevice,
        output_device: AudioDevice,
        stream_profile: str = DEFAULT_STREAM_PROFILE,
        sample_rate_mode: str = DEFAULT_SAMPLE_RATE_MODE,
    ) -> None:
        self.keep_awake.stop()
        self.stop(resume_keep_awake=False)

        if input_device.hostapi != WASAPI_HOSTAPI or output_device.hostapi != WASAPI_HOSTAPI:
            raise RuntimeError("Renderer route must use Windows WASAPI devices")
        if input_device.max_input_channels < MAX_INPUT_CHANNELS:
            raise RuntimeError("Input must expose at least 16 channels")
        if output_device.max_output_channels < OUTPUT_CHANNELS:
            raise RuntimeError("Output must expose at least 2 channels")

        prepare_output = getattr(self.volume_follower, "prepare_output_endpoint", None)
        if callable(prepare_output):
            try:
                prepare_output(output_device.native_endpoint_for("output"))
            except Exception:
                pass
        self._refresh_volume_state(force=True)

        requested_profile = _normalize_stream_profile(stream_profile)
        requested_sample_rate_mode = _normalize_sample_rate_mode(sample_rate_mode)
        sample_rate = _resolve_sample_rate(requested_sample_rate_mode, input_device, output_device)
        active_profile = requested_profile
        if hasattr(self.processor, "set_sample_rate"):
            self.processor.set_sample_rate(sample_rate)
        self.processor.reset_runtime_state()

        last_error: Exception | None = None
        stream: sd.Stream | None = None
        if self._native_backend is not None:
            for candidate in _profile_start_candidates(requested_profile):
                try:
                    blocksize, _ = _stream_settings(candidate, sample_rate)
                    self._native_backend.start(input_device, output_device, candidate, blocksize, sample_rate)
                    active_profile = candidate
                    break
                except Exception as exc:
                    last_error = exc
                    self._native_backend.stop()
            else:
                detail = f"{type(last_error).__name__}: {last_error}" if last_error else "Unknown stream error"
                raise RuntimeError(f"Unable to start C++ WASAPI stream: {detail}")
        else:
            for candidate in _profile_start_candidates(requested_profile):
                try:
                    stream = self._open_stream(input_device, output_device, candidate, sample_rate)
                    stream.start()
                    active_profile = candidate
                    break
                except Exception as exc:
                    last_error = exc
                    if stream is not None:
                        _safe_close_stream(stream)
                    stream = None

            if stream is None:
                detail = f"{type(last_error).__name__}: {last_error}" if last_error else "Unknown stream error"
                raise RuntimeError(f"Unable to start WASAPI stream: {detail}")
            self._stream = stream

        with self._state_lock:
            self._running = True
            backend_label = "C++" if self._native_backend is not None else STREAM_PROFILES[active_profile]
            self._status = f"Running ({backend_label})"
            self._input_device = input_device
            self._output_device = output_device
            self._input_channels = MAX_INPUT_CHANNELS
            self._callback_status = ""
            self._callback_status_count = 0
            self._callback_status_time = 0.0
            self._dsp_error_count = 0
            self._callback_invocation_count = 0
            self._processed_frame_count = 0
            self._xrun_count = 0
            self._stream_profile = active_profile
            self._sample_rate_mode = requested_sample_rate_mode
            self._sample_rate = sample_rate
            self._route = (
                f"{input_device.name} ({input_device.hostapi}) -> "
                f"{output_device.name} ({output_device.hostapi})"
            )

    def stop(self, resume_keep_awake: bool = True) -> None:
        if self._native_backend is not None:
            self._native_backend.stop()
        else:
            stream = self._stream
            self._stream = None
            if stream is not None:
                _safe_close_stream(stream)
        with self._state_lock:
            self._running = False
            self._status = "Stopped"
            output_device = self._output_device
        if resume_keep_awake:
            self.keep_awake.update_output_device(output_device, renderer_running=False, sample_rate=self._sample_rate)

    def set_keep_output_awake(
        self,
        enabled: bool,
        output_device: AudioDevice | None = None,
        sample_rate: int | None = None,
    ) -> None:
        with self._state_lock:
            running = self._running
            active_output = output_device or self._output_device
            if sample_rate is not None:
                self._sample_rate = int(sample_rate)
            active_sample_rate = self._sample_rate
        self.keep_awake.set_enabled(enabled, active_output, running, active_sample_rate)

    def refresh_keep_output_awake(
        self,
        output_device: AudioDevice | None = None,
        sample_rate: int | None = None,
    ) -> None:
        with self._state_lock:
            running = self._running
            active_output = output_device or self._output_device
            if sample_rate is not None:
                self._sample_rate = int(sample_rate)
            active_sample_rate = self._sample_rate
        self.keep_awake.update_output_device(active_output, running, active_sample_rate)

    def poll_volume(self) -> VolumeState:
        return self._refresh_volume_state(force=False)

    def _refresh_volume_state(self, force: bool = False) -> VolumeState:
        now = monotonic()
        if not force and now - self._last_volume_poll < self._volume_poll_interval:
            return self._volume_state
        self._last_volume_poll = now
        self._volume_state = self.volume_follower.get_state()
        setter = getattr(self.processor, "set_master_volume", None)
        if callable(setter):
            setter(self._volume_state.scalar, self._volume_state.muted)
        return self._volume_state

    def snapshot(self) -> EngineSnapshot:
        cpu_load = 0.0
        stream_latency: tuple[float, float] | None = None
        native_snapshot = self._native_backend.snapshot() if self._native_backend is not None else None
        stream = self._stream
        if native_snapshot is not None:
            cpu_load = native_snapshot.cpu_load
            stream_latency = native_snapshot.stream_latency
        elif stream is not None:
            try:
                cpu_load = float(stream.cpu_load)
            except Exception:
                cpu_load = 0.0
            try:
                latency = stream.latency
                if isinstance(latency, tuple) and len(latency) == 2:
                    stream_latency = (float(latency[0]), float(latency[1]))
            except Exception:
                stream_latency = None
        with self._state_lock:
            dsp_snapshot = native_snapshot.dsp if native_snapshot is not None else self.processor.snapshot()
            running = native_snapshot.running if native_snapshot is not None else self._running
            status = native_snapshot.status if native_snapshot is not None else self._status
            route = native_snapshot.route if native_snapshot is not None else self._route
            input_channels = native_snapshot.input_channels if native_snapshot is not None else self._input_channels
            callback_status = native_snapshot.callback_status if native_snapshot is not None else self._callback_status
            callback_status_count = (
                native_snapshot.callback_status_count if native_snapshot is not None else self._callback_status_count
            )
            dsp_error_count = native_snapshot.dsp_error_count if native_snapshot is not None else self._dsp_error_count
            callback_invocation_count = (
                native_snapshot.callback_invocation_count
                if native_snapshot is not None
                else self._callback_invocation_count
            )
            processed_frame_count = (
                native_snapshot.processed_frame_count if native_snapshot is not None else self._processed_frame_count
            )
            xrun_count = native_snapshot.xrun_count if native_snapshot is not None else self._xrun_count
            mmcss_registered = native_snapshot.mmcss_registered if native_snapshot is not None else False
            stream_profile = native_snapshot.stream_profile if native_snapshot is not None else self._stream_profile
            sample_rate = self._sample_rate
            sample_rate_mode = self._sample_rate_mode
            return EngineSnapshot(
                running=running,
                status=status,
                input_device=self._input_device,
                output_device=self._output_device,
                input_channels=input_channels,
                route=route,
                callback_status=callback_status,
                callback_status_count=callback_status_count,
                callback_status_time=self._callback_status_time,
                dsp_error_count=dsp_error_count,
                callback_invocation_count=callback_invocation_count,
                processed_frame_count=processed_frame_count,
                xrun_count=xrun_count,
                mmcss_registered=mmcss_registered,
                cpu_load=cpu_load,
                stream_latency=stream_latency,
                stream_profile=stream_profile,
                sample_rate=sample_rate,
                sample_rate_mode=sample_rate_mode,
                volume=self._volume_state,
                dsp=dsp_snapshot,
            )

    def close(self) -> None:
        self.stop(resume_keep_awake=False)
        self.keep_awake.close()
        if self._native_backend is not None:
            self._native_backend.close()
        self.volume_follower.close()

    @property
    def uses_native_backend(self) -> bool:
        return self._native_backend is not None

    def _open_stream(
        self,
        input_device: AudioDevice,
        output_device: AudioDevice,
        stream_profile: str,
        sample_rate: int,
    ) -> sd.Stream:
        blocksize, latency = _stream_settings(stream_profile, sample_rate)
        return sd.Stream(
            samplerate=sample_rate,
            blocksize=blocksize,
            channels=(MAX_INPUT_CHANNELS, OUTPUT_CHANNELS),
            device=(input_device.id, output_device.id),
            dtype="float32",
            latency=latency,
            callback=self._callback,
        )

    def _callback(self, indata, outdata, frames, time, status) -> None:
        self._callback_invocation_count += 1
        self._processed_frame_count += int(frames)
        if status:
            status_text = str(status)
            now = monotonic()
            if self._state_lock.acquire(False):
                try:
                    self._status = status_text
                    self._callback_status = status_text
                    self._callback_status_count += 1
                    self._xrun_count += 1
                    self._callback_status_time = now
                finally:
                    self._state_lock.release()
        try:
            self.processor.process(indata, outdata)
        except Exception as exc:
            outdata.fill(0.0)
            if self._state_lock.acquire(False):
                try:
                    self._status = f"DSP error: {exc}"
                    self._dsp_error_count += 1
                finally:
                    self._state_lock.release()

def _normalize_stream_profile(profile: str) -> str:
    normalized = _PROFILE_ALIASES.get(profile, profile)
    return normalized if normalized in STREAM_PROFILES else DEFAULT_STREAM_PROFILE


def _profile_start_candidates(profile: str) -> tuple[str, ...]:
    return _PROFILE_FALLBACKS[_normalize_stream_profile(profile)]


def _normalize_sample_rate_mode(value: object) -> str:
    return normalize_sample_rate_mode(value)


def _resolve_sample_rate(
    sample_rate_mode: object,
    input_device: AudioDevice | None = None,
    output_device: AudioDevice | None = None,
) -> int:
    return resolve_sample_rate(sample_rate_mode, input_device, output_device)


def _scaled_stream_block_size(base_block_size: int, sample_rate: int) -> int:
    try:
        rate = int(sample_rate)
    except (TypeError, ValueError):
        rate = SAMPLE_RATE
    if rate <= SAMPLE_RATE:
        return int(base_block_size)
    scaled = int(round(base_block_size * (rate / SAMPLE_RATE)))
    return max(64, min(4096, scaled))


def _stream_settings(stream_profile: str, sample_rate: int = SAMPLE_RATE) -> tuple[int, str]:
    stream_profile = _normalize_stream_profile(stream_profile)
    if stream_profile == "ultra":
        return _scaled_stream_block_size(ULTRA_BLOCK_SIZE, sample_rate), "low"
    if stream_profile == "raw":
        return _scaled_stream_block_size(LOW_LATENCY_BLOCK_SIZE, sample_rate), "low"
    return _scaled_stream_block_size(ULTRA_BLOCK_SIZE, sample_rate), "low"


def _safe_close_stream(stream: sd.Stream) -> None:
    try:
        stream.stop()
    except Exception:
        pass
    try:
        stream.close()
    except Exception:
        pass
