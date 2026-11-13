"""Buduje vidsum/web/vidsum.ico z icon.svg (≥32 px) i packaging/icon_small.svg (16–24 px: grubsze kreski).
Wymaga rsvg-convert i Pillow. Uruchomienie: python packaging/make_icon.py"""
import io
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def render(svg: Path, size: int) -> Image.Image:
    png = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(svg)],
                         check=True, capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    imgs = [render(ROOT / ("packaging/icon_small.svg" if s <= 24 else "vidsum/web/icon.svg"), s) for s in SIZES]
    big = imgs[-1]
    big.save(ROOT / "vidsum/web/vidsum.ico", format="ICO", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])


if __name__ == "__main__":
    main()
