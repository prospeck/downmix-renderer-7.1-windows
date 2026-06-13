from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from downmix_renderer import settings


class SettingsPathTests(unittest.TestCase):
    def test_default_settings_path_uses_mocked_appdata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "Roaming"
            with patch.dict(settings.os.environ, {"APPDATA": str(appdata)}, clear=False):
                self.assertEqual(
                    settings.default_settings_path(),
                    appdata / "Downmix Renderer" / "settings.json",
                )

    def test_default_settings_path_falls_back_to_mocked_home_when_appdata_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "User"
            with patch.dict(settings.os.environ, {}, clear=False):
                settings.os.environ.pop("APPDATA", None)
                with patch("downmix_renderer.settings.Path.home", return_value=home):
                    self.assertEqual(
                        settings.default_settings_path(),
                        home / "AppData" / "Roaming" / "Downmix Renderer" / "settings.json",
                    )

    def test_default_settings_path_does_not_use_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "Roaming"
            with patch.dict(settings.os.environ, {"APPDATA": str(appdata)}, clear=False):
                with patch("downmix_renderer.settings.Path.cwd", side_effect=AssertionError("cwd used")):
                    self.assertEqual(
                        settings.default_settings_path(),
                        appdata / "Downmix Renderer" / "settings.json",
                    )

    def test_default_settings_path_never_uses_system32(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "User"
            with patch.dict(settings.os.environ, {"APPDATA": r"C:\Windows\System32"}, clear=False):
                with patch("downmix_renderer.settings.Path.home", return_value=home):
                    resolved = settings.default_settings_path()

            self.assertEqual(
                resolved,
                home / "AppData" / "Roaming" / "Downmix Renderer" / "settings.json",
            )
            self.assertNotIn(r"c:\windows\system32", str(resolved).casefold())

    def test_save_settings_temp_file_is_created_in_same_safe_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Downmix Renderer" / "settings.json"
            replace_calls: list[tuple[Path, Path]] = []
            real_replace = settings.os.replace

            def record_replace(src: str | Path, dst: str | Path) -> None:
                replace_calls.append((Path(src), Path(dst)))
                real_replace(src, dst)

            with patch("downmix_renderer.settings.os.replace", record_replace):
                settings.save_settings({"keep_output_awake": True}, target)

            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"keep_output_awake": True})
            self.assertEqual(replace_calls, [(target.with_suffix(target.suffix + ".tmp"), target)])
            self.assertEqual(replace_calls[0][0].parent, target.parent)

    def test_save_settings_handles_permission_and_os_errors_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"
            with patch("downmix_renderer.settings.Path.write_text", side_effect=PermissionError("denied")):
                settings.save_settings({"x": 1}, target)
            with patch("downmix_renderer.settings.os.replace", side_effect=OSError("replace failed")):
                settings.save_settings({"x": 1}, target)

    def test_load_settings_returns_empty_for_missing_corrupt_permission_and_non_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "settings.json"

            self.assertEqual(settings.load_settings(target), {})

            target.write_text("{", encoding="utf-8")
            self.assertEqual(settings.load_settings(target), {})

            target.write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(settings.load_settings(target), {})

            target.write_text('{"ok": true}', encoding="utf-8")
            with patch("downmix_renderer.settings.Path.read_text", side_effect=PermissionError("denied")):
                self.assertEqual(settings.load_settings(target), {})

    def test_explicit_system32_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "Roaming"
            with patch.dict(settings.os.environ, {"APPDATA": str(appdata)}, clear=False):
                safe = settings._safe_settings_path(Path(r"C:\Windows\System32\settings.json"))

            self.assertEqual(safe, appdata / "Downmix Renderer" / "settings.json")
            self.assertNotIn(r"c:\windows\system32", str(safe).casefold())


if __name__ == "__main__":
    unittest.main()
