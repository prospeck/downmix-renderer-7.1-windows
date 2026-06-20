from __future__ import annotations

import os
import sys
from pathlib import Path

APP_STARTUP_FILE = "Downmix Renderer.lnk"
LEGACY_STARTUP_FILES = ("DownmixRenderer.cmd", "TaranDownmixRendererSuite.cmd")
PRODUCTION_DIST_NAME = "production testing"
PACKAGE_EXECUTABLE_NAME = "Downmixrenderer.exe"
RELATED_STARTUP_EXTENSIONS = {".lnk", ".cmd", ".bat", ".ps1"}
RELATED_STARTUP_MARKERS = (
    "downmix renderer",
    "downmixrenderer",
    "downmix_renderer",
    "renderer_app.py",
    "tarandownmixrenderersuite",
)


def _startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return _shell_startup_dir()


def _shell_startup_dir() -> Path | None:
    if os.name != "nt":
        return None
    try:
        from win32com.client import Dispatch

        startup = str(Dispatch("WScript.Shell").SpecialFolders("Startup") or "").strip()
    except Exception:
        return None
    return Path(startup) if startup else None


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
        return False, "Startup folder is unavailable"

    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            _remove_related_startup_entries(path.parent, app_root, keep_path=path)
            _create_shortcut(path, app_root)
            return True, str(path)

        for candidate in _related_startup_entries(path.parent, app_root):
            if candidate.exists():
                candidate.unlink()
        return True, "disabled"
    except Exception as exc:
        return False, str(exc)


def _remove_related_startup_entries(startup_dir: Path, app_root: Path, keep_path: Path | None = None) -> None:
    keep_resolved = _normalized_path_text(keep_path) if keep_path is not None else ""
    for candidate in _related_startup_entries(startup_dir, app_root):
        if keep_resolved and _normalized_path_text(candidate) == keep_resolved:
            continue
        if candidate.exists():
            candidate.unlink()


def _related_startup_entries(startup_dir: Path, app_root: Path | None = None) -> list[Path]:
    candidates: dict[str, Path] = {}
    for path in startup_script_paths():
        candidates[_normalized_path_text(path)] = path

    if startup_dir.exists():
        try:
            children = list(startup_dir.iterdir())
        except OSError:
            children = []
        for child in children:
            if child.suffix.lower() not in RELATED_STARTUP_EXTENSIONS:
                continue
            if _is_related_startup_entry(child, app_root):
                candidates[_normalized_path_text(child)] = child
    return list(candidates.values())


def _is_related_startup_entry(path: Path, app_root: Path | None = None) -> bool:
    if _text_mentions_downmix(path.stem):
        return True

    suffix = path.suffix.lower()
    if suffix == ".lnk":
        target = _shortcut_target(path)
        if target is None:
            return False
        if app_root is not None and _path_is_within(target, app_root):
            return True
        return _text_mentions_downmix(str(target))

    if suffix in {".cmd", ".bat", ".ps1"}:
        text = _read_startup_script_text(path)
        if not text:
            return False
        return _text_mentions_downmix(text)

    return False


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


def _text_mentions_downmix(value: str) -> bool:
    text = value.casefold().replace("_", " ").replace("-", " ")
    compact = text.replace(" ", "")
    for marker in RELATED_STARTUP_MARKERS:
        normalized_marker = marker.casefold().replace("_", " ").replace("-", " ")
        if normalized_marker in text or normalized_marker.replace(" ", "") in compact:
            return True
    return False


def _read_startup_script_text(path: Path) -> str:
    try:
        data = path.read_bytes()[:16384]
    except OSError:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text:
            return text
    return data.decode("utf-8", errors="ignore")


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _normalized_path_text(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        resolved = path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = path.expanduser().absolute()
    return str(resolved).rstrip("\\/").casefold()
