# Downmix Renderer Architecture Summary

Last verified: 2026-07-02

This checkout is a PyQt5 desktop shell with a native C++ WASAPI/miniaudio backend, not a JUCE project. The release-sensitive boundary is the Sharur DSP implementation in `downmix_renderer/dsp.py` and `cpp_backend/downmix_native.cpp`; this summary documents the current system and does not propose DSP changes.

## Project Layout

- `downmix_renderer/`: application package, PyQt UI, device inventory, settings, presets, route probing, Python DSP fallback, native DLL binding.
- `cpp_backend/`: native miniaudio/WASAPI backend source and vendored `miniaudio.h`.
- `assets/`: icon/logo resources used by source and packaged builds.
- `scripts/`: native build, PyInstaller release build, signing, icon/probe helpers.
- `tests/`: unit, UI, device, preset, startup, release, and native/Python parity tests.
- `docs/`: technical specification, design notes, route decision record, and this architecture summary.

## Runtime Data Flow

```text
WASAPI capture device, normally 16-channel VB-CABLE
    -> AudioEngine route validation and backend selection
    -> native C++ backend in production, Python sounddevice fallback for tests/dev
    -> Sharur DSP path
    -> stereo WASAPI output device
    -> UI snapshots for meters, diagnostics, liveness, and Raw Monitor
```

`AudioEngine` validates 16-channel WASAPI input and stereo WASAPI output, resolves auto/fixed sample-rate mode, applies the current PEQ/layout/trim/settings state, starts the native backend when available, and falls back to the Python stream path only when configured or when the native backend is unavailable.

## DSP Boundary

The DSP path prepares a 16-channel field, measures raw/effective channel levels, optionally applies non-default channel repair/upmix features, runs the fixed Sharur matrix, then applies gain, PEQ, L/R swap, L-R Correction, trim, optional Sound Enhancer, limiter, and master volume. Matrix coefficients, LFE filter constants, limiter behavior, PEQ math, channel mapping, and native/Python parity are pinned by tests and are treated as frozen for this hardening pass.

## UI Architecture

`RendererWindow` owns the main PyQt shell. The View tab is the primary control surface: bed input visualizer, stereo sum meters, route selector, Start/Stop render toggle, profile selector, and 7.1/9.1.6 monitor/view-mode controls. The Advanced tab consolidates renderer settings, PEQ/correction editors, presets, automation, diagnostics launch, Raw Monitor launch, route probing, and startup options.

Secondary windows are independent top-level non-modal dialogs. Raw Monitor follows the same active channel layout/source-index mapping as the View visualizer. Diagnostics mirrors `RendererWindow.diag_labels` and is intentionally separate from Raw Monitor.

## Threading And Timers

- The Qt GUI runs on the main thread.
- The UI refresh timer runs every 40 ms and reads backend snapshots to update meters, diagnostics, status, and recovery state.
- Device polling runs from Qt timers and re-enumerates through worker helpers so route refresh does not block normal UI paint.
- Route Probe runs in a `QThread`, stopping/resuming the renderer around capture when needed.
- The native audio callback runs outside Python in the miniaudio/WASAPI thread and is registered with MMCSS when Windows allows it.
- Python fallback processing uses `sounddevice.Stream` callbacks and `DownmixProcessor`.

## Device Switching Model

The renderer owns the VB-CABLE-to-physical-output bridge. Windows default-output changes are handled as asynchronous route events; the app does not close/reopen its own window and does not automate source-app playback. If Windows default output moves to a direct speaker/DAC endpoint while VB-CABLE is still active, the renderer retargets the bridge after a short grace period. If VB-CABLE becomes silent, the renderer pauses/releases its stream and preserves resume intent. Returning default output to VB-CABLE schedules a settled resume.

The switching path is generation-guarded, liveness-checked, and uses native endpoint identity when available so stale PortAudio ids do not cause retry loops or missed device changes.

## Verification Surface

The current automated suite covers UI construction and layout, diagnostics, Raw Monitor mapping, route selector teardown, switching state-machine behavior, audio-engine startup/fallback, native/Python DSP parity, matrix constants, PEQ parsing, settings safety, startup shortcut handling, release packaging defaults, and Windows endpoint volume following. Manual hardware validation is still required for actual Bluetooth dropout/reconnect, real WASAPI device removal, and by-ear artifact checks.
