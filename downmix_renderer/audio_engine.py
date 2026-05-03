from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic

import sounddevice as sd

from .constants import BLOCK_SIZE, MAX_INPUT_CHANNELS, OUTPUT_CHANNELS, SAMPLE_RATE
from .devices import AudioDevice, WASAPI_HOSTAPI
from .dsp import DownmixProcessor, DspSnapshot
from .volume import VolumeFollower, VolumeState, create_volume_follower


@dataclass(frozen=True)
class EngineSnapshot:
    running: bool
    status: str
    input_device: AudioDevice | None
    output_device: AudioDevice | None
    input_channels: int
    route: str
    volume: VolumeState
    dsp: DspSnapshot


class AudioEngine:
    def __init__(
        self,
        processor: DownmixProcessor | None = None,
        volume_follower: VolumeFollower | None = None,
    ) -> None:
        self.processor = processor or DownmixProcessor()
        self.volume_follower = volume_follower or create_volume_follower()
        self._stream: sd.Stream | None = None
        self._state_lock = Lock()
        self._running = False
        self._status = "Stopped"
        self._input_device: AudioDevice | None = None
        self._output_device: AudioDevice | None = None
        self._input_channels = 0
        self._route = "No route"
        self._volume_state = self.volume_follower.get_state()
        self._last_volume_poll = monotonic()
        self._volume_poll_interval = 0.10
        self.processor.set_master_volume(self._volume_state.scalar, self._volume_state.muted)

    def start(self, input_device: AudioDevice, output_device: AudioDevice) -> None:
        self.stop()

        if input_device.hostapi != WASAPI_HOSTAPI or output_device.hostapi != WASAPI_HOSTAPI:
            raise RuntimeError("Renderer route must use Windows WASAPI devices")
        if input_device.max_input_channels < MAX_INPUT_CHANNELS:
            raise RuntimeError("Input must expose at least 16 channels")
        if output_device.max_output_channels < OUTPUT_CHANNELS:
            raise RuntimeError("Output must expose at least 2 channels")

        self.processor.reset_runtime_state()
        self._stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=(MAX_INPUT_CHANNELS, OUTPUT_CHANNELS),
            device=(input_device.id, output_device.id),
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        self._stream.start()

        with self._state_lock:
            self._running = True
            self._status = "Running"
            self._input_device = input_device
            self._output_device = output_device
            self._input_channels = MAX_INPUT_CHANNELS
            self._route = (
                f"{input_device.name} ({input_device.hostapi}) -> "
                f"{output_device.name} ({output_device.hostapi})"
            )

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._state_lock:
            self._running = False
            self._status = "Stopped"

    def poll_volume(self) -> VolumeState:
        now = monotonic()
        if now - self._last_volume_poll < self._volume_poll_interval:
            return self._volume_state
        self._last_volume_poll = now
        self._volume_state = self.volume_follower.get_state()
        self.processor.set_master_volume(self._volume_state.scalar, self._volume_state.muted)
        return self._volume_state

    def snapshot(self) -> EngineSnapshot:
        with self._state_lock:
            return EngineSnapshot(
                running=self._running,
                status=self._status,
                input_device=self._input_device,
                output_device=self._output_device,
                input_channels=self._input_channels,
                route=self._route,
                volume=self._volume_state,
                dsp=self.processor.snapshot(),
            )

    def close(self) -> None:
        self.stop()
        self.volume_follower.close()

    def _callback(self, indata, outdata, frames, time, status) -> None:
        if status:
            with self._state_lock:
                self._status = str(status)
        try:
            self.processor.process(indata, outdata)
        except Exception as exc:
            outdata.fill(0.0)
            with self._state_lock:
                self._status = f"DSP error: {exc}"
