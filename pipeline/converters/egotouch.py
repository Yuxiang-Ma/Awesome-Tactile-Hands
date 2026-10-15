#!/usr/bin/env python
"""EgoTouch episode -> viewer grid recording (site/data/eg_*.json + poster).

The videos are not copied: the page plays them from the EgoTouch dataset repo at a pinned revision, so only the converted
tactile and pose signals (a few hundred kB) are hosted here.

    python ext/egotouch.py --site site --rev <sha> ~/data/ext/egotouch/Home/twist_bottle_cap/20260320_140403_874
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path

import numpy as np

REPO = "zhouzhoujy/EgoTouch"
FPS = 30
# finger column blocks of the published 21 x 21 grid; the left hand has its thumb on the right, the right hand is mirrored
BLOCKS = {"lh": {"thumb": (17, 20), "index": (13, 16), "middle": (9, 12), "ring": (5, 8), "little": (1, 4)},
          "rh": {"thumb": (1, 4), "index": (5, 8), "middle": (9, 12), "ring": (13, 16), "little": (17, 20)}}
PALM_ROW = 13


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def hand(z, side: str, key: str, n: int) -> dict:
    g = z[f"{side}_pressure_grid"][:n]
    rows, cols = g.shape[1:]
    mask = ~np.isnan(g).all(axis=0)
    cells = np.flatnonzero(mask.ravel()).astype(np.uint16)
    vals = np.nan_to_num(g.reshape(len(g), -1)[:, cells], nan=0.0)
    tax = np.clip(np.round(vals * 255), 0, 255).astype(np.uint8)
    r, c = cells // cols, cells % cols
    regions = [{"name": f, "cells": np.flatnonzero((r < PALM_ROW) & (c >= a) & (c < b)).tolist()} for f, (a, b) in BLOCKS[key].items()]
    regions.append({"name": "palm", "cells": np.flatnonzero(r >= PALM_ROW).tolist()})
    assert sum(len(x["cells"]) for x in regions) == len(cells), "every taxel belongs to exactly one region"
    base = bool(z[f"baseline_corrected_{side}"])
    return {"key": key, "title": f"{side.capitalize()} glove", "rate": FPS, "rows": int(rows), "cols": int(cols),
            "cells": b64(cells), "tax": b64(tax), "range": float(z["tactile_max"]), "regions": regions,
            "unit": "raw counts", "baseline_corrected": base}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", type=Path, help="local copy of <scene>/<task>/<stamp>")
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--rev", required=True, help="dataset commit the video URLs are pinned to")
    args = ap.parse_args()
    ep = args.episode.expanduser()
    rel = "/".join(ep.parts[-3:])
    scene, task, stamp = ep.parts[-3:]
    vid = f"eg_{task}_{stamp}"
    z = np.load(ep / "pressure_grids.npz")
    jq = jsonl(ep / "jq_pressure.json")
    n = int(z["num_frames"])
    assert [j["frame_index"] for j in jq] == list(range(n)), "one tactile row per video frame"
    vive = jsonl(ep / "vive_poses.json")[:n]

    src = lambda name: f"https://huggingface.co/datasets/{REPO}/resolve/{args.rev}/{rel}/{name}"
    videos = [{"key": "chest", "title": "Chest camera", "src": src("chest.mp4"), "src_size": [640, 480], "fps_src": FPS},
              {"key": "left", "title": "Left wrist camera", "src": src("left.mp4"), "src_size": [640, 480], "fps_src": FPS},
              {"key": "right", "title": "Right wrist camera", "src": src("right.mp4"), "src_size": [640, 480], "fps_src": FPS}]
    hands = [hand(z, "left", "lh", n), hand(z, "right", "rh", n)]

    quat = {h: np.array([j[f"quat_{h}"] for j in jq], np.float32) for h in ("left", "right")}
    # some episodes have no tracker poses at all, others drop single frames: missing samples stay NaN (gaps in the plot)
    nan3 = [np.nan] * 3
    pos = {h: np.array([v.get("poses", {}).get(f"{h}_wrist", {}).get("trans", nan3) for v in vive] + [nan3] * (n - len(vive)), np.float32)
           for h in ("left", "right")}
    lines_q = [l for k, a in enumerate("wxyz") for l in (
        {"name": "L " + a, "data": b64(quat["left"][:, k]), "col": ["#8e44ad", "#2e86c1", "#17a589", "#c99a06"][k]},
        {"name": "R " + a, "data": b64(quat["right"][:, k]), "col": ["#8e44ad", "#2e86c1", "#17a589", "#c99a06"][k], "dash": True})]
    lines_p = [l for k, a in enumerate("xyz") for l in (
        {"name": "L " + a, "data": b64(pos["left"][:, k]), "col": ["#2e86c1", "#17a589", "#c99a06"][k]},
        {"name": "R " + a, "data": b64(pos["right"][:, k]), "col": ["#2e86c1", "#17a589", "#c99a06"][k], "dash": True})]
    has_vive = bool(np.isfinite(pos["left"]).any() or np.isfinite(pos["right"]).any())
    series = ([{"title": "Wrist position · Vive trackers (m, left solid, right dashed)", "lines": lines_p, "legendText": "x, y, z: blue, green, yellow"}] if has_vive else []) + [
              {"title": "Glove orientation · quaternion (left solid, right dashed)", "lines": lines_q, "fixed": [-1, 1],
               "legendText": "w, x, y, z: purple, blue, green, yellow"}]
    unc = [h["title"].split()[0].lower() for h in hands if not h["baseline_corrected"]]
    notes = (f"<p>One row per video frame: the three cameras and both gloves share the 30 Hz frame index of the release, so no re-timing is applied. "
             f"Videos stream from the <a href=\"https://huggingface.co/datasets/{REPO}\">EgoTouch</a> dataset repo (revision {args.rev[:7]}); only the tactile "
             f"and pose signals are converted here.</p><p>Taxels are drawn from the release's <code>pressure_grids.npz</code>, which places the 256 glove "
             f"channels on a 21 × 21 layout (left hand thumb on the right, right hand mirrored, as in the release's own visualization) and divides by "
             f"<code>tactile_max</code> = {hands[0]['range']:.0f}. Values are shown back in raw counts. Regions follow the finger columns of that layout; the "
             f"palm is everything below the fingers. "
             + (f"The {' and '.join(unc)} glove is marked as not baseline-corrected in this file, so a constant offset remains. " if unc else "")
             + ("Wrist positions come from the Vive trackers, " if has_vive else "This episode has no Vive tracker poses; ")
             + "orientation comes from the glove IMUs.</p>")
    dur = n / FPS
    title = task.replace("_", " ").capitalize().replace(" t shirt", " T-shirt")
    item = {"id": vid, "title": title, "label": f"{scene} · {stamp[:8]}",
            "sub": f"{dur:.0f} s", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (args.site / "data").mkdir(parents=True, exist_ok=True)
    (args.site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    (args.site / "media").mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(ep / "chest.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(args.site / "media" / f"{vid}.jpg")], check=True)
    print(json.dumps(item))


if __name__ == "__main__":
    main()
