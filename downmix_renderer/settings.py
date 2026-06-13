from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
APP_SETTINGS_DIR = "Downmix Renderer"
SETTINGS_FILE = "settings.json"


def default_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    candidates: list[Path] = []
    if appdata:
        candidates.append(Path(appdata).expanduser())
    candidates.append(Path.home() / "AppData" / "Roaming")
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile).expanduser() / "AppData" / "Roaming")
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        candidates.append(Path(localappdata).expanduser())
    for key in ("TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value).expanduser())

    for root in candidates:
        settings_path = root / APP_SETTINGS_DIR / SETTINGS_FILE
        if not _is_system32_path(settings_path):
            return settings_path

    return Path(r"C:\Users\Public\AppData\Roaming") / APP_SETTINGS_DIR / SETTINGS_FILE


def load_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = _safe_settings_path(path)
    try:
        if not settings_path.exists():
            return {}
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (PermissionError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        LOGGER.warning("Unable to load settings from %s: %s", settings_path, exc)
        return {}
    except Exception as exc:
        LOGGER.warning("Unexpected settings load failure from %s: %s", settings_path, exc)
        return {}


def save_settings(data: dict[str, Any], path: Path | None = None) -> None:
    settings_path = _safe_settings_path(path)
    temp_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp_path, settings_path)
    except (PermissionError, OSError, TypeError, ValueError) as exc:
        LOGGER.warning("Unable to save settings to %s: %s", settings_path, exc)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
    except Exception as exc:
        LOGGER.warning("Unexpected settings save failure to %s: %s", settings_path, exc)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_settings_path(path: Path | None) -> Path:
    if path is None:
        return default_settings_path()
    candidate = Path(path).expanduser()
    return default_settings_path() if _is_system32_path(candidate) else candidate


def _is_system32_path(path: Path) -> bool:
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = Path(path).expanduser().absolute()

    roots = [Path(r"C:\Windows\System32")]
    for key in ("SystemRoot", "WINDIR"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value) / "System32")

    path_text = _normalized_path_text(resolved)
    for root in roots:
        root_text = _normalized_path_text(root)
        if path_text == root_text or path_text.startswith(root_text + "\\"):
            return True
    return False


def _normalized_path_text(path: Path) -> str:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = path.expanduser().absolute()
    return str(resolved).rstrip("\\/").casefold()
