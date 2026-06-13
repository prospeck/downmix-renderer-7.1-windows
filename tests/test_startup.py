from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from downmix_renderer import startup


class StartupShortcutTests(unittest.TestCase):
    def test_startup_path_uses_per_user_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                path = startup.startup_script_path()

        self.assertIsNotNone(path)
        self.assertEqual(path.name, "Downmix Renderer.lnk")

    def test_enable_creates_shortcut_and_cleans_legacy_cmd_files(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                startup_dir.mkdir(parents=True)
                for legacy_name in startup.LEGACY_STARTUP_FILES:
                    (startup_dir / legacy_name).write_text("legacy", encoding="utf-8")

                created: list[Path] = []

                def fake_create(path: Path, app_root: Path) -> None:
                    created.append(path)
                    path.write_text("shortcut", encoding="utf-8")

                with patch("downmix_renderer.startup._create_shortcut", fake_create):
                    ok, detail = startup.set_system_autostart(True, Path.cwd())

                self.assertTrue(ok, detail)
                self.assertEqual(created, [startup_dir / "Downmix Renderer.lnk"])
                self.assertTrue(created[0].exists())
                for legacy_name in startup.LEGACY_STARTUP_FILES:
                    self.assertFalse((startup_dir / legacy_name).exists())
                self.assertEqual(detail, str(startup_dir / "Downmix Renderer.lnk"))

    def test_disable_removes_shortcut_and_legacy_cmd_files(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                startup_dir.mkdir(parents=True)
                paths = [startup_dir / "Downmix Renderer.lnk"]
                paths += [startup_dir / legacy_name for legacy_name in startup.LEGACY_STARTUP_FILES]
                for path in paths:
                    path.write_text("startup", encoding="utf-8")

                ok, detail = startup.set_system_autostart(False, Path.cwd())

                self.assertTrue(ok, detail)
                self.assertEqual(detail, "disabled")
                self.assertFalse(any(path.exists() for path in paths))

    def test_enabled_shortcut_must_point_to_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                shortcut = startup.startup_script_path()
                self.assertIsNotNone(shortcut)
                shortcut.parent.mkdir(parents=True)
                shortcut.write_text("shortcut", encoding="utf-8")
                missing_target = Path(appdata) / "old" / "Downmixrenderer.exe"

                with patch("downmix_renderer.startup._shortcut_target", return_value=missing_target):
                    self.assertFalse(startup.is_system_autostart_enabled(Path.cwd()))

    def test_frozen_shortcut_config_uses_current_executable_location(self) -> None:
        with tempfile.TemporaryDirectory() as app_dir:
            executable = Path(app_dir) / "Finalised version 3" / "Downmixrenderer.exe"
            executable.parent.mkdir(parents=True)
            executable.write_text("exe", encoding="utf-8")

            with (
                patch.object(startup.sys, "frozen", True, create=True),
                patch.object(startup.sys, "executable", str(executable)),
            ):
                target, arguments, working_directory, icon = startup._shortcut_config(Path("C:/old/build"))

            self.assertEqual(target, executable)
            self.assertEqual(arguments, "")
            self.assertEqual(working_directory, executable.parent)
            self.assertEqual(icon, executable)


if __name__ == "__main__":
    unittest.main()
