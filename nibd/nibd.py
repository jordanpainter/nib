"""The Nib daemon: one long-lived process holding the quantiser.

Same shape as chess-coach's `coachd`: a Unix socket speaking JSON lines, started
on demand by the Swift app and never launched by hand. It exists so the pipeline
has exactly one implementation, and because Pillow does the image work better
than anything Swift offers without pulling in a framework.

Protocol: one JSON object per line in, one JSON object per line out.
Every reply carries "ok": true/false. A false reply always carries "error".
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sys
import urllib.error
import traceback
from pathlib import Path

from PIL import Image

import effects as effects_mod
import looks as looks_mod
import quantise

STATE = Path(os.path.expanduser("~/.nib"))
SOCK = STATE / "nibd.sock"
OUT = STATE / "output"


def handle(req: dict) -> dict:
    cmd = req.get("cmd")

    if cmd == "ping":
        return {"ok": True, "pong": True}

    if cmd == "quantise":
        path = req["path"]
        if not os.path.exists(path):
            return {"ok": False, "error": f"no such file: {path}"}
        size = int(req.get("size", 48))
        palette = req["palette"]
        source = Image.open(path)
        if req.get("trim", True):
            source = quantise.trim(source)
        # A two-colour palette means a two-tone subject, so take the line-art
        # path: threshold first, reduce the mask. `ink_bias` becomes the
        # coverage threshold, inverted so the slider still reads "more ink".
        if req.get("line_art") and len(palette) == 2:
            grid = quantise.line_art(
                source,
                size=size,
                coverage=max(0.05, 0.55 - float(req.get("ink_bias", 0.4)) * 0.5),
            )
            counts = quantise.usage(grid)
            return {"ok": True, "grid": grid, "size": size,
                    "usage": {str(k): v for k, v in sorted(counts.items())}}
        grid = quantise.quantise(
            source,
            size=size,
            palette=palette,
            metric=req.get("metric", "lab"),
            dither=bool(req.get("dither", False)),
            ink_bias=float(req.get("ink_bias", 0.0)),
            adaptive=bool(req.get("adaptive", False)),
        )
        if req.get("drop_background") is not None:
            grid = quantise.drop_background(grid, int(req["drop_background"]))
        counts = quantise.usage(grid)
        return {
            "ok": True,
            "grid": grid,
            "size": size,
            "usage": {str(k): v for k, v in sorted(counts.items())},
        }

    if cmd == "export":
        grid = req["grid"]
        palette = req["palette"]
        scale = int(req.get("scale", 1))
        name = req.get("name") or "nib"
        look = req.get("look", "clean")
        OUT.mkdir(parents=True, exist_ok=True)
        img = looks_mod.render(grid, palette, scale, look)
        suffix = "" if scale == 1 else f"@{scale}x"
        # The look is in the filename, so a decorated export can never be
        # mistaken for the clean one sitting next to it in the same folder.
        if look != "clean":
            suffix += f"_{look}"
        dest = Path(req["path"]) if req.get("path") else OUT / f"{name}_{len(grid)}x{len(grid)}{suffix}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        return {"ok": True, "path": str(dest)}

    if cmd == "render_look":
        # The preview panel. Returns the image itself rather than writing a file:
        # a preview is not an export, and littering ~/.nib/output with every
        # keystroke would make finding a real export impossible.
        img = looks_mod.render(req["grid"], req["palette"],
                               int(req.get("scale", 12)), req.get("look", "screen"))
        return {"ok": True, "png": base64.b64encode(quantise.png_bytes(img)).decode(),
                "width": img.width, "height": img.height}

    if cmd == "duotone":
        look = looks_mod.find(req.get("look", "terminal"))
        if not look or not look["duotone"]:
            return {"ok": False, "error": "that look has no duotone"}
        return {"ok": True, "colors": looks_mod.duotone(req["palette"], *look["duotone"],
                                                        invert=look.get("invert", True))}

    if cmd == "gradient":
        n = len(req["grid"])
        rect = req.get("rect") or [0, 0, n - 1, n - 1]
        grid, colors, full = effects_mod.gradient(
            req["grid"], req["palette"], rect,
            req["from"], req["to"],
            bands=req.get("bands", 5), mode=req.get("mode", "vertical"),
            dither=bool(req.get("dither", False)))
        return {"ok": True, "grid": grid, "palette": colors, "full": full}

    if cmd == "effects":
        return {"ok": True, "effects": effects_mod.EFFECTS}

    if cmd == "effect":
        grid, colors, full = effects_mod.apply(req["grid"], req["palette"], req["effect"])
        return {"ok": True, "grid": grid, "palette": colors, "full": full}

    if cmd == "looks":
        return {"ok": True, **looks_mod.available(),
                "looks": [{"id": l["id"], "name": l["name"],
                           "filtered": l["screen"] is not None} for l in looks_mod.LOOKS]}

    if cmd == "analyse":
        path = req["path"]
        if not os.path.exists(path):
            return {"ok": False, "error": f"no such file: {path}"}
        return {"ok": True, **quantise.analyse(Image.open(path))}

    if cmd == "extract_palette":
        path = req["path"]
        if not os.path.exists(path):
            return {"ok": False, "error": f"no such file: {path}"}
        colors = quantise.extract_palette(Image.open(path), int(req.get("colors", 16)))
        return {"ok": True, "colors": colors}

    if cmd == "remap":
        # Nearest colour for every index of one palette in another, in Lab.
        # The app applies the map to every frame itself; this exists so that
        # colour distance has one implementation, and it is not the hue-blind one.
        old = [quantise.hex_to_rgb(c) for c in req["from"]]
        new = [quantise.hex_to_rgb(c) for c in req["to"]]
        if not old or not new:
            return {"ok": False, "error": "remap needs two non-empty palettes"}
        lab_new = [quantise.rgb_to_lab(c) for c in new]
        mapping = []
        for c in old:
            lab = quantise.rgb_to_lab(c)
            best, best_d = 0, None
            for i, t in enumerate(lab_new):
                d = sum((a - b) ** 2 for a, b in zip(lab, t))
                if best_d is None or d < best_d:
                    best, best_d = i, d
            mapping.append(best)
        return {"ok": True, "map": mapping}

    if cmd == "export_gif":
        frames = req["frames"]
        palette = req["palette"]
        if len(frames) < 2:
            return {"ok": False, "error": "a GIF needs more than one frame"}
        if len(palette) > 255:
            return {"ok": False, "error": "GIF holds 255 colours plus transparency"}
        fps = max(1.0, float(req.get("fps", 8)))
        scale = int(req.get("scale", 1))
        name = req.get("name") or "nib"
        OUT.mkdir(parents=True, exist_ok=True)
        look = req.get("look", "clean")
        imgs, durations = [], []
        for f in frames:
            durations.append(int(round(max(1, int(f.get("hold", 1))) / fps * 1000)))
        if look == "clean":
            imgs = [quantise.gif_frame(f["grid"], palette, scale=scale) for f in frames]
        else:
            # A filtered frame is full colour -- bloom alone invents thousands of
            # shades -- so it has to be re-quantised. Every frame is quantised
            # against the *first* frame's palette rather than its own, or the
            # colours crawl from frame to frame as each one picks a new 255.
            rgb = [looks_mod.render(f["grid"], palette, scale, look) for f in frames]
            master = rgb[0].quantize(colors=255, method=Image.MEDIANCUT)
            imgs = [master] + [im.quantize(palette=master, dither=Image.Dither.NONE)
                               for im in rgb[1:]]
        suffix = "" if scale == 1 else f"@{scale}x"
        if look != "clean":
            suffix += f"_{look}"
        dest = Path(req["path"]) if req.get("path") else OUT / f"{name}_{len(frames)}f{suffix}.gif"
        dest.parent.mkdir(parents=True, exist_ok=True)
        # disposal=2 clears each frame back to the background before the next is
        # drawn. Without it a transparent cell shows whatever the previous frame
        # left there, and an animation with holes in it smears.
        save_args = {"save_all": True, "append_images": imgs[1:], "duration": durations,
                     "loop": 0, "disposal": 2, "optimize": False}
        if look == "clean":
            save_args["transparency"] = len(palette)   # a screen has no transparency
        imgs[0].save(dest, **save_args)
        return {"ok": True, "path": str(dest), "frames": len(frames)}

    return {"ok": False, "error": f"unknown cmd: {cmd!r}"}


def variant_specs(kind: str, palette: list[str]) -> list[dict]:
    """The spread offered for a given kind of image.

    Deliberately a spread rather than a single guess. Every parameter we measured
    is right for some drawings and wrong for others -- 0.5 suits a bold pen, 0.8
    rescues a light one -- so showing a handful and letting the user point beats
    any heuristic.
    """
    if kind == "line_art":
        return [
            {"label": "Fine, 2 tone",   "ink_bias": 0.4, "palette": MONO,  "line_art": True},
            {"label": "Fine, 4 tone",   "ink_bias": 0.4, "palette": GREY4, "line_art": False},
            # Black where Fine would put ink, grey where only Bold would: the
            # grey is the threshold itself, so it lands on half-filled cells
            # and never haloes an edge the way averaging does.
            {"label": "Fine, 3 tone",   "ink_bias": 0.4, "palette": GREY3, "line_art": True,
             "grey": 0.15},
            # Bias varying per cell from how busy the neighbourhood is. Measured
            # across all 14 doodles: clearly better where detail is dense (the
            # castle's scroll, the raccoon's chest) and neutral on plain outlines.
            {"label": "Adaptive, 4 tone", "ink_bias": 0.8, "palette": GREY4,
             "line_art": False, "adaptive": True},
            {"label": "Medium, 2 tone", "ink_bias": 0.6, "palette": MONO,  "line_art": True},
            {"label": "Bold, 2 tone",   "ink_bias": 0.8, "palette": MONO,  "line_art": True},
            {"label": "Bold, 6 tone",   "ink_bias": 0.8, "palette": GREY6, "line_art": False},
            # Reduce to twice the target first, then halve. Measured cleaner than
            # going direct, and only at an integer ratio: via 96 to 48 beats
            # direct, via 128 to 48 is worse because each output cell straddles
            # source cells unevenly and smears the edges.
            {"label": "Via 2x, 2 tone", "ink_bias": 0.5, "palette": MONO,
             "line_art": True, "cascade": True},
        ]
    return ([{"label": f"{n} colours from image", "colors": n} for n in (4, 8, 12, 16, 24)]
            + [{"label": "16 colours, via 2x", "colors": 16, "cascade": True}])


MONO  = ["#ffffff", "#000000"]
GREY3 = ["#ffffff", "#8b9199", "#000000"]
GREY4 = ["#ffffff", "#9fa5ad", "#4a5058", "#000000"]
GREY6 = ["#ffffff", "#c9ccd1", "#8b9199", "#4a5058", "#22262b", "#000000"]


def handle_stream(req: dict):
    """Commands that report progress. Yields many replies for one request; the
    last one carries "done": true so the client knows to stop reading."""
    if req.get("cmd") == "variants":
        path = req["path"]
        if not os.path.exists(path):
            yield {"ok": False, "error": f"no such file: {path}", "done": True}
            return
        size = int(req.get("size", 48))
        source = Image.open(path)
        if req.get("trim", True):
            source = quantise.trim(source)
        info = quantise.analyse(source)
        yield {"ok": True, "event": {"kind": "analysed", "of": info["kind"],
                                     "saturation": info["saturation"]}}

        for i, spec in enumerate(variant_specs(info["kind"], None)):
            # Cascading means reducing to twice the target first, then
            # halving that. For the threshold path it also thresholds twice,
            # which rounds toward ink and comes out bolder.
            stage = source
            if spec.get("cascade"):
                half = size * 2
                if spec.get("line_art"):
                    stage = quantise.render(
                        quantise.line_art(source, size=half,
                                          coverage=max(0.05, 0.55 - spec["ink_bias"] * 0.5)),
                        spec["palette"]).convert("RGB")
                else:
                    pal2 = quantise.extract_palette(source, spec.get("colors", 16))
                    stage = quantise.render(
                        quantise.quantise(source, size=half, palette=pal2, metric="lab"),
                        pal2).convert("RGB")

            if "colors" in spec:
                pal = quantise.extract_palette(stage, spec["colors"])
                grid = quantise.quantise(stage, size=size, palette=pal, metric="lab")
            else:
                pal = spec["palette"]
                if spec["line_art"]:
                    grid = quantise.line_art(stage, size=size,
                                             coverage=max(0.05, 0.55 - spec["ink_bias"] * 0.5),
                                             grey=spec.get("grey"))
                else:
                    grid = quantise.quantise(stage, size=size, palette=pal,
                                             metric="lab", ink_bias=spec["ink_bias"],
                                             adaptive=spec.get("adaptive", False))
            # Sent one at a time so the picker fills in as they land rather than
            # sitting blank until every variant is done.
            yield {"ok": True, "event": {"kind": "variant", "index": i,
                                         "label": spec["label"], "grid": grid,
                                         "palette": pal}}
        yield {"ok": True, "done": True, "count": len(variant_specs(info["kind"], None))}
        return

    yield handle(req)
    return


def serve() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    if SOCK.exists():
        SOCK.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK))
    srv.listen(8)
    sys.stderr.write(f"nibd listening on {SOCK}\n")
    sys.stderr.flush()

    while True:
        conn, _ = srv.accept()
        try:
            with conn, conn.makefile("rwb") as f:
                for raw in f:
                    line = raw.decode().strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line)
                        if req.get("cmd") == "variants":
                            for reply in handle_stream(req):
                                f.write((json.dumps(reply) + "\n").encode())
                                f.flush()
                            continue
                        reply = handle(req)
                    except Exception as e:  # never die on one bad request
                        traceback.print_exc()
                        reply = {"ok": False, "error": f"{type(e).__name__}: {e}", "done": True}
                    f.write((json.dumps(reply) + "\n").encode())
                    f.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    serve()
