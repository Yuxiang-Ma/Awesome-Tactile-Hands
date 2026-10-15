#!/usr/bin/env python
"""EgoTactile episode -> viewer grid recording (site/data/et_*.json, site/media/et_*.jpg and et_*_ego.mp4).

The released videos are MPEG-4 Part 2 (not playable in browsers), so the egocentric video is transcoded to H.264 into
site/media. EgoTactile is CC BY-NC 4.0, which allows redistribution with attribution; the notes and the rail entry say so.

    python ext/egotactile.py --site site --rev <sha> ~/data/ext/egotactile/<dl>/Raw_data/gloved_hand/p003/Mug/repeat0000
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from pathlib import Path

import numpy as np

REPO = "HustleHard/EgoTactile"
CODE = "https://github.com/Russell-Zeng/EgoTactile"
CODE_REV = "569cad3"  # commit of the code repo the layout below was copied from
FPS = 15
RANGE = 150.0  # N, fixed for all episodes; above every pad reading in the sampled episodes (max 135) and below the paper's 200 N cap

# Taxel layout of the glove, copied verbatim from the release's own renderer (scripts/raw_to_training.py,
# LEFT_/RIGHT_MASK_INDEXED): a 17 x 19 canvas, value = 1-based index into sensor_256, 0 = no taxel. Fingertip pads
# (4 x 3) on top, one strip sensor per finger drawn over 6 cells (the renderer divides it by 6), palm (72) below.
# The right hand has its thumb on the left; the left hand is mirrored.
_RH = """
240 239 238 0 237 236 235 0 234 233 232 0 231 230 229 0 228 227 226
256 255 254 0 253 252 251 0 250 249 248 0 247 246 245 0 244 243 242
16 15 14 0 13 12 11 0 10 9 8 0 7 6 5 0 4 3 2
32 31 30 0 29 28 27 0 26 25 24 0 23 22 21 0 20 19 18
0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
47 0 0 0 0 44 0 0 0 41 0 0 0 38 0 0 0 35 0
47 0 0 0 0 44 0 0 0 41 0 0 0 38 0 0 0 35 0
0 47 0 0 0 44 0 0 0 41 0 0 0 38 0 0 0 35 0
0 47 0 0 0 44 0 0 0 41 0 0 0 38 0 0 0 35 0
0 0 47 0 0 44 0 0 0 41 0 0 0 38 0 0 0 35 0
0 0 47 0 0 44 0 0 0 41 0 0 0 38 0 0 0 35 0
0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
0 0 0 0 0 0 0 61 60 59 58 57 56 55 54 53 52 51 50
0 0 0 0 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66
0 0 0 0 96 95 94 93 92 91 90 89 88 87 86 85 84 83 82
0 0 0 0 112 111 110 109 108 107 106 105 104 103 102 101 100 99 98
0 0 0 0 128 127 126 125 124 123 122 121 120 119 118 117 116 115 114
"""
_LH = """
31 30 29 0 28 27 26 0 25 24 23 0 22 21 20 0 19 18 17
15 14 13 0 12 11 10 0 9 8 7 0 6 5 4 0 3 2 1
255 254 253 0 252 251 250 0 249 248 247 0 246 245 244 0 243 242 241
239 238 237 0 236 235 234 0 233 232 231 0 230 229 228 0 227 226 225
0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
0 222 0 0 0 219 0 0 0 216 0 0 0 213 0 0 0 0 210
0 222 0 0 0 219 0 0 0 216 0 0 0 213 0 0 0 0 210
0 222 0 0 0 219 0 0 0 216 0 0 0 213 0 0 0 210 0
0 222 0 0 0 219 0 0 0 216 0 0 0 213 0 0 0 210 0
0 222 0 0 0 219 0 0 0 216 0 0 0 213 0 0 210 0 0
0 222 0 0 0 219 0 0 0 216 0 0 0 213 0 0 210 0 0
0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
207 206 205 204 203 202 201 200 199 198 197 196 0 0 0 0 0 0 0
191 190 189 188 187 186 185 184 183 182 181 180 179 178 177 0 0 0 0
175 174 173 172 171 170 169 168 167 166 165 164 163 162 161 0 0 0 0
159 158 157 156 155 154 153 152 151 150 149 148 147 146 145 0 0 0 0
143 142 141 140 139 138 137 136 135 134 133 132 131 130 129 0 0 0 0
"""
MASK = {"RH": np.array([[int(v) for v in r.split()] for r in _RH.strip().splitlines()]),
        "LH": np.array([[int(v) for v in r.split()] for r in _LH.strip().splitlines()])}
# finger assignment of the 1-based channels (fingertip pad + strip), from the release's scripts/denoise.py
FINGERS = {
    "RH": {"thumb": [240, 239, 238, 256, 255, 254, 16, 15, 14, 32, 31, 30, 47], "index": [237, 236, 235, 253, 252, 251, 13, 12, 11, 29, 28, 27, 44],
           "middle": [234, 233, 232, 250, 249, 248, 10, 9, 8, 26, 25, 24, 41], "ring": [231, 230, 229, 247, 246, 245, 7, 6, 5, 23, 22, 21, 38],
           "little": [228, 227, 226, 244, 243, 242, 4, 3, 2, 20, 19, 18, 35]},
    "LH": {"thumb": [19, 18, 17, 3, 2, 1, 243, 242, 241, 227, 226, 225, 210], "index": [22, 21, 20, 6, 5, 4, 246, 245, 244, 230, 229, 228, 213],
           "middle": [25, 24, 23, 9, 8, 7, 249, 248, 247, 233, 232, 231, 216], "ring": [28, 27, 26, 12, 11, 10, 252, 251, 250, 236, 235, 234, 219],
           "little": [31, 30, 29, 15, 14, 13, 255, 254, 253, 239, 238, 237, 222]}}
STRIPS = {"RH": {47, 44, 41, 38, 35}, "LH": {222, 219, 216, 213, 210}}


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def pretty(obj: str) -> str:
    """'PowerBank-20000mAh' -> 'power bank (20000mAh)', 'KidsBasketball' -> 'kids basketball'."""
    head, *rest = obj.split("-")
    words = " ".join(re.findall(r"[A-Z][a-z]*|[a-z]+|\d+\w*", head)).lower()
    return words + (f" ({', '.join(rest)})" if rest else "")


def hand(sensor: np.ndarray, side: str) -> tuple[dict, int]:
    """sensor: n x 256 raw readings of one glove -> grid hand dict, and the number of clipped values."""
    m = MASK[side]
    rows, cols = m.shape
    cells = np.flatnonzero(m.ravel() > 0).astype(np.uint16)  # 162 drawn positions, row-major
    ch = m.ravel()[cells]  # 1-based channel behind each position (strip channels repeat 6 times)
    div = np.array([6.0 if c in STRIPS[side] else 1.0 for c in ch])
    vals = sensor[:, ch - 1] / div  # a strip's reading is spread evenly over its 6 cells, as the release's renderer does
    clipped = int((vals > RANGE).sum())
    tax = np.clip(np.round(vals / RANGE * 255), 0, 255).astype(np.uint8)
    regions = [{"name": f, "cells": np.flatnonzero(np.isin(ch, chans)).tolist()} for f, chans in FINGERS[side].items()]
    regions = sorted(regions, key=lambda r: ["thumb", "index", "middle", "ring", "little"].index(r["name"]))
    used = set(sum((r["cells"] for r in regions), []))
    regions.append({"name": "palm", "cells": [k for k in range(len(cells)) if k not in used]})
    assert sum(len(r["cells"]) for r in regions) == len(cells) == 162 and len(regions[-1]["cells"]) == 72
    key = "rh" if side == "RH" else "lh"
    return ({"key": key, "title": f"{'Right' if side == 'RH' else 'Left'} glove", "rate": FPS, "rows": int(rows), "cols": int(cols),
             "cells": b64(cells), "tax": b64(tax), "range": RANGE, "unit": "N", "regions": regions}, clipped)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", type=Path, help="local copy of Raw_data/<subset>/<pid>/<object>/<repeat>")
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--rev", required=True, help="dataset commit the episode was downloaded at")
    ap.add_argument("--object-info", type=Path, help="Raw_data/object_info.json (category, weight, material)")
    args = ap.parse_args()
    ep = args.episode.expanduser()
    subset, pid, obj, rep = ep.parts[-4:]
    vid = f"et_{subset.split('_')[0]}_{pid}_{obj.lower()}_r{int(rep.removeprefix('repeat'))}"
    recs = json.loads((ep / "data.json").read_text())
    n = len(recs)
    assert [r["frame_id"] for r in recs] == list(range(n)), "one record per 15 Hz tick"
    nf = int(subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries", "stream=nb_read_packets",
                             "-of", "csv=p=0", str(ep / "video.mp4")], capture_output=True, text=True, check=True).stdout.strip())
    assert nf == n, f"video has {nf} frames, data.json {n} records"
    sides = [s for s in ("LH", "RH") if any(s in r for r in recs)]
    hands, clipped, anomalies = [], 0, set()
    for s in sides:
        assert all(s in r for r in recs), f"{s} missing in some records"
        S = np.array([r[s]["sensor_256"] for r in recs], np.float64)
        h, c = hand(S, s)
        hands.append(h)
        clipped += c
        anomalies |= {r[s]["anomaly"] for r in recs} - {"none"}
    # timing of the held glove sample relative to the video frame of the same tick
    lag = np.array([1000 * (r[sides[0]]["timestamp"] - r["camera_timestamp"]) for r in recs], np.float32)

    # video: MPEG-4 Part 2 in the release -> H.264, 960 px wide, same 15 fps frame sequence
    (args.site / "media").mkdir(parents=True, exist_ok=True)
    mp4 = args.site / "media" / f"{vid}_ego.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ep / "video.mp4"), "-vf", "scale=960:-2", "-c:v", "libx264", "-crf", "28",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    dur = n / FPS
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(ep / "video.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(args.site / "media" / f"{vid}.jpg")], check=True)
    videos = [{"key": "ego", "title": "Egocentric camera" + (" (bare hand in view)" if subset == "bare_hand" else ""),
               "src": f"media/{vid}_ego.mp4", "src_size": [1280, 720], "fps_src": FPS}]
    series = [{"title": "Glove sample timing · glove timestamp minus video frame timestamp (ms)",
               "lines": [{"name": "glove − frame", "data": b64(lag), "col": "#7f8c8d"}]}]

    info = json.loads(args.object_info.read_text()).get(obj, {}) if args.object_info else {}
    name = pretty(obj)
    title = f"Pick up {name}"
    meta = [info.get("category"), f"{info['weight_g']} g" if "weight_g" in info else None, (info.get("surface_material") or "").replace("_", " ") or None]
    src_rel = f"Raw_data/{subset}/{pid}/{obj}/{rep}"
    bare = ("<p>Bare-hand subset: the hand in the video is bare. Per the release, a gloved hand performs a synchronized grasp of the "
            "same object off camera (metronome-guided), and its readings are the pressure reference shown here, so contact timing can "
            "differ from the video by about 0.1 s (the paper reports mean onset/release gaps of 105/118 ms in a dual-glove check).</p>"
            if subset == "bare_hand" else "")
    notes = (f"<p>EgoTactile (Zeng et al., arXiv 2606.09243), CC BY-NC 4.0, episode <code>{src_rel}</code> at dataset revision "
             f"{args.rev[:7]}. The video is the release's egocentric camera (1280 × 720, 15 fps, MPEG-4 Part 2), re-encoded to H.264 at "
             f"960 px for the browser; nothing else was changed.</p>"
             f"<p>One row per video frame: the release writes one record per tick of a 15 Hz master clock, holding the latest video frame and "
             f"the latest glove sample (the paper gives the glove rate as about 17 Hz), so frame <i>i</i> and record <i>i</i> are shown together "
             f"without re-timing. The bottom plot shows how far the held glove sample is from the frame on each tick.</p>"
             f"<p>The glove reports 256 channels per hand, of which 137 are wired. The layout is the release's own "
             f"(<code>scripts/raw_to_training.py</code> in <a href=\"{CODE}\">the code repo</a>, commit {CODE_REV}), and matches the release's "
             f"rendered visualization: a 4 × 3 pad per fingertip on top, one strip sensor along each finger drawn as 6 cells, and a 72-taxel palm "
             f"below, which gives the 162 sensing locations the paper counts. As in the release's renderer, a strip's reading is divided evenly "
             f"over its 6 cells, so per-finger sums add the strip once. Regions follow the release's finger assignment "
             f"(<code>scripts/denoise.py</code>). The right hand has its thumb on the left, as in the release's figure.</p>"
             f"<p>Values are the raw readings in N (the paper: 0–350 N range; it normalizes with a 5 N noise floor and a 200 N cap). No "
             f"thresholding or the release's contact denoising is applied, so small readings on untouched taxels remain. Colours run to "
             f"{RANGE:.0f} N" + (f"; {clipped} cell values above that were clipped" if clipped else "") + ". "
             + (f"Records flagged by the release: {', '.join(sorted(anomalies))}. " if anomalies else "")
             + "Only the gloved hand is recorded; participants wore the glove on the grasping (right) hand.</p>" + bare)
    item = {"id": vid, "title": title, "label": f"{subset.replace('_', '-')} · {pid}",
            "sub": " · ".join([f"{dur:.0f} s"] + [m for m in meta if m]), "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (args.site / "data").mkdir(parents=True, exist_ok=True)
    (args.site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(item))


if __name__ == "__main__":
    main()
