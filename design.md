# Downmix Renderer Design System

Last updated: 2026-06-14

## Design Intent

Downmix Renderer is a focused Windows audio utility. The UI should feel premium, technical, and fast, without becoming decorative or marketing-like. Controls must make repeated routing, monitoring, and preset work efficient. Audio behavior has priority over animation: visuals must never introduce avoidable lag, DWM pressure, or audio-thread coupling.

## Visual Language

- Primary surface: OLED black with restrained near-black panels.
- Accent language: white/gray contrast, soft green status for active audio, muted red only for stopped/error states.
- Backdrop: subtle animated wavy-dot field with cursor-reactive movement. The root window paints the live field across exposed Qt chrome, including the tabs/header area. The OS title bar is not custom-painted; it uses Windows dark-titlebar integration where available so native minimize/close behavior remains reliable.
- Cards: compact 8 px radius panels for repeated controls only. Do not nest cards inside cards.
- Typography: Segoe UI/Inter/Arial, compact dashboard sizing, no viewport-scaled type, no negative letter spacing.
- Assets: use the local logo/icon files in `assets/`; do not introduce external image dependencies for the shell.

## Layout Rules

- The first screen is the actual renderer, not a landing page.
- The route lane owns routing actions: fixed `CABLE Input`, output device, compact sample rate, and a refresh icon.
- Keep output/session controls close to renderer state, not hidden in debug tooling.
- Main renderer columns remain stable at launch size and high DPI; fixed-format controls use explicit heights and minimum widths to avoid layout jumps.
- The Presets tab keeps profile management and PEQ/correction controls together because those values are saved as one profile surface.
- Diagnostic text can wrap, but controls should not resize due to changing meter/status text.

## Motion And Performance

- Main UI refresh: 40 ms.
- Backdrop cadence: 70 ms.
- Room visualizer: faster while idle, relaxed while rendering to reduce GPU/DWM contention.
- PEQ parsing is debounced and never runs directly from audio callbacks.
- Animations are short, non-blocking Qt animations. Avoid heavy effects, blurs, particle systems, or continuous repaints outside the existing clipped regions.

## Component Rules

- Primary commands use clear text: `Render`, `Raw Monitor`, `New`, `Update`, `Delete`; route refresh uses an icon-only button with a tooltip.
- Icon-only controls are reserved for compact header actions such as renderer details and GitHub.
- Toggles are used for binary audio/session options.
- `Sound Enhancer` is a Gain / Monitor toggle because it is optional post-mix loudness processing, not a route or diagnostic action.
- Numeric audio values use sliders or constrained line edits with clamping.
- Route combo popups use the themed route view and show enough items to avoid cramped scroll affordances.
- The header status says `Shared WASAPI | Ready` or `Shared WASAPI | ULTRA Mode` because the production backend uses WASAPI shared mode.

## Window Behavior

- Main window: native Windows frame with dark-titlebar integration where supported. Keep native minimize, maximize, close, drag, focus, and taskbar behavior intact.
- Raw Monitor: independent top-level non-modal window with its own title, minimize, and close controls. It is not parent-owned by the main renderer, so minimizing the renderer does not minimize Raw Monitor.
- Application shutdown: the main renderer still closes Raw Monitor deliberately so the process exits cleanly.
- Renderer details/help dialogs may stay parented to the main window because they are transient support surfaces.

## Audio-Safety Constraints

- Do not change matrix coefficients, LFE delay behavior, limiter behavior, PEQ math, channel trim semantics, or native/Python DSP parity unless fixing a verified audio bug.
- Loudness enhancement must stay optional, post-mix, bounded by safety limiting, and mirrored between Python and native DSP.
- UI polish must not add dependencies or move work onto the audio callback path.
- Device refresh and recovery must reuse established route/device helpers rather than creating parallel enumeration flows.

## Documentation And Testing Expectations

- Docs must describe the current local testing artifact path: `testing\Downmixrenderer.exe`.
- Tests should cover UI construction, layout regressions, Raw Monitor independence, route refresh behavior, startup shortcut validation, DSP invariants, PEQ parsing, settings safety, and native/Python parity where the DLL is available.
- Any future behavior change should start with a regression test that fails for the old behavior and passes for the new behavior.
