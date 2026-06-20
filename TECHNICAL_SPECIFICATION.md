# Downmix Renderer Technical Specification

Last updated: 2026-06-21

Current local production-test artifact: `production testing\Downmixrenderer.exe`

Executable name: `Downmixrenderer.exe`

## 1. Purpose And Scope

Downmix Renderer is a Windows desktop audio utility that captures a 16-channel WASAPI input stream, applies a fixed Sharur multichannel-to-stereo rendering path, and outputs stereo to a selected WASAPI playback device. The application is optimized for a VB-CABLE-style 16-channel capture route and a stereo DAC or speaker endpoint.

The production runtime is a PyQt5 control shell backed by a native C++ WASAPI/miniaudio renderer. A Python/sounddevice DSP path remains available for tests and legacy development via `DOWNMIX_RENDERER_AUDIO_BACKEND=python`.

This specification covers the current implementation and intentionally does not redefine or change audio logic. The fixed matrix coefficients, LFE timing behavior, limiter behavior, PEQ calculations, and channel mapping described here are implementation documentation, not proposed changes.

## 2. High-Level Architecture

The application is organized as a layered desktop renderer:

```text
User / UI controls
    |
    v
PyQt5 application shell (`downmix_renderer.app`)
    |
    v
AudioEngine orchestration (`downmix_renderer.audio_engine`)
    |
    +--> Native C++ WASAPI backend (`downmix_renderer.native_audio` -> `cpp_backend/downmix_native.cpp`)
    |
    +--> Python fallback backend (`sounddevice.Stream` + `downmix_renderer.dsp.DownmixProcessor`)
    |
    v
DSP pipeline: input normalize -> optional channel repair/upmix -> LFE/dry alignment -> matrix
    -> preamp -> PEQ/swap/correction -> trim -> optional Sound Enhancer -> limiter -> master volume -> stereo output
```

### 2.1 Design Approach

The design separates UI/state management from real-time audio processing:

- The PyQt layer owns controls, settings persistence, preset management, live diagnostics, route probing, and visual meters.
- `AudioEngine` owns stream lifecycle, runtime backend selection, route validation, snapshots, and Windows volume following.
- The native C++ backend owns the production duplex WASAPI stream and real-time DSP work.
- The Python DSP implementation mirrors the native algorithm for deterministic unit tests and fallback operation.
- Device and preset matching logic is isolated from the audio callback path.
- Settings are persisted atomically to avoid partial JSON writes.
- DSP parameters are applied through lock-protected Python state or atomic/native published configuration objects to avoid callback-time UI coupling.

### 2.2 Production Backend

The packaged app loads `downmix_renderer\downmix_renderer_native.dll`, which wraps miniaudio with WASAPI backend selection. The native engine:

- Captures 16 float32 channels at 48 kHz.
- Plays two float32 channels at 48 kHz.
- Uses a duplex WASAPI device.
- Opens streams in WASAPI shared mode in the current C++ configuration.
- Uses the `ultra` profile by default with a 128-frame block request at 48 kHz.
- Scales stream block requests at 96 kHz and 192 kHz to preserve the same approximate callback time budget as 48 kHz.
- Uses RAW fallback profile with a 256-frame block request at 48 kHz if needed, also scaled by sample rate.
- Registers the native callback thread with Windows MMCSS using the `Pro Audio` task category and critical AVRT priority when available.
- Publishes callback-invocation and processed-frame counters so the UI can verify stream liveness after device switches.
- Exposes a C ABI consumed by Python through `ctypes`.

The UI labels the stream as "Shared WASAPI" to match the native miniaudio configuration (`ma_share_mode_shared`) with pro-audio hints for the ultra profile.

### 2.3 Python Fallback Backend

The Python backend is selected by setting:

```powershell
$env:DOWNMIX_RENDERER_AUDIO_BACKEND = "python"
```

It uses `sounddevice.Stream`, the same public `AudioEngine` interface, and `DownmixProcessor` for DSP. This path is primarily useful for development comparison and unit testing.

## 3. Runtime Feature Breakdown

### 3.1 Device Routing

The renderer targets:

- Input: WASAPI device exposing at least 16 input channels.
- Output: WASAPI device exposing at least 2 output channels.
- Sample rate: auto-selected from route defaults or manually fixed to 48, 96, or 192 kHz.
- Audio format: float32.

Input devices are filtered to Windows WASAPI devices with `max_input_channels >= 16`. VB-CABLE-style devices are ranked first when their names indicate "VB-Audio Virtual Cable", "16 channel", or "16ch".

Output devices are filtered to Windows WASAPI devices with `max_output_channels >= 2`. Preferred outputs are ranked using common DAC/speaker keywords such as `qudelix`, `dac`, and `speakers`.

### 3.2 Renderer Transport

The main renderer control is a custom render toggle. It starts or stops `AudioEngine`.

Start sequence:

1. Read selected input and output devices.
2. Reject non-WASAPI routes.
3. Reject inputs with fewer than 16 channels.
4. Reject outputs with fewer than 2 channels.
5. Apply current PEQ/routing state before stream start.
6. Reset runtime DSP state.
7. Start native backend if available, otherwise Python stream.
8. Persist `was_running` and `auto_start` flags.

Stop sequence:

1. Stop native backend or Python stream.
2. Resume keep-awake silent output if enabled.
3. Persist stopped state.

### 3.3 Presets

Preset schema version: `3`

Each preset stores:

- Preset id and display name.
- Input device identity.
- Output device identity.
- Preamp value.
- Channel layout view.
- 7.1 surround fill state.
- 9.1.6 upmix state.
- L/R swap state.
- User/global PEQ enabled state and text.
- L-R Correction enabled state and text.
- Channel trim left/right dB.
- Output matching keywords.

Presets are user-created; the app starts with no built-in presets. Manual preset selection suppresses automatic switching until Windows default output identity changes.

### 3.4 Smart Output Switching

Smart preset switching polls device state every 500 ms. Native WASAPI endpoint default state is preferred over PortAudio's cached host API default when available, so Windows default-output flips are detected without waiting for stale PortAudio state to refresh. The observed default output is tracked by an identity tuple that includes native endpoint id when present, device name, host API, channel count, sample rate, and whether the endpoint is a VB-CABLE playback endpoint. This prevents reused or stale PortAudio numeric ids from suppressing a real Windows output change. Every third poll may still force a PortAudio inventory refresh if no probe is running and either the renderer is stopped or the native backend is active. The route bar also exposes a refresh icon, which forces immediate re-enumeration through the same preservation logic without requiring an app restart.

Default-output routing rule:

- Windows default output is `CABLE Input` or another VB-CABLE playback endpoint: the renderer may start or recover the selected render route.
- Windows default output is a normal speaker/DAC endpoint: the renderer enters direct-output handoff. If VB-CABLE becomes silent, the renderer pauses capture/playback, disables keep-awake for that route, fully releases the stream, and preserves resume intent. If VB-CABLE keeps receiving active audio, the renderer retargets the bridge to the new physical endpoint after `DIRECT_OUTPUT_HANDOFF_BRIDGE_RETARGET_SECONDS`.
- Automatic recovery/watchdog paths must satisfy both user intent (`_force_auto_start` or a currently running stream) and the current Windows default-output rule before calling `start_audio()`.

Preset matching score:

- Exact active output id match: +1000.
- Same name and host API: +250.
- Case-insensitive same name: +150.
- Same host API: +10.
- Non-generic preset keyword found in active output name: +5 per keyword.

The highest scoring available preset is selected.

### 3.4.1 Output-Switching Architecture Decision

Final decision: keep the renderer in control of the VB-CABLE-to-physical-output bridge and treat Windows default-output changes as asynchronous stream-routing events. The UI shell does not automate Apple Music, does not pause/play the media app, and does not rely on a track change. Instead, it applies the following state machine:

1. Detect the new Windows default-output identity using native endpoint metadata when available.
2. If the new default is direct speaker/DAC output while the renderer is active, enter direct-output handoff instead of immediately stopping the stream.
3. Watch the raw VB-CABLE input level from renderer snapshots.
4. If the cable stays active for at least `DIRECT_OUTPUT_HANDOFF_BRIDGE_RETARGET_SECONDS` (`120 ms`), select the new direct endpoint in the renderer output combo and restart only the renderer stream while preserving direct-output handoff state. This handles Apple Music Lossless, where Apple can keep feeding the old VB-CABLE stream until the current track is recreated.
5. If the cable goes silent for `DIRECT_OUTPUT_HANDOFF_SILENCE_SECONDS` (`450 ms`), pause/release the renderer path. This preserves the smooth Dolby Atmos/direct-output behavior where Apple Music or Windows routing moves the active audio away from VB-CABLE correctly.
6. If Windows default returns to VB-CABLE, schedule a short settled resume (`DIRECT_OUTPUT_RESUME_SETTLE_MS`, `120 ms`) so route restarts do not race endpoint changes.

Alternatives considered and rejected:

- Force stop/restart on every direct-output switch: rejected because it breaks the smooth Dolby Atmos path and adds avoidable glitches.
- Automate Apple Music pause/play or track changes: rejected because it is brittle, user-visible, and outside the renderer's ownership boundary.
- Wait for Apple Music to change tracks: rejected because it leaves Lossless playback on the previous physical endpoint until the user changes tracks.
- Always rebuild immediately on any default-output observation: rejected because device notifications are asynchronous and can arrive in different orders; immediate rebuilds increase race risk during rapid switching.
- Rewrite native audio routing or DSP behavior: rejected because the verified bug is a UI/state stream-routing issue, not a matrix/DSP/backend audio-processing defect.

Why the final implementation is reliable:

- It follows Windows Core Audio stream-routing guidance: default-device and session notifications are asynchronous, clients must be prepared to reopen/rebind streams quickly, and state transfer must be owned by the application.
- It uses measured signal state from the renderer (`raw_channel_levels`) rather than guessing the media app's mode. Active cable input means keep bridging and retarget; sustained silence means release.
- It reuses existing route selection, device identity, liveness, and recovery helpers instead of creating a parallel device path.
- It is generation-guarded and bounded. Stale liveness checks are ignored, liveness rebuilds are limited, and stale miniaudio callback-status text is consumed once.
- It changes only the renderer bridge target during Lossless handoff. Matrix coefficients, DSP math, PEQ, limiter, channel mapping, and backend processing are untouched.

Reference material used for this decision:

- Windows Core Audio Stream Routing: <https://learn.microsoft.com/en-us/windows/win32/coreaudio/stream-routing>
- Stream Routing Implementation Considerations: <https://learn.microsoft.com/en-us/windows/win32/coreaudio/stream-routing-implementation-considerations>
- Qt QWidget painting/update behavior: <https://doc.qt.io/qt-6/qwidget.html>
- Qt threading basics for GUI-vs-worker ownership: <https://doc.qt.io/qt-6.8/thread-basics.html>

### 3.5 Channel Layout Views

Two monitor layouts exist:

- `windows_7_1` (`7.1 Monitor`): `FL FR FC LFE BL BR SL SR`
- `sharur_9_1_6`: `FL FR FC LFE BL BR BLC BRC SL SR TFL TFR TSL TSR TBL TBR`

The layout selector changes meter/visualizer interpretation and the matrix input shape used by the DSP path. The default is `windows_7_1`.

### 3.6 7.1 Surround Fill

Surround fill is an optional Windows 7.1 repair helper. It detects active back channels with silent side channels and splits the back signal between back and side positions:

```text
if BL active and SL silent:
    SL = 0.5 * BL
    BL = 0.5 * BL

if BR active and SR silent:
    SR = 0.5 * BR
    BR = 0.5 * BR
```

Activity threshold: `1e-4`

### 3.7 9.1.6 Monitor Upmix

The 9.1.6 monitor path can synthesize missing BLC/BRC and height channels from an 8-channel Windows 7.1 bed. It does not run when the input layout is already a Sharur 9.1.6 input.

Generated-channel gain: `0.5011872336272722` (approximately -6 dB)

Generation uses:

- Side/rear difference signals.
- Decorrelating first-order all-pass stages.
- High-pass "air" extraction around 3.5 kHz.
- High-pass/low-pass shaping for generated channels.
- Small shelf boosts on selected height bands.

### 3.8 Channel Sanity Guard

The channel sanity mechanism exists in the DSP implementation but is forced off in the current UI flow. When enabled in code, it detects likely duplicated front-channel content in surround channels:

- Front peak threshold: `1e-4`
- Correlation threshold: `0.995`
- Duplicate count threshold: `3`
- RMS ratio range: `0.35` to `1.65`

If enough channels match front L/R too closely, duplicated non-front channels are zeroed.

### 3.9 L/R Swap

L/R swap is applied after global PEQ and before L-R Correction. Correction mapping follows the active physical output mapping.

When swap is enabled:

- Stereo left and right samples are swapped.
- L-R Correction CH:0/CH:1 filter sets are mapped to the opposite physical side before runtime configuration is sent to the processor.

### 3.10 Channel Trim

Channel trim is a final output-level adjustment for left/right imbalance. It is clamped to attenuation only:

```text
TRIM_MIN_DB = -24.0
TRIM_MAX_DB = 0.0
```

Helper text shown in the UI:

```text
Quick fine-tuning for output level L/R imbalance. If L-R Correction is enabled, do not use the channel trim setting.
```

Trim is applied after global PEQ, L/R swap, and L-R Correction, and before the limiter.

### 3.11 PEQ And L-R Correction

The app has two PEQ stages:

- User/global PEQ: applied to both stereo channels before L/R swap.
- L-R Correction: applied per physical stereo side after L/R swap.

Supported text syntax is Equalizer APO-like:

- `Preamp: -3 dB`
- `Filter 1: ON PK Fc 1000 Hz Gain -2 dB Q 1.2`
- `Filter: ON LS Fc 100 Hz Gain 3 dB Q 0.707`
- `Filter: ON HS Fc 8000 Hz Gain -1 dB Q 0.707`
- `Filter: ON LP Fc 18000 Hz Q 0.707`
- `Filter: ON HP Fc 20 Hz Q 0.707`
- `Channel: L`, `Channel: R`, `Channel: 1`, `Channel: 2`
- `CH:0` and `CH:1` Qudelix-style prefixes.

Unsupported commands are ignored with compact warnings.

PEQ limits:

- Max filters per stage: `32`
- Max absolute gain: `24 dB`
- Min frequency: `5 Hz`
- Max frequency: `0.98 * Nyquist`
- Q range: `0.1` to `20.0`
- Shelf default Q: `0.7071067811865476`
- Runtime PEQ crossfade: `128 samples`
- Denormal guard: `1e-30`

### 3.12 Raw Monitor And Route Probe

Raw Monitor displays the active monitor layout using the same channel-index mapping as Channel Field. In `windows_7_1` it shows `FL FR FC LFE BL BR SL SR` mapped to indices `0..7`; in `sharur_9_1_6` it shows all 16 labels including `TFL/TFR/TSL/TSR/TBL/TBR` mapped to indices `10..15`. It uses the current DSP monitor peaks/RMS so generated/upmixed channels light consistently with Channel Field. It is created as an independent top-level, non-modal window with its own title, minimize, and close controls, so minimizing the main renderer does not minimize the monitor. The main window still keeps a reference and closes the monitor during application shutdown.

Route Probe can:

- Enumerate devices and host APIs.
- Check 16-channel format support at 48 kHz.
- Capture channel activity for a timed interval.
- Classify the result as:
  - `channels_above_8_detected`
  - `eight_or_fewer_channels`
  - `likely_channel_fill`
  - `no_signal`
  - `capture_failed`
  - `no_16ch_capture_device`

## 4. Signal Flow And Processing Pipeline

The real-time processing pipeline is:

```text
Input buffer: frames x N channels
    |
    v
Prepare 16-channel buffer
    |
    v
Raw peak/RMS measurement
    |
    v
Optional channel sanity and 7.1 surround fill
    |
    v
Optional 9.1.6 bus construction/generation
    |
    v
Rendered channel peak/RMS measurement
    |
    v
Sharur processing:
    - LFE low-pass
    - Dry channel delay
    |
    v
Stereo matrix sum
    |
    v
Preamp gain
    |
    v
User/global PEQ
    |
    v
L/R swap
    |
    v
L-R Correction
    |
    v
Channel trim
    |
    v
Optional Sound Enhancer:
    - fixed post-mix makeup gain
    - protected -1 dBFS ceiling
    |
    v
Soft limiter
    |
    v
Windows/default endpoint master volume and mute
    |
    v
Stereo output buffer
```

## 5. Mathematical Specification

### 5.1 dB Conversion

Gain from decibels:

```text
gain = 10^(dB / 20)
```

Decibels from linear amplitude:

```text
dB = 20 * log10(max(value, 1e-6))
```

### 5.2 Fixed Stereo Matrix

For each frame, the stereo output before gain/EQ is:

```text
L = sum(input_channel_i * M[i][0])
R = sum(input_channel_i * M[i][1])
```

Windows 7.1 matrix:

| Channel | Left coeff | Right coeff |
| --- | ---: | ---: |
| FL | 1.0 | 0.0 |
| FR | 0.0 | 1.0 |
| FC | 0.70710678 | 0.70710678 |
| LFE | 2.26464431 | 2.26464431 |
| BL | 1.0 | 0.0 |
| BR | 0.0 | 1.0 |
| SL | 1.0 | 0.0 |
| SR | 0.0 | 1.0 |

Sharur 9.1.6 matrix:

| Channel | Left coeff | Right coeff |
| --- | ---: | ---: |
| FL | 1.0 | 0.0 |
| FR | 0.0 | 1.0 |
| FC | 0.70710678 | 0.70710678 |
| LFE | 2.26464431 | 2.26464431 |
| BL | 1.0 | 0.0 |
| BR | 0.0 | 1.0 |
| BLC | 1.0 | 0.0 |
| BRC | 0.0 | 1.0 |
| SL | 1.0 | 0.0 |
| SR | 0.0 | 1.0 |
| TFL | 1.0 | 0.0 |
| TFR | 0.0 | 1.0 |
| TSL | 1.0 | 0.0 |
| TSR | 0.0 | 1.0 |
| TBL | 1.0 | 0.0 |
| TBR | 0.0 | 1.0 |

These coefficients are pinned by tests and must not be edited without explicit approval.

### 5.3 LFE Low-Pass Filter

The LFE channel is filtered through a fourth-order Butterworth low-pass implemented as two second-order sections.

Constants:

```text
fc = 125 Hz
fs = 48000 Hz
Q values = 0.541196100146197, 1.3065629648763766
```

For each section:

```text
k = tan(pi * fc / fs)
norm = 1 / (1 + k / Q + k^2)
b0 = k^2 * norm
b1 = 2 * b0
b2 = b0
a1 = 2 * (k^2 - 1) * norm
a2 = (1 - k / Q + k^2) * norm
```

The section uses transposed Direct Form II:

```text
y  = b0 * x + z1
z1 = b1 * x - a1 * y + z2
z2 = b2 * x - a2 * y
```

### 5.4 Dry Delay Alignment

All non-LFE channels are delayed by:

```text
DRY_DELAY_SAMPLES = 172
```

At 48 kHz:

```text
delay_seconds = 172 / 48000 = 0.0035833333 s
delay_ms = 3.5833333 ms
```

The delayed dry path is intended to align with the LFE low-pass timing behavior.

### 5.5 Preamp

Preamp is applied after matrix summing and before PEQ:

```text
stereo *= 10^(preamp_db / 20)
```

Default preamp:

```text
DEFAULT_PREAMP_DB = -14
```

### 5.6 PEQ Biquad Formulas

Definitions:

```text
w0 = 2 * pi * frequency_hz / sample_rate
sin_w0 = sin(w0)
cos_w0 = cos(w0)
A = 10^(gain_db / 40)
alpha = sin_w0 / (2 * Q)
```

Peaking EQ:

```text
b0 = 1 + alpha * A
b1 = -2 * cos_w0
b2 = 1 - alpha * A
a0 = 1 + alpha / A
a1 = -2 * cos_w0
a2 = 1 - alpha / A
```

Low shelf:

```text
beta = 2 * sqrt(A) * alpha
b0 = A * ((A + 1) - (A - 1) * cos_w0 + beta)
b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
b2 = A * ((A + 1) - (A - 1) * cos_w0 - beta)
a0 = (A + 1) + (A - 1) * cos_w0 + beta
a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
a2 = (A + 1) + (A - 1) * cos_w0 - beta
```

High shelf:

```text
beta = 2 * sqrt(A) * alpha
b0 = A * ((A + 1) + (A - 1) * cos_w0 + beta)
b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
b2 = A * ((A + 1) + (A - 1) * cos_w0 - beta)
a0 = (A + 1) - (A - 1) * cos_w0 + beta
a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
a2 = (A + 1) - (A - 1) * cos_w0 - beta
```

Low-pass:

```text
b0 = (1 - cos_w0) / 2
b1 = 1 - cos_w0
b2 = (1 - cos_w0) / 2
a0 = 1 + alpha
a1 = -2 * cos_w0
a2 = 1 - alpha
```

High-pass:

```text
b0 = (1 + cos_w0) / 2
b1 = -(1 + cos_w0)
b2 = (1 + cos_w0) / 2
a0 = 1 + alpha
a1 = -2 * cos_w0
a2 = 1 - alpha
```

All coefficients are normalized before runtime use:

```text
b0' = b0 / a0
b1' = b1 / a0
b2' = b2 / a0
a1' = a1 / a0
a2' = a2 / a0
```

### 5.7 Bandwidth-To-Q Conversion

When a filter specifies bandwidth in octaves:

```text
Q = 1 / (2 * sinh(ln(2) * bandwidth / 2))
```

### 5.8 PEQ Runtime Application

PEQ uses transposed Direct Form II:

```text
y  = b0 * x + z1
z1 = b1 * x - a1 * y + z2
z2 = b2 * x - a2 * y
```

Samples and state values below `1e-30` are set to zero to avoid denormal performance penalties.

When PEQ settings change, the processor keeps the previous PEQ state/config and crossfades to the new config:

```text
t = (crossfade_frame + 1) / 128
output = old_output * (1 - t) + new_output * t
```

### 5.9 Channel Trim

Trim input is normalized as:

```text
trim_db = clamp(value, -24.0, 0.0)
trim_gain = 10^(trim_db / 20)
```

Then:

```text
left *= trim_left_gain
right *= trim_right_gain
```

### 5.10 Sound Enhancer

Sound Enhancer is an optional post-mix loudness stage intended for quiet laptop speakers. It runs after matrix, preamp, PEQ, L/R swap, speaker correction, and channel trim, and before the final limiter. It does not change routing, matrix coefficients, PEQ math, trim semantics, LFE timing, or channel mapping.

The stage uses fixed makeup gain plus a protected ceiling. Peak detection for this stage uses a lightweight 4x Catmull-Rom inter-sample estimate, so the safety envelope reacts to obvious between-sample overshoots instead of only raw sample peaks:

```text
makeup_gain = 10^(7.5 / 20)
ceiling = 10^(-1.0 / 20)
estimated_peak = max(sample_peak, 4x inter-sample estimate)
boosted_peak = estimated_peak * makeup_gain
```

If `boosted_peak` exceeds the ceiling, a fast safety gain is applied before the final limiter:

```text
target_safety_gain = ceiling / boosted_peak
alpha = 0.85 if target_safety_gain < previous_safety_gain else 0.08
smoothed_safety_gain = (1 - alpha) * previous_safety_gain + alpha * target_safety_gain
applied_safety_gain = min(smoothed_safety_gain, target_safety_gain)
stereo *= makeup_gain * applied_safety_gain
```

If a block still exceeds the ceiling by the inter-sample estimate due to numerical edge cases, the block is scaled down immediately to the same ceiling. This is a safety guard, not a tone-shaping clipper.

### 5.11 Limiter

The limiter protects against output samples exceeding absolute amplitude `1.0`.

For each block:

```text
peak = max(abs(left), abs(right))

if peak > 1.0:
    target_gain = 1.0 / peak
    clipping = true
else:
    target_gain = 1.0
    clipping = false

alpha = 0.4 if target_gain < previous_limiter_gain else 0.05
smoothed_gain = (1 - alpha) * previous_limiter_gain + alpha * target_gain

if clipping:
    applied_limiter_gain = min(smoothed_gain, target_gain)
else:
    applied_limiter_gain = smoothed_gain
```

Final output:

```text
stereo *= applied_limiter_gain
stereo *= master_volume * user_volume
```

If the Windows endpoint is muted:

```text
stereo *= 0
```

In the current UI flow, user volume is held at `1.0`; master volume follows the Windows endpoint volume.

## 6. Calibration And Correction Methods

### 6.1 Preamp Headroom

Default preamp of `-14 dB` provides headroom before PEQ, trim, and limiter. The preamp is stored per preset and globally in settings.

### 6.2 L-R Correction

L-R Correction is intended for per-output left/right balance calibration. The stage can load text files using UTF-8 with BOM, UTF-16, CP1252, or replacement fallback. Corrections are parsed into left/right cascades.

When L/R swap is off:

```text
CH:0 -> left output
CH:1 -> right output
```

When L/R swap is on:

```text
CH:1 -> left output
CH:0 -> right output
```

### 6.3 Channel Trim Guidance

Channel trim is a lightweight attenuation-only balance control. It should not be combined with L-R Correction for the same calibration problem because both affect final L/R balance.

## 7. Dependencies And Frameworks

### 7.1 Python Runtime

Required Python version:

```text
>= 3.10
```

Primary dependencies:

| Dependency | Purpose |
| --- | --- |
| PyQt5 | Desktop UI, custom widgets, timers, dialogs |
| numpy | Python DSP, vectorized metrics, PEQ math |
| sounddevice | PortAudio device enumeration and Python fallback stream |
| pywin32 / win32com | Startup shortcut creation and packaged hidden imports |
| pycaw / comtypes | Optional Windows volume endpoint access |
| ctypes | Native DLL bridge and CoreAudio fallback volume access |
| PyInstaller | Windows packaging |
| Pillow | Icon generation script dependency |
| ziglang | Native DLL build script toolchain |

### 7.2 Native Runtime

Native code dependencies:

| Dependency | Purpose |
| --- | --- |
| miniaudio | WASAPI device enumeration, duplex stream, callbacks |
| Windows WASAPI | Capture/playback audio backend |
| C++ standard library | vectors, arrays, atomics, mutexes, chrono |

## 8. File Structure And Module Responsibilities

| Path | Responsibility |
| --- | --- |
| `renderer_app.py` | Thin executable entrypoint calling `downmix_renderer.app.main()` |
| `renderer_app.spec` | PyInstaller production packaging config; outputs a local `Downmixrenderer.exe` package folder |
| `downmix_renderer/app.py` | PyQt UI, custom controls, preset tab, PEQ controls, route probe UI, timers, persistence orchestration |
| `downmix_renderer/audio_engine.py` | Stream lifecycle, backend selection, route validation, snapshots, keep-awake output |
| `downmix_renderer/dsp.py` | Python reference/fallback DSP implementation |
| `downmix_renderer/native_audio.py` | ctypes bridge to native DLL and native snapshot conversion |
| `cpp_backend/downmix_native.cpp` | Production C++ WASAPI/miniaudio backend and native DSP mirror |
| `cpp_backend/miniaudio.h` | Vendored miniaudio single-header backend |
| `downmix_renderer/peq.py` | PEQ parser, validation, biquad coefficient generation, runtime config |
| `downmix_renderer/matrix.py` | Fixed Sharur and Windows 7.1 matrix coefficients |
| `downmix_renderer/layouts.py` | Speaker enums and 7.1/9.1.6 layout definitions |
| `downmix_renderer/routing.py` | 9.1.6-to-7.1 folding helper |
| `downmix_renderer/devices.py` | PortAudio device inventory, WASAPI filtering, saved-device matching |
| `downmix_renderer/presets.py` | Preset schema, load/update/match helpers |
| `downmix_renderer/settings.py` | Safe settings path resolution and atomic JSON persistence |
| `downmix_renderer/startup.py` | Windows Startup folder shortcut management |
| `downmix_renderer/volume.py` | Windows endpoint volume following with pycaw/ctypes/null fallback |
| `downmix_renderer/route_probe.py` | CLI and UI-callable route inventory/capture diagnostics |
| `scripts/build_native_backend.py` | Build native DLL using ziglang |
| `scripts/make_icon.py` | Build icon assets |
| `tests/` | Unit tests for UI, DSP, native parity, PEQ, settings, presets, route probing, startup |
| `assets/` | Production logo/icon assets used by UI and package |
| `production testing/` | Current local production-test package folder, ignored by git |

## 9. UI/UX Logic And Interaction Flow

### 9.1 Main Renderer Tab

The main tab is arranged into:

- Route card: fixed `CABLE Input` presentation, output selector, compact sample-rate selector, and refresh icon action.
- Transport card: render start/stop toggle and status.
- Volume/preamp card: preamp control and display.
- Keep-awake card: silent output stream option when renderer is stopped.
- Channel card: live channel tiles and room visualizer.
- Meter card: stereo sum meter.
- Diagnostics card: route, stream, limiter, Sound Enhancer, active channels, output/volume, upmix/PEQ summaries.

The UI refresh timer runs every 40 ms. It polls engine snapshots, applies stream self-heal checks, updates meters, channel tiles, diagnostics, and render toggle state.

### 9.2 Presets Tab

The presets tab contains:

- Saved profile list.
- Profile creation/update/deletion controls.
- Output routing and PEQ panel.
- L/R swap controls.
- Channel trim controls.
- L-R Correction channel mapping helper.
- Global PEQ editor.
- L-R Correction editor.

PEQ text edits are debounced with a 260 ms timer before rebuilding runtime config.

### 9.3 Window And Visual Design

The app uses:

- Native Windows window controls with dark titlebar integration where available.
- Custom-rendered toggle, meter, tile, room visualizer, and backdrop widgets.
- The backdrop matches the `Finalised version 3` two-layer behavior: a live cursor-reactive root wavy-dot field across the Qt chrome plus the cinematic page overlay.
- Fusion Qt style with application stylesheet.
- Local logo and icon assets.

## 10. Error Handling And Fallback Mechanisms

### 10.1 Audio Startup Errors

Startup errors are caught in `RendererWindow.start_audio()`. The status is updated and `was_running` is persisted as false.

Native backend startup tries profile fallback candidates:

```text
ultra -> ultra, raw
raw -> raw
```

If all candidates fail, the native backend reports a detailed C++/miniaudio error string.

### 10.2 DSP Callback Errors

Python callback errors:

- Output buffer is zeroed.
- DSP error count increments.
- Status contains the exception.

Native callback errors:

- Output buffer is zeroed if processing fails.
- DSP error count increments.
- Callback continues without throwing into miniaudio.

### 10.3 Runtime Stream Recovery

The native backend publishes miniaudio device notifications for stop, reroute, interruption, and unlock events into the snapshot callback status. The UI shell handles recovery from the main thread. Fresh stop/reroute/interruption statuses bypass the idle-recovery cooldown because they are explicit device events. Stale callback status counts are ignored so old notification text cannot trigger repeated rebuilds during rapid switching. Before any automatic restart, recovery forces a fresh device/default-output check, confirms the user has not stopped rendering, and confirms the current Windows default-output rule allows the action.

If the default output is a direct speaker/DAC endpoint, recovery uses direct-output handoff instead of blindly restarting. Active Lossless input can retarget the renderer bridge to the direct endpoint; silent cable input pauses/releases the renderer path.

After every start or device-switch recovery, the UI schedules a short liveness check. If callback or frame counters do not advance within `AUDIO_LIVENESS_TIMEOUT_MS`, the app treats the start as silent/faulted, fully tears the stream down, re-enumerates devices, and rebuilds once through the same direction-neutral start path. Stale liveness checks are ignored through a start-generation guard.

Idle/silent-output recovery is rate-limited by `RECOVERY_COOLDOWN_SECONDS` and ignores intentional silence when the Windows endpoint volume is muted or effectively zero. Explicit device notifications are not delayed by this idle cooldown.

### 10.4 Settings Errors

Settings load returns `{}` on:

- Missing file.
- Permission errors.
- JSON decode errors.
- Type/value errors.

Settings save writes to `settings.json.tmp` and uses `os.replace()` for atomic replacement. Temporary files are removed on save failure when possible.

Settings paths are guarded against `System32` fallback mistakes.

### 10.5 Device Disappearance

If an active preset route disappears:

- The renderer stops if running.
- Status becomes a warning.
- `was_running` is persisted false.

Device lists are refreshed while preserving current selections when possible.

Manual route refresh and periodic polling both preserve selected input/output identities when possible. If a running route changes materially, the renderer restarts on the refreshed route.

### 10.6 Volume Follower Fallback

Volume follower selection:

1. pycaw endpoint follower.
2. ctypes CoreAudio endpoint follower.
3. Null follower with scalar `1.0`, muted `False`, available `False`.

### 10.7 Startup Shortcut Fallback

Startup autostart returns `(False, detail)` when APPDATA is unavailable or shortcut creation/removal fails. The UI re-syncs checkbox state from the actual Startup folder and treats stale shortcuts pointing at missing or relocated executables as disabled.

When enabling or disabling boot autostart, `downmix_renderer.startup` scans only the per-user Startup folder and only launcher-style files (`.lnk`, `.cmd`, `.bat`, `.ps1`). It removes related Downmix Renderer entries by explicit file name, shortcut target, target location inside the app root, or script body markers such as `Downmixrenderer.exe` / `renderer_app.py`. Unrelated Startup items are left untouched.

### 10.8 Bonjour / External Service Errors

The renderer does not reference Bonjour, mDNS, ZeroConf, dns-sd, AirPlay, or Apple network discovery APIs. If Bonjour-related errors appear during launch or media playback, they are expected to originate from the local Windows/media environment or another installed component rather than from Downmix Renderer startup or routing logic.

## 11. Performance And Optimization Strategy

### 11.1 Real-Time Audio Path

Performance choices:

- Native C++ backend is the production path.
- Audio callback avoids Python execution in normal packaged operation.
- Native WASAPI ULTRA mode uses a low-latency 128-frame period at 48 kHz with three periods, then scales frame count at 96 kHz and 192 kHz so GPU/DWM scheduling pressure does not shrink the callback deadline below the 48 kHz time budget.
- UI animation work is throttled while rendering where it does not alter the `Finalised version 3` backdrop behavior, and backdrop repaint regions skip hidden/covered pixels to reduce GPU/DWM contention without changing DSP math or stream routing.
- DSP buffers are preallocated and resized outside steady-state operation.
- Native configuration is shared through atomics and immutable PEQ config snapshots.
- PEQ updates are published atomically and crossfaded, avoiding abrupt discontinuities.
- Meters and snapshots use atomic values or non-blocking locks.
- Python fallback uses reusable numpy scratch arrays.
- Denormal guards avoid CPU stalls for near-zero biquad states.

### 11.2 Stream Profiles

Profiles:

| Profile | Block size | Latency request |
| --- | ---: | --- |
| `ultra` | 128 frames at 48 kHz, 256 at 96 kHz, 512 at 192 kHz | `low` |
| `raw` | 256 frames at 48 kHz, 512 at 96 kHz, 1024 at 192 kHz | `low` |

Native backend clamps requested block size between 64 and 4096 frames and reserves enough DSP capacity for eight blocks.

### 11.3 UI Responsiveness

The UI uses timers instead of blocking loops:

- 40 ms UI refresh.
- 500 ms device polling.
- 70 ms live animated backdrop update matching `Finalised version 3`, with root/page repaint regions clipped to visible areas.
- Room visualizer animation relaxes from 55 ms idle to 90 ms while rendering.
- 260 ms PEQ debounce.

Route probing runs in a `QThread` and stops/resumes renderer state around capture.

### 11.4 Current Responsiveness Measurements

Latest safe-harness measurements were taken with `DOWNMIX_RENDERER_AUDIO_BACKEND=python`, mocked device inventory, and isolated settings so real audio hardware and user state were not disturbed:

| Path | Median | p95 | Notes |
| --- | ---: | ---: | --- |
| Window construction | ~25 ms | ~28 ms | Dominated by normal Qt widget setup and initial device/settings mocks in the test harness |
| `update_ui()` steady-state loop | ~0.065 ms | ~0.11 ms | Below the 40 ms UI timer budget by a wide margin |
| Backdrop advance scheduling | ~0.0004 ms | ~0.0005 ms | Uses Qt `update()` so paint events are coalesced by Qt |
| Lossless bridge retarget handoff | ~0.044 ms | ~0.06 ms | Retargets only the renderer bridge and reuses normal start/liveness checks |

Optimization decision: no broad refactor is justified by these numbers. The most important performance rule is to keep blocking device enumeration, route probing, and startup shortcut work out of the steady UI path, while leaving the verified audio-routing state machine untouched. Future optimization proposals must include before/after measurements and regression coverage.

## 12. Testing And Validation

### 12.1 Test Suites

Current unit test coverage:

| Test file | Focus |
| --- | --- |
| `tests/test_dsp.py` | Matrix constants, DSP gain staging, limiter, LFE delay, surround fill, upmix, PEQ crossfade |
| `tests/test_native_dsp.py` | Native DLL trim behavior and native/Python DSP parity where available |
| `tests/test_peq.py` | PEQ parser, channel mapping, warnings, biquad generation |
| `tests/test_audio_engine.py` | Engine startup validation, profile fallback, keep-awake behavior, backend selection |
| `tests/test_app_ui.py` | PyQt widget construction, routing/preset UI, PEQ controls, trim controls, startup UI, diagnostics, refresh-device behavior, Raw Monitor independent-window behavior, idle recovery hooks, production backdrop cadence |
| `tests/test_presets.py` | Preset schema, matching, keyword behavior, trim/PEQ persistence |
| `tests/test_route_probe.py` | Route probe classification and channel-fill detection |
| `tests/test_settings.py` | Settings path safety and atomic persistence behavior |
| `tests/test_startup.py` | Startup shortcut creation/removal behavior, stale target validation, and related-entry cleanup without touching unrelated Startup items |

### 12.2 Full Validation Command

```powershell
python -m unittest discover -s tests
```

### 12.3 Production Build Command

```powershell
python scripts\make_icon.py
python scripts\build_native_backend.py
pyinstaller --noconfirm --distpath "." --workpath build renderer_app.spec
```

The default PyInstaller output folder is:

```text
Finalised Version
```

The current production-test build is generated with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -DistName "production testing"
```

The EXE name remains:

```text
Downmixrenderer.exe
```

Taskbar identity requirements:

- `renderer_app.spec` embeds `assets\downmix_renderer_logo.ico` into `Downmixrenderer.exe`.
- The icon must contain at least 16, 32, 48, and 256 px frames.
- Startup configures Qt high-DPI scaling defaults, then calls `SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)` before creating `QApplication`.
- The main window sends `WM_SETICON` for both `ICON_SMALL` and `ICON_BIG` from the local `.ico` asset, so fresh Windows profiles do not depend on a manual pin to associate the icon.

### 12.4 Manual End-To-End Validation Checklist

Recommended validation pass:

1. Launch `production testing\Downmixrenderer.exe`.
2. Confirm the app opens without framework/runtime errors.
3. Confirm the route bar shows `CABLE Input` for the VB-CABLE capture endpoint.
4. Confirm output selector shows available WASAPI stereo outputs.
5. Start renderer with a valid route.
6. Confirm status changes to running and meters update.
7. Toggle 7.1 Monitor and 9.1.6 Monitor layouts and confirm visualizer/channel tiles update.
8. Toggle 7.1 surround fill and verify diagnostics report armed/active state.
9. Toggle 9.1.6 upmix and verify diagnostics report armed/active state.
10. Load or paste User/global PEQ and confirm status/warning labels.
11. Load or paste L-R Correction and confirm left/right filter counts.
12. Toggle L/R swap and confirm correction mapping helper behavior.
13. Apply channel trim values inside `-24..0 dB` and confirm they persist.
14. Create, update, select, and delete a preset.
15. Confirm smart switching selects matching presets when Windows default output changes.
16. Switch Windows default output from VB-CABLE to normal speakers while rendering a source that stops feeding VB-CABLE; confirm audio routes directly within about 1 second and the renderer pauses/releases, with no Apple Music restart.
17. Switch Windows default output from normal speakers back to VB-CABLE; confirm the renderer resumes without app restart.
18. While Apple Music Dolby Atmos is actively playing, switch between direct outputs and confirm switching is seamless, with no app restart and no track change.
19. While Apple Music Lossless is actively playing, switch between direct outputs and confirm the current track follows the newly selected output without changing tracks.
20. With renderer stopped and Windows default output on normal speakers, leave the app open for 15 minutes and confirm no capture/render restart attempts.
21. Rapidly switch Windows default output 10+ times and confirm there are no crashes, stale handles, or audible artifacts.
22. Press the route refresh icon after connecting or waking an output device and confirm the current selection is preserved when possible.
23. Stop renderer and confirm keep-awake can hold the output endpoint open when enabled only while Windows default output is VB-CABLE.
24. Open Raw Monitor in both `7.1 Monitor` and `9.1.6 Monitor`; confirm every label lights against the same Channel Field source, including `SL/SR` and height channels.
25. Toggle Auto-start on Boot and confirm the Startup shortcut targets the current `Downmixrenderer.exe`.
26. Launch on a clean Windows profile and confirm the taskbar icon is correct immediately before pinning.
27. Leave playback idle, resume playback, and confirm audio returns without pressing Stop/Render when default output is VB-CABLE.
28. Run Route Probe while renderer is stopped or allow UI to stop/resume it.
29. Relaunch app and confirm settings/presets restore.

## 13. Known Limitations

- The native backend is Windows-only.
- The app supports auto, 48 kHz, 96 kHz, and 192 kHz route modes; full manual validation depends on endpoint support.
- The production route expects a 16-channel capture device; lower channel counts are rejected at engine start.
- The native backend prefers CoreAudio endpoint identity when available and falls back to name matching; duplicate device names without endpoint identity can still be ambiguous.
- PEQ parser supports a practical Equalizer APO subset, not every command.
- Channel sanity is present in DSP code but forced off by the current UI flow.
- User volume is currently held at `1.0`; Windows endpoint volume is the live loudness follower.
- Full audio validation requires actual Windows WASAPI devices and cannot be fully proven by unit tests alone.
- The final package is a local build artifact and is intentionally ignored by git.

## 14. Future Scalability Considerations

Potential future work:

- Add true exclusive-mode WASAPI option if required by the route.
- Make sample rate configurable while preserving 48 kHz defaults and test vectors.
- Add stronger native/Python parity tests for every PEQ filter type.
- Add automated UI screenshot regression tests for the PyQt surface.
- Add signed release packaging and version bump automation.
- Add device disambiguation beyond display name for duplicate WASAPI endpoints.
- Add a structured diagnostic export containing settings, device inventory, active preset, route probe, and DSP snapshot.
- Add import/export for preset bundles.
- Add a migration layer if future preset schema versions are introduced.
- Add optional per-channel calibration profiles for advanced speaker correction.

## 15. Production Readiness Criteria

The application is considered production-ready when:

- Unit tests pass.
- Native DLL builds successfully.
- PyInstaller creates `production testing\Downmixrenderer.exe` for this release.
- The EXE launches and stays running from `production testing\Downmixrenderer.exe`.
- The UI restores settings without crashing.
- Audio stream starts on a valid 16-channel WASAPI input and stereo WASAPI output.
- DSP snapshot values update under signal.
- Presets persist and reload.
- PEQ parser warnings are visible rather than fatal.
- Route-probe failure does not leave the renderer in a broken state.
- No temporary build/debug folders remain in the source tree except the intentionally local production package.
