from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Lock

import numpy as np

from .constants import (
    DEFAULT_CHANNEL_CONFIG,
    DEFAULT_PREAMP_DB,
    MAX_INPUT_CHANNELS,
    OUTPUT_CHANNELS,
    SAMPLE_RATE,
    TRIM_MAX_DB,
    TRIM_MIN_DB,
)
from .layouts import (
    GENERATED_SHARUR_SPEAKERS,
    SHARUR_9_1_6_LAYOUT,
    WINDOWS_7_1_LAYOUT,
    WINDOWS_TO_SHARUR_COPY,
)
from .matrix import SHARUR_916_STEREO_MATRIX, WINDOWS_71_STEREO_MATRIX
from .peq import MAX_FILTERS_PER_STAGE, BiquadCoefficients, PeqCascade, PeqRuntimeConfig

LFE_CHANNEL_INDEX = 3
LFE_LOWPASS_CUTOFF_HZ = 125.0
DRY_DELAY_SAMPLES = 172
SURROUND_FILL_PAIRS = ((4, 6), (5, 7))
SURROUND_FILL_THRESHOLD = 1e-4
CHANNEL_SANITY_THRESHOLD = 1e-4
CHANNEL_SANITY_CORRELATION = 0.995
CHANNEL_SANITY_MIN_DUPLICATES = 3
UPMIX_916_THRESHOLD = 1e-4
UPMIX_916_AIR_HIGHPASS_HZ = 3500.0
UPMIX_916_GENERATED_GAIN = 0.5011872336272722
_BUTTERWORTH_Q_VALUES = (0.541196100146197, 1.3065629648763766)
_UPMIX_DECORRELATION_COEFFS = (
    (0.57, -0.49, 0.63, -0.41),
    (-0.46, 0.61, -0.38, 0.54),
    (0.52, -0.67, 0.46, -0.59),
    (-0.62, 0.43, -0.55, 0.36),
    (0.49, -0.58, 0.37, -0.66),
    (-0.53, 0.39, -0.61, 0.48),
    (0.44, -0.64, 0.56, -0.35),
    (-0.59, 0.51, -0.42, 0.63),
)
_UPMIX_FILTER_SLOTS = 24
PEQ_CROSSFADE_SAMPLES = 128
PEQ_DENORMAL_GUARD = 1e-30
SOUND_ENHANCER_MAKEUP_DB = 7.5
SOUND_ENHANCER_CEILING_DB = -1.0
SOUND_ENHANCER_MAKEUP_GAIN = 10 ** (SOUND_ENHANCER_MAKEUP_DB / 20.0)
SOUND_ENHANCER_CEILING = 10 ** (SOUND_ENHANCER_CEILING_DB / 20.0)
SOUND_ENHANCER_ATTACK_ALPHA = 0.85
SOUND_ENHANCER_RELEASE_ALPHA = 0.08
SOUND_ENHANCER_TRUE_PEAK_FRACTIONS = (0.25, 0.5, 0.75)


def db_to_linear(db_value: float) -> float:
    return float(10 ** (db_value / 20.0))


def linear_to_db(value: float) -> float:
    return float(20.0 * np.log10(max(float(value), 1e-6)))


def clamp_trim_db(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(TRIM_MIN_DB, min(TRIM_MAX_DB, parsed))


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


def _safe_sample_rate(sample_rate: object) -> int:
    try:
        value = float(sample_rate)
    except (TypeError, ValueError):
        return SAMPLE_RATE
    if not math.isfinite(value) or value <= 0:
        return SAMPLE_RATE
    return int(round(value))


def _dry_delay_samples_for_rate(sample_rate: object) -> int:
    rate = _safe_sample_rate(sample_rate)
    return max(1, int(round(DRY_DELAY_SAMPLES * rate / SAMPLE_RATE)))


def estimate_lfe_filter_delay(sample_rate: float = SAMPLE_RATE, impulse_frames: int | None = None) -> dict[str, float]:
    frames = impulse_frames or max(4096, int(sample_rate // 4))
    impulse = np.zeros(frames, dtype=np.float64)
    impulse[0] = 1.0
    response = impulse.copy()
    sections = _butterworth_lowpass_sos(LFE_LOWPASS_CUTOFF_HZ, sample_rate)
    for b0, b1, b2, a1, a2 in sections:
        z1 = 0.0
        z2 = 0.0
        for frame in range(frames):
            sample = float(response[frame])
            output = b0 * sample + z1
            z1 = b1 * sample - a1 * output + z2
            z2 = b2 * sample - a2 * output
            response[frame] = output
    energy = response * response
    total_energy = max(float(np.sum(energy)), 1e-24)
    measured_peak = int(np.argmax(np.abs(response)))
    measured_centroid = float(np.dot(np.arange(frames, dtype=np.float64), energy) / total_energy)
    expected = int(round(DRY_DELAY_SAMPLES * sample_rate / SAMPLE_RATE))
    return {
        "sample_rate": float(sample_rate),
        "expected_dry_delay_samples": float(expected),
        "measured_peak_samples": float(measured_peak),
        "measured_energy_centroid_samples": measured_centroid,
        "peak_difference_samples": float(measured_peak - expected),
        "centroid_difference_samples": float(measured_centroid - expected),
    }


@dataclass(frozen=True)
class DspSnapshot:
    channel_levels: np.ndarray
    channel_rms: np.ndarray
    raw_channel_levels: np.ndarray
    raw_channel_rms: np.ndarray
    left_meter: float
    right_meter: float
    preamp_db: float
    trim_left_db: float
    trim_right_db: float
    limiter_gain: float
    clipping: bool
    user_volume: float
    master_volume: float
    master_muted: bool
    surround_fill_enabled: bool
    surround_fill_active: bool
    upmix_9_1_6_enabled: bool
    upmix_9_1_6_active: bool
    channel_sanity_enabled: bool
    channel_sanity_active: bool
    sound_enhancer_enabled: bool
    sound_enhancer_gain: float

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
        matrix: np.ndarray | None = None,
        max_channels: int = MAX_INPUT_CHANNELS,
        sample_rate: float = SAMPLE_RATE,
    ) -> None:
        self.sharur_matrix = np.asarray(matrix if matrix is not None else SHARUR_916_STEREO_MATRIX, dtype=np.float64)
        self.windows_matrix = np.asarray(WINDOWS_71_STEREO_MATRIX, dtype=np.float64)
        if self.sharur_matrix.shape != (max_channels, OUTPUT_CHANNELS):
            raise ValueError("matrix must be 16x2")
        if self.windows_matrix.shape != (len(WINDOWS_7_1_LAYOUT.speakers), OUTPUT_CHANNELS):
            raise ValueError("Windows 7.1 matrix must be 8x2")
        self.matrix = self.sharur_matrix

        self.max_channels = max_channels
        self.sample_rate = _safe_sample_rate(sample_rate)
        self._dry_delay_samples = _dry_delay_samples_for_rate(self.sample_rate)
        self._config_lock = Lock()
        self._state_lock = Lock()
        self._monitor_layout = DEFAULT_CHANNEL_CONFIG
        self._input_layout = DEFAULT_CHANNEL_CONFIG
        self._preamp_db = float(preamp_db)
        self._preamp_gain = db_to_linear(preamp_db)
        self._trim_left_db = 0.0
        self._trim_right_db = 0.0
        self._trim_left_gain = 1.0
        self._trim_right_gain = 1.0
        self._user_volume = 1.0
        self._master_volume = 1.0
        self._master_muted = False
        self._surround_fill_enabled = False
        self._upmix_9_1_6_enabled = False
        self._channel_sanity_enabled = False
        self._limiter_gain = 1.0
        self._sound_enhancer_enabled = False
        self._sound_enhancer_safety_gain = 1.0
        self._sound_enhancer_applied_gain = 1.0

        self._scratch_frames = 0
        self._input16 = np.zeros((0, max_channels), dtype=np.float32)
        self._effective16 = np.zeros((0, max_channels), dtype=np.float32)
        self._render16 = np.zeros((0, max_channels), dtype=np.float32)
        self._processed16 = np.zeros((0, max_channels), dtype=np.float32)
        self._abs16 = np.zeros((0, max_channels), dtype=np.float32)
        self._square16 = np.zeros((0, max_channels), dtype=np.float64)
        self._lfe_scratch = np.zeros(0, dtype=np.float32)
        self._upmix_scratch = np.zeros((0, _UPMIX_FILTER_SLOTS), dtype=np.float32)
        self._stereo = np.zeros((0, OUTPUT_CHANNELS), dtype=np.float64)
        self._stereo_abs = np.zeros((0, OUTPUT_CHANNELS), dtype=np.float64)
        self._mono_abs = np.zeros(0, dtype=np.float64)
        self._dry_delay_buffer = np.zeros((self._dry_delay_samples, max_channels), dtype=np.float32)
        self._lfe_lowpass_sos = _butterworth_lowpass_sos(LFE_LOWPASS_CUTOFF_HZ, self.sample_rate)
        self._lfe_filter_state = np.zeros((len(self._lfe_lowpass_sos), 2), dtype=np.float64)
        self._decor_x1 = np.zeros((len(_UPMIX_DECORRELATION_COEFFS), len(_UPMIX_DECORRELATION_COEFFS[0])), dtype=np.float64)
        self._decor_y1 = np.zeros((len(_UPMIX_DECORRELATION_COEFFS), len(_UPMIX_DECORRELATION_COEFFS[0])), dtype=np.float64)
        self._hp_x1 = np.zeros(_UPMIX_FILTER_SLOTS, dtype=np.float64)
        self._hp_y1 = np.zeros(_UPMIX_FILTER_SLOTS, dtype=np.float64)
        self._lp_y1 = np.zeros(_UPMIX_FILTER_SLOTS, dtype=np.float64)
        self._peq_config = PeqRuntimeConfig()
        self._pending_peq_config: PeqRuntimeConfig | None = None
        self._peq_state = self._new_peq_state()
        self._peq_transition_config: PeqRuntimeConfig | None = None
        self._peq_transition_state = self._new_peq_state()
        self._peq_crossfade_remaining = 0
        self._peq_old_stereo = np.zeros((0, OUTPUT_CHANNELS), dtype=np.float64)

        self._channel_levels = np.zeros(max_channels, dtype=np.float32)
        self._channel_rms = np.zeros(max_channels, dtype=np.float32)
        self._raw_channel_levels = np.zeros(max_channels, dtype=np.float32)
        self._raw_channel_rms = np.zeros(max_channels, dtype=np.float32)
        self._work_channel_levels = np.zeros(max_channels, dtype=np.float32)
        self._work_channel_rms = np.zeros(max_channels, dtype=np.float32)
        self._work_raw_channel_levels = np.zeros(max_channels, dtype=np.float32)
        self._work_raw_channel_rms = np.zeros(max_channels, dtype=np.float32)
        self._work_peaks = np.zeros(max_channels, dtype=np.float32)
        self._work_rms64 = np.zeros(max_channels, dtype=np.float64)
        self._left_meter = 0.0
        self._right_meter = 0.0
        self._clipping = False
        self._surround_fill_active = False
        self._upmix_9_1_6_active = False
        self._channel_sanity_active = False

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

    def set_sample_rate(self, sample_rate: object) -> None:
        next_rate = _safe_sample_rate(sample_rate)
        if next_rate == self.sample_rate:
            return
        with self._config_lock:
            self.sample_rate = next_rate
            self._dry_delay_samples = _dry_delay_samples_for_rate(next_rate)
            self._dry_delay_buffer = np.zeros((self._dry_delay_samples, self.max_channels), dtype=np.float32)
            self._lfe_lowpass_sos = _butterworth_lowpass_sos(LFE_LOWPASS_CUTOFF_HZ, self.sample_rate)
            self._lfe_filter_state = np.zeros((len(self._lfe_lowpass_sos), 2), dtype=np.float64)
        self.reset_runtime_state()

    def set_channel_trim_db(self, left_db: float, right_db: float) -> None:
        left = clamp_trim_db(left_db)
        right = clamp_trim_db(right_db)
        with self._config_lock:
            self._trim_left_db = left
            self._trim_right_db = right
            self._trim_left_gain = db_to_linear(left)
            self._trim_right_gain = db_to_linear(right)

    def set_surround_fill_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self._surround_fill_enabled = bool(enabled)

    def set_upmix_9_1_6_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self._upmix_9_1_6_enabled = bool(enabled)

    def set_channel_sanity_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self._channel_sanity_enabled = bool(enabled)

    def set_sound_enhancer_enabled(self, enabled: bool) -> None:
        with self._config_lock:
            self._sound_enhancer_enabled = bool(enabled)
            self._sound_enhancer_safety_gain = 1.0
            self._sound_enhancer_applied_gain = 1.0

    def set_peq_config(self, config: PeqRuntimeConfig) -> None:
        if not isinstance(config, PeqRuntimeConfig):
            raise TypeError("config must be a PeqRuntimeConfig")
        with self._config_lock:
            self._pending_peq_config = config

    def set_monitor_layout(self, layout_id: str) -> None:
        layout_id = layout_id if layout_id in {WINDOWS_7_1_LAYOUT.id, SHARUR_9_1_6_LAYOUT.id} else DEFAULT_CHANNEL_CONFIG
        with self._config_lock:
            self._monitor_layout = layout_id

    def set_input_layout(self, layout_id: str) -> None:
        layout_id = layout_id if layout_id in {WINDOWS_7_1_LAYOUT.id, SHARUR_9_1_6_LAYOUT.id} else DEFAULT_CHANNEL_CONFIG
        with self._config_lock:
            self._input_layout = layout_id

    def reset_limiter(self) -> None:
        self.reset_runtime_state()

    def reset_runtime_state(self) -> None:
        self._limiter_gain = 1.0
        self._dry_delay_buffer.fill(0.0)
        self._lfe_filter_state.fill(0.0)
        self._decor_x1.fill(0.0)
        self._decor_y1.fill(0.0)
        self._hp_x1.fill(0.0)
        self._hp_y1.fill(0.0)
        self._lp_y1.fill(0.0)
        self._sound_enhancer_safety_gain = 1.0
        self._sound_enhancer_applied_gain = 1.0
        self._peq_state = self._new_peq_state()
        self._peq_transition_state = self._new_peq_state()
        self._peq_transition_config = None
        self._peq_crossfade_remaining = 0

    def process(self, indata: np.ndarray, outdata: np.ndarray | None = None) -> np.ndarray:
        if indata.ndim != 2:
            raise ValueError("indata must be a frames x channels array")

        frames, channels = indata.shape
        self._ensure_scratch(frames)
        input16 = self._prepare_input(indata, frames, channels)
        self._measure_levels(input16, frames, self._work_raw_channel_levels, self._work_raw_channel_rms)

        with self._config_lock:
            surround_fill_enabled = self._surround_fill_enabled
            upmix_9_1_6_enabled = self._upmix_9_1_6_enabled
            channel_sanity_enabled = self._channel_sanity_enabled
            monitor_layout = self._monitor_layout
            input_layout = self._input_layout

        channel_sanity_active = False
        surround_fill_active = False
        upmix_9_1_6_active = False
        source16 = input16
        if surround_fill_enabled or channel_sanity_enabled:
            source16 = self._effective16[:frames]
            if frames:
                source16[:] = input16
            channel_sanity_active = self._apply_channel_sanity(source16, frames, channel_sanity_enabled)
            if input_layout == WINDOWS_7_1_LAYOUT.id:
                surround_fill_active = self._apply_surround_fill(source16, frames, surround_fill_enabled)

        if monitor_layout == SHARUR_9_1_6_LAYOUT.id:
            render16 = self._build_sharur_9_1_6_bus(source16, frames, channels, input_layout)
            upmix_9_1_6_active = self._generate_missing_sharur_9_1_6(render16, frames, source16, channels, input_layout, upmix_9_1_6_enabled)
            matrix = self.sharur_matrix
        else:
            render16 = source16
            matrix = self.windows_matrix

        self._measure_levels(render16, frames, self._work_channel_levels, self._work_channel_rms)
        processed16 = self._apply_sharur_processing(render16, frames)

        with self._config_lock:
            preamp_gain = self._preamp_gain
            preamp_db = self._preamp_db
            trim_left_gain = self._trim_left_gain
            trim_right_gain = self._trim_right_gain
            trim_left_db = self._trim_left_db
            trim_right_db = self._trim_right_db
            user_volume = self._user_volume
            master_volume = self._master_volume
            master_muted = self._master_muted
            surround_fill_enabled = self._surround_fill_enabled
            upmix_9_1_6_enabled = self._upmix_9_1_6_enabled
            channel_sanity_enabled = self._channel_sanity_enabled
            sound_enhancer_enabled = self._sound_enhancer_enabled

        sound_enhancer_limited = False
        sound_enhancer_gain = 1.0
        self._mix_to_stereo(processed16, frames, matrix)
        self._stereo[:frames] *= preamp_gain
        self._apply_peq_routing(frames)
        if trim_left_gain != 1.0 or trim_right_gain != 1.0:
            self._stereo[:frames, 0] *= trim_left_gain
            self._stereo[:frames, 1] *= trim_right_gain
        if sound_enhancer_enabled:
            sound_enhancer_gain, sound_enhancer_limited = self._apply_sound_enhancer(frames)
        else:
            self._sound_enhancer_applied_gain = 1.0

        peak_before_limiter = self._peak_stereo(self._stereo[:frames], frames)
        target_gain = 1.0
        clipping = sound_enhancer_limited
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
            if outdata.shape[0] != frames or outdata.shape[1] < OUTPUT_CHANNELS:
                raise ValueError("outdata must match frames and have at least 2 channels")
            if outdata.shape[1] > OUTPUT_CHANNELS:
                outdata.fill(0.0)
            outdata[:, :OUTPUT_CHANNELS] = self._stereo[:frames]
            rendered = outdata[:, :OUTPUT_CHANNELS]

        left_meter = self._peak_mono(rendered[:, 0], frames)
        right_meter = self._peak_mono(rendered[:, 1], frames)

        if self._state_lock.acquire(False):
            try:
                self._channel_levels[:] = self._work_channel_levels
                self._channel_rms[:] = self._work_channel_rms
                self._raw_channel_levels[:] = self._work_raw_channel_levels
                self._raw_channel_rms[:] = self._work_raw_channel_rms
                self._left_meter = left_meter
                self._right_meter = right_meter
                self._clipping = clipping
                self._surround_fill_active = surround_fill_active
                self._upmix_9_1_6_active = upmix_9_1_6_active
                self._channel_sanity_active = channel_sanity_active
                self._snapshot_preamp_db = preamp_db
                self._snapshot_trim_left_db = trim_left_db
                self._snapshot_trim_right_db = trim_right_db
                self._snapshot_user_volume = user_volume
                self._snapshot_master_volume = master_volume
                self._snapshot_master_muted = master_muted
                self._snapshot_surround_fill_enabled = surround_fill_enabled
                self._snapshot_upmix_9_1_6_enabled = upmix_9_1_6_enabled
                self._snapshot_channel_sanity_enabled = channel_sanity_enabled
                self._snapshot_sound_enhancer_enabled = sound_enhancer_enabled
                self._snapshot_sound_enhancer_gain = sound_enhancer_gain
            finally:
                self._state_lock.release()

        return rendered

    def snapshot(self) -> DspSnapshot:
        with self._state_lock:
            preamp_db = getattr(self, "_snapshot_preamp_db", self._preamp_db)
            trim_left_db = getattr(self, "_snapshot_trim_left_db", self._trim_left_db)
            trim_right_db = getattr(self, "_snapshot_trim_right_db", self._trim_right_db)
            user_volume = getattr(self, "_snapshot_user_volume", self._user_volume)
            master_volume = getattr(self, "_snapshot_master_volume", self._master_volume)
            master_muted = getattr(self, "_snapshot_master_muted", self._master_muted)
            surround_fill_enabled = getattr(
                self, "_snapshot_surround_fill_enabled", self._surround_fill_enabled
            )
            upmix_9_1_6_enabled = getattr(
                self, "_snapshot_upmix_9_1_6_enabled", self._upmix_9_1_6_enabled
            )
            channel_sanity_enabled = getattr(
                self, "_snapshot_channel_sanity_enabled", self._channel_sanity_enabled
            )
            sound_enhancer_enabled = getattr(
                self, "_snapshot_sound_enhancer_enabled", self._sound_enhancer_enabled
            )
            sound_enhancer_gain = getattr(
                self, "_snapshot_sound_enhancer_gain", self._sound_enhancer_applied_gain
            )
            return DspSnapshot(
                channel_levels=self._channel_levels.copy(),
                channel_rms=self._channel_rms.copy(),
                raw_channel_levels=self._raw_channel_levels.copy(),
                raw_channel_rms=self._raw_channel_rms.copy(),
                left_meter=float(self._left_meter),
                right_meter=float(self._right_meter),
                preamp_db=float(preamp_db),
                trim_left_db=float(trim_left_db),
                trim_right_db=float(trim_right_db),
                limiter_gain=float(self._limiter_gain),
                clipping=bool(self._clipping),
                user_volume=float(user_volume),
                master_volume=float(master_volume),
                master_muted=bool(master_muted),
                surround_fill_enabled=bool(surround_fill_enabled),
                surround_fill_active=bool(self._surround_fill_active),
                upmix_9_1_6_enabled=bool(upmix_9_1_6_enabled),
                upmix_9_1_6_active=bool(self._upmix_9_1_6_active),
                channel_sanity_enabled=bool(channel_sanity_enabled),
                channel_sanity_active=bool(self._channel_sanity_active),
                sound_enhancer_enabled=bool(sound_enhancer_enabled),
                sound_enhancer_gain=float(sound_enhancer_gain),
            )

    def _ensure_scratch(self, frames: int) -> None:
        if frames <= self._scratch_frames:
            return
        capacity = max(256, 1 << (frames - 1).bit_length())
        self._scratch_frames = capacity
        self._input16 = np.zeros((capacity, self.max_channels), dtype=np.float32)
        self._effective16 = np.zeros((capacity, self.max_channels), dtype=np.float32)
        self._render16 = np.zeros((capacity, self.max_channels), dtype=np.float32)
        self._processed16 = np.zeros((capacity, self.max_channels), dtype=np.float32)
        self._abs16 = np.zeros((capacity, self.max_channels), dtype=np.float32)
        self._square16 = np.zeros((capacity, self.max_channels), dtype=np.float64)
        self._lfe_scratch = np.zeros(capacity, dtype=np.float32)
        self._upmix_scratch = np.zeros((capacity, _UPMIX_FILTER_SLOTS), dtype=np.float32)
        self._stereo = np.zeros((capacity, OUTPUT_CHANNELS), dtype=np.float64)
        self._stereo_abs = np.zeros((capacity, OUTPUT_CHANNELS), dtype=np.float64)
        self._mono_abs = np.zeros(capacity, dtype=np.float64)
        self._peq_old_stereo = np.zeros((capacity, OUTPUT_CHANNELS), dtype=np.float64)

    def _prepare_input(self, indata: np.ndarray, frames: int, channels: int) -> np.ndarray:
        input16 = self._input16[:frames]
        input16.fill(0.0)
        copy_channels = min(channels, self.max_channels)
        if copy_channels:
            input16[:, :copy_channels] = indata[:, :copy_channels]
            np.nan_to_num(input16[:, :copy_channels], copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        return input16

    def _measure_levels(
        self,
        samples: np.ndarray,
        frames: int,
        levels_out: np.ndarray,
        rms_out: np.ndarray,
    ) -> None:
        if not frames:
            levels_out.fill(0.0)
            rms_out.fill(0.0)
            return

        abs_view = self._abs16[:frames]
        np.abs(samples, out=abs_view)
        np.max(abs_view, axis=0, out=levels_out)

        square_view = self._square16[:frames]
        np.multiply(samples, samples, out=square_view, casting="unsafe")
        np.mean(square_view, axis=0, out=self._work_rms64)
        np.sqrt(self._work_rms64, out=self._work_rms64)
        rms_out[:] = self._work_rms64

    def _channel_peaks(self, samples: np.ndarray, frames: int) -> np.ndarray:
        if not frames:
            self._work_peaks.fill(0.0)
            return self._work_peaks
        abs_view = self._abs16[:frames]
        np.abs(samples, out=abs_view)
        np.max(abs_view, axis=0, out=self._work_peaks)
        return self._work_peaks

    def _peak_mono(self, samples: np.ndarray, frames: int) -> float:
        if not frames:
            return 0.0
        mono = self._mono_abs[:frames]
        np.abs(samples, out=mono)
        return float(np.max(mono))

    def _peak_stereo(self, samples: np.ndarray, frames: int) -> float:
        if not frames:
            return 0.0
        stereo_abs = self._stereo_abs[:frames]
        np.abs(samples, out=stereo_abs)
        return float(np.max(stereo_abs))

    def _apply_sound_enhancer(self, frames: int) -> tuple[float, bool]:
        """Apply transparent laptop-speaker loudness with a protected ceiling.

        The enhancer is intentionally post-mix and pre-final-limiter: it does
        not change matrix/downmix math, PEQ, trims, routing, or channel state.
        It adds fixed makeup gain for quiet laptop speakers, then uses a fast
        safety gain to keep the boosted block under a -1 dBFS ceiling before
        the existing full-scale limiter gets a final chance to catch anomalies.
        """
        if not frames:
            self._sound_enhancer_applied_gain = 1.0
            return 1.0, False

        peak = self._estimate_true_peak_stereo(self._stereo[:frames], frames)
        target_safety_gain = 1.0
        limited = False
        if peak > 1e-12:
            boosted_peak = peak * SOUND_ENHANCER_MAKEUP_GAIN
            if boosted_peak > SOUND_ENHANCER_CEILING:
                target_safety_gain = SOUND_ENHANCER_CEILING / boosted_peak
                limited = True

        alpha = (
            SOUND_ENHANCER_ATTACK_ALPHA
            if target_safety_gain < self._sound_enhancer_safety_gain
            else SOUND_ENHANCER_RELEASE_ALPHA
        )
        smoothed_safety_gain = (
            (1.0 - alpha) * self._sound_enhancer_safety_gain
        ) + (alpha * target_safety_gain)
        applied_safety_gain = min(smoothed_safety_gain, target_safety_gain) if limited else smoothed_safety_gain
        self._sound_enhancer_safety_gain = smoothed_safety_gain

        applied_gain = SOUND_ENHANCER_MAKEUP_GAIN * applied_safety_gain
        self._stereo[:frames] *= applied_gain

        post_peak = self._estimate_true_peak_stereo(self._stereo[:frames], frames)
        if post_peak > SOUND_ENHANCER_CEILING:
            emergency_gain = SOUND_ENHANCER_CEILING / post_peak
            self._stereo[:frames] *= emergency_gain
            applied_gain *= emergency_gain
            limited = True

        self._sound_enhancer_applied_gain = applied_gain
        return applied_gain, limited

    def _estimate_true_peak_stereo(self, samples: np.ndarray, frames: int) -> float:
        """Estimate inter-sample stereo peaks without heap work in the callback path.

        This is a lightweight 4x Catmull-Rom guard for the optional Sound
        Enhancer. It is intentionally conservative compared with raw sample
        peak limiting, but it avoids changing the downmix matrix, routing, PEQ,
        or trim stages.
        """
        if frames <= 0:
            return 0.0
        sample_peak = self._peak_stereo(samples, frames)
        if frames < 2:
            return sample_peak

        peak = sample_peak
        sample_count = min(frames, samples.shape[0])
        channels = min(OUTPUT_CHANNELS, samples.shape[1])
        for channel in range(channels):
            for index in range(sample_count - 1):
                p0 = float(samples[index - 1 if index > 0 else index, channel])
                p1 = float(samples[index, channel])
                p2 = float(samples[index + 1, channel])
                p3_index = index + 2 if index + 2 < sample_count else index + 1
                p3 = float(samples[p3_index, channel])
                for frac in SOUND_ENHANCER_TRUE_PEAK_FRACTIONS:
                    value = self._catmull_rom_sample(p0, p1, p2, p3, frac)
                    abs_value = abs(value)
                    if abs_value > peak:
                        peak = abs_value
        return float(peak)

    @staticmethod
    def _catmull_rom_sample(p0: float, p1: float, p2: float, p3: float, frac: float) -> float:
        frac2 = frac * frac
        frac3 = frac2 * frac
        return 0.5 * (
            (2.0 * p1)
            + ((-p0 + p2) * frac)
            + ((2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * frac2)
            + ((-p0 + 3.0 * p1 - 3.0 * p2 + p3) * frac3)
        )

    def _mix_to_stereo(self, processed16: np.ndarray, frames: int, matrix: np.ndarray) -> None:
        stereo = self._stereo[:frames]
        stereo.fill(0.0)
        if matrix.shape[0] == len(WINDOWS_7_1_LAYOUT.speakers):
            np.dot(processed16[:, : len(WINDOWS_7_1_LAYOUT.speakers)], matrix, out=stereo)
            return
        np.dot(processed16, matrix, out=stereo)

    @staticmethod
    def _new_peq_state() -> dict[str, np.ndarray]:
        return {
            "global": np.zeros((OUTPUT_CHANNELS, MAX_FILTERS_PER_STAGE, 2), dtype=np.float64),
            "speaker_left": np.zeros((MAX_FILTERS_PER_STAGE, 2), dtype=np.float64),
            "speaker_right": np.zeros((MAX_FILTERS_PER_STAGE, 2), dtype=np.float64),
        }

    def _apply_peq_routing(self, frames: int) -> None:
        if not frames:
            return
        self._activate_pending_peq_config()
        if self._peq_config.bypassed and self._peq_transition_config is None:
            return

        stereo = self._stereo[:frames]
        if self._peq_transition_config is None:
            self._apply_peq_config_to_stereo(stereo, frames, self._peq_config, self._peq_state)
            return

        old = self._peq_old_stereo[:frames]
        old[:] = stereo
        self._apply_peq_config_to_stereo(old, frames, self._peq_transition_config, self._peq_transition_state)
        self._apply_peq_config_to_stereo(stereo, frames, self._peq_config, self._peq_state)

        fade_frames = min(frames, self._peq_crossfade_remaining)
        if fade_frames > 0:
            total = float(PEQ_CROSSFADE_SAMPLES)
            start = PEQ_CROSSFADE_SAMPLES - self._peq_crossfade_remaining
            ramp = (np.arange(fade_frames, dtype=np.float64) + start + 1.0) / total
            stereo[:fade_frames, :] = old[:fade_frames, :] * (1.0 - ramp[:, None]) + stereo[:fade_frames, :] * ramp[:, None]
            self._peq_crossfade_remaining -= fade_frames
        if self._peq_crossfade_remaining <= 0:
            self._peq_transition_config = None
            self._peq_transition_state = self._new_peq_state()

    def _activate_pending_peq_config(self) -> None:
        with self._config_lock:
            pending = self._pending_peq_config
            self._pending_peq_config = None
        if pending is None or pending == self._peq_config:
            return
        self._peq_transition_config = self._peq_config
        self._peq_transition_state = self._peq_state
        self._peq_config = pending
        self._peq_state = self._new_peq_state()
        self._peq_crossfade_remaining = PEQ_CROSSFADE_SAMPLES

    def _apply_peq_config_to_stereo(
        self,
        stereo: np.ndarray,
        frames: int,
        config: PeqRuntimeConfig,
        state: dict[str, np.ndarray],
    ) -> None:
        if config.global_cascade.active:
            self._apply_cascade_to_channel(stereo[:, 0], frames, config.global_cascade, state["global"][0])
            self._apply_cascade_to_channel(stereo[:, 1], frames, config.global_cascade, state["global"][1])
        if config.lr_swap_enabled:
            left = stereo[:, 0].copy()
            stereo[:, 0] = stereo[:, 1]
            stereo[:, 1] = left
        if config.speaker_enabled:
            if config.speaker_left.active:
                self._apply_cascade_to_channel(stereo[:, 0], frames, config.speaker_left, state["speaker_left"])
            if config.speaker_right.active:
                self._apply_cascade_to_channel(stereo[:, 1], frames, config.speaker_right, state["speaker_right"])

    def _apply_cascade_to_channel(
        self,
        samples: np.ndarray,
        frames: int,
        cascade: PeqCascade,
        state: np.ndarray,
    ) -> None:
        if abs(cascade.preamp_db) > 1e-9:
            samples[:frames] *= db_to_linear(cascade.preamp_db)
        for index, coeff in enumerate(cascade.biquads[:MAX_FILTERS_PER_STAGE]):
            self._apply_biquad(samples, frames, coeff, state[index])

    @staticmethod
    def _apply_biquad(samples: np.ndarray, frames: int, coeff: BiquadCoefficients, state: np.ndarray) -> None:
        z1 = float(state[0])
        z2 = float(state[1])
        b0, b1, b2, a1, a2 = coeff.as_tuple()
        for frame in range(frames):
            sample = float(samples[frame])
            output = b0 * sample + z1
            z1 = b1 * sample - a1 * output + z2
            z2 = b2 * sample - a2 * output
            if abs(output) < PEQ_DENORMAL_GUARD:
                output = 0.0
            samples[frame] = output
        if abs(z1) < PEQ_DENORMAL_GUARD:
            z1 = 0.0
        if abs(z2) < PEQ_DENORMAL_GUARD:
            z2 = 0.0
        state[0] = z1
        state[1] = z2

    def _apply_channel_sanity(self, field16: np.ndarray, frames: int, enabled: bool) -> bool:
        if not enabled or not frames:
            return False

        peaks = self._channel_peaks(field16, frames)
        if peaks[0] <= CHANNEL_SANITY_THRESHOLD or peaks[1] <= CHANNEL_SANITY_THRESHOLD:
            return False

        left = field16[:, 0]
        right = field16[:, 1]
        left_energy = max(float(np.dot(left, left)), 1e-12)
        right_energy = max(float(np.dot(right, right)), 1e-12)
        front_rms = max(np.sqrt(left_energy / frames), np.sqrt(right_energy / frames), CHANNEL_SANITY_THRESHOLD)
        duplicated: list[int] = []
        for index in range(2, self.max_channels):
            if peaks[index] <= CHANNEL_SANITY_THRESHOLD:
                continue
            channel = field16[:, index]
            channel_energy = max(float(np.dot(channel, channel)), 1e-12)
            channel_rms = np.sqrt(channel_energy / frames)
            left_corr = abs(float(np.dot(channel, left))) / np.sqrt(channel_energy * left_energy)
            right_corr = abs(float(np.dot(channel, right))) / np.sqrt(channel_energy * right_energy)
            rms_ratio = channel_rms / front_rms
            if max(left_corr, right_corr) >= CHANNEL_SANITY_CORRELATION and 0.35 <= rms_ratio <= 1.65:
                duplicated.append(index)

        if len(duplicated) < CHANNEL_SANITY_MIN_DUPLICATES:
            return False

        field16[:, duplicated] = 0.0
        return True

    def _apply_surround_fill(self, effective16: np.ndarray, frames: int, enabled: bool) -> bool:
        if not enabled or not frames:
            return False

        active = False
        for source_index, target_index in SURROUND_FILL_PAIRS:
            source = effective16[:, source_index]
            target = effective16[:, target_index]
            source_active = self._peak_mono(source, frames) > SURROUND_FILL_THRESHOLD
            target_silent = self._peak_mono(target, frames) <= SURROUND_FILL_THRESHOLD
            if source_active and target_silent:
                effective16[:, target_index] = source * 0.5
                effective16[:, source_index] = source * 0.5
                active = True
        return active

    def _build_sharur_9_1_6_bus(
        self,
        source16: np.ndarray,
        frames: int,
        source_channels: int,
        input_layout: str,
    ) -> np.ndarray:
        bus = self._render16[:frames]
        bus.fill(0.0)
        if not frames:
            return bus

        if input_layout == SHARUR_9_1_6_LAYOUT.id:
            bus[:] = source16[:, : self.max_channels]
            return bus

        for source_index, target_index in WINDOWS_TO_SHARUR_COPY:
            if source_index < self.max_channels and target_index < self.max_channels:
                bus[:, target_index] = source16[:, source_index]
        return bus

    def _generate_missing_sharur_9_1_6(
        self,
        bus: np.ndarray,
        frames: int,
        source16: np.ndarray,
        source_channels: int,
        input_layout: str,
        enabled: bool,
    ) -> bool:
        if not enabled or not frames or input_layout == SHARUR_9_1_6_LAYOUT.id:
            return False

        peaks = self._channel_peaks(source16, frames)
        if np.max(peaks[: len(WINDOWS_7_1_LAYOUT.speakers)]) <= UPMIX_916_THRESHOLD:
            return False

        scratch = self._upmix_scratch[:frames]
        fl = bus[:, 0]
        fr = bus[:, 1]
        fc = bus[:, 2]
        bl = bus[:, 4]
        br = bus[:, 5]
        sl = bus[:, 8]
        sr = bus[:, 9]

        if self._peak_mono(sl, frames) <= UPMIX_916_THRESHOLD and self._peak_mono(sr, frames) <= UPMIX_916_THRESHOLD:
            scratch[:, 18] = 0.5 * bl + 0.25 * fl
            scratch[:, 19] = 0.5 * br + 0.25 * fr
            side_src_l = scratch[:, 18]
            side_src_r = scratch[:, 19]
        else:
            side_src_l = sl
            side_src_r = sr

        front_side = scratch[:, 0]
        side_side = scratch[:, 1]
        rear_side = scratch[:, 2]
        front_side[:] = 0.5 * (fl - fr)
        side_side[:] = 0.5 * (side_src_l - side_src_r)
        rear_side[:] = 0.5 * (bl - br)

        front_amb_l = self._decorrelate(front_side, scratch[:, 3], 0)
        front_amb_r = self._decorrelate(front_side, scratch[:, 4], 1)
        side_amb_l = self._decorrelate(side_side, scratch[:, 5], 2)
        side_amb_r = self._decorrelate(side_side, scratch[:, 6], 3)
        rear_amb_l = self._decorrelate(rear_side, scratch[:, 7], 4)
        rear_amb_r = self._decorrelate(rear_side, scratch[:, 8], 5)

        fl_air = self._highpass(fl, scratch[:, 9], 0, UPMIX_916_AIR_HIGHPASS_HZ)
        fr_air = self._highpass(fr, scratch[:, 10], 1, UPMIX_916_AIR_HIGHPASS_HZ)
        fc_air = self._highpass(fc, scratch[:, 11], 2, UPMIX_916_AIR_HIGHPASS_HZ)
        sl_air = self._highpass(side_src_l, scratch[:, 12], 3, UPMIX_916_AIR_HIGHPASS_HZ)
        sr_air = self._highpass(side_src_r, scratch[:, 13], 4, UPMIX_916_AIR_HIGHPASS_HZ)
        bl_air = self._highpass(bl, scratch[:, 14], 5, UPMIX_916_AIR_HIGHPASS_HZ)
        br_air = self._highpass(br, scratch[:, 15], 6, UPMIX_916_AIR_HIGHPASS_HZ)

        work = scratch[:, 16]

        work[:] = 0.55 * bl + 0.20 * side_src_l + 0.20 * rear_amb_l + 0.10 * side_amb_l
        self._shape_generated(work, bus[:, 6], 7, 0, highpass_hz=100.0, lowpass_hz=14000.0, shelf_db=0.0)
        work[:] = 0.55 * br + 0.20 * side_src_r + 0.20 * rear_amb_r + 0.10 * side_amb_r
        self._shape_generated(work, bus[:, 7], 8, 1, highpass_hz=100.0, lowpass_hz=14000.0, shelf_db=0.0)

        work[:] = 0.18 * fl_air + 0.06 * fc_air + 0.30 * front_amb_l + 0.08 * side_amb_l
        self._shape_generated(work, bus[:, 10], 9, 2, highpass_hz=200.0, lowpass_hz=14000.0, shelf_db=2.0)
        work[:] = 0.18 * fr_air + 0.06 * fc_air + 0.30 * front_amb_r + 0.08 * side_amb_r
        self._shape_generated(work, bus[:, 11], 10, 3, highpass_hz=200.0, lowpass_hz=14000.0, shelf_db=2.0)

        work[:] = 0.16 * sl_air + 0.08 * bl_air + 0.35 * side_amb_l + 0.12 * rear_amb_l
        self._shape_generated(work, bus[:, 12], 11, 4, highpass_hz=200.0, lowpass_hz=13000.0, shelf_db=1.0)
        work[:] = 0.16 * sr_air + 0.08 * br_air + 0.35 * side_amb_r + 0.12 * rear_amb_r
        self._shape_generated(work, bus[:, 13], 12, 5, highpass_hz=200.0, lowpass_hz=13000.0, shelf_db=1.0)

        work[:] = 0.16 * bl_air + 0.08 * sl_air + 0.35 * rear_amb_l + 0.10 * side_amb_l
        self._shape_generated(work, bus[:, 14], 13, 6, highpass_hz=250.0, lowpass_hz=12000.0, shelf_db=0.5)
        work[:] = 0.16 * br_air + 0.08 * sr_air + 0.35 * rear_amb_r + 0.10 * side_amb_r
        self._shape_generated(work, bus[:, 15], 14, 7, highpass_hz=250.0, lowpass_hz=12000.0, shelf_db=0.5)

        for speaker in GENERATED_SHARUR_SPEAKERS:
            bus[:, SHARUR_9_1_6_LAYOUT.index_of(speaker)] *= UPMIX_916_GENERATED_GAIN
        return True

    def _decorrelate(self, source: np.ndarray, output: np.ndarray, slot: int) -> np.ndarray:
        output[:] = source
        coeffs = _UPMIX_DECORRELATION_COEFFS[slot % len(_UPMIX_DECORRELATION_COEFFS)]
        for stage, gain in enumerate(coeffs):
            x1 = float(self._decor_x1[slot, stage])
            y1 = float(self._decor_y1[slot, stage])
            for index in range(len(output)):
                sample = float(output[index])
                value = -gain * sample + x1 + gain * y1
                output[index] = value
                x1 = sample
                y1 = value
            self._decor_x1[slot, stage] = x1
            self._decor_y1[slot, stage] = y1
        return output

    def _shape_generated(
        self,
        source: np.ndarray,
        output: np.ndarray,
        hp_slot: int,
        lp_slot: int,
        *,
        highpass_hz: float,
        lowpass_hz: float,
        shelf_db: float,
    ) -> np.ndarray:
        self._highpass(source, output, hp_slot, highpass_hz)
        self._lowpass(output, output, lp_slot, lowpass_hz)
        if shelf_db:
            output *= db_to_linear(shelf_db)
        return output

    def _highpass(self, source: np.ndarray, output: np.ndarray, slot: int, cutoff_hz: float) -> np.ndarray:
        alpha = 1.0 / (1.0 + (2.0 * np.pi * cutoff_hz / self.sample_rate))
        x1 = float(self._hp_x1[slot])
        y1 = float(self._hp_y1[slot])
        for index in range(len(source)):
            sample = float(source[index])
            value = alpha * (y1 + sample - x1)
            output[index] = value
            x1 = sample
            y1 = value
        self._hp_x1[slot] = x1
        self._hp_y1[slot] = y1
        return output

    def _lowpass(self, source: np.ndarray, output: np.ndarray, slot: int, cutoff_hz: float) -> np.ndarray:
        alpha = 1.0 - float(np.exp(-2.0 * np.pi * cutoff_hz / self.sample_rate))
        y1 = float(self._lp_y1[slot])
        for index in range(len(source)):
            y1 += alpha * (float(source[index]) - y1)
            output[index] = y1
        self._lp_y1[slot] = y1
        return output

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
        delay = self._dry_delay_samples
        head = min(frames, delay)
        processed16[:head] = self._dry_delay_buffer[:head]
        if frames > delay:
            processed16[delay:frames] = input16[: frames - delay]

        if frames >= delay:
            self._dry_delay_buffer[:] = input16[frames - delay:frames]
        else:
            keep = delay - frames
            self._dry_delay_buffer[:keep] = self._dry_delay_buffer[frames:]
            self._dry_delay_buffer[keep:] = input16[:frames]
