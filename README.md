# Downmix Renderer

Premium Windows WASAPI downmix renderer for routing a multichannel VB-CABLE capture endpoint to a stereo DAC. The public release package is `Downmix Renderer Software\Downmixrenderer.exe`.

## Highlights

- OLED-black native-window shell with a dark Windows title bar where available.
- WASAPI-only device lists to keep routing focused and clean.
- Shared WASAPI production stream with ULTRA Mode as the default low-latency profile, using native three-period buffering and MMCSS registration.
- Sharur matrix preserved exactly from the original app and pinned by tests.
- Windows volume-key following through CoreAudio endpoint volume.
- Saved preamp, route, layout, PEQ, correction, and trim state per profile.
- User-created preset buttons with create, update, delete, and one-click switching.
- Runtime smart preset switching when the active Windows output device changes.
- Compact View-page profile switching: saved profile names are available beside the 7.1/9.1.6 and Spatial/Channels controls, with `-` shown when no profiles exist.
- Instant A/B default-output switching: VB-CABLE engages the renderer, direct speakers either receive the live bridge or pause/release the render path depending on whether VB-CABLE is still actively fed.
- Lossless-safe output switching: when Apple Music keeps feeding VB-CABLE after a Windows output change, the renderer retargets its bridge to the new physical output without pausing Apple Music or waiting for a track change.
- Endpoint-aware Windows default-output tracking so reused/stale PortAudio ids do not block smart switching after a real device change.
- Manual route refresh icon for immediate WASAPI re-enumeration without restarting.
- Optional Sound Enhancer, adding protected post-mix loudness without changing downmix routing.
- ULTRA Mode as the default aggressive shared-WASAPI path, with RAW Mode as the alternate low-latency route.
- Optional system boot autostart via a Startup-folder launcher that validates the current executable path and removes old Downmix launchers.
- High-DPI Qt startup configuration for consistent Windows scaling and icon rendering across laptops and monitors.
- Self-healing stream recovery for device invalidation, interruption, and idle-resume silence.
- Post-switch liveness checks that rebuild the stream if callbacks do not resume after a default-device change.
- Native callback-thread MMCSS registration for cleaner playback under GPU/DPC scheduling pressure.
- Audio-safe UI animation mode that caches the dotted backdrop while rendering to reduce GPU/DWM contention on NVIDIA, Intel, AMD, and CPU-only systems.
- View visualizers share one signal language: Spatial nodes and Channels capsules both use dB-bucketed channel color. Capsules, Spatial nodes, and L/R sum meters use darker OLED-toned paint while preserving the existing meter response.
- Premium route/profile dropdowns release their popup event filters during shutdown so Qt exits cleanly without changing dropdown appearance or interaction.
- Sample-rate-aware native stream buffers that keep the callback time budget stable at 48, 96, and 192 kHz without changing DSP math.
- Independent Raw Monitor window with its own native minimize/close controls.
- Windows 7.1 channel view using stream order `FL FR FC LFE BL BR SL SR`.
- Live renderer backend in C++ via a native WASAPI DLL; Python remains the UI/control shell.

## Quick Start

Run from source:

```powershell
python renderer_app.py
```

Run the packaged app:

```powershell
& ".\Downmix Renderer Software\Downmixrenderer.exe"
```

Recommended route:

- Input: `CABLE Output (VB-Audio Virtual Cable)` using `Windows WASAPI`.
- Output: your DAC/speakers using `Windows WASAPI`.
- Start with `7.1 Monitor` channel view for Windows playback.

## Presets

The app starts with zero presets. Create only the presets you actually use:

1. Select the WASAPI input and output.
2. Set Preamp, channel layout, PEQ, correction, and routing options.
3. Type a preset name and click `New`; it appears as a button.
4. Click a preset button to switch instantly.
5. Click `Update` to overwrite the active preset with the current controls.
6. Click `Delete` to remove the active preset.

Each preset saves device identities, preamp, channel layout, Sound Enhancer, PEQ/correction state, trim, and output-device matching hints. Settings are written atomically to avoid partial saves.

The View page includes the same saved profiles as a compact name-only selector. It uses the existing profile apply path, so switching there has the same behavior as selecting a saved profile in Advanced.

## Smart Switching

`Smart preset switching` matches the current Windows WASAPI default output to a saved preset. If you manually click another preset, the app respects that manual choice until Windows reports a different default output identity. The identity includes the native endpoint when available, not just PortAudio's numeric device id, so reused or stale ids do not pin the app to an old route.

When Windows default output is `CABLE Input`, the renderer may run or recover the selected route. When Windows default output changes to normal speakers or another direct endpoint, the app enters a short direct-output handoff window. If Apple Music reroutes cleanly and VB-CABLE goes silent, the renderer pauses/releases capture and preserves resume intent. If Lossless playback continues feeding VB-CABLE, the renderer retargets its output bridge to the newly selected physical endpoint after a short grace period, so the current track follows the Windows output change without requiring an Apple Music pause/play or track change.

`Auto-start on Boot` writes a Windows Startup-folder shortcut. It does not require admin rights. When enabled or disabled, the app removes related old Downmix Renderer `.lnk`, `.cmd`, `.bat`, and `.ps1` Startup entries by explicit name, target, or script-content checks, while leaving unrelated Startup items alone.

## Device Refresh And Recovery

Use the refresh icon in the route bar after connecting or waking an output device. The app re-enumerates WASAPI devices immediately, preserves the selected route when possible, refreshes the endpoint-aware default-output identity, and restarts the renderer only when the active route materially changes and Windows default output is still VB-CABLE.

The native backend reports WASAPI stop, reroute, and interruption notifications to the UI shell. Fresh notifications are handled immediately; stale notification text is consumed once and ignored so rapid switching does not loop. If playback resumes after an idle period but the renderer sees input activity with sustained silent output, the current route is restarted automatically only when the user has not stopped rendering and the current Windows default output is VB-CABLE.

After each start or default-device recovery, the app verifies that callback/frame counters are advancing. If the stream reports running but no buffers flow within a short timeout, it fully releases and rebuilds the route once from a fresh device enumeration.

This switching behavior is intentionally conservative. It follows Windows Core Audio stream-routing guidance: route changes are asynchronous, old streams must be rebound quickly, and application state should be preserved. Future work must not replace this with media-player play/pause automation, unconditional restarts, or parallel device-enumeration paths.

This refinement preserves switching, PEQ, limiter, routing preferences, and output-device state-machine behavior. The only DSP change is the guarded 9.1.6 upmix field generation described below.

## Audio Stability

ULTRA Mode remains a shared-WASAPI path so Apple Music, VLC, browsers, Bluetooth endpoints, virtual cables, and normal Windows audio routing can coexist. The native stream requests a small 128-frame period at 48 kHz, keeps three periods in the buffer for multitasking headroom, registers the callback thread with MMCSS where Windows allows it, and scales the requested frame count at 96/192 kHz so the callback time budget stays stable.

The app treats the WASAPI period as a hint rather than a guarantee. If an endpoint rejects the Ultra hint, the engine falls back to RAW Mode without changing the saved preference or touching output-device switching.

## Channel Layouts

Default `7.1 Monitor` view:

```text
FL FR FC LFE BL BR SL SR
```

`9.1.6 Monitor` keeps the original 16-channel Sharur labels for diagnostics. Matrix coefficients are unchanged in both views.

Raw Monitor follows the active channel layout and uses the same source-index mapping as Channel Field, so `SL`/`SR` and all height channels light against the same physical channels in both supported layouts.

## Upmix Behavior

`7.1 Upmix` is a conservative fill helper, not a full creative cinematic upmix. It mainly helps 5.1-style beds by splitting active back-surround content into side/rear positions such as `SL/SR` or `Ls/Rs` when the matching side channels are missing.

`9.1.6 Upmix` builds a controlled immersive field from real surround energy or stereo-width information. It fills missing `SL/SR`, rear-center, and height channels with shaped/decorrelated ambience, avoids synthetic LFE, preserves the front/center image, and leaves true 9.1.6 input channels untouched.

## Route Probe

Enumerate devices and format support:

```powershell
python -m downmix_renderer.route_probe --duration 0 --output route_probe_inventory.json
```

Capture channel activity while Apple Music Atmos is playing:

```powershell
python -m downmix_renderer.route_probe --duration 20 --output route_probe_apple_music.json
```

Truth criteria:

- `channels_above_8_detected`: the installed route delivered more than 7.1.
- `eight_or_fewer_channels`: Windows/VB-CABLE capped the route before the renderer.
- `no_signal`: Apple Music/Dolby Access/output routing is not feeding VB-CABLE.

## Development

For the full implementation reference, see `TECHNICAL_SPECIFICATION.md`.
For the accepted visual language and interaction rules, see `design.md`.

Run tests:

```powershell
python -m unittest discover -s tests
```

Build the EXE:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
```

The release script rebuilds the native WASAPI DLL, packages the app into
`Downmix Renderer Software` by default, and can optionally sign the EXE/DLL files with `-Sign`.
For a local throwaway testing folder, pass a different `-DistName`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -DistName "testing"
```

For the public release package, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -DistName "Downmix Renderer Software"
```

The packaged app loads `downmix_renderer\downmix_renderer_native.dll` for the
production live audio path. Set `DOWNMIX_RENDERER_AUDIO_BACKEND=python` only for
legacy development comparison tests.
