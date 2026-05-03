from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import numpy as np

from .constants import DEFAULT_PREAMP_DB, MAX_INPUT_CHANNELS, OUTPUT_CHANNELS, SAMPLE_RATE
from .matrix import MATRIX

LFE_CHANNEL_INDEX = 3
LFE_LOWPASS_CUTOFF_HZ = 125.0
DRY_DELAY_SAMPLES = 172
_BUTTERWORTH_Q_VALUES = (0.541196100146197, 1.3065629648763766)


def db_to_linear(db_value: float) -> float:
    return float(10 ** (db_value / 20.0))


def linear_to_db(value: float) -> float:
    return float(20.0 * np.log10(max(float(value), 1e-6)))


def _butterworth_lowpass_sos(cutoff_hz: float, sample_rate: float) -> np.ndarray:
    k = float(np.tan(np.pi * cutoff_hz / sample_rate))
    sections = []
    for q in _BUTTERWORTH_Q_VALUES:
        norm = 1.0 / (1.0 + k / q + k * k)
        b0 = k * k * norm
        b1 = 2.0 * b0
        b2 = b0
        a1 = 2.0 * (k * k - 1.0) * norm
        a2 = (1.0 - k / q + k * k) * norm
        sections.append((b0, b1, b2, a1, a2))
    return np.array(sections, dtype=np.float64)


@dataclass(frozen=True)
class DspSnapshot:
    channel_levels: np.ndarray
    left_meter: float
    right_meter: float
    preamp_db: float
    limiter_gain: float
    clipping: bool
    user_volume: float
    master_volume: float
    master_muted: bool

    @property
    def active_channel_count(self) -> int:
        return int(np.count_nonzero(self.channel_levels > 1e-4))


class DownmixProcessor:
    """Real-time-safe 16ch-to-stereo downmixer.

    The matrix is fixed. Preamp provides renderer headroom. Master volume is
    intentionally separate so Windows media keys can control loudness without
    changing the Sharur matrix or the saved preamp value.
    """

    def __init__(
        self,
        preamp_db: float = DEFAULT_PREAMP_DB,
        matrix: np.ndarray = MATRIX,
        max_channels: int = MAX_INPUT_CHANNELS,
    ) -> None:
        self.matrix = np.asarray(matrix, dtype=np.float64)
        if self.matrix.shape != (max_channels, OUTPUT_CHANNELS):
            raise ValueError("matrix must be 16x2")

        self.max_channels = max_channels
        self._config_lock = Lock()
        self._state_lock = Lock()
        self._preamp_db = float(preamp_db)
        self._preamp_gain = db_to_linear(preamp_db)
        self._user_volume = 1.0
        self._master_volume = 1.0
        self._master_muted = False
        self._limiter_gain = 1.0

        self._scratch_frames = 0
        self._input16 = np.zeros((0, max_channels), dtype=np.float32)
        self._processed16 = np.zeros((0, max_channels), dtype=np.float32)
        self._lfe_scratch = np.zeros(0, dtype=np.float32)
        self._stereo = np.zeros((0, OUTPUT_CHANNELS), dtype=np.float64)
        self._dry_delay_buffer = np.zeros((DRY_DELAY_SAMPLES, max_channels), dtype=np.float32)
        self._lfe_lowpass_sos = _butterworth_lowpass_sos(LFE_LOWPASS_CUTOFF_HZ, SAMPLE_RATE)
        self._lfe_filter_state = np.zeros((len(self._lfe_lowpass_sos), 2), dtype=np.float64)

        self._channel_levels = np.zeros(max_channels, dtype=np.float32)
        self._left_meter = 0.0
        self._right_meter = 0.0
        self._clipping = False

    def set_preamp_db(self, db_value: float) -> None:
        with self._config_lock:
            self._preamp_db = float(db_value)
            self._preamp_gain = db_to_linear(self._preamp_db)

    def set_master_volume(self, scalar: float, muted: bool = False) -> None:
        scalar = min(1.0, max(0.0, float(scalar)))
        with self._config_lock:
            self._master_volume = scalar
            self._master_muted = bool(muted)

    def set_user_volume(self, scalar: float) -> None:
        scalar = min(1.0, max(0.0, float(scalar)))
        with self._config_lock:
            self._user_volume = scalar

    def reset_limiter(self) -> None:
        self.reset_runtime_state()

    def reset_runtime_state(self) -> None:
        self._limiter_gain = 1.0
        self._dry_delay_buffer.fill(0.0)
        self._lfe_filter_state.fill(0.0)

    def process(self, indata: np.ndarray, outdata: np.ndarray | None = None) -> np.ndarray:
        if indata.ndim != 2:
            raise ValueError("indata must be a frames x channels array")

        frames, channels = indata.shape
        self._ensure_scratch(frames)
        input16 = self._prepare_input(indata, frames, channels)
        channel_levels = (
            np.max(np.abs(input16), axis=0).astype(np.float32, copy=False)
            if frames
            else np.zeros(self.max_channels, dtype=np.float32)
        )
        processed16 = self._apply_sharur_processing(input16, frames)

        with self._config_lock:
            preamp_gain = self._preamp_gain
            preamp_db = self._preamp_db
            user_volume = self._user_volume
            master_volume = self._master_volume
            master_muted = self._master_muted

        np.dot(processed16, self.matrix, out=self._stereo[:frames])
        self._stereo[:frames] *= preamp_gain

        peak_before_limiter = float(np.max(np.abs(self._stereo[:frames]))) if frames else 0.0
        target_gain = 1.0
        clipping = False
        if peak_before_limiter > 1.0:
            target_gain = 1.0 / peak_before_limiter
            clipping = True

        alpha = 0.4 if target_gain < self._limiter_gain else 0.05
        smoothed_gain = (1.0 - alpha) * self._limiter_gain + alpha * target_gain
        applied_limiter_gain = min(smoothed_gain, target_gain) if clipping else smoothed_gain
        self._limiter_gain = smoothed_gain

        self._stereo[:frames] *= applied_limiter_gain
        if master_muted:
            self._stereo[:frames] *= 0.0
        else:
            self._stereo[:frames] *= master_volume * user_volume

        if outdata is None:
            rendered = self._stereo[:frames].copy()
        else:
            outdata.fill(0.0)
            if outdata.shape[0] != frames or outdata.shape[1] < OUTPUT_CHANNELS:
                raise ValueError("outdata must match frames and have at least 2 channels")
            outdata[:, :OUTPUT_CHANNELS] = self._stereo[:frames]
            rendered = outdata[:, :OUTPUT_CHANNELS]

        left_meter = float(np.max(np.abs(rendered[:, 0]))) if frames else 0.0
        right_meter = float(np.max(np.abs(rendered[:, 1]))) if frames else 0.0

        with self._state_lock:
            self._channel_levels[:] = channel_levels
            self._left_meter = left_meter
            self._right_meter = right_meter
            self._clipping = clipping
            self._snapshot_preamp_db = preamp_db
            self._snapshot_user_volume = user_volume
            self._snapshot_master_volume = master_volume
            self._snapshot_master_muted = master_muted

        return rendered

    def snapshot(self) -> DspSnapshot:
        with self._state_lock:
            preamp_db = getattr(self, "_snapshot_preamp_db", self._preamp_db)
            user_volume = getattr(self, "_snapshot_user_volume", self._user_volume)
            master_volume = getattr(self, "_snapshot_master_volume", self._master_volume)
            master_muted = getattr(self, "_snapshot_master_muted", self._master_muted)
            return DspSnapshot(
                channel_levels=self._channel_levels.copy(),
                left_meter=float(self._left_meter),
                right_meter=float(self._right_meter),
                preamp_db=float(preamp_db),
                limiter_gain=float(self._limiter_gain),
                clipping=bool(self._clipping),
                user_volume=float(user_volume),
                master_volume=float(master_volume),
                master_muted=bool(master_muted),
            )

    def _ensure_scratch(self, frames: int) -> None:
        if frames <= self._scratch_frames:
            return
        self._scratch_frames = frames
        self._input16 = np.zeros((frames, self.max_channels), dtype=np.float32)
        self._processed16 = np.zeros((frames, self.max_channels), dtype=np.float32)
        self._lfe_scratch = np.zeros(frames, dtype=np.float32)
        self._stereo = np.zeros((frames, OUTPUT_CHANNELS), dtype=np.float64)

    def _prepare_input(self, indata: np.ndarray, frames: int, channels: int) -> np.ndarray:
        input16 = self._input16[:frames]
        input16.fill(0.0)
        copy_channels = min(channels, self.max_channels)
        if copy_channels:
            input16[:, :copy_channels] = indata[:, :copy_channels]
        return input16

    def _apply_sharur_processing(self, input16: np.ndarray, frames: int) -> np.ndarray:
        processed16 = self._processed16[:frames]
        if not frames:
            return processed16

        lfe = self._filter_lfe(input16[:, LFE_CHANNEL_INDEX], frames)
        self._apply_dry_delay(input16, processed16, frames)
        processed16[:, LFE_CHANNEL_INDEX] = lfe
        return processed16

    def _filter_lfe(self, samples: np.ndarray, frames: int) -> np.ndarray:
        lfe = self._lfe_scratch[:frames]
        lfe[:] = samples

        for section_index, (b0, b1, b2, a1, a2) in enumerate(self._lfe_lowpass_sos):
            z1, z2 = self._lfe_filter_state[section_index]
            for frame in range(frames):
                sample = float(lfe[frame])
                output = b0 * sample + z1
                z1 = b1 * sample - a1 * output + z2
                z2 = b2 * sample - a2 * output
                lfe[frame] = output
            self._lfe_filter_state[section_index, 0] = z1
            self._lfe_filter_state[section_index, 1] = z2

        return lfe

    def _apply_dry_delay(self, input16: np.ndarray, processed16: np.ndarray, frames: int) -> None:
        head = min(frames, DRY_DELAY_SAMPLES)
        processed16[:head] = self._dry_delay_buffer[:head]
        if frames > DRY_DELAY_SAMPLES:
            processed16[DRY_DELAY_SAMPLES:frames] = input16[: frames - DRY_DELAY_SAMPLES]

        if frames >= DRY_DELAY_SAMPLES:
            self._dry_delay_buffer[:] = input16[frames - DRY_DELAY_SAMPLES:frames]
        else:
            keep = DRY_DELAY_SAMPLES - frames
            self._dry_delay_buffer[:keep] = self._dry_delay_buffer[frames:]
            self._dry_delay_buffer[keep:] = input16[:frames]
