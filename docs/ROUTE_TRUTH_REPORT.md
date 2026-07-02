# Windows 9.1.6 Route Truth Report

Generated from `route_probe_inventory.json` in this safe copy.

## Hard Findings From This PC

- `CABLE Output (VB-Audio Virtual Cable)` exposes **16 input channels through Windows WASAPI** at 48 kHz. This means the renderer can capture a 16-channel VB-CABLE stream.
- `CABLE Input (VB-Audio Virtual Cable)` exposes only **8 output channels through Windows WASAPI**, and a 16-channel WASAPI render format is rejected with `Invalid number of channels`.
- 16-channel output is accepted through **MME**, **DirectSound**, and **WDM-KS** VB-Audio endpoints, but those are not necessarily the endpoint path Apple Music/Dolby Access will use.
- The current inventory run did not capture Apple Music playback. The Apple Music truth test still requires running the probe while an Atmos track is playing.

## VB-Audio Format Matrix

| ID | Host API | Mode | Device | 16ch @ 48 kHz |
|---:|---|---|---|---|
| 1 | MME | input | CABLE Output (VB-Audio Virtual) | OK |
| 5 | MME | output | CABLE Input (VB-Audio Virtual) | OK |
| 7 | MME | output | CABLE In 16ch (VB-Audio Virtual) | OK |
| 10 | Windows DirectSound | input | CABLE Output (VB-Audio Virtual Cable) | OK |
| 14 | Windows DirectSound | output | CABLE Input (VB-Audio Virtual Cable) | OK |
| 16 | Windows DirectSound | output | CABLE In 16ch (VB-Audio Virtual Cable) | OK |
| 19 | Windows WASAPI | output | CABLE Input (VB-Audio Virtual Cable) | Invalid number of channels |
| 20 | Windows WASAPI | output | CABLE In 16ch (VB-Audio Virtual Cable) | Invalid number of channels |
| 24 | Windows WASAPI | input | CABLE Output (VB-Audio Virtual Cable) | OK |
| 34 | Windows WDM-KS | input | CABLE Output (VB-Audio Point) | OK |
| 35 | Windows WDM-KS | output | Output (VB-Audio Point) | OK |
| 36 | Windows WDM-KS | input | Input (VB-Audio Point) | OK |

## Apple Music Atmos Test Command

Start an Apple Music Dolby Atmos track, keep the default output routed to VB-CABLE, then run:

```powershell
python -m downmix_renderer.route_probe --duration 20 --output route_probe_apple_music.json
```

Interpretation:

- `channels_above_8_detected`: the installed route can feed more than 7.1 into the renderer.
- `eight_or_fewer_channels`: the Windows/VB-CABLE route is the blocker, not the DSP.
- `no_signal`: Apple Music/Dolby Access/output routing is not feeding the selected VB-CABLE capture endpoint.

## App Patch Status

- The renderer is refactored into `downmix_renderer/` modules.
- The Sharur matrix is unchanged and pinned by unit tests.
- Windows volume keys are followed through CoreAudio endpoint volume and applied as a separate post-render master gain.
- Device settings now persist by stable identity instead of numeric PortAudio IDs only.
- The UI now includes route, channel-count, volume, limiter, and active-channel diagnostics.
- Output-device switching is now verified by user playback testing for both Apple Music Dolby Atmos and Lossless tracks.
- The final switching behavior keeps ownership inside the renderer bridge: Dolby Atmos/direct reroutes can pause/release when VB-CABLE goes silent, while Lossless tracks that continue feeding VB-CABLE cause the renderer bridge to retarget to the newly selected physical output without Apple Music automation or a track change.
- Future route work should preserve `_sync_renderer_with_windows_default_output()`, `_maybe_pause_after_direct_output_handoff()`, `_retarget_direct_output_handoff_bridge()`, `_maybe_recover_audio_stream()`, and `_verify_audio_liveness()` as one coordinated state machine unless a new regression test proves a safer replacement.
