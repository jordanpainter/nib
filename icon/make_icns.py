"""Build Resources/AppIcon.icns from icon/nib-icon-32.png.

    python3 icon/make_icns.py

The source is the 32x32 pixel art itself, not an upscale, so every size from
32px up is a whole multiple of the grid and scales nearest-neighbour with every
cell the same width. 16px cannot be a multiple, so it is filtered.

Written with Pillow, not iconutil. iconutil stores 16px and 32px at 1x in a
legacy run-length format that comes back with corrupted pixels (3 at 16px, a
whole row at 32px), and hand-written PNG entries for those two tags are not
read back at all. Pillow omits the 1x 16 and 32 entries; macOS scales from the
Retina ones, which round-trip exactly.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
src = Image.open(ROOT / "icon" / "nib-icon-32.png").convert("RGB")


def at(px: int) -> Image.Image:
    if px >= src.width:
        return src.resize((px, px), Image.NEAREST).convert("RGBA")
    return (src.resize((1024, 1024), Image.NEAREST)
            .resize((px, px), Image.LANCZOS).convert("RGBA"))


at(1024).save(ROOT / "Resources" / "AppIcon.icns", format="ICNS",
              append_images=[at(p) for p in (16, 32, 64, 128, 256, 512)])
at(1024).save(ROOT / "icon" / "nib-icon.png")
print("wrote Resources/AppIcon.icns and icon/nib-icon.png")
