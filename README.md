# Downmix Renderer

Premium Windows WASAPI downmix renderer for routing a multichannel VB-CABLE capture endpoint to a stereo DAC. The current local production-test package is `production testing\Downmixrenderer.exe`.

## Highlights

- OLED-black native-window shell with a dark Windows title bar where available.
- WASAPI-only device lists to keep routing focused and clean.
- Shared WASAPI production stream with ULTRA Mode as the default low-latency profile.
- Sharur matrix preserved exactly from the original app and pinned by tests.
- Windows volume-key following through CoreAudio endpoint volume.
- Saved preamp, route, layout, PEQ, correction, and trim state per profile.
- User-created preset buttons with create, update, delete, and one-click switching.
- Runtime smart preset switching when the active Windows output device changes.
- Instant A/B default-output switching: VB-CABLE engages the renderer, direct speakers pause and release the render path.
- Manual route refresh icon for immediate WASAPI re-enumeration without restarting.
- Optional Sound Enhancer for laptop speakers, adding protected post-mix loudness without changing downmix routing.
- ULTRA Mode as the default aggressive shared-WASAPI path, with RAW Mode as the alternate low-latency route.
- Optional system boot autostart via a Startup-folder launcher that validates the current executable path.
- Self-healing stream recovery for device invalidation, interruption, and idle-resume silence.
- Post-switch liveness checks that rebuild the stream if callbacks do not resume after a default-device change.
- Native callback-thread MMCSS registration for cleaner playback under GPU/DPC scheduling pressure.
- Audio-safe UI animation mode that caches the dotted backdrop while rendering to reduce GPU/DWM contention on NVIDIA, Intel, AMD, and CPU-only systems.
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
& ".\production testing\Downmixrenderer.exe"
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

## Smart Switching

`Smart preset switching` matches the current Windows WASAPI default output to a saved preset. If you manually click another preset, the app respects that manual choice until Windows reports a different default output device.

When Windows default output is `CABLE Input`, the renderer may run or recover the selected route. When Windows default output changes to normal speakers or another direct endpoint, the app stops and releases the capture/render path, disables keep-awake for that route, and preserves resume intent so switching back to VB-CABLE resumes without restarting the app.

`Auto-start on Boot` writes a Windows Startup-folder shortcut. It does not require admin rights. On launch, the app ignores stale shortcuts that point to missing or relocated executables, then recreates the shortcut when you enable boot autostart again.

## Device Refresh And Recovery

Use the refresh icon in the route bar after connecting or waking an output device. The app re-enumerates WASAPI devices immediately, preserves the selected route when possible, and restarts the renderer only when the active route materially changes and Windows default output is still VB-CABLE.

The native backend reports WASAPI stop, reroute, and interruption notifications to the UI shell. If playback resumes after an idle period but the renderer sees input activity with sustained silent output, the current route is restarted automatically only when the user has not stopped rendering and the current Windows default output is VB-CABLE.

After each start or default-device recovery, the app verifies that callback/frame counters are advancing. If the stream reports running but no buffers flow within a short timeout, it fully releases and rebuilds the route once from a fresh device enumeration.

## Channel Layouts

Default `7.1 Monitor` view:

```text
FL FR FC LFE BL BR SL SR
```

`9.1.6 Monitor` keeps the original 16-channel Sharur labels for diagnostics. Matrix coefficients are unchanged in both views.

Raw Monitor follows the active channel layout and uses the same source-index mapping as Channel Field, so `SL`/`SR` and all height channels light against the same physical channels in both supported layouts.

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
`Finalised Version` by default, and can optionally sign the EXE/DLL files with `-Sign`.
For a local throwaway testing folder, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -DistName "testing"
```

For the current production-test package, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -DistName "production testing"
```

The packaged app loads `downmix_renderer\downmix_renderer_native.dll` for the
production live audio path. Set `DOWNMIX_RENDERER_AUDIO_BACKEND=python` only for
legacy development comparison tests.
