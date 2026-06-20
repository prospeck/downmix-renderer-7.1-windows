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

    def test_startup_path_falls_back_to_windows_shell_startup_folder(self) -> None:
        with tempfile.TemporaryDirectory() as startup_dir:
            class FakeShell:
                def SpecialFolders(self, name: str) -> str:
                    self.requested = name
                    return startup_dir

            fake_shell = FakeShell()
            with (
                patch.dict(os.environ, {}, clear=False),
                patch("downmix_renderer.startup.os.name", "nt"),
                patch("win32com.client.Dispatch", return_value=fake_shell),
            ):
                os.environ.pop("APPDATA", None)
                path = startup.startup_script_path()

        self.assertIsNotNone(path)
        self.assertEqual(path, Path(startup_dir) / "Downmix Renderer.lnk")

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

    def test_enable_removes_stale_downmix_shortcuts_without_touching_unrelated_startup_items(self) -> None:
        with tempfile.TemporaryDirectory() as appdata, tempfile.TemporaryDirectory() as app_dir:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                app_root = Path(app_dir)
                startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                startup_dir.mkdir(parents=True)
                stale_shortcut = startup_dir / "Downmix Renderer Old.lnk"
                stale_script = startup_dir / "renderer backup.cmd"
                unrelated_shortcut = startup_dir / "Music Helper.lnk"
                stale_shortcut.write_text("old shortcut", encoding="utf-8")
                stale_script.write_text(r'"C:\old\renderer_app.py"', encoding="utf-8")
                unrelated_shortcut.write_text("music", encoding="utf-8")

                def fake_target(path: Path) -> Path | None:
                    if path == stale_shortcut:
                        return Path(r"C:\old\Downmixrenderer.exe")
                    if path == unrelated_shortcut:
                        return Path(r"C:\tools\music-helper.exe")
                    return None

                def fake_create(path: Path, app_root: Path) -> None:
                    path.write_text("current shortcut", encoding="utf-8")

                with (
                    patch("downmix_renderer.startup._shortcut_target", fake_target),
                    patch("downmix_renderer.startup._create_shortcut", fake_create),
                ):
                    ok, detail = startup.set_system_autostart(True, app_root)

                self.assertTrue(ok, detail)
                self.assertFalse(stale_shortcut.exists())
                self.assertFalse(stale_script.exists())
                self.assertTrue(unrelated_shortcut.exists())
                self.assertTrue((startup_dir / "Downmix Renderer.lnk").exists())

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

    def test_disable_removes_related_relocated_downmix_entries_only(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                startup_dir.mkdir(parents=True)
                relocated = startup_dir / "Updated renderer.lnk"
                unrelated = startup_dir / "Updater.lnk"
                relocated.write_text("old shortcut", encoding="utf-8")
                unrelated.write_text("updater", encoding="utf-8")

                def fake_target(path: Path) -> Path | None:
                    if path == relocated:
                        return Path(r"C:\Apps\Downmix Renderer v2\Downmixrenderer.exe")
                    if path == unrelated:
                        return Path(r"C:\Apps\Updater\Updater.exe")
                    return None

                with patch("downmix_renderer.startup._shortcut_target", fake_target):
                    ok, detail = startup.set_system_autostart(False, Path.cwd())

                self.assertTrue(ok, detail)
                self.assertEqual(detail, "disabled")
                self.assertFalse(relocated.exists())
                self.assertTrue(unrelated.exists())

    def test_disable_removes_related_utf16_powershell_startup_entry(self) -> None:
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                startup_dir.mkdir(parents=True)
                script = startup_dir / "Renderer Startup.ps1"
                script.write_text(
                    r'Start-Process "C:\Apps\Downmix Renderer\Downmixrenderer.exe"',
                    encoding="utf-16",
                )

                ok, detail = startup.set_system_autostart(False, Path.cwd())

                self.assertTrue(ok, detail)
                self.assertFalse(script.exists())

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

    def test_source_shortcut_config_prefers_production_testing_executable(self) -> None:
        with tempfile.TemporaryDirectory() as app_dir:
            app_root = Path(app_dir)
            executable = app_root / "production testing" / "Downmixrenderer.exe"
            executable.parent.mkdir(parents=True)
            executable.write_text("exe", encoding="utf-8")

            with (
                patch.object(startup.sys, "frozen", False, create=True),
                patch.object(startup.sys, "executable", str(app_root / "python.exe")),
            ):
                target, arguments, working_directory, icon = startup._shortcut_config(app_root)

            self.assertEqual(target, executable)
            self.assertEqual(arguments, "")
            self.assertEqual(working_directory, executable.parent)
            self.assertEqual(icon, executable)

    def test_enabled_shortcut_must_match_production_testing_executable_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as appdata, tempfile.TemporaryDirectory() as app_dir:
            with patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
                app_root = Path(app_dir)
                expected = app_root / "production testing" / "Downmixrenderer.exe"
                stale = app_root / "testing" / "Downmixrenderer.exe"
                expected.parent.mkdir(parents=True)
                stale.parent.mkdir(parents=True)
                expected.write_text("exe", encoding="utf-8")
                stale.write_text("old exe", encoding="utf-8")
                shortcut = startup.startup_script_path()
                self.assertIsNotNone(shortcut)
                shortcut.parent.mkdir(parents=True)
                shortcut.write_text("shortcut", encoding="utf-8")

                with (
                    patch.object(startup.sys, "frozen", False, create=True),
                    patch("downmix_renderer.startup._shortcut_target", return_value=stale),
                ):
                    self.assertFalse(startup.is_system_autostart_enabled(app_root))

                with (
                    patch.object(startup.sys, "frozen", False, create=True),
                    patch("downmix_renderer.startup._shortcut_target", return_value=expected),
                ):
                    self.assertTrue(startup.is_system_autostart_enabled(app_root))

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
