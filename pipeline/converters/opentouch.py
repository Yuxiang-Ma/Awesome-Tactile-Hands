#!/usr/bin/env python
"""OpenTouch clip -> viewer grid recording (site/data/ot_*.json, site/media/ot_*_ego.mp4 + poster).

OpenTouch (Song et al. 2025, arXiv 2512.16842) ships one HDF5 per scene from Google Drive. Each file holds clips
data/<demo_XX>/ with the right-hand glove's 16 x 16 electrode readout (`right_pressure`), the Aria RGB frames as JPEG bytes
(`rgb_images_jpeg`), Rokoko hand pose and per-frame timestamps, all already on one 30 Hz frame index. Only the right hand is
instrumented. Per-clip text annotations come from the release's final_annotations/<scene>_merged.csv.

The release states no license for the data, so the converted video is re-hosted for preview with attribution (see the meta
notes). Reads the HDF5 with h5py; run it with an interpreter that has numpy + h5py, e.g.

    python -I ext/opentouch.py --site site --ann ~/data/ext/opentouch/ann/final_annotations \\
        --layout ~/data/ext/opentouch/repo/preprocess/scratch/handLayoutNewest_meshid.json \\
        ~/data/ext/opentouch/dl/eat_mcdonalds.hdf5 demo_00 [demo_XX ...]
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import subprocess
from pathlib import Path

import h5py
import numpy as np

FPS = 30
FULL = 3072.0  # raw reading at rest (the readout saturates there); pressure lowers it, down to 0
ROWS = COLS = 16
# Physical layout = the release's own 16 x 16 channel grid. Its handLayoutNewest_meshid.json (positions per "r-c" channel,
# MANO vertex ids, erasedNodes) shows that this grid already reads as a palmar view of the right hand: rows 0-8 are the four
# fingers, fingertip in row 0, two columns each (little 0-1, ring 3-4, middle 6-7, index 9-10; columns 2, 5, 8 are gaps),
# rows 9-15 x columns 0-10 are the palm (row 9 next to the fingers, row 15 at the wrist), and rows 12-15 x columns 11-15
# are the thumb, running sideways off the palm with its tip in column 15. 72 + 77 + 20 = 169 taxels, as in the paper.
FINGER_COLS = {"thumb": None, "index": (9, 11), "middle": (6, 8), "ring": (3, 5), "little": (0, 2)}


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def region_of(r: int, c: int) -> str | None:
    if r >= 12 and c >= 11:
        return "thumb"
    if r >= 9 and c <= 10:
        return "palm"
    for name, span in FINGER_COLS.items():
        if span and r <= 8 and span[0] <= c < span[1]:
            return name
    return None  # grid position with no taxel


def taxel_cells(layout: Path | None) -> np.ndarray:
    cells = np.array([r * COLS + c for r in range(ROWS) for c in range(COLS) if region_of(r, c)], np.uint16)
    assert len(cells) == 169, len(cells)
    if layout:  # cross-check against the release's layout file: same set of live channels
        d = json.loads(layout.expanduser().read_text())
        erased = set(d["erasedNodes"])
        live = sorted(int(k.split("-")[0]) * COLS + int(k.split("-")[1]) for k in d["positions"] if k not in erased)
        assert live == cells.tolist(), "taxel set differs from handLayoutNewest_meshid.json"
    return cells


def hand(p: np.ndarray, cells: np.ndarray) -> dict:
    flat = p.reshape(len(p), -1)[:, cells].astype(np.float32)
    val = np.clip(FULL - flat, 0, FULL)  # counts below rest: 0 = no load, 3072 = full scale
    tax = np.round(val / FULL * 255).astype(np.uint8)
    r, c = cells // COLS, cells % COLS
    names = [region_of(int(a), int(b)) for a, b in zip(r, c)]
    regions = [{"name": n, "cells": [k for k, m in enumerate(names) if m == n]} for n in ("thumb", "index", "middle", "ring", "little", "palm")]
    assert sum(len(x["cells"]) for x in regions) == len(cells)
    return {"key": "rh", "title": "Right glove", "rate": FPS, "rows": ROWS, "cols": COLS, "cells": b64(cells), "tax": b64(tax),
            "range": FULL, "unit": "counts below rest (3072 − raw)", "regions": regions}


def encode_video(jpegs, out: Path) -> None:
    # the release stores the JPEGs with red and blue exchanged (its own exporter defaults to channel_order="bgr"); swap back
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                           "-vf", "colorchannelmixer=rr=0:rb=1:bb=0:br=1,format=yuv420p", "-c:v", "libx264", "-crf", "28",
                           "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)], stdin=subprocess.PIPE)
    for b in jpegs:
        ff.stdin.write(bytes(b))
    ff.stdin.close()
    assert ff.wait() == 0, "ffmpeg failed"


STOPS = np.array([[22, 35, 51], [20, 87, 104], [33, 169, 174], [107, 218, 162], [241, 227, 112], [255, 130, 78]], np.float32)  # viewer ramp


def tactile_poster(p: np.ndarray, cells: np.ndarray, out: Path, w: int = 240, h: int = 180) -> None:
    """Poster without video: the grid at the frame of largest total pressure, in the viewer's colour ramp."""
    flat = np.clip(FULL - p.reshape(len(p), -1)[:, cells].astype(np.float32), 0, FULL)
    x = flat[int(flat.sum(1).argmax())] / FULL * (len(STOPS) - 1)
    i = np.minimum(len(STOPS) - 2, np.floor(x).astype(int))
    rgb = (STOPS[i] + (STOPS[i + 1] - STOPS[i]) * (x - i)[:, None]).astype(np.uint8)
    img = np.empty((h, w, 3), np.uint8)
    img[:] = (11, 18, 27)
    cs, gap = 9, 2
    x0, y0 = (w - (COLS * (cs + gap) - gap)) // 2, (h - (ROWS * (cs + gap) - gap)) // 2
    for k, c in enumerate(cells.tolist()):
        r, q = divmod(c, COLS)
        img[y0 + r * (cs + gap):y0 + r * (cs + gap) + cs, x0 + q * (cs + gap):x0 + q * (cs + gap) + cs] = rgb[k]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-", "-frames:v", "1",
                    "-q:v", "3", str(out)], input=img.tobytes(), check=True)


def sentence(s: str) -> str:
    return s[:1].upper() + s[1:]


def convert(h5: Path, demo: str, ann: dict, cells: np.ndarray, site: Path, with_video: bool) -> dict:
    scene = h5.stem
    vid = f"ot_{scene}_{demo}"
    with h5py.File(h5, "r") as f:
        g = f["data"][demo]
        ts = g["timestamps"][()]
        n = len(ts)
        p = g["right_pressure"][()]
        wrist = g["right_wrist_pos"][()].astype(np.float32)
        jpegs = g["rgb_images_jpeg"][()]
        w, hgt = (int(g.attrs.get("image_width", 640)), int(g.attrs.get("image_height", 480)))
        labels = g["labels"][0] if "labels" in g else None
    assert p.shape == (n, ROWS, COLS) and len(jpegs) == n and len(wrist) == n, "one row per frame in every stream"
    dt = np.diff(ts) / 1e6
    row = ann.get(f"{scene}::{demo}", {})
    dur = n / FPS

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    H = hand(p, cells)
    videos = []
    if with_video:  # opt-in: only once the data license permits re-hosting or the viewer's owner has approved it
        encode_video(jpegs, media / f"{vid}_ego.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(media / f"{vid}_ego.mp4"), "-frames:v", "1",
                        "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)
        videos = [{"key": "ego", "title": "Egocentric camera · Aria RGB", "src": f"media/{vid}_ego.mp4", "src_size": [w, hgt], "fps_src": FPS}]
    else:
        tactile_poster(p, cells, media / f"{vid}.jpg")

    series = [{"title": "Right wrist position · Rokoko (m, frame as released)",
               "lines": [{"name": a, "data": b64(wrist[:, k]), "col": ["#2e86c1", "#17a589", "#c99a06"][k]} for k, a in enumerate("xyz")]}]

    act, obj = row.get("action", "").strip(), row.get("object_name", "").strip()
    title = sentence(f"{act} ({obj})" if act and obj else act or obj) if act or obj else f"{scene} {demo}"
    task = None
    try:
        on, pk, post = (int(float(row[k])) for k in ("onset_idx", "peak_idx", "post_idx"))
        if 0 <= on <= pk <= post < n and post > on:
            steps = [s for s in ({"start": on / FPS, "end": pk / FPS, "text": "Contact onset to peak (release annotation)"},
                                 {"start": pk / FPS, "end": (post + 1) / FPS, "text": "Peak to post-contact (release annotation)"}) if s["end"] > s["start"]]
            task = {"task": title, "start": on / FPS, "end": (post + 1) / FPS, "steps": steps}
    except (KeyError, ValueError):
        pass

    flags = []
    if labels is not None:
        if labels["low_light"]:
            flags.append("low light")
        if labels["hand_out_of_frame"]:
            flags.append("hand out of frame")
    desc = row.get("description", "").strip()
    notes = (f"<p>Clip <code>{demo}</code> of <code>{scene}.hdf5</code> from the "
             "<a href=\"https://github.com/OpenTouch-MIT/opentouch\">OpenTouch</a> release. Video, glove and pose share the release's "
             f"frame index (timestamps {dt.min():.1f}–{dt.max():.1f} ms apart, about 30 Hz), so one row is one camera frame and no re-timing "
             "is applied. "
             + ("The video is the RGB stream of the Aria glasses as stored in the release (640 × 480 JPEG, with red and blue "
                "exchanged in the file, swapped back here), re-encoded for the browser.</p>" if videos else
                "The egocentric video (Aria glasses RGB, 640 × 480 in the release files) is not hosted here: the release states no "
                "license, so only the tactile and wrist signals are shown. The clip and its video are in the original release.</p>")
             + "<p>Only the right hand wears the tactile glove. Its 16 × 16 electrode grid is drawn as stored: the release's hand layout "
             "file (<code>handLayoutNewest_meshid.json</code>) places these channels on the fingers (fingertips in the top row, two "
             "columns per finger), the palm below and the thumb to the right, a palmar view of the right hand. The 87 grid "
             "crossings that layout marks as erased are not shown; they read non-zero during contact but sit on no taxel. "
             f"The raw reading is {FULL:.0f} at rest and falls with pressure, so the viewer shows {FULL:.0f} − raw, on the full scale "
             "of 0–3072 counts. The release has no force calibration; the paper states a calibrated range of 0.02–50 kPa for the sensing film.</p>"
             + (f"<p>Release annotation ({esc(row.get('environment', ''))}, grip: {esc(row.get('grip_type', ''))}"
                f"{', ' + esc(row.get('model', '')) + '-written' if row.get('model') else ''}): {esc(desc)}</p>" if desc else "")
             + (f"<p>Flagged in the release: {', '.join(flags)}.</p>" if flags else "")
             + "<p>The wrist position is the Rokoko glove's, in the frame the release stores it in. Hand landmarks are in the release "
               "but are not drawn: they are 3-D and not registered to the video here.</p>")
    item = {"id": vid, "title": title, "label": f"{sentence(row.get('environment', '') or scene)} · {scene}",
            "sub": f"{dur:.1f} s · {row.get('grip_type', '').strip() or 'grip not annotated'}", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": [H],
           "series": series, "notes": notes, "item": item}
    if task:
        out["task"] = task
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    return item


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("hdf5", type=Path, help="one scene file of the release, e.g. eat_mcdonalds.hdf5")
    ap.add_argument("demos", nargs="+", help="clip ids under data/, e.g. demo_00")
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--ann", type=Path, required=True, help="the release's final_annotations/ folder")
    ap.add_argument("--video", action="store_true", help="also re-encode the Aria RGB clip into site/media (re-hosting, see above)")
    ap.add_argument("--layout", type=Path, help="handLayoutNewest_meshid.json from the code repo, to cross-check the taxel set")
    args = ap.parse_args()
    h5 = args.hdf5.expanduser()
    cands = sorted(args.ann.expanduser().glob(f"{h5.stem}*_merged.csv"))
    ann = {r["clip_id"]: r for c in cands for r in csv.DictReader(c.open())}
    cells = taxel_cells(args.layout)
    for d in args.demos:
        print(json.dumps(convert(h5, d, ann, cells, args.site, args.video)))


if __name__ == "__main__":
    main()
