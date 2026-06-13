from __future__ import annotations

import unittest
from pathlib import Path


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
        self.assertNotIn('Join-Path "dist" $DistName', source)


if __name__ == "__main__":
    unittest.main()
