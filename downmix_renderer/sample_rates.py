from __future__ import annotations

import math

from .constants import SAMPLE_RATE

SAMPLE_RATE_MODE_AUTO = "auto"
SUPPORTED_SAMPLE_RATES = (48000, 96000, 192000)
SAMPLE_RATE_MODES = (SAMPLE_RATE_MODE_AUTO, *(str(rate) for rate in SUPPORTED_SAMPLE_RATES))
SAMPLE_RATE_LABELS = {
    SAMPLE_RATE_MODE_AUTO: "Auto",
    "48000": "48 kHz",
    "96000": "96 kHz",
    "192000": "192 kHz",
}
DEFAULT_SAMPLE_RATE_MODE = SAMPLE_RATE_MODE_AUTO


def normalize_sample_rate_mode(value: object) -> str:
    if value is None:
        return DEFAULT_SAMPLE_RATE_MODE
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = int(round(float(value)))
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_SAMPLE_RATE_MODE
        return str(numeric) if numeric in SUPPORTED_SAMPLE_RATES else DEFAULT_SAMPLE_RATE_MODE

    text = str(value).strip().lower()
    if text in {"", "auto", "automatic", "default"}:
        return DEFAULT_SAMPLE_RATE_MODE

    compact = text.replace(" ", "")
    if compact.endswith("khz"):
        try:
            numeric = int(round(float(compact[:-3]) * 1000.0))
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_SAMPLE_RATE_MODE
    elif compact.endswith("k"):
        try:
            numeric = int(round(float(compact[:-1]) * 1000.0))
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_SAMPLE_RATE_MODE
    else:
        try:
            numeric = int(round(float(compact)))
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_SAMPLE_RATE_MODE
    return str(numeric) if numeric in SUPPORTED_SAMPLE_RATES else DEFAULT_SAMPLE_RATE_MODE


def resolve_sample_rate(sample_rate_mode: object, input_device: object | None = None, output_device: object | None = None) -> int:
    mode = normalize_sample_rate_mode(sample_rate_mode)
    if mode != SAMPLE_RATE_MODE_AUTO:
        return int(mode)

    for device in (input_device, output_device):
        rate = _device_default_rate(device)
        if rate in SUPPORTED_SAMPLE_RATES:
            return rate
    return SAMPLE_RATE


def sample_rate_label(sample_rate_mode: object) -> str:
    return SAMPLE_RATE_LABELS[normalize_sample_rate_mode(sample_rate_mode)]


def _device_default_rate(device: object | None) -> int | None:
    if device is None:
        return None
    try:
        value = float(getattr(device, "default_samplerate"))
    except (TypeError, ValueError, AttributeError):
        return None
    if not math.isfinite(value):
        return None
    return int(round(value))
