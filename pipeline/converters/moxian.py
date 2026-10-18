#!/usr/bin/env python
"""Moxian EGO-PRO sample session (one annotated MCAP) -> viewer grid recording (site/data/mx_*.json + videos + poster).

Each session is one Foxglove MCAP at a 60 Hz frame index (schema egopro 4.0): three JPEG cameras, per-hand raw tactile
(460 channels), the release's per-patch pressure in newtons, a taxel position map, MANUS-style hand skeletons, Vive
head/wrist poses and Chinese subtask captions. The viewer clock is 30 Hz (every second frame).

    python -I ext/moxian.py --site site ~/data/ext/moxian/raw/Sample\\ Data/X002/X002_00001.annotated.mcap
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path

import numpy as np
from mcap.reader import make_reader

SRC_FPS = 60
STEP = 2                   # viewer clock = every second 60 Hz frame
FPS = SRC_FPS // STEP
RANGE = 48.0               # raw counts drawn as full scale (set from the sampled sessions, see notes)
COLS_RAW = 20              # the 460 channels are a 23 x 20 matrix: rows 0-14 palm, rows 15-22 finger strips (4 columns per finger)
REGION = {"palm": "palm", "thumb_tip": "thumb", "index_tip": "index", "middle_tip": "middle", "ring_tip": "ring", "little_tip": "little"}
PATCH = ["palm", "thumb", "index", "middle", "ring", "pinky"]
LINE_COLS = ["#7f8c8d", "#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#cb4335"]
GRID = 24                  # viewer grid is GRID x GRID per hand
# the release names tasks in Chinese only; these English titles are the catalog's translation
TITLES = {"堆叠碗": "Stack bowls", "插入试管": "Insert test tubes", "折叠衣物": "Fold clothes", "擦拭": "Wipe a surface",
          "倾倒": "Pour", "手内转向": "Reorient an object in hand", "粘扣剥离": "Peel a hook-and-loop strip",
          "剪刀类工具操作": "Use scissors"}
VIDEOS = [("head", "Head camera", 960), ("left", "Left wrist camera", 640), ("right", "Right wrist camera", 640)]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def varint(b: bytes, i: int) -> tuple[int, int]:
    v = s = 0
    while True:
        x = b[i]; i += 1; v |= (x & 0x7F) << s; s += 7
        if x < 0x80:
            return v, i


def jpeg_of(msg: bytes) -> bytes:
    """foxglove.CompressedImage protobuf: field 2 (bytes) is the image."""
    i = 0
    while i < len(msg):
        key, i = varint(msg, i)
        field, wire = key >> 3, key & 7
        if wire == 2:
            n, i = varint(msg, i)
            if field == 2:
                return msg[i:i + n]
            i += n
        elif wire == 0:
            _, i = varint(msg, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError(f"wire type {wire}")
    raise ValueError("no image data")


def layout(points: list[dict], hand: str) -> tuple[np.ndarray, list[str]]:
    """Grid cell (row * GRID + col) for each of the 460 raw channels that point_mapping places (others -1), and its region.

    point_mapping gives every placed channel a position in a normalized hand drawing (palm 14 x 15 on a regular grid, each
    finger a 4 x 8 strip from base to tip, the thumb strip diagonal and all strips overlapping the palm's top rows). The
    viewer keeps the release's rows and columns but draws the strips upright above the palm and the thumb beside it."""
    pts = [p for p in points if p["hand"] == hand]
    idx = np.array([int(p["point_id"].split("_")[1]) - 1 for p in pts])   # point ids are 1-based channel numbers
    xy = np.array([p["position_m"][:2] for p in pts])
    reg = np.array([REGION[p["hand_region"]] for p in pts])
    cell = np.full(460, -1)
    name = [""] * 460
    thumb_x = xy[reg == "thumb", 0].mean()
    thumb_right = thumb_x > xy[reg == "palm", 0].mean()
    fingers = sorted(("index", "middle", "ring", "little"), key=lambda f: xy[reg == f, 0].mean())
    col0 = {f: (0 if thumb_right else 5) + 5 * k for k, f in enumerate(fingers)}
    col0["thumb"] = 20 if thumb_right else 0
    for f in col0:
        m = np.flatnonzero(reg == f)
        rows = idx[m] // COLS_RAW
        assert len(m) == 32 and set(rows) == set(range(15, 23)), f
        for r in range(15, 23):
            k = m[rows == r]
            k = k[np.argsort(xy[k, 0])]
            top = 22 - r + (6 if f == "thumb" else 0)
            for j, q in enumerate(k):
                cell[idx[q]] = top * GRID + col0[f] + j
                name[idx[q]] = f
    m = np.flatnonzero(reg == "palm")
    xs, ys = np.unique(np.round(xy[m, 0], 4)), np.unique(np.round(xy[m, 1], 4))
    assert len(m) == 210 and len(xs) == 14 and len(ys) == 15
    pc0 = 3 if thumb_right else GRID - 3 - 14
    for q in m:
        r = 9 + int(np.searchsorted(ys, round(xy[q, 1], 4)))
        c = pc0 + int(np.searchsorted(xs, round(xy[q, 0], 4)))
        cell[idx[q]] = r * GRID + c
        name[idx[q]] = "palm"
    placed = cell[cell >= 0]
    assert len(placed) == 370 and len(set(placed.tolist())) == 370, "one grid cell per placed channel"
    return cell, name


def hand_panel(raw: np.ndarray, cell: np.ndarray, name: list[str], key: str, title: str) -> dict:
    ch = np.flatnonzero(cell >= 0)
    order = ch[np.argsort(cell[ch])]
    tax = np.clip(np.round(raw[:, order] / RANGE * 255), 0, 255).astype(np.uint8)
    regions = [{"name": f, "cells": [k for k, c in enumerate(order) if name[c] == f]} for f in ("thumb", "index", "middle", "ring", "little", "palm")]
    assert sum(len(r["cells"]) for r in regions) == len(order)
    return {"key": key, "title": title, "rate": FPS, "rows": GRID, "cols": GRID, "cells": b64(cell[order].astype(np.uint16)),
            "tax": b64(tax), "range": RANGE, "unit": "raw counts", "regions": regions,
            "label": "370 taxels · palm 14×15, fingers 4×8"}


def encode(jpegs: list[bytes], out: Path, width: int, rotate: bool) -> None:
    vf = ("hflip,vflip," if rotate else "") + f"scale={width}:-2,format=yuv420p"
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                           "-vf", vf, "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", "-an", str(out)], stdin=subprocess.PIPE)
    for b in jpegs:
        ff.stdin.write(b)
    ff.stdin.close()
    assert ff.wait() == 0, "ffmpeg failed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mcap", type=Path)
    ap.add_argument("--site", type=Path, required=True)
    args = ap.parse_args()
    meta, points, review = {}, None, None
    raw = {"left": {}, "right": {}}
    patch, wrist, img = {}, {"left": {}, "right": {}}, {k: {} for k, _, _ in VIDEOS}
    sizes = {}
    with open(args.mcap.expanduser(), "rb") as f:
        rd = make_reader(f)
        for _, ch, m in rd.iter_messages():
            t = ch.topic
            fr = round(m.log_time * SRC_FPS / 1e9)
            if t.startswith("/meta/"):
                meta[t[6:]] = json.loads(m.data)
            elif t == "/tactile/point_mapping":
                points = json.loads(m.data)["points"]
            elif t.startswith("/tactile/raw/"):
                d = json.loads(m.data)
                assert d["frame_60"] == fr and d["unit"] == "raw"
                raw[d["hand"]][fr] = d["values"]
            elif t == "/tactile/patch_pressure":
                d = json.loads(m.data)
                assert d["unit"] == "newton"
                patch[fr] = d["patches"]
            elif t.startswith("/pose/wrist/"):
                d = json.loads(m.data)
                wrist[t.rsplit("/", 1)[1]][fr] = d["position_m"] if d.get("valid", True) else [np.nan] * 3
            elif t.startswith("/ego_video/") and fr % STEP == 0:
                img[t.rsplit("/", 1)[1]][fr] = jpeg_of(m.data)
        for a in rd.iter_attachments():
            if a.name == "semantic_review.json":
                review = json.loads(a.data)
    block, sess = meta["block"], meta["session"]
    n60 = sess["num_frames_60"]
    for h in raw:
        assert sorted(raw[h]) == list(range(n60)), f"{h}: one tactile row per 60 Hz frame"
    frames = list(range(0, n60, STEP))
    n = len(frames)
    task_zh = block["task_name"]
    vid = f"mx_{sess['session_id']}"
    cn = {h: np.array([raw[h][k] for k in frames], np.float32) for h in raw}

    hands, unplaced = [], {}
    for h, key in (("left", "lh"), ("right", "rh")):
        cell, name = layout(points, h)
        hands.append(hand_panel(cn[h], cell, name, key, f"{h.capitalize()} glove"))
        un = np.flatnonzero(cell < 0)
        live = un[(cn[h][:, un] > 0).any(0)]
        s_un, s_pl = cn[h][:, un].sum(1), cn[h][:, cell >= 0].sum(1)
        unplaced[h] = (len(un), len(live), s_un, float(np.corrcoef(s_un, s_pl)[0, 1]))

    media = args.site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    for key, title, w in VIDEOS:
        js = [img[key][k] for k in frames]
        assert len(js) == n, f"{key}: one image per frame"
        encode(js, media / f"{vid}_{key}.mp4", w, rotate=key == "head")
        hgt = 540 if key == "head" else 480
        videos.append({"key": key, "title": title, "src": f"media/{vid}_{key}.mp4", "src_size": [w, hgt], "fps_src": FPS})
    mid = img["head"][frames[n // 2]]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-c:v", "mjpeg", "-i", "-", "-frames:v", "1",
                    "-vf", "hflip,vflip,scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], input=mid, check=True)

    series = []
    for h, hn in (("left", "Left"), ("right", "Right")):
        lines = [{"name": p, "data": b64(np.array([patch[k][f"{h}_{p}"] for k in frames], np.float32)), "col": LINE_COLS[i]}
                 for i, p in enumerate(PATCH)]
        series.append({"title": f"{hn} glove · patch pressure from the release (N)", "lines": lines,
                       "legendText": "palm, thumb, index, middle, ring, pinky: grey, purple, blue, green, yellow, red"})
    series.append({"title": "Channels with no position in point_mapping · sum (raw counts)",
                   "lines": [{"name": "L", "data": b64(unplaced["left"][2]), "col": "#2e86c1"},
                             {"name": "R", "data": b64(unplaced["right"][2]), "col": "#2e86c1", "dash": True}],
                   "legendText": "left solid, right dashed"})
    nan3 = [np.nan] * 3
    pos = {h: np.array([wrist[h].get(k, nan3) for k in frames], np.float32) for h in wrist}
    series.append({"title": "Wrist position · world frame (m, left solid, right dashed)", "legendText": "x, y, z: blue, green, yellow",
                   "lines": [l for k, a in enumerate("xyz") for l in (
                       {"name": "L " + a, "data": b64(pos["left"][:, k]), "col": ["#2e86c1", "#17a589", "#c99a06"][k]},
                       {"name": "R " + a, "data": b64(pos["right"][:, k]), "col": ["#2e86c1", "#17a589", "#c99a06"][k], "dash": True})]})

    title = TITLES[task_zh]
    steps = [{"start": s["start_time_s"], "end": s["end_time_s"],
              "text": s["type"].replace("_", " ").capitalize() + " · " + s["caption"]} for s in review["subtasks"]]
    dur = n / FPS
    task = {"task": title, "start": 0.0, "end": dur, "steps": steps}
    lu, ll = unplaced["left"][:2], unplaced["right"][:2]
    notes = (
        f"<p>Session {sess['session_id']} (task {block['task_id']}, <span lang=\"zh-CN\">{task_zh}</span>; the English title is "
        f"the catalog's translation). The release puts every stream on one 60 Hz frame index ({n60} frames, "
        f"{sess['duration_s']:.1f} s); the viewer uses every second frame (30 Hz) for touch, poses and the three cameras. "
        f"The head camera is stored upside down and is rotated 180°, as in the provider's Foxglove layout.</p>"
        f"<p>Taxels: <code>/tactile/raw/&lt;hand&gt;</code> holds 460 raw channels per glove, a 23 × 20 matrix. "
        f"<code>/tactile/point_mapping</code> places 370 of them: a 14 × 15 palm and, for each finger, a 4 × 8 strip from "
        f"base to tip (the release calls these regions <code>*_tip</code>). The viewer keeps the release's rows and columns "
        f"and draws the strips upright above the palm with the thumb beside it; the release's own drawing tilts the thumb "
        f"and overlaps the strips with the palm's top rows. Values are raw counts, drawn with {RANGE:.0f} as full scale "
        f"(the release states no full scale or calibration for this stream).</p>"
        f"<p>The other {lu[0]} channels per glove have no position in the map. In this session {lu[1]} (left) and "
        f"{ll[1]} (right) of them read above zero; their sum is plotted (correlation with the sum of the placed taxels: "
        f"left {unplaced['left'][3]:.2f}, right {unplaced['right'][3]:.2f}). "
        f"Patch pressure is the release's own <code>/tactile/patch_pressure</code> in newtons, one value per palm and finger; "
        f"how it is derived from the raw channels is not documented.</p>"
        f"<p>Task steps are the release's subtasks: its English type label, then its Chinese caption. Not shown: the 25-joint "
        f"hand skeletons, head pose, per-hand atomic action labels and camera calibration.</p>")
    item = {"id": vid, "title": title, "label": f"{task_zh} · {block['task_id']}", "sub": f"{dur:.0f} s · {len(steps)} steps",
            "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "task": task, "item": item}
    (args.site / "data").mkdir(parents=True, exist_ok=True)
    p = args.site / "data" / f"{vid}.json"
    p.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    stats = {h: [float(np.percentile(cn[h][:, np.flatnonzero(layout(points, h)[0] >= 0)], q)) for q in (99, 99.5, 99.9, 100)] for h in cn}
    print(json.dumps({**item, "json_kb": p.stat().st_size // 1024, "pct_99_99.5_99.9_max": stats, "unplaced_live": [lu[1], ll[1]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
