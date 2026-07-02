from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def _read_pyproject_lists() -> tuple[list[str], list[str]]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    def read_list(header: str, key: str) -> list[str]:
        in_header = False
        in_list = False
        values: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                in_header = line == header
                in_list = False
                continue
            if not in_header:
                continue
            if line.startswith(f"{key} = ["):
                in_list = True
                continue
            if in_list and line == "]":
                return values
            if in_list and line.startswith('"'):
                values.append(line.strip('",'))
        return values

    return read_list("[project]", "dependencies"), read_list("[project.optional-dependencies]", "build")


class ReleaseHardeningTests(unittest.TestCase):
    def test_runtime_and_build_dependencies_are_declared_and_pinned(self) -> None:
        dependencies, build_dependencies = _read_pyproject_lists()

        self.assertIn("pywin32==311", dependencies)
        self.assertTrue(all("==" in dependency for dependency in dependencies))
        self.assertTrue(all("==" in dependency for dependency in build_dependencies))
        self.assertTrue(any(dependency.startswith("ziglang==") for dependency in build_dependencies))

    def test_native_build_script_does_not_install_unpinned_tools_or_suppress_warnings(self) -> None:
        source = (ROOT / "scripts" / "build_native_backend.py").read_text(encoding="utf-8")

        self.assertNotIn('"pip"', source)
        self.assertNotIn('"install"', source)
        self.assertNotIn('"-w"', source)
        self.assertIn('"-Wall"', source)
        self.assertIn('"-Wextra"', source)
        self.assertIn("DLL.with_suffix", source)
        self.assertIn("IMPORT_LIB", source)
        self.assertIn("(PDB, IMPORT_LIB)", source)
        self.assertIn("artifact.unlink", source)

    def test_release_signing_script_signs_and_verifies_pe_files(self) -> None:
        source = (ROOT / "scripts" / "sign_release.ps1").read_text(encoding="utf-8")

        self.assertIn("signtool", source.casefold())
        self.assertIn("sign", source.casefold())
        self.assertIn("verify", source.casefold())
        self.assertIn("timestamp", source.casefold())
        self.assertIn("*.exe", source)
        self.assertIn("*.dll", source)

    def test_release_build_targets_root_finalised_folder(self) -> None:
        source = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")

        self.assertIn('--distpath "."', source)
        self.assertIn("--workpath build", source)
        self.assertIn("-Path $DistName", source)
        self.assertIn("Get-CimInstance Win32_Process", source)
        self.assertIn("Stop-Process -Id $_.ProcessId -Force", source)
        self.assertIn('Join-Path $root "build"', source)
        self.assertIn("Remove-Item -LiteralPath $buildDir -Recurse -Force", source)
        self.assertNotIn('Join-Path "dist" $DistName', source)

    def test_public_release_defaults_to_downmix_renderer_software_folder(self) -> None:
        build_script = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
        spec = (ROOT / "renderer_app.spec").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tech_spec = (ROOT / "docs" / "TECHNICAL_SPECIFICATION.md").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn('[string]$DistName = "Downmix Renderer Software"', build_script)
        self.assertIn('"DOWNMIX_RENDERER_DIST_NAME", "Downmix Renderer Software"', spec)
        self.assertIn(r"Downmix Renderer Software\Downmixrenderer.exe", readme)
        self.assertIn(r"Downmix Renderer Software\Downmixrenderer.exe", tech_spec)
        for generated_path in (
            "Downmix Renderer Software/",
            "production testing/",
            "ui testing/",
            "DMR macos/",
            "*.7z",
        ):
            self.assertIn(generated_path, gitignore)

    def test_release_package_disables_upx_for_windows_compatibility(self) -> None:
        source = (ROOT / "renderer_app.spec").read_text(encoding="utf-8")

        self.assertNotIn("upx=True", source)
        self.assertGreaterEqual(source.count("upx=False"), 2)

    def test_native_ultra_stream_keeps_shared_wasapi_stability_guards(self) -> None:
        native_source = (ROOT / "cpp_backend" / "downmix_native.cpp").read_text(encoding="utf-8")
        engine_source = (ROOT / "downmix_renderer" / "audio_engine.py").read_text(encoding="utf-8")

        self.assertIn("config.capture.shareMode = ma_share_mode_shared", native_source)
        self.assertIn("config.playback.shareMode = ma_share_mode_shared", native_source)
        self.assertIn("config.periods = 3", native_source)
        self.assertIn("config.performanceProfile = ma_performance_profile_low_latency", native_source)
        self.assertIn("config.wasapi.usage = ma_wasapi_usage_pro_audio", native_source)
        self.assertIn("config.wasapi.noAutoConvertSRC = MA_TRUE", native_source)
        self.assertIn("out.inputLatency = static_cast<float>(blockSize_) / static_cast<float>(sampleRate_)", native_source)
        self.assertNotIn("capturePeriodSize_", native_source)
        self.assertNotIn("playbackPeriodSize_", native_source)
        self.assertIn('"ultra": ("ultra", "raw")', engine_source)

    def test_icon_contains_standard_windows_taskbar_sizes(self) -> None:
        icon_path = ROOT / "assets" / "downmix_renderer_logo.ico"

        with Image.open(icon_path) as image:
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(image.ico.sizes()))


if __name__ == "__main__":
    unittest.main()
