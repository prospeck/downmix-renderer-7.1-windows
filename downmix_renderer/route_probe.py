from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd

from .constants import MAX_INPUT_CHANNELS, OUTPUT_CHANNELS, SAMPLE_RATE
from .devices import AudioDevice, check_format_support, list_devices


@dataclass(frozen=True)
class FormatCheck:
    device_id: int
    name: str
    hostapi: str
    mode: str
    channels: int
    samplerate: int
    ok: bool
    detail: str


@dataclass(frozen=True)
class CaptureResult:
    attempted: bool
    device_id: int | None
    name: str
    hostapi: str
    samplerate: int
    channels: int
    duration_seconds: float
    frames_captured: int
    threshold: float
    peaks: list[float]
    rms: list[float]
    front_correlations: list[float]
    active_channels: list[int]
    likely_windows_channel_fill: bool
    truth: str
    detail: str


def inventory() -> dict[str, object]:
    devices = list_devices()
    return {
        "hostapis": list(sd.query_hostapis()),
        "default_device": list(sd.default.device),
        "devices": [dev.to_dict() for dev in devices],
        "format_checks": [asdict(check) for check in format_checks(devices)],
    }


def format_checks(devices: list[AudioDevice]) -> list[FormatCheck]:
    checks: list[FormatCheck] = []
    for dev in devices:
        if dev.max_input_channels > 0:
            ok, detail = check_format_support(dev.id, "input", MAX_INPUT_CHANNELS, SAMPLE_RATE)
            checks.append(
                FormatCheck(
                    dev.id,
                    dev.name,
                    dev.hostapi,
                    "input",
                    MAX_INPUT_CHANNELS,
                    SAMPLE_RATE,
                    ok,
                    detail,
                )
            )
        if dev.max_output_channels > 0:
            ok, detail = check_format_support(dev.id, "output", OUTPUT_CHANNELS, SAMPLE_RATE)
            checks.append(
                FormatCheck(
                    dev.id,
                    dev.name,
                    dev.hostapi,
                    "output",
                    OUTPUT_CHANNELS,
                    SAMPLE_RATE,
                    ok,
                    detail,
                )
            )
    return checks


def preferred_capture_device(devices: list[AudioDevice]) -> AudioDevice | None:
    candidates = [dev for dev in devices if dev.max_input_channels >= MAX_INPUT_CHANNELS]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda dev: (
            "CABLE Output" not in dev.name,
            "Windows WASAPI" not in dev.hostapi,
            dev.default_samplerate != SAMPLE_RATE,
            dev.id,
        ),
    )[0]


def capture_device_by_id(devices: list[AudioDevice], device_id: int | None) -> AudioDevice | None:
    if device_id is None:
        return None
    return next(
        (dev for dev in devices if dev.id == device_id and dev.max_input_channels >= MAX_INPUT_CHANNELS),
        None,
    )


def capture_activity(
    device: AudioDevice | None = None,
    duration_seconds: float = 20.0,
    threshold: float = 1e-4,
) -> CaptureResult:
    devices = list_devices()
    selected = device or preferred_capture_device(devices)
    if selected is None:
        return CaptureResult(
            False,
            None,
            "",
            "",
            SAMPLE_RATE,
            MAX_INPUT_CHANNELS,
            0.0,
            0,
            threshold,
            [],
            [],
            [],
            [],
            False,
            "no_16ch_capture_device",
            "No input device exposes 16 capture channels",
        )

    peaks = np.zeros(MAX_INPUT_CHANNELS, dtype=np.float64)
    square_sum = np.zeros(MAX_INPUT_CHANNELS, dtype=np.float64)
    cross_sum = np.zeros((MAX_INPUT_CHANNELS, 2), dtype=np.float64)
    frame_count = 0

    def callback(indata, frames, time_info, status) -> None:
        nonlocal frame_count
        data = indata[:, :MAX_INPUT_CHANNELS]
        peaks[:] = np.maximum(peaks, np.max(np.abs(data), axis=0))
        square_sum[:] += np.sum(np.square(data, dtype=np.float64), axis=0)
        cross_sum[:, 0] += np.sum(data * data[:, 0:1], axis=0)
        cross_sum[:, 1] += np.sum(data * data[:, 1:2], axis=0)
        frame_count += frames

    started = time.monotonic()
    try:
        with sd.InputStream(
            device=selected.id,
            channels=MAX_INPUT_CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=256,
            dtype="float32",
            latency="low",
            callback=callback,
        ):
            while time.monotonic() - started < duration_seconds:
                time.sleep(0.05)
    except Exception as exc:
        return CaptureResult(
            True,
            selected.id,
            selected.name,
            selected.hostapi,
            SAMPLE_RATE,
            MAX_INPUT_CHANNELS,
            max(0.0, time.monotonic() - started),
            frame_count,
            threshold,
            peaks.tolist(),
            [],
            [],
            [],
            False,
            "capture_failed",
            f"{type(exc).__name__}: {exc}",
        )

    rms = np.sqrt(square_sum / max(frame_count, 1))
    front_correlations = _front_correlations(square_sum, cross_sum)
    active = [index + 1 for index, value in enumerate(peaks) if value > threshold]
    likely_fill = _looks_like_windows_channel_fill(active, rms, front_correlations, threshold)
    if not active:
        truth = "no_signal"
        detail = "No channels crossed threshold during capture"
    elif max(active) > 8:
        truth = "channels_above_8_detected"
        detail = "Installed route delivered signal above 7.1"
    elif likely_fill:
        truth = "likely_channel_fill"
        detail = "Channels above stereo closely track front L/R; Windows/device enhancement or channel-fill is likely upstream"
    else:
        truth = "eight_or_fewer_channels"
        detail = "Installed route did not deliver signal above channel 8"

    return CaptureResult(
        True,
        selected.id,
        selected.name,
        selected.hostapi,
        SAMPLE_RATE,
        MAX_INPUT_CHANNELS,
        max(0.0, time.monotonic() - started),
        frame_count,
        threshold,
        peaks.tolist(),
        rms.tolist(),
        front_correlations,
        active,
        likely_fill,
        truth,
        detail,
    )


def _front_correlations(square_sum: np.ndarray, cross_sum: np.ndarray) -> list[float]:
    correlations: list[float] = []
    left_energy = max(float(square_sum[0]), 1e-12)
    right_energy = max(float(square_sum[1]), 1e-12)
    for index in range(MAX_INPUT_CHANNELS):
        energy = max(float(square_sum[index]), 1e-12)
        left_corr = abs(float(cross_sum[index, 0])) / np.sqrt(energy * left_energy)
        right_corr = abs(float(cross_sum[index, 1])) / np.sqrt(energy * right_energy)
        correlations.append(float(min(1.0, max(left_corr, right_corr))))
    return correlations


def _looks_like_windows_channel_fill(
    active_channels: list[int],
    rms: np.ndarray,
    front_correlations: list[float],
    threshold: float,
) -> bool:
    if len(active_channels) < 4 or not {1, 2}.issubset(set(active_channels)):
        return False
    front_rms = max(float(rms[0]), float(rms[1]), threshold)
    copied = 0
    for channel_number in active_channels:
        index = channel_number - 1
        if index < 2:
            continue
        rms_ratio = float(rms[index]) / front_rms
        if front_correlations[index] >= 0.985 and 0.35 <= rms_ratio <= 1.65:
            copied += 1
    return copied >= 2


def run_probe(duration_seconds: float, threshold: float, device_id: int | None = None) -> dict[str, object]:
    result = inventory()
    if duration_seconds > 0:
        devices = list_devices()
        selected = capture_device_by_id(devices, device_id) or preferred_capture_device(devices)
        result["capture"] = asdict(
            capture_activity(selected, duration_seconds=duration_seconds, threshold=threshold)
        )
    else:
        result["capture"] = asdict(
            CaptureResult(
                False,
                None,
                "",
                "",
                SAMPLE_RATE,
                MAX_INPUT_CHANNELS,
                0.0,
                0,
                threshold,
                [],
                [],
                [],
                [],
                False,
                "not_captured",
                "Run with --duration while Apple Music Atmos is playing",
            )
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Windows 16-channel renderer routing")
    parser.add_argument("--duration", type=float, default=0.0, help="Capture duration in seconds")
    parser.add_argument("--threshold", type=float, default=1e-4, help="Peak threshold for active channel")
    parser.add_argument("--device-id", type=int, help="Capture a specific PortAudio input device ID")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    args = parser.parse_args(argv)

    report = run_probe(args.duration, args.threshold, args.device_id)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
