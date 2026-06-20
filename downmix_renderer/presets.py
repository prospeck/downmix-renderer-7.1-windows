from __future__ import annotations

from dataclasses import dataclass, field
import math
from time import time
from uuid import uuid4

from .constants import DEFAULT_CHANNEL_CONFIG, DEFAULT_PREAMP_DB, TRIM_MAX_DB, TRIM_MIN_DB
from .devices import AudioDevice, find_saved_device
from .sample_rates import DEFAULT_SAMPLE_RATE_MODE, normalize_sample_rate_mode

PRESET_SCHEMA_VERSION = 3
SUPPORTED_PRESET_SCHEMA_VERSIONS = {2, PRESET_SCHEMA_VERSION}
DEFAULT_AUDIO_STABILITY = "ultra"
_AUDIO_STABILITY_ALIASES = {
    "low_latency": "raw",
    "legacy_low": "raw",
    "low": "raw",
    "raw_mode": "raw",
    "normal": "ultra",
    "balanced": "ultra",
    "safe": "ultra",
    "stable": "ultra",
    "ultra_mode": "ultra",
}
_AUDIO_STABILITY_VALUES = {"ultra", "raw"}
GENERIC_OUTPUT_KEYWORDS = {
    "audio",
    "device",
    "headphone",
    "headphones",
    "output",
    "speaker",
    "speakers",
}
PREAMP_MIN_DB = -20
PREAMP_MAX_DB = 0


@dataclass
class Preset:
    id: str
    name: str
    input_device: dict[str, object] | None = None
    output_device: dict[str, object] | None = None
    preamp_db: int = DEFAULT_PREAMP_DB
    user_volume: float = 1.0
    channel_config: str = DEFAULT_CHANNEL_CONFIG
    surround_fill_enabled: bool = False
    upmix_9_1_6_enabled: bool = False
    channel_sanity_enabled: bool = False
    sound_enhancer_enabled: bool = False
    audio_stability: str = DEFAULT_AUDIO_STABILITY
    sample_rate_mode: str = DEFAULT_SAMPLE_RATE_MODE
    output_keywords: list[str] = field(default_factory=list)
    lr_swap_enabled: bool = False
    global_peq_enabled: bool = False
    global_peq_text: str = ""
    global_peq_visible: bool = True
    speaker_eq_enabled: bool = False
    speaker_eq_text: str = ""
    speaker_eq_visible: bool = True
    trim_left_db: float = 0.0
    trim_right_db: float = 0.0
    user_created: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Preset":
        return cls(
            id=str(data.get("id") or f"preset-{uuid4().hex[:8]}"),
            name=str(data.get("name") or "Preset"),
            input_device=data.get("input_device") if isinstance(data.get("input_device"), dict) else None,
            output_device=data.get("output_device") if isinstance(data.get("output_device"), dict) else None,
            preamp_db=_normalize_preamp_db(data.get("preamp_db", DEFAULT_PREAMP_DB)),
            user_volume=_normalize_user_volume(data.get("user_volume", 1.0)),
            channel_config=str(data.get("channel_config", DEFAULT_CHANNEL_CONFIG)),
            surround_fill_enabled=bool(data.get("surround_fill_enabled", False)),
            upmix_9_1_6_enabled=bool(data.get("upmix_9_1_6_enabled", False)),
            channel_sanity_enabled=bool(data.get("channel_sanity_enabled", False)),
            sound_enhancer_enabled=bool(data.get("sound_enhancer_enabled", False)),
            audio_stability=_normalize_audio_stability(str(data.get("audio_stability") or DEFAULT_AUDIO_STABILITY)),
            sample_rate_mode=normalize_sample_rate_mode(data.get("sample_rate_mode", DEFAULT_SAMPLE_RATE_MODE)),
            output_keywords=_normalize_output_keywords(data.get("output_keywords", [])),
            lr_swap_enabled=bool(data.get("lr_swap_enabled", False)),
            global_peq_enabled=bool(data.get("global_peq_enabled", False)),
            global_peq_text=str(data.get("global_peq_text") or ""),
            global_peq_visible=bool(data.get("global_peq_visible", True)),
            speaker_eq_enabled=bool(data.get("speaker_eq_enabled", False)),
            speaker_eq_text=str(data.get("speaker_eq_text") or ""),
            speaker_eq_visible=bool(data.get("speaker_eq_visible", True)),
            trim_left_db=_normalize_trim_db(data.get("trim_left_db", 0.0)),
            trim_right_db=_normalize_trim_db(data.get("trim_right_db", 0.0)),
            user_created=bool(data.get("user_created", True)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "input_device": self.input_device,
            "output_device": self.output_device,
            "preamp_db": self.preamp_db,
            "user_volume": self.user_volume,
            "channel_config": self.channel_config,
            "surround_fill_enabled": self.surround_fill_enabled,
            "upmix_9_1_6_enabled": self.upmix_9_1_6_enabled,
            "channel_sanity_enabled": self.channel_sanity_enabled,
            "sound_enhancer_enabled": self.sound_enhancer_enabled,
            "audio_stability": self.audio_stability,
            "sample_rate_mode": normalize_sample_rate_mode(self.sample_rate_mode),
            "output_keywords": self.output_keywords,
            "lr_swap_enabled": self.lr_swap_enabled,
            "global_peq_enabled": self.global_peq_enabled,
            "global_peq_text": self.global_peq_text,
            "global_peq_visible": self.global_peq_visible,
            "speaker_eq_enabled": self.speaker_eq_enabled,
            "speaker_eq_text": self.speaker_eq_text,
            "speaker_eq_visible": self.speaker_eq_visible,
            "trim_left_db": _normalize_trim_db(self.trim_left_db),
            "trim_right_db": _normalize_trim_db(self.trim_right_db),
            "user_created": self.user_created,
        }


def load_presets(settings: dict[str, object], devices: list[AudioDevice]) -> list[Preset]:
    if _safe_int(settings.get("preset_schema_version", 0), 0) not in SUPPORTED_PRESET_SCHEMA_VERSIONS:
        return []
    raw_presets = settings.get("presets")
    if isinstance(raw_presets, list) and raw_presets:
        presets: list[Preset] = []
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            try:
                presets.append(Preset.from_dict(item))
            except Exception:
                continue
        return presets
    return []


def preset_from_current(
    name: str,
    input_device: AudioDevice | None,
    output_device: AudioDevice | None,
    preamp_db: int,
    user_volume: float,
    channel_config: str,
    surround_fill_enabled: bool = False,
    upmix_9_1_6_enabled: bool = False,
    channel_sanity_enabled: bool = False,
    sound_enhancer_enabled: bool = False,
    audio_stability: str = DEFAULT_AUDIO_STABILITY,
    sample_rate_mode: str = DEFAULT_SAMPLE_RATE_MODE,
    lr_swap_enabled: bool = False,
    global_peq_enabled: bool = False,
    global_peq_text: str = "",
    global_peq_visible: bool = True,
    speaker_eq_enabled: bool = False,
    speaker_eq_text: str = "",
    speaker_eq_visible: bool = True,
    trim_left_db: float = 0.0,
    trim_right_db: float = 0.0,
) -> Preset:
    return Preset(
        id=f"preset-{int(time())}-{uuid4().hex[:6]}",
        name=name.strip() or "Preset",
        input_device=_identity(input_device, "input"),
        output_device=_identity(output_device, "output"),
        preamp_db=preamp_db,
        user_volume=user_volume,
        channel_config=channel_config,
        surround_fill_enabled=surround_fill_enabled,
        upmix_9_1_6_enabled=upmix_9_1_6_enabled,
        channel_sanity_enabled=channel_sanity_enabled,
        sound_enhancer_enabled=sound_enhancer_enabled,
        audio_stability=_normalize_audio_stability(audio_stability),
        sample_rate_mode=normalize_sample_rate_mode(sample_rate_mode),
        output_keywords=_keywords_for(output_device),
        lr_swap_enabled=lr_swap_enabled,
        global_peq_enabled=global_peq_enabled,
        global_peq_text=global_peq_text,
        global_peq_visible=global_peq_visible,
        speaker_eq_enabled=speaker_eq_enabled,
        speaker_eq_text=speaker_eq_text,
        speaker_eq_visible=speaker_eq_visible,
        trim_left_db=_normalize_trim_db(trim_left_db),
        trim_right_db=_normalize_trim_db(trim_right_db),
    )


def update_preset_from_current(
    preset: Preset,
    input_device: AudioDevice | None,
    output_device: AudioDevice | None,
    preamp_db: int,
    user_volume: float,
    channel_config: str,
    surround_fill_enabled: bool = False,
    upmix_9_1_6_enabled: bool = False,
    channel_sanity_enabled: bool = False,
    sound_enhancer_enabled: bool = False,
    audio_stability: str = DEFAULT_AUDIO_STABILITY,
    sample_rate_mode: str = DEFAULT_SAMPLE_RATE_MODE,
    lr_swap_enabled: bool = False,
    global_peq_enabled: bool = False,
    global_peq_text: str = "",
    global_peq_visible: bool = True,
    speaker_eq_enabled: bool = False,
    speaker_eq_text: str = "",
    speaker_eq_visible: bool = True,
    trim_left_db: float = 0.0,
    trim_right_db: float = 0.0,
) -> None:
    preset.input_device = _identity(input_device, "input")
    preset.output_device = _identity(output_device, "output")
    preset.preamp_db = preamp_db
    preset.user_volume = user_volume
    preset.channel_config = channel_config
    preset.surround_fill_enabled = surround_fill_enabled
    preset.upmix_9_1_6_enabled = upmix_9_1_6_enabled
    preset.channel_sanity_enabled = channel_sanity_enabled
    preset.sound_enhancer_enabled = sound_enhancer_enabled
    preset.audio_stability = _normalize_audio_stability(audio_stability)
    preset.sample_rate_mode = normalize_sample_rate_mode(sample_rate_mode)
    preset.output_keywords = _keywords_for(output_device)
    preset.lr_swap_enabled = lr_swap_enabled
    preset.global_peq_enabled = global_peq_enabled
    preset.global_peq_text = global_peq_text
    preset.global_peq_visible = global_peq_visible
    preset.speaker_eq_enabled = speaker_eq_enabled
    preset.speaker_eq_text = speaker_eq_text
    preset.speaker_eq_visible = speaker_eq_visible
    preset.trim_left_db = _normalize_trim_db(trim_left_db)
    preset.trim_right_db = _normalize_trim_db(trim_right_db)


def match_preset_for_output(
    presets: list[Preset],
    active_output: AudioDevice | None,
    devices: list[AudioDevice],
) -> Preset | None:
    if active_output is None:
        return None

    best: tuple[int, Preset] | None = None
    active_name = active_output.name.lower()
    for preset in presets:
        score = 0
        matched_identity = False
        preset_output = find_saved_device(devices, preset.output_device, "output")
        if preset.output_device is not None and preset_output is None:
            continue
        if preset_output is None:
            continue
        preset_endpoint = preset_output.native_endpoint_for("output")
        active_endpoint = active_output.native_endpoint_for("output")
        if preset_endpoint and active_endpoint and preset_endpoint != active_endpoint:
            continue
        if preset_output.id == active_output.id:
            score += 1000
            matched_identity = True
        if preset_output.name == active_output.name and preset_output.hostapi == active_output.hostapi:
            score += 250
            matched_identity = True
        elif preset_output.name.lower() == active_name:
            score += 150
            matched_identity = True
        if preset_endpoint and active_endpoint and preset_endpoint == active_endpoint:
            score += 2000
            matched_identity = True
        for keyword in preset.output_keywords:
            if keyword and keyword not in GENERIC_OUTPUT_KEYWORDS and keyword in active_name:
                score += 5
                matched_identity = True
        if not matched_identity:
            continue
        if preset_output.hostapi == active_output.hostapi:
            score += 10
        if score and (best is None or score > best[0]):
            best = (score, preset)
    return best[1] if best else None


def _identity(device: AudioDevice | None, mode: str) -> dict[str, object] | None:
    return device.identity(mode) if device else None


def _normalize_audio_stability(value: str) -> str:
    normalized = _AUDIO_STABILITY_ALIASES.get(value, value)
    return normalized if normalized in _AUDIO_STABILITY_VALUES else DEFAULT_AUDIO_STABILITY


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _normalize_preamp_db(value: object) -> int:
    parsed = _safe_int(value, DEFAULT_PREAMP_DB)
    return max(PREAMP_MIN_DB, min(PREAMP_MAX_DB, parsed))


def _normalize_user_volume(value: object) -> float:
    parsed = _safe_float(value, 1.0)
    return max(0.0, min(1.0, parsed))


def _normalize_output_keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).lower() for item in value if str(item).strip()]


def _normalize_trim_db(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(TRIM_MIN_DB, min(TRIM_MAX_DB, parsed))


def _keywords_for(device: AudioDevice | None) -> list[str]:
    if device is None:
        return []
    lower = device.name.lower()
    keywords = []
    for keyword in ("qudelix", "bluetooth", "bt", "usb", "dac", "realtek"):
        if keyword in lower:
            keywords.append(keyword)
    return keywords
