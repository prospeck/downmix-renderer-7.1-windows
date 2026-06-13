from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import math
import re


MAX_FILTERS_PER_STAGE = 32
MAX_GAIN_DB = 24.0
MIN_Q = 0.1
MAX_Q = 20.0
MIN_FREQUENCY_HZ = 5.0
SHELF_DEFAULT_Q = 0.7071067811865476
SAMPLE_RATE_FALLBACK = 48000.0

_FILTER_RE = re.compile(r"^\s*Filter(?:\s+\d+)?\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE)
_PREAMP_RE = re.compile(r"^\s*Preamp\s*:\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*dB\b", re.IGNORECASE)
_CHANNEL_RE = re.compile(r"^\s*(?:Channel|Channels)\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE)
_CH_PREFIX_RE = re.compile(r"^\s*CH\s*[:=]\s*(?P<channel>[01LRlr])\b\s*(?P<body>.*)$", re.IGNORECASE)
_CH_INLINE_RE = re.compile(r"\bCH\s*[:=]\s*(?P<channel>[01])\b", re.IGNORECASE)
_NUMBER_RE = r"([+-]?\d+(?:\.\d+)?)"


@dataclass(frozen=True)
class BiquadCoefficients:
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        return (self.b0, self.b1, self.b2, self.a1, self.a2)


@dataclass(frozen=True)
class PeqFilter:
    kind: str
    frequency_hz: float
    gain_db: float
    q: float
    source_line: int = 0


@dataclass(frozen=True)
class PeqCascade:
    enabled: bool = False
    preamp_db: float = 0.0
    filters: tuple[PeqFilter, ...] = ()
    biquads: tuple[BiquadCoefficients, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.enabled and (self.biquads or abs(self.preamp_db) > 1e-9))


@dataclass(frozen=True)
class PeqRuntimeConfig:
    global_cascade: PeqCascade = field(default_factory=PeqCascade)
    speaker_left: PeqCascade = field(default_factory=PeqCascade)
    speaker_right: PeqCascade = field(default_factory=PeqCascade)
    speaker_enabled: bool = False
    lr_swap_enabled: bool = False
    sample_rate: float = SAMPLE_RATE_FALLBACK
    generation: int = 0

    @property
    def bypassed(self) -> bool:
        return (
            not self.global_cascade.active
            and not (self.speaker_enabled and (self.speaker_left.active or self.speaker_right.active))
            and not self.lr_swap_enabled
        )


@dataclass(frozen=True)
class PeqParseReport:
    warnings: tuple[str, ...] = ()
    global_filter_count: int = 0
    speaker_left_filter_count: int = 0
    speaker_right_filter_count: int = 0

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


@dataclass(frozen=True)
class _ParsedProgram:
    shared_filters: tuple[PeqFilter, ...]
    left_filters: tuple[PeqFilter, ...]
    right_filters: tuple[PeqFilter, ...]
    shared_preamp_db: float
    left_preamp_db: float
    right_preamp_db: float
    warnings: tuple[str, ...]


def build_runtime_config(
    *,
    global_text: str,
    global_enabled: bool,
    speaker_text: str,
    speaker_enabled: bool,
    lr_swap_enabled: bool,
    sample_rate: float,
    generation: int = 0,
) -> tuple[PeqRuntimeConfig, PeqParseReport]:
    sample_rate = _safe_sample_rate(sample_rate)
    global_program = _parse_program_cached(str(global_text or ""), sample_rate)
    speaker_program = _parse_program_cached(str(speaker_text or ""), sample_rate)

    global_filters, global_preamp, global_warnings = _global_stage_from_program(global_program)
    global_biquads, global_compile_warnings = _compile_filters(global_filters, sample_rate)

    speaker_left_filters = speaker_program.shared_filters + speaker_program.left_filters
    speaker_right_filters = speaker_program.shared_filters + speaker_program.right_filters
    speaker_left_preamp = _clamp_gain(speaker_program.shared_preamp_db + speaker_program.left_preamp_db)
    speaker_right_preamp = _clamp_gain(speaker_program.shared_preamp_db + speaker_program.right_preamp_db)
    speaker_left_biquads, speaker_left_warnings = _compile_filters(speaker_left_filters, sample_rate)
    speaker_right_biquads, speaker_right_warnings = _compile_filters(speaker_right_filters, sample_rate)

    # Speaker files are imported as CH:0 / CH:1. The physical output mapping flips
    # with L/R swap to match the Sharur/Qudelix-style route contract.
    if lr_swap_enabled:
        mapped_left_filters = speaker_right_filters
        mapped_right_filters = speaker_left_filters
        mapped_left_preamp = speaker_right_preamp
        mapped_right_preamp = speaker_left_preamp
        mapped_left_biquads = speaker_right_biquads
        mapped_right_biquads = speaker_left_biquads
    else:
        mapped_left_filters = speaker_left_filters
        mapped_right_filters = speaker_right_filters
        mapped_left_preamp = speaker_left_preamp
        mapped_right_preamp = speaker_right_preamp
        mapped_left_biquads = speaker_left_biquads
        mapped_right_biquads = speaker_right_biquads

    warnings = (
        global_program.warnings
        + global_warnings
        + global_compile_warnings
        + speaker_program.warnings
        + speaker_left_warnings
        + speaker_right_warnings
    )
    config = PeqRuntimeConfig(
        global_cascade=PeqCascade(
            enabled=bool(global_enabled),
            preamp_db=global_preamp,
            filters=global_filters,
            biquads=global_biquads,
        ),
        speaker_left=PeqCascade(
            enabled=bool(speaker_enabled),
            preamp_db=mapped_left_preamp,
            filters=mapped_left_filters,
            biquads=mapped_left_biquads,
        ),
        speaker_right=PeqCascade(
            enabled=bool(speaker_enabled),
            preamp_db=mapped_right_preamp,
            filters=mapped_right_filters,
            biquads=mapped_right_biquads,
        ),
        speaker_enabled=bool(speaker_enabled),
        lr_swap_enabled=bool(lr_swap_enabled),
        sample_rate=sample_rate,
        generation=int(generation),
    )
    report = PeqParseReport(
        warnings=warnings,
        global_filter_count=len(global_filters),
        speaker_left_filter_count=len(speaker_left_filters),
        speaker_right_filter_count=len(speaker_right_filters),
    )
    return config, report


@lru_cache(maxsize=64)
def _parse_program_cached(text: str, sample_rate: float) -> _ParsedProgram:
    del sample_rate
    return _parse_program(text)


def _parse_program(text: str) -> _ParsedProgram:
    shared_filters: list[PeqFilter] = []
    left_filters: list[PeqFilter] = []
    right_filters: list[PeqFilter] = []
    shared_preamp = 0.0
    left_preamp = 0.0
    right_preamp = 0.0
    warnings: list[str] = []
    current_channels: tuple[int, ...] | None = None

    for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        line_channel = None
        prefix = _CH_PREFIX_RE.match(line)
        if prefix:
            line_channel = _channel_token_to_index(prefix.group("channel"), qudelix_zero_based=True)
            line = prefix.group("body").strip()
            if not line:
                current_channels = (line_channel,) if line_channel is not None else None
                continue

        channel_match = _CHANNEL_RE.match(line)
        if channel_match:
            parsed = _parse_channel_list(channel_match.group("body"))
            if parsed is None:
                current_channels = None
                warnings.append(f"Line {line_no}: unsupported channel selector ignored.")
            else:
                current_channels = parsed
            continue

        inline = _CH_INLINE_RE.search(line)
        if inline and line_channel is None:
            line_channel = _channel_token_to_index(inline.group("channel"), qudelix_zero_based=True)

        preamp_match = _PREAMP_RE.match(line)
        if preamp_match:
            value = _parse_float(preamp_match.group("value"))
            if value is None:
                warnings.append(f"Line {line_no}: malformed preamp ignored.")
                continue
            value = _clamp_gain(value)
            targets = (line_channel,) if line_channel is not None else current_channels
            if targets is None:
                shared_preamp = _clamp_gain(shared_preamp + value)
            else:
                if 0 in targets:
                    left_preamp = _clamp_gain(left_preamp + value)
                if 1 in targets:
                    right_preamp = _clamp_gain(right_preamp + value)
            continue

        filter_match = _FILTER_RE.match(line)
        if not filter_match:
            # Equalizer APO ignores unknown commands; keep that behavior, but expose
            # a compact status so malformed PEQ text is debuggable.
            if ":" in line:
                warnings.append(f"Line {line_no}: unsupported command ignored.")
            continue

        parsed_filter = _parse_filter_body(filter_match.group("body"), line_no)
        if isinstance(parsed_filter, str):
            if parsed_filter:
                warnings.append(parsed_filter)
            continue

        targets = (line_channel,) if line_channel is not None else current_channels
        if targets is None:
            _append_limited(shared_filters, parsed_filter, warnings, "shared")
        else:
            if 0 in targets:
                _append_limited(left_filters, parsed_filter, warnings, "left")
            if 1 in targets:
                _append_limited(right_filters, parsed_filter, warnings, "right")

    return _ParsedProgram(
        shared_filters=tuple(shared_filters),
        left_filters=tuple(left_filters),
        right_filters=tuple(right_filters),
        shared_preamp_db=shared_preamp,
        left_preamp_db=left_preamp,
        right_preamp_db=right_preamp,
        warnings=tuple(warnings[:24]),
    )


def _parse_filter_body(body: str, line_no: int) -> PeqFilter | str:
    normalized = " ".join(body.replace(",", " ").split())
    tokens = normalized.split()
    if not tokens:
        return f"Line {line_no}: empty filter ignored."
    if tokens[0].casefold() == "off":
        return ""
    if tokens[0].casefold() != "on":
        return f"Line {line_no}: filter is not ON and was ignored."
    if len(tokens) < 2:
        return f"Line {line_no}: filter type missing."

    kind = tokens[1].upper()
    if kind in {"XFEED", "CROSSFEED"}:
        return ""
    aliases = {
        "PK": "PK",
        "PEQ": "PK",
        "LS": "LS",
        "LSC": "LS",
        "LSHELF": "LS",
        "LOWSHELF": "LS",
        "HS": "HS",
        "HSC": "HS",
        "HSHELF": "HS",
        "HIGHSHELF": "HS",
        "LP": "LP",
        "LPF": "LP",
        "LOWPASS": "LP",
        "HP": "HP",
        "HPF": "HP",
        "HIGHPASS": "HP",
    }
    if kind not in aliases:
        return f"Line {line_no}: unsupported filter type {kind} ignored."
    kind = aliases[kind]

    frequency = _field_number(normalized, r"\bFc\s+" + _NUMBER_RE)
    gain = _field_number(normalized, r"\bGain\s+" + _NUMBER_RE)
    q = _field_number(normalized, r"\bQ\s+" + _NUMBER_RE)
    bandwidth = _field_number(normalized, r"\bBW\s+Oct\s+" + _NUMBER_RE)

    if frequency is None:
        return f"Line {line_no}: filter frequency missing."
    if gain is None:
        if kind in {"LP", "HP"}:
            gain = 0.0
        else:
            return f"Line {line_no}: filter gain missing."
    if q is None and bandwidth is not None:
        q = _bandwidth_octaves_to_q(bandwidth)
    if q is None and kind in {"LP", "HP"}:
        q = SHELF_DEFAULT_Q
    if q is None:
        q = SHELF_DEFAULT_Q if kind in {"LS", "HS"} else None
    if q is None:
        return f"Line {line_no}: peaking filter Q missing."

    frequency = float(frequency)
    gain = _clamp_gain(float(gain))
    q = _clamp_q(float(q))
    if not math.isfinite(frequency) or frequency <= 0:
        return f"Line {line_no}: invalid frequency ignored."

    return PeqFilter(
        kind=kind,
        frequency_hz=frequency,
        gain_db=gain,
        q=q,
        source_line=line_no,
    )


def _compile_filters(filters: tuple[PeqFilter, ...], sample_rate: float) -> tuple[tuple[BiquadCoefficients, ...], tuple[str, ...]]:
    compiled: list[BiquadCoefficients] = []
    warnings: list[str] = []
    nyquist = sample_rate * 0.5
    max_frequency = max(MIN_FREQUENCY_HZ, nyquist * 0.98)
    for filt in filters[:MAX_FILTERS_PER_STAGE]:
        frequency = min(max(float(filt.frequency_hz), MIN_FREQUENCY_HZ), max_frequency)
        try:
            coeff = _biquad_for_filter(filt.kind, frequency, filt.gain_db, filt.q, sample_rate)
        except (ValueError, OverflowError):
            warnings.append(f"Line {filt.source_line}: unstable filter ignored.")
            continue
        if _coefficients_are_finite(coeff):
            compiled.append(coeff)
        else:
            warnings.append(f"Line {filt.source_line}: non-finite filter ignored.")
    if len(filters) > MAX_FILTERS_PER_STAGE:
        warnings.append(f"Only the first {MAX_FILTERS_PER_STAGE} filters were used for one PEQ stage.")
    return tuple(compiled), tuple(warnings[:24])


def _biquad_for_filter(kind: str, frequency_hz: float, gain_db: float, q: float, sample_rate: float) -> BiquadCoefficients:
    w0 = 2.0 * math.pi * frequency_hz / sample_rate
    sin_w0 = math.sin(w0)
    cos_w0 = math.cos(w0)
    a = 10.0 ** (gain_db / 40.0)
    alpha = sin_w0 / (2.0 * q)

    if kind == "PK":
        b0 = 1.0 + alpha * a
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * a
        a0 = 1.0 + alpha / a
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / a
    elif kind == "LS":
        beta = 2.0 * math.sqrt(a) * alpha
        b0 = a * ((a + 1.0) - (a - 1.0) * cos_w0 + beta)
        b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w0)
        b2 = a * ((a + 1.0) - (a - 1.0) * cos_w0 - beta)
        a0 = (a + 1.0) + (a - 1.0) * cos_w0 + beta
        a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w0)
        a2 = (a + 1.0) + (a - 1.0) * cos_w0 - beta
    elif kind == "HS":
        beta = 2.0 * math.sqrt(a) * alpha
        b0 = a * ((a + 1.0) + (a - 1.0) * cos_w0 + beta)
        b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w0)
        b2 = a * ((a + 1.0) + (a - 1.0) * cos_w0 - beta)
        a0 = (a + 1.0) - (a - 1.0) * cos_w0 + beta
        a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w0)
        a2 = (a + 1.0) - (a - 1.0) * cos_w0 - beta
    elif kind == "LP":
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif kind == "HP":
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    else:
        raise ValueError(kind)

    if abs(a0) < 1e-24:
        raise ValueError("zero a0")
    return BiquadCoefficients(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def _global_stage_from_program(program: _ParsedProgram) -> tuple[tuple[PeqFilter, ...], float, tuple[str, ...]]:
    warnings: list[str] = []
    if program.shared_filters or abs(program.shared_preamp_db) > 1e-9:
        if program.left_filters or program.right_filters:
            warnings.append("Global PEQ used shared filters and ignored channel-specific filters.")
        return program.shared_filters, program.shared_preamp_db, tuple(warnings)
    if program.left_filters and not program.right_filters:
        warnings.append("Global PEQ used left/CH:0 filters because no shared filters were present.")
        return program.left_filters, program.left_preamp_db, tuple(warnings)
    if program.right_filters and not program.left_filters:
        warnings.append("Global PEQ used right/CH:1 filters because no shared filters were present.")
        return program.right_filters, program.right_preamp_db, tuple(warnings)
    if program.left_filters and program.right_filters:
        warnings.append("Global PEQ used left/CH:0 filters and ignored right/CH:1 filters.")
        return program.left_filters, program.left_preamp_db, tuple(warnings)
    return (), 0.0, ()


def _parse_channel_list(body: str) -> tuple[int, ...] | None:
    channels: list[int] = []
    for raw in re.split(r"[\s,;]+", body.strip()):
        if not raw:
            continue
        index = _channel_token_to_index(raw, qudelix_zero_based=False)
        if index is None:
            continue
        if index not in channels:
            channels.append(index)
    return tuple(channels) if channels else None


def _channel_token_to_index(token: str, *, qudelix_zero_based: bool) -> int | None:
    clean = token.strip().strip("[]()").upper()
    if clean in {"L", "LEFT", "FL", "CH0"}:
        return 0
    if clean in {"R", "RIGHT", "FR", "CH1"}:
        return 1
    if clean in {"0", "1"} and qudelix_zero_based:
        return int(clean)
    if clean == "1":
        return 0
    if clean == "2":
        return 1
    return None


def _append_limited(target: list[PeqFilter], filt: PeqFilter, warnings: list[str], label: str) -> None:
    if len(target) >= MAX_FILTERS_PER_STAGE:
        if not any(f"Only the first {MAX_FILTERS_PER_STAGE}" in warning and label in warning for warning in warnings):
            warnings.append(f"Only the first {MAX_FILTERS_PER_STAGE} {label} filters were used.")
        return
    target.append(filt)


def _field_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return _parse_float(match.group(1)) if match else None


def _parse_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _clamp_gain(value: float) -> float:
    return min(MAX_GAIN_DB, max(-MAX_GAIN_DB, float(value)))


def _clamp_q(value: float) -> float:
    return min(MAX_Q, max(MIN_Q, float(value)))


def _safe_sample_rate(sample_rate: float) -> float:
    try:
        value = float(sample_rate)
    except (TypeError, ValueError):
        value = SAMPLE_RATE_FALLBACK
    return value if math.isfinite(value) and value > 1000.0 else SAMPLE_RATE_FALLBACK


def _bandwidth_octaves_to_q(bandwidth: float) -> float:
    bw = max(1e-6, float(bandwidth))
    return 1.0 / (2.0 * math.sinh(math.log(2.0) * bw / 2.0))


def _coefficients_are_finite(coeff: BiquadCoefficients) -> bool:
    return all(math.isfinite(value) for value in coeff.as_tuple())
