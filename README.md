# Nib

A pixel art editor for macOS that imports images well.

Open a photo or a drawing and Nib offers you a spread of reductions to choose
from rather than guessing once. Pick one, edit it by hand, add layers and frames,
and export a PNG or a GIF.

![The editor](docs/images/editor.png)

## Why a spread

Every parameter worth tuning turned out to be right for some drawings and wrong
for others. A bold marker wants less stroke thickening; a light pen needs more.
More greys rescue one subject and dirty another. There is no setting that works
everywhere, so Nib builds six options and lets you point at one.

![The import spread](docs/images/import-spread.png)

## What it does

- **Import** — six reductions to choose from, streamed in as they are made.
  Line art and colour take different paths, chosen automatically.
- **Draw** — paint, fill, eyedropper, line, rectangle, ellipse, rectangular
  select with move, copy and paste. Live mirror symmetry. Undo and redo.
- **Layers** — as many as you like, as a timeline: frames across, layers down.
  At one layer it looks exactly like a filmstrip.
- **Animate** — frames, per-frame hold, onion skin, playback, GIF export.
  Rolling wraps a layer around the edges, so rolling one layer and not another
  gives you parallax.
- **Palette** — add, replace, swap and remove colours. Swapping palettes remaps
  every frame to the nearest colour in Lab rather than re-importing, so your
  edits survive it. Swatches double as a pixel census.
- **Effects** — scanlines, glow, colour fringe, CRT and Prism, computed at cell
  resolution so the result is still pixel art you can keep drawing on.
- **Looks** — a CRT screen filter applied at export, with a 1:1 preview.

Full walkthrough with screenshots: [`docs/FUNCTIONALITY.md`](docs/FUNCTIONALITY.md).

## Running it

Requires macOS 14+, Swift 5.10+, and Python 3 with Pillow.

```bash
git clone https://github.com/jordanpainter/nib.git
cd nib
python3 -m pip install pillow numpy    # numpy is optional; it powers the looks
swift build
.build/debug/Nib                        # or: .build/debug/Nib ~/drawing.png
```

Nib starts its Python helper (`nibd`) on its own; you never launch it by hand.
Without `numpy` everything works except the export looks, which say so.

Projects are `.nibart` files: plain JSON holding the layers, every frame's cels,
the palette and the import settings.

## How it is built

```
Swift app  ──JSON lines over a Unix socket──▶  nibd  ──▶  Pillow
```

The app is SwiftUI and AppKit. The image work lives in `nibd/`, a long-lived
Python process, because Pillow does the reduction better than anything Swift
offers without pulling in a framework.

| | |
|---|---|
| `Sources/Nib/` | the app: canvas, timeline, tools, state |
| `nibd/` | quantiser, palette extraction, GIF encoding, effects, looks |
| `docs/` | what every control does |

## Status

Early but usable. Not there yet: flip and rotate, a lasso, tweening.

## Licence

MIT — see [`LICENSE`](LICENSE).
