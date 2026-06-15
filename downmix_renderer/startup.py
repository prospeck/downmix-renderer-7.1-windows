from __future__ import annotations

import os
import sys
from pathlib import Path

APP_STARTUP_FILE = "Downmix Renderer.lnk"
LEGACY_STARTUP_FILES = ("DownmixRenderer.cmd", "TaranDownmixRendererSuite.cmd")
PRODUCTION_DIST_NAME = "production testing"
PACKAGE_EXECUTABLE_NAME = "Downmixrenderer.exe"


def _startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_script_path() -> Path | None:
    startup_dir = _startup_dir()
    if startup_dir is None:
        return None
    return startup_dir / APP_STARTUP_FILE


def startup_script_paths() -> list[Path]:
    startup_dir = _startup_dir()
    if startup_dir is None:
        return []
    return [startup_dir / APP_STARTUP_FILE, *(startup_dir / name for name in LEGACY_STARTUP_FILES)]


def is_system_autostart_enabled(app_root: Path | None = None) -> bool:
    return any(_startup_entry_valid(path, app_root) for path in startup_script_paths())


def set_system_autostart(enabled: bool, app_root: Path) -> tuple[bool, str]:
    path = startup_script_path()
    if path is None:
        return False, "APPDATA is unavailable"

    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            _remove_legacy_startup_entries(path.parent)
            _create_shortcut(path, app_root)
            return True, str(path)

        for candidate in startup_script_paths():
            if candidate.exists():
                candidate.unlink()
        return True, "disabled"
    except Exception as exc:
        return False, str(exc)


def _remove_legacy_startup_entries(startup_dir: Path) -> None:
    for name in LEGACY_STARTUP_FILES:
        candidate = startup_dir / name
        if candidate.exists():
            candidate.unlink()


def _startup_entry_valid(path: Path, app_root: Path | None = None) -> bool:
    if not path.exists():
        return False
    target = _shortcut_target(path)
    if target is None:
        return False
    if not target.exists():
        return False
    expected_target = _preferred_packaged_target(app_root)
    if expected_target is not None:
        try:
            return target.resolve() == expected_target.resolve()
        except Exception:
            return False
    if getattr(sys, "frozen", False):
        try:
            return target.resolve() == Path(sys.executable).resolve()
        except Exception:
            return False
    if app_root is None or target.name.casefold() in {"python.exe", "pythonw.exe"}:
        return True
    try:
        target.resolve().relative_to(app_root.resolve())
    except ValueError:
        return False
    return True


def _preferred_packaged_target(app_root: Path | None) -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    if app_root is None:
        return None
    packaged = Path(app_root) / PRODUCTION_DIST_NAME / PACKAGE_EXECUTABLE_NAME
    return packaged if packaged.exists() else None


def _shortcut_target(path: Path) -> Path | None:
    if path.suffix.lower() != ".lnk" or os.name != "nt":
        return None
    try:
        from win32com.client import Dispatch

        shortcut = Dispatch("WScript.Shell").CreateShortcut(str(path))
        target = str(shortcut.TargetPath or "").strip()
        return Path(target) if target else None
    except Exception:
        return None


def _shortcut_config(app_root: Path) -> tuple[Path, str, Path, Path]:
    executable = _preferred_packaged_target(app_root)
    if executable is not None:
        return executable, "", executable.parent, executable

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else Path(sys.executable)
    script = app_root / "renderer_app.py"
    icon = app_root / "assets" / "downmix_renderer_logo.ico"
    icon_target = icon if icon.exists() else runner
    return runner, f'"{script}"', app_root, icon_target


def _create_shortcut(path: Path, app_root: Path) -> None:
    from win32com.client import Dispatch

    target, arguments, working_directory, icon = _shortcut_config(app_root)
    shortcut = Dispatch("WScript.Shell").CreateShortcut(str(path))
    shortcut.TargetPath = str(target)
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = str(working_directory)
    shortcut.IconLocation = f"{icon},0"
    shortcut.Description = "Downmix Renderer"
    shortcut.Save()
