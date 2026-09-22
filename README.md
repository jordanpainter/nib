<p align="center">
  <img src="docs/media/header.webp" width="384" alt="A pixel-art penguin holding a paintbrush, sitting on snow under a dusk sky while stars drift slowly behind him">
</p>

<h1 align="center">Nib</h1>

<p align="center">
  <b>A pixel art editor for macOS</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/macOS-14%2B-111?logo=apple&logoColor=white" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Swift-5.10-F05138?logo=swift&logoColor=white" alt="Swift 5.10">
  <img src="https://img.shields.io/badge/licence-MIT-3d8b6d" alt="MIT licence">
</p>

<p align="center">
  <a href="#import">Import</a> ·
  <a href="#draw">Draw</a> ·
  <a href="#animate">Animate</a> ·
  <a href="#work-with-claude">Work with Claude</a> ·
  <a href="#install">Install</a>
</p>

Nib is an open source pixel art editor I made when I got bored. Open a drawing
or a photo and it turns it into a spread of pixel art versions. Pick one, edit
it, animate it, and export a PNG or a GIF.

<p align="center">
  <img src="docs/media/colour.png" width="900" alt="NASA's Blue Marble photograph of the Earth beside six pixel-art versions of it, from 6 colours to 32">
  <br>
  <sub>A photo through the colour ladder: one import, six palettes, from 6 colours to 32.</sub>
</p>

---

## Import

<p align="center">
  <img src="docs/media/import.webp" width="900" alt="Importing a doodle: the original sits beside a grid of twelve reductions, and one is picked">
</p>

Works on doodles and photos alike. Nib shows every version side by side and
you pick one.

- **Line art:** twelve versions, three stroke weights by two to five tones.
- **Colour:** six versions, from 6 to 32 colours.
- **Crop:** drag a square on the original to choose what gets converted.

---

## Draw

Pencil, fill, eyedropper, line, rectangle, ellipse, rectangle and lasso
selection, with cut, copy, paste, flip and rotate. Live mirror symmetry, a grid
overlay, a tile preview for patterns that repeat, and fifty levels of undo.

<p align="center">
  <img src="docs/media/transparent.gif" width="720" alt="Picking the transparent swatch and filling the white background, which becomes a checkerboard">
</p>

The palette panel counts every colour's pixels, builds shading ramps that lean
warm or cool instead of just going darker, and swaps whole palettes by
remapping to the nearest colour, so your edits survive it.

<p align="center">
  <img src="docs/media/recolour.webp" width="900" alt="A pixel-art tulip field: three red swatches are each changed to a yellow from the swatch menu, and the field turns from red to yellow in three steps">
</p>

---

## Animate

<p align="center">
  <img src="docs/media/animate.webp" width="900" alt="Selecting the Stars layer, then Frame, Roll Across Frames, Full turn and Build: the timeline fills with 48 frames and the stars drift behind the penguin">
</p>

Frames across, layers down, in one timeline: click any cell to go straight to
that frame and layer. Per-frame holds, onion skin up to three frames either
side, copy and paste whole frames, and GIF export.

**Roll Across Frames** turns one frame into a loop where a single layer moves
and the rest hold still. That is how the header works: four layers (sky,
stars, snow, penguin), and only the stars roll, one cell per frame for 48
frames, which is exactly one lap of the canvas, so the loop has no seam.

---

## Work with Claude <img src="docs/media/clawd.webp" width="100" align="right" alt="Clawd, drawn in Nib, thinking: a bubble fills with three dots, and he blinks">

Nib comes with an MCP server, so Claude can edit your drawings, either a saved
file or the window you have open.

> Hey Claude, working on something in nib. Can you generate me three new
> "starry night" backgrounds behind the penguin?

<p align="center">
  <img src="docs/media/claude-options.png" width="828" alt="A sheet of three labelled options: Van Gogh, Midnight violet and Dusk horizon, each a different night sky behind the penguin">
</p>

> Liking option 3, can we make some of those stars slightly smaller? Then apply
> it in Nib.

<p align="center">
  <img src="docs/media/claude-window.png" width="480" alt="The Nib window showing the new sky on its own layer, with the log reading: claude, apply option-1">
</p>

- Options come back as a sheet; nothing changes until you pick one.
- Every change is one undo step.
- If you draw while it works, your strokes are kept and its edit is redone.

Connect it to Claude Code (needs [uv](https://docs.astral.sh/uv/)):

```bash
claude mcp add nib -- uv run --directory /path/to/nib/nib-mcp server.py
```

---

## Install

Needs macOS 14 or later, Swift 5.10 or later, and Python 3 with Pillow.

```bash
git clone https://github.com/jordanpainter/nib.git
cd nib
python3 -m pip install pillow numpy
./bundle.sh
open build/Nib.app
```

`./bundle.sh` builds `Nib.app` with its icon and its Python helper inside, so
you can drag it to Applications. For development, `swift build` and
`.build/debug/Nib` work too, optionally followed by a file to open.

`numpy` is optional. Without it, export looks are unavailable and colour
palettes fall back to a simpler method that can lose small vivid details.

Projects are `.nibart` files: plain JSON holding the layers, every frame, the
palette and the import settings.

---

## How it is built

```
Swift app  ──JSON lines over a Unix socket──▶  nibd  ──▶  Pillow
    ▲
    └──────  JSON lines over a Unix socket  ──  nib-mcp  ◀──  your Claude
```

The app is SwiftUI and AppKit. The image work lives in `nibd`, a long-lived
Python process, because Pillow does the reduction better than anything Swift
offers without pulling in a framework. `nib-mcp` sends Claude's edits to the
open window as whole documents, so the app keeps no second copy of any tool.

| | |
|---|---|
| `Sources/Nib/` | the app: canvas, timeline, tools, state |
| `nibd/` | quantiser, palette extraction, GIF encoding, effects, looks |
| `nib-mcp/` | the MCP server: tools for Claude, and the live link to the window |
| `docs/` | [what every control does](docs/FUNCTIONALITY.md) |

---

## Licence

MIT. See [`LICENSE`](LICENSE).

<sub>Nib is an independent project, not affiliated with, endorsed by or sponsored
by Anthropic. Claude and Clawd are trademarks of Anthropic. The Clawd in this
README is fan art, drawn in Nib. The Earth is NASA's Blue Marble photograph,
public domain. The tulip field photo is by Filio, CC0, via Wikimedia Commons.</sub>
