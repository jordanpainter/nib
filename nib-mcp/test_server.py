"""Drives every tool through a real MCP client, in-process.

    uv run --directory nib-mcp python test_server.py [project.nibart]

With a project path, the workflow tests run on a scratch copy of it; without,
on a generated one. Nothing outside a temporary directory is ever written.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile

from mcp import Client

import nibcore as core
import server

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def text(r) -> str:
    return "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")


def images(r) -> int:
    return sum(1 for c in r.content if getattr(c, "type", "") == "image")


def err(r) -> bool:
    return bool(getattr(r, "is_error", None) or getattr(r, "isError", None))


def sample_project(path: str):
    """A 32x32 penguin-ish blob on a white backdrop layer, if none was given."""
    p = core.Project.blank(32, ["#ffffff", "#000000", "#ff4245"])
    core.structure(p, "add_layer", name="Sprite")
    core.paint(p, 1, cells=[[x, y] for x in range(10, 22) for y in range(8, 24)], layer="Sprite")
    core.paint(p, 2, cells=[[4, 10], [5, 10]], layer="Sprite")
    core.paint(p, 0, fill_at=[0, 0], layer=0)
    p.save(path)


async def main(source: str | None):
    tmp = tempfile.mkdtemp(prefix="nibmcp-")
    proj = os.path.join(tmp, "work.nibart")
    if source:
        shutil.copy(os.path.expanduser(source), proj)
    else:
        sample_project(proj)

    async with Client(server.server) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        check("17 tools listed", len(tools) == 17, str(sorted(tools)))

        r = await c.call_tool("render", {})
        check("tool before opening gives a readable error", err(r) and "No project open" in text(r), text(r))

        r = await c.call_tool("open_project", {"path": proj})
        check("open_project returns summary and render", "Layers" in text(r) and images(r) == 1)
        before = json.loads(json.dumps(server.S.project.data))

        r = await c.call_tool("select", {"by": "inside", "name": "subject"})
        inside = len(server.S.masks["subject"])
        r2 = await c.call_tool("select", {"by": "outside", "name": "bg"})
        check("inside + outside cover the canvas",
              inside + len(server.S.masks["bg"]) == server.S.project.size ** 2)
        check("select returns an outlined render", images(r) == 1)

        r = await c.call_tool("structure", {"op": "add_layer", "name": "Sunset", "position": "bottom"})
        check("add_layer at bottom", server.S.project.layers[0]["name"] == "Sunset", text(r))

        stops = ["#ffd6a5", "#ffbeaa", "#f5aabe", "#d2a5dc"]
        r = await c.call_tool("gradient", {"stops": stops, "bands": 5, "dither": True, "layer": "Sunset"})
        bottom = server.S.project.cel(0, "Sunset")
        check("gradient fills the whole bottom layer", all(v >= 0 for row in bottom for v in row))
        check("gradient uses 5 band colours", len({v for row in bottom for v in row}) == 5)
        check("change tools return a render", images(r) == 1)

        r = await c.call_tool("undo", {"steps": 2})
        check("undo 2 removes the gradient and the layer",
              server.S.project.data == before, text(r))

        opts = [{"label": name, "steps": [
                    {"tool": "structure", "args": {"op": "add_layer", "name": "BG", "position": "bottom"}},
                    {"tool": "gradient", "args": {"stops": st, "layer": "BG", "dither": d}}]}
                for name, st, d in (("sunset dithered", stops, True),
                                    ("dusk", ["#ffc8b4", "#b9a0e6", "#8ca0eb"], False),
                                    ("teal", ["#00c7ab", "#00c7ab"], False))]
        r = await c.call_tool("propose", {"options": opts, "as_icon": True})
        check("propose returns one sheet", images(r) == 1 and "3 options" in text(r), text(r))
        check("propose changes nothing", server.S.project.data == before)

        r = await c.call_tool("apply", {"handle": "option-1"})
        check("apply commits the chosen option", server.S.project.layers[0]["name"] == "BG")
        r = await c.call_tool("undo", {})
        check("apply is one undo step", server.S.project.data == before, text(r))

        n_before = len(server.S.project.palette)
        r = await c.call_tool("palette", {"op": "shade", "index": 1, "darker": False, "steps": 3})
        check("shade appends a 3-step ramp", len(server.S.project.palette) == n_before + 3, text(r))
        def sat(h):
            r, g, b = core.hex_rgb(h)
            return 0 if max(r, g, b) == 0 else (max(r, g, b) - min(r, g, b)) / max(r, g, b)
        src = server.S.project.palette[1]
        check("shading a grey adds no colour (saturation never rises)",
              all(sat(h) <= sat(src) + 0.01 for h in server.S.project.palette[n_before:]),
              f"{src} -> {server.S.project.palette[n_before:]}")
        await c.call_tool("undo", {})

        g0 = server.S.project.cel(0, None)
        g0 = [row[:] for row in g0]
        await c.call_tool("transform", {"op": "flip_h"})
        await c.call_tool("transform", {"op": "flip_h"})
        check("flip twice is identity", server.S.project.cel(0, None) == g0)
        await c.call_tool("transform", {"op": "rotate_cw", "mask": "subject"})
        check("rotate a selection changes the layer", server.S.project.cel(0, None) != g0)
        for _ in range(3):
            await c.call_tool("undo", {})

        r = await c.call_tool("transform", {"op": "recentre"})
        check("recentre runs", not err(r), text(r))
        await c.call_tool("undo", {})

        r = await c.call_tool("paint", {"colour": 1, "cells": [[99, 99]]})
        check("off-canvas paint is a readable error", err(r) and "off the" in text(r), text(r))
        r = await c.call_tool("transform", {"op": "flip_h", "layer": "Nope"})
        check("bad layer name lists the real ones", err(r) and "Layers:" in text(r), text(r))

        r = await c.call_tool("inspect", {"x0": 0, "y0": 0, "x1": 5, "y1": 2})
        check("inspect gives a text grid", len(text(r).splitlines()) == 4, text(r))

        r = await c.call_tool("preview_icon", {})
        check("preview_icon returns a sheet", images(r) == 1)

        # Save guard: the app saving the same file underneath must be refused.
        server.S.project.checkpoint("x")
        os.utime(proj, (1, 1))
        r = await c.call_tool("save", {})
        check("save refuses a file changed on disk", err(r) and "changed on disk" in text(r), text(r))
        out = os.path.join(tmp, "copy.nibart")
        r = await c.call_tool("save", {"path": out})
        check("save to a new path works", os.path.exists(out), text(r))
        r = await c.call_tool("save", {"path": proj})
        check("save refuses an existing other file", err(r) and "exists" in text(r), text(r))
        reopened = core.Project.open(out)
        check("saved file reads back identical", reopened.data == server.S.project.data)
        with open(out) as f:
            raw = json.load(f)
        check("saved file has every key the app requires",
              all(k in raw for k in ("palette", "paletteName", "selectedIndex", "frames", "fps", "layers")))

        icns = os.path.join(tmp, "icon.icns")
        r = await c.call_tool("export", {"kind": "icns", "path": icns})
        check("export icns", os.path.getsize(icns) > 1000, text(r))
        pngp = os.path.join(tmp, "x.png")
        await c.call_tool("export", {"kind": "png", "path": pngp, "scale": 4})
        from PIL import Image as PImage
        check("export png at 4x", PImage.open(pngp).size == (server.S.project.size * 4,) * 2)

        img = os.path.expanduser("~/avatars/kelvin.png")
        if os.path.exists(img):
            r = await c.call_tool("import_image", {"path": img, "size": 32})
            check("import_image offers 8 options", "8 options" in text(r) and images(r) == 1, text(r))
            r = await c.call_tool("apply", {"handle": "import-3"})
            check("applying an import starts a project from it",
                  server.S.project.data["paletteName"] == "Fine, 3 tone", text(r))

    shutil.rmtree(tmp)
    print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)}")
    return not FAILS


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None)) else 1)
