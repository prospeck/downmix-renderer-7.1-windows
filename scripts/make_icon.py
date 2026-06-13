from __future__ import annotations

from pathlib import Path

from PIL import Image


def make_icon(path: Path) -> None:
    source = path.with_suffix(".png")
    if not source.exists():
        raise FileNotFoundError(f"Missing logo source: {source}")

    logo = Image.open(source).convert("RGBA")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [logo.resize((size, size), Image.Resampling.LANCZOS) for size in sizes]

    path.parent.mkdir(parents=True, exist_ok=True)
    images[-1].save(path, sizes=[(size, size) for size in sizes])


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    make_icon(root / "assets" / "downmix_renderer_logo.ico")
