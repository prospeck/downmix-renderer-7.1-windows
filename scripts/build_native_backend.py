from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "downmix_renderer" / "downmix_renderer_native.dll"
PDB = DLL.with_suffix(".pdb")
SOURCE = ROOT / "cpp_backend" / "downmix_native.cpp"


def zig_exe() -> Path:
    spec = importlib.util.find_spec("ziglang")
    if spec is not None and spec.origin:
        candidate = Path(spec.origin).resolve().parent / "zig.exe"
        if candidate.exists():
            return candidate

    raise RuntimeError("Pinned build environment is missing ziglang; run with the project build extras available.")


def main() -> int:
    zig = zig_exe()
    DLL.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(zig),
        "c++",
        "-target",
        "x86_64-windows-gnu",
        "-std=c++17",
        "-O3",
        "-Wall",
        "-Wextra",
        "-shared",
        str(SOURCE),
        "-o",
        str(DLL),
        "-lwinmm",
        "-lole32",
        "-luuid",
        "-lavrt",
    ]
    subprocess.check_call(command, cwd=ROOT)
    if PDB.exists():
        PDB.unlink()
    print(DLL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
