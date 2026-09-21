"""Build Resources/AppIcon.icns from icon/nib-icon-48.png.

    python3 icon/make_icns.py

The source is the 48x48 pixel art itself, exactly as drawn, edge to edge.

Icon sizes are powers of two and 48 divides none of them, so cells cannot all
be the same width at every size. At 512 and 1024 nearest-neighbour is used
anyway: cells come out 10-11 and 21-22 pixels, a difference nobody can see. Below
that the unevenness shows (at 128, cells 2 and 3 pixels wide side by side), so
those sizes are drawn from an exact 22x enlargement and filtered down, which
keeps them even at the cost of a little softness where it cannot be seen.

Written with Pillow, not iconutil. iconutil stores 16px and 32px at 1x in a
legacy run-length format that comes back with corrupted pixels (3 at 16px, a
whole row at 32px), and hand-written PNG entries for those two tags are not
read back at all. Pillow omits the 1x 16 and 32 entries; macOS scales from the
Retina ones, which round-trip exactly.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
src = Image.open(ROOT / "icon" / "nib-icon-48.png").convert("RGB")
big = src.resize((src.width * 22, src.height * 22), Image.NEAREST)


def at(px: int) -> Image.Image:
    if px >= 512:
        return src.resize((px, px), Image.NEAREST).convert("RGBA")
    return big.resize((px, px), Image.LANCZOS).convert("RGBA")


at(1024).save(ROOT / "Resources" / "AppIcon.icns", format="ICNS",
              append_images=[at(p) for p in (16, 32, 64, 128, 256, 512)])
at(1024).save(ROOT / "icon" / "nib-icon.png")
print("wrote Resources/AppIcon.icns and icon/nib-icon.png")
