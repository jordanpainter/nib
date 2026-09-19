"""Nib's MCP server: lets a person's own Claude session work on Nib projects.

    uv run --directory nib-mcp server.py        # stdio, for Claude Code / Desktop

Design and reasoning: docs/AGENT_TOOLS.md. Every operation lives in nibcore.py;
this file only turns them into tools, keeps the session (one open project, its
named selections, pending proposals), and returns a small render with every
change so the agent always sees what it just did.
"""
from __future__ import annotations

import copy
import functools
import os
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import nibcore as core
from nibcore import NibError, Project

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nibd"))
import nibd  # noqa: E402  (the importer's option spread lives there)

INSTRUCTIONS = """\
You are working in Nib, a pixel-art editor, on the person's own drawings.

How to work:
- You are a studio assistant, not the artist. Do mechanical work (backgrounds,
  palettes, shading ramps, recolours, centring, icons, animation frames) and
  leave drawing decisions to the person. Never try to draw a subject from
  scratch cell by cell; it has been measured and it does not work.
- Look after every change: each change tool returns a render. Check it.
- Whenever a tool makes something for the person to look at (render,
  preview_icon, propose, import_image, open_project, apply), it saves it and
  gives the path as "Preview for the person: <path>". Always put that file in
  the conversation with a file-sending tool, every time: tool images are
  usually collapsed out of their sight. Never describe a sheet instead of
  showing it.
- When there is more than one reasonable choice (a background, a colour, a
  tip), use `propose` to show a labelled sheet and let the person pick, then
  `apply` their choice. Do not decide taste on their behalf.
- Nothing is written to disk until `save`. It refuses to overwrite a file that
  changed since it was opened (the person may have saved from the app); never
  pass overwrite=true for that case unless they say so.
- Canvases are square; cells are palette indices, -1 is transparent. Layers are
  listed bottom to top; tools act on the top layer unless you name one.
"""

server = MCPServer("nib", instructions=INSTRUCTIONS)


def tool(fn):
    """Register a tool, turning NibError into ToolError. The SDK shows a
    ToolError's message to the model and replaces anything else with a generic
    "Error executing tool", so without this the agent would be told a call
    failed but never why ("no layer called X; the layers are...")."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NibError as e:
            raise ToolError(str(e)) from e
    return server.tool()(wrapped)


class Session:
    project: Project | None = None
    masks: dict[str, core.Mask] = {}
    pending: dict[str, Project] = {}


S = Session()


def need() -> Project:
    if S.project is None:
        raise NibError("No project open. Use open_project, new_project or import_image first.")
    return S.project


def mask_of(name: str | None) -> core.Mask | None:
    if name is None:
        return None
    if name not in S.masks:
        raise NibError(f"No selection called {name!r}. Make one with `select`. Have: {list(S.masks)}")
    return S.masks[name]


def look(p: Project, frame: int = 0, size: int = 256, mask: core.Mask | None = None) -> Image:
    im = core.scaled(core.grid_image(p, p.composite(frame)), size)
    if mask:
        im = core.outline_mask(im, mask, p.size)
    return Image(data=core.png(im), format="png")


PREVIEWS = Path.home() / ".nib" / "previews"


def for_person(im, name: str) -> list:
    """An image the person needs to see. MCP hands tool images to the model
    only, so it is also written to ~/.nib/previews and its path returned for
    the agent to show. Keeps the newest 40."""
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    path = PREVIEWS / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.png"
    im.save(path)
    for old in sorted(PREVIEWS.glob("*.png"))[:-40]:
        old.unlink()
    # Worded for the moment the agent reads it, right beside the image. Tool
    # images do reach the person in the desktop app, but inside a collapsed
    # "Used N tools" group when calls are batched, and not at all in a
    # terminal; an agent told they "cannot" see it went off building its own
    # sheets. So: may not have seen it, show the file, carry on.
    return [Image(data=core.png(im), format="png"),
            f"Preview for the person: {path}\n"
            "Always show the person this file in the conversation, every time, "
            "even if the image seems visible: tool images are usually collapsed "
            "out of their sight. Use a tool that sends or displays a file to the "
            "user (the Claude desktop app has one); only if you have none, give a "
            "markdown link to the path. Do not rebuild the image yourself."]


def person_look(p: Project, name: str, frame: int = 0, size: int = 384) -> list:
    return for_person(core.scaled(core.grid_image(p, p.composite(frame)), size), name)


def changed(label: str, text: str, frame: int = 0) -> list:
    return [f"{label}: {text}", look(need(), frame)]


# ---------------------------------------------------------------- session

@tool
def open_project(path: str) -> list:
    """Open a Nib project (.nibart). Returns its layers, palette with cell
    counts per colour, and a render."""
    S.project, S.masks, S.pending = Project.open(path), {}, {}
    return [S.project.summary()] + person_look(S.project, "open")


@tool
def new_project(size: int = 32) -> list:
    """Start a blank square canvas, white and black palette. 32 suits icons."""
    S.project, S.masks, S.pending = Project.blank(size), {}, {}
    return [S.project.summary()]


@tool
def import_image(path: str, size: int = 32, crop: bool = True) -> list:
    """Reduce an image to pixel art with Nib's quantiser. Returns a sheet of
    every option (Fine, Bold, 3 tone...) and a handle per option; `apply` the
    one the person picks to start a project from it. `crop` trims blank margin."""
    S.pending = {}
    items = []
    for r in nibd.handle_stream({"cmd": "variants", "path": str(Path(path).expanduser()),
                                 "size": size, "trim": crop}):
        if not r.get("ok", True):
            raise NibError(r.get("error", "import failed"))
        e = r.get("event", {})
        if e.get("kind") != "variant":
            continue
        p = Project.blank(size, list(e["palette"]))
        p.data["paletteName"] = e["label"]
        p.frames[0]["cels"][0] = e["grid"]
        handle = f"import-{len(S.pending) + 1}"
        S.pending[handle] = p
        items.append((f"{handle}: {e['label']}", core.grid_image(p, e["grid"])))
    return [f"{len(items)} options. Show the person and `apply` their pick.",
            *for_person(core.sheet(items, sizes=(160,), columns=4), "import-options")]


@tool
def save(path: str | None = None, overwrite: bool = False) -> str:
    """Write the project. With no path, saves over the file it was opened from,
    but refuses if that file changed on disk since opening."""
    return f"saved {need().save(path, overwrite)}"


# ---------------------------------------------------------------- looking

@tool
def render(frame: int = 0, size: int = 512, all_frames: bool = False) -> list:
    """Render the project, transparency as a checkerboard. `all_frames` shows
    every frame side by side."""
    p = need()
    if not all_frames:
        return person_look(p, "render", frame, size)
    items = [(f"frame {i}", core.grid_image(p, p.composite(i))) for i in range(len(p.frames))]
    return for_person(core.sheet(items, sizes=(min(size, 192),), columns=6), "frames")


@tool
def inspect(x0: int = 0, y0: int = 0, x1: int | None = None, y1: int | None = None,
            frame: int = 0, layer: str | int | None = None) -> str:
    """Cells as text (palette indices, '.' for transparent), for exact
    positions. Rows are y, columns x. Omit `layer` for the composite."""
    p = need()
    n = p.size
    x1 = n - 1 if x1 is None else x1
    y1 = n - 1 if y1 is None else y1
    g = p.cel(frame, layer) if layer is not None else p.composite(frame)
    w = max(2, len(str(len(p.palette) - 1)) + 1)
    head = "    " + "".join(str(x).rjust(w) for x in range(x0, x1 + 1))
    rows = [str(y).rjust(3) + " " + "".join(("." if g[y][x] < 0 else str(g[y][x])).rjust(w)
                                          for x in range(x0, x1 + 1)) for y in range(y0, y1 + 1)]
    return head + "\n" + "\n".join(rows)


@tool
def preview_icon(frame: int = 0) -> list:
    """The project as a macOS app icon: masked the way macOS 26 masks a square
    icon, at 256/128/64/32px on a light and a dark Dock. Judge at 32."""
    p = need()
    return for_person(core.icon_preview([("current", core.as_icon(p, frame))]), "icon")


# ---------------------------------------------------------------- selecting

@tool
def select(by: str, name: str = "selection", rect: list[int] | None = None,
           colour: str | int | None = None, layer: str | int | None = None,
           frame: int = 0) -> list:
    """Make a named selection that other tools take as `mask`.
    by: all | rect (rect=[x0,y0,x1,y1] inclusive) | colour | layer (its
    non-transparent cells) | outside (background reachable from the edges,
    ignoring full backdrop layers) | inside (everything else: the subject)."""
    p = need()
    m = core.select(p, by, frame, layer, rect, colour)
    S.masks[name] = m
    return [f"{name}: {len(m)} cells, bounds {core.bounds(m)}", look(p, frame, mask=m)]


# ---------------------------------------------------------------- changing

@tool
def paint(colour: str | int, cells: list[list[int]] | None = None,
          fill_at: list[int] | None = None, frame: int = 0,
          layer: str | int | None = None) -> list:
    """Low-level fixes: set cells [[x,y],...] to a colour, and/or flood-fill
    from fill_at=[x,y]. colour: palette index, hex, or 'transparent'. For small
    corrections only, not for drawing a subject."""
    p = need()
    p.checkpoint("paint")
    return changed("paint", f"{core.paint(p, colour, cells, fill_at, frame, layer)} cells", frame)


@tool
def transform(op: str, mask: str | None = None, frame: int = 0, layer: str | int | None = None,
              dx: int = 0, dy: int = 0, size: int | None = None) -> list:
    """op: flip_h | flip_v | rotate_cw | rotate_ccw (the mask, or the whole
    layer) | roll (dx, dy, wrapping; one layer) | recentre (all layers move
    together so the subject is centred) | canvas_size (size=N, centred)."""
    p = need()
    p.checkpoint(op)
    return changed(op, core.transform(p, op, mask_of(mask), frame, layer, dx, dy, size), frame)


@tool
def gradient(stops: list[str], bands: int = 5, mode: str = "vertical", dither: bool = False,
             mask: str | None = None, frame: int = 0, layer: str | int | None = None) -> list:
    """Banded gradient through any number of hex stops, top to bottom by
    default. mode: vertical | horizontal | diagonal | radial. dither adds a
    2x2 checker at band edges. Fills the mask, or the whole layer. For a
    background, add a layer at the bottom first with `structure`."""
    p = need()
    p.checkpoint("gradient")
    return changed("gradient", core.gradient(p, stops, bands, mode, dither, mask_of(mask), frame, layer), frame)


@tool
def palette(op: str, index: int | None = None, colour: str | None = None,
            to: int | None = None, darker: bool = True, steps: int = 1) -> list:
    """op: add (colour) | replace (index, colour: every cell of that index
    changes colour) | swap (index, to: moves cells to another index) | remove
    (index; cells go to the nearest colour) | shade (index, darker, steps:
    appends a hand-shading ramp, hue-shifted, greys stay neutral)."""
    p = need()
    p.checkpoint(f"palette {op}")
    return changed(f"palette {op}", core.palette_op(p, op, index, colour, to, darker, steps))


@tool
def structure(op: str, name: str | None = None, layer: str | int | None = None,
              position: str | int | None = None, frame: int = 0) -> list:
    """op: add_layer (name, position: top|bottom|index) | delete_layer |
    move_layer (position) | hide_layer | show_layer | rename_layer (name) |
    add_frame | duplicate_frame (frame) | delete_frame (frame)."""
    p = need()
    p.checkpoint(op)
    return changed(op, core.structure(p, op, name, layer, position, frame)) + [p.summary()]


@tool
def undo(steps: int = 1) -> list:
    """Undo the last change(s) made in this session."""
    p = need()
    done = p.undo(steps)
    return [f"undid: {', '.join(done) or 'nothing'}", look(p)]


# ---------------------------------------------------------------- choosing

CHANGE_TOOLS = {"paint": paint, "transform": transform, "gradient": gradient,
                "palette": palette, "structure": structure}


@tool
def propose(options: list[dict], sizes: list[int] | None = None, as_icon: bool = False) -> list:
    """Try several versions on scratch copies and show them side by side;
    nothing changes until `apply`. Each option: {"label": str, "steps":
    [{"tool": "gradient"|"palette"|"transform"|"paint"|"structure", "args": {...}}]}.
    sizes: pixel sizes to show each at, e.g. [160, 32]. as_icon: show each
    masked as a macOS icon at Dock sizes, light and dark."""
    base = need()
    S.pending = {}
    items = []
    for i, opt in enumerate(options, 1):
        trial = copy.deepcopy(base)
        trial.history = []
        saved, S.project = S.project, trial
        try:
            for step in opt.get("steps", []):
                tool = CHANGE_TOOLS.get(step.get("tool"))
                if tool is None:
                    raise NibError(f"propose can run {list(CHANGE_TOOLS)}, not {step.get('tool')!r}.")
                tool(**step.get("args", {}))
        finally:
            S.project = saved
        handle = f"option-{i}"
        S.pending[handle] = trial
        label = f"{handle}: {opt.get('label', '')}"
        items.append((label, core.as_icon(trial) if as_icon else core.grid_image(trial, trial.composite(0))))
    img = (core.icon_preview(items, sizes=tuple(sizes or (256, 128, 64, 32))) if as_icon
           else core.sheet(items, sizes=tuple(sizes or (160,)), columns=4))
    return [f"{len(items)} options. Show the person and `apply` their pick.",
            *for_person(img, "options")]


@tool
def apply(handle: str) -> list:
    """Commit an option from `propose` or `import_image` (e.g. "option-3")."""
    if handle not in S.pending:
        raise NibError(f"No pending option {handle!r}. Have: {list(S.pending)}")
    chosen = S.pending.pop(handle)
    if S.project is not None and handle.startswith("option-"):
        S.project.checkpoint(f"apply {handle}")
        S.project.data = chosen.data
    else:
        S.project, S.masks = chosen, {}
    S.pending = {}
    return [f"applied {handle}"] + person_look(S.project, "applied")


# ---------------------------------------------------------------- export

@tool
def export(kind: str, path: str, scale: int = 8, frame: int = 0) -> str:
    """kind: png (one frame, scaled by whole numbers) | gif (every frame, holds
    and fps honoured) | icns (macOS icon; canvas must divide 1024)."""
    return f"wrote {core.export(need(), kind, path, scale, frame)}"


if __name__ == "__main__":
    server.run()
