# Pre-Release Hardening Log

Last updated: 2026-07-02

## Cleanup Decisions

- Moved long-form docs into `docs/` to separate documentation from source, resources, scripts, tests, and local build output.
- Kept `README.md` at repo root as the project entry point.
- Kept `downmix_renderer/`, `cpp_backend/`, `assets/`, `scripts/`, and `tests/` in place because they already match the actual hybrid PyQt/C++ project boundaries.
- Removed the stale tracked `production testing/` package subtree in the verified baseline checkpoint; the current public release artifact is rebuilt locally as `Downmix Renderer Software/` and remains ignored by git.
- Updated `scripts/build_native_backend.py` to remove generated native `.pdb` and `.lib` side artifacts after building `downmix_renderer_native.dll`.

## Confirmed Referenced

- `assets/downmix_renderer_logo.ico` and `.png` are used by `renderer_app.spec`, `downmix_renderer/app.py`, and startup shortcut logic.
- `scripts/build_release.ps1`, `scripts/build_native_backend.py`, `scripts/sign_release.ps1`, `scripts/make_icon.py`, and `scripts/probe_route.py` are referenced by README/docs, tests, or packaging flow.
- `cpp_backend/miniaudio.h` is required by `cpp_backend/downmix_native.cpp`.
- `docs/ROUTE_TRUTH_REPORT.md`, `docs/TECHNICAL_SPECIFICATION.md`, and `docs/design.md` remain release documentation, not build inputs.

## Intentionally Retained Local Artifacts

- `downmix_renderer/downmix_renderer_native.dll` is ignored by git but retained after native builds so native/Python parity tests and source smoke checks can run without skipping.
- `__pycache__/` folders are ignored disposable Python cache output and may be removed at any time; test and compile runs recreate them.
