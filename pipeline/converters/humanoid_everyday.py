#!/usr/bin/env python
"""Humanoid Everyday episode -> viewer grid recording (site/data/hu_*.json + poster).

Humanoid Everyday (USC-PSI-Lab/humanoid-everyday, LeRobot v2.1, Apache-2.0 on the dataset card) stores one parquet per
episode with the depth image and the LiDAR cloud inside it (~100 MB). `fetch` range-reads only the small columns of the
requested episodes (tactile, joints, IMU, odometry, actions) at a pinned revision and downloads the episode's egocentric
mp4 for the poster; `convert` turns one fetched episode into the viewer format. The video is not copied: the page plays the
release's own H.264 mp4 from the dataset repo at the pinned revision.

    python -I ext/humanoid_everyday.py fetch ~/data/ext/humanoid_everyday/eps 3422 8208      # needs pyarrow + huggingface_hub
    python -I ext/humanoid_everyday.py convert --site site ~/data/ext/humanoid_everyday/eps/ep003422  # needs pyarrow, numpy, ffmpeg

Tactile (G1 episodes only). Each Unitree Dex3-1 hand has 9 pressure sensors (3 fingertips, 3 finger pads, 3 palm pads);
the robot reports 12 values per sensor (`press_sensor_state[i].pressure[12]`, 30000 = no reading). The release's
`observation.tactile.values` (18, 4) is NOT that array. The recording code of the release (Humanoid-Everyday teleop,
commit 9611546, teleop/master.py + teleop/worker.py) writes the 13 odometry values and then the 216 pressure values
(left hand 9 x 12, then right hand) into shared memory, but reads the pressure block starting where the odometry starts,
i.e. 13 values early. It then reshapes those 216 values to 18 rows of 12 and keeps, per row, indices [0, 2, 9, 11]
("type A", 4 values) or [3, 6, 8] ("type B", 3 values, NaN-padded) according to which positions are not 0/30000. So
release row k (sensor_id k), kept index i is pressure value p = 12 (k - 1) + i - 13 of the true left+right array:
hand = p // 108, sensor = (p % 108) // 12, element = p % 12, and p < 0 is odometry. `unshift` undoes this per frame.
The result is consistent in every sampled episode: the recovered elements are exactly Unitree's per-sensor sets (A = 0, 2,
9, 11 on the pads and palm, B = 3, 6, 8 on the fingertips), all other recovered elements are 30000. 22 of the 66 sensor
elements survive (12 left, 10 right); the right hand's last two palm sensors fall off the end of the shifted block.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np

REPO = "USC-PSI-Lab/humanoid-everyday"
REV = "71f6210e91c2a7e8b8e4d47db0147444a1a0640e"
FPS = 30
COLS = ["observation.tactile.values", "observation.tactile.sensor_id", "observation.hand_joints", "observation.arm_joints",
        "observation.imu.rpy", "observation.odometry.position", "observation.odometry.quat", "action", "timestamp",
        "frame_index", "episode_index", "task_index"]
INVALID = 30000.0

# Dex3-1 press_sensor_state order per hand (thumb base, thumb tip, middle base, middle tip, index base, index tip, palm 0-2)
# and the element indices that carry readings on each sensor type. The order is the enum in i2ca/prometheus-vla
# lerobot-ext/robot/unitree_g1/g1_utils.py (Dex3_1_*_PressureTemperatureSensors, with the same per-type index lists as the
# release's recording code); Unitree's own sensor-map figure could not be read. The data agree with it: sensors 1, 3, 5
# are the only ones whose readings sit at the type-B indices.
SENSORS = [("thumb", "pad"), ("thumb", "tip"), ("middle", "pad"), ("middle", "tip"), ("index", "pad"), ("index", "tip"),
           ("palm", "palm 1"), ("palm", "palm 2"), ("palm", "palm 3")]
TYPE_A, TYPE_B = [0, 2, 9, 11], [3, 6, 8]
ELEMS = [TYPE_B if part == "tip" else TYPE_A for _, part in SENSORS]
# schematic hand, right hand seen from the palm (thumb on the left, as in the other collections); left hand mirrored.
# top-left (row, col) of each sensor block; pads and palm sensors are 2 x 2 (elements 0, 2 / 9, 11), fingertips 3 x 1
# (elements 3, 6, 8 top to bottom). The element order inside a block is the index order, not a documented position.
ORIGIN = {("thumb", "tip"): (2, 0), ("thumb", "pad"): (6, 0), ("index", "tip"): (0, 3), ("index", "pad"): (4, 3),
          ("middle", "tip"): (0, 6), ("middle", "pad"): (4, 6), ("palm", "palm 1"): (9, 0), ("palm", "palm 2"): (9, 3),
          ("palm", "palm 3"): (9, 6)}
ROWS, GCOLS = 11, 8
REGIONS = ["thumb", "index", "middle", "palm"]
JOINTS = ["thumb rotation", "thumb lower", "thumb upper", "middle lower", "middle upper", "index lower", "index upper"]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def url(path: str) -> str:
    return f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/{path}"


def paths(e: int) -> tuple[str, str]:
    return (f"data/chunk-{e // 1000:03d}/episode_{e:06d}.parquet", f"videos/chunk-{e // 1000:03d}/egocentric/episode_{e:06d}.mp4")


# ---------------------------------------------------------------- fetch (pyarrow + huggingface_hub)
def fetch(root: Path, eps: list[int]) -> None:
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem, hf_hub_download
    fs = HfFileSystem()
    for f in ("meta/tasks.jsonl", "meta/episodes.jsonl", "meta/info.json"):
        if not (root / f).exists():
            hf_hub_download(REPO, f, repo_type="dataset", revision=REV, local_dir=root)
    for e in eps:
        out = root / f"ep{e:06d}"
        out.mkdir(parents=True, exist_ok=True)
        data, video = paths(e)
        if not (out / "cols.parquet").exists():
            with fs.open(f"datasets/{REPO}@{REV}/{data}", "rb", block_size=1 << 20) as fh:
                t = pq.ParquetFile(fh).read(columns=COLS)
            pq.write_table(t, out / "cols.parquet")
        if not (out / "egocentric.mp4").exists():
            p = hf_hub_download(REPO, video, repo_type="dataset", revision=REV, local_dir=root / "dl")
            Path(p).rename(out / "egocentric.mp4")
        print(e, "fetched", file=sys.stderr)


# ---------------------------------------------------------------- convert (pyarrow + numpy + ffmpeg)
def unshift(values: list, ids: list) -> np.ndarray:
    """Per-frame release rows -> (n, 2, 9, 12) true pressure array, NaN where the release kept nothing (or 30000)."""
    n = len(values)
    out = np.full((n, 2, 9, 12), np.nan, np.float64)
    for f, (rows, sid) in enumerate(zip(values, ids)):
        for row, k in zip(rows, sid):
            typ_b = row[3] is None or np.isnan(row[3])
            for c, i in enumerate(TYPE_B if typ_b else TYPE_A):
                p = 12 * (k - 1) + i - 13
                if p < 0:
                    continue                      # odometry values, not pressure
                h, s, el = p // 108, (p % 108) // 12, p % 12
                v = row[c]
                if v is not None and v != INVALID and np.isfinite(v):
                    assert el in ELEMS[s], (f, k, i, h, s, el, v)   # a reading outside the sensor's own element set
                    out[f, h, s, el] = v
    return out


def hand(delta: np.ndarray, live: list[tuple[int, int]], key: str, rng: float) -> dict:
    """delta: (n, 9, 12) pressure above rest of one hand; live: (sensor, element) slots that carry data."""
    mirror = key == "lh"
    pos = lambda s, el: (lambda r0, c0: (r0 + (ELEMS[s].index(el) // 2 if len(ELEMS[s]) == 4 else ELEMS[s].index(el)),
                                         c0 + (ELEMS[s].index(el) % 2 if len(ELEMS[s]) == 4 else 0)))(*ORIGIN[SENSORS[s]])
    flat = lambda rc: rc[0] * GCOLS + (GCOLS - 1 - rc[1] if mirror else rc[1])
    order = sorted(live, key=lambda x: (REGIONS.index(SENSORS[x[0]][0]), x[0], ELEMS[x[0]].index(x[1])))
    cells = np.array([flat(pos(s, el)) for s, el in order], np.uint16)
    inactive = sorted(flat(pos(s, el)) for s in range(9) for el in ELEMS[s] if (s, el) not in live)
    vals = np.stack([delta[:, s, el] for s, el in order], axis=1)
    tax = np.clip(np.round(np.nan_to_num(vals, nan=0.0) / rng * 255), 0, 255).astype(np.uint8)
    regions = [{"name": g, "cells": [q for q, (s, _) in enumerate(order) if SENSORS[s][0] == g]} for g in REGIONS]
    side = "Left" if key == "lh" else "Right"
    return {"key": key, "title": f"{side} hand", "rate": FPS, "rows": ROWS, "cols": GCOLS, "cells": b64(cells), "tax": b64(tax),
            "range": rng, "unit": "raw above rest (unit not stated, ≈ Pa)", "regions": regions, "inactive": inactive,
            "label": f"9 sensors · {len(order)} of 33 readings recorded"}


def nice_ceil(x: float) -> float:
    m = 10 ** np.floor(np.log10(x))
    return float(min(k * m for k in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if k * m >= x))


def convert(ep: Path, site: Path, meta: Path) -> None:
    import pyarrow.parquet as pq
    t = pq.read_table(ep / "cols.parquet").to_pydict()
    e = int(t["episode_index"][0])
    n = len(t["timestamp"])
    assert t["frame_index"] == list(range(n)), "complete episode"
    assert np.allclose(t["timestamp"], np.arange(n) / FPS, atol=2e-3), "one row per 30 Hz frame"
    tasks = {r["task_index"]: r for r in map(json.loads, (meta / "tasks.jsonl").read_text().splitlines()) if r}
    task = tasks[t["task_index"][0]]
    nfr = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_frames", "-of", "csv=p=0", str(ep / "egocentric.mp4")],
                             capture_output=True, text=True, check=True).stdout.strip())
    assert nfr == n, (nfr, n)

    P = unshift(t["observation.tactile.values"], t["observation.tactile.sensor_id"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # elements the release never recorded are all-NaN
        rest = np.nanmedian(P[:FPS], axis=0)                    # per element, first second
    delta = P - rest
    live = {h: [(s, el) for s in range(9) for el in ELEMS[s] if np.isfinite(P[:, h, s, el]).mean() > 0.99] for h in (0, 1)}
    pos_d = np.clip(np.nan_to_num(delta, nan=0.0), 0, None)
    peak = pos_d.reshape(n, -1).max(axis=1)
    rng = max(200.0, nice_ceil(float(np.percentile(peak, 99.5))))
    hands = [hand(delta[:, 0], live[0], "lh", rng), hand(delta[:, 1], live[1], "rh", rng)]

    fcol = {"thumb": "#8e44ad", "index": "#2e86c1", "middle": "#17a589", "palm": "#7f8c8d"}
    series = []
    for h, side in enumerate(("Left", "Right")):
        lines = []
        for s, (g, part) in enumerate(SENSORS):
            els = [el for el in ELEMS[s] if (s, el) in live[h]]
            if not els:
                continue
            v = np.nansum(np.stack([delta[:, h, s, el] for el in els], 1), axis=1).astype(np.float32)
            name = f"{g} {part}" if g != "palm" else part
            lines.append({"name": name, "data": b64(v), "col": fcol[g], "dash": part == "pad"})
        series.append({"title": f"{side} hand · per sensor, raw above rest (sum of recorded readings; tips solid, pads dashed)",
                       "lines": lines})
    hj = np.array(t["observation.hand_joints"], np.float32)
    assert hj.shape == (n, 14)
    jc = ["#8e44ad", "#a569bd", "#d2b4de", "#17a589", "#76d7c4", "#2e86c1", "#85c1e9"]
    for h, side in enumerate(("Left", "Right")):
        series.append({"title": f"{side} hand · Dex3-1 joint angles (rad)",
                       "lines": [{"name": j, "data": b64(hj[:, 7 * h + k]), "col": jc[k]} for k, j in enumerate(JOINTS)]})

    vid = f"hu_{e}"
    data, video = paths(e)
    videos = [{"key": "egocentric", "title": "Head camera (RealSense D435, color)", "src": url(video), "src_size": [640, 480],
               "fps_src": FPS}]
    dur = n / FPS
    tpk = float(np.argmax(pos_d[:, :, :, :].reshape(n, -1).sum(axis=1)) / FPS)
    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{tpk:.2f}", "-i", str(ep / "egocentric.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)

    nl, nr = len(live[0]), len(live[1])
    notes = (f"<p>One row per frame of the release's 30 Hz recording: the head-camera video (played from the "
             f"<a href=\"https://huggingface.co/datasets/{REPO}\">Humanoid Everyday</a> repo, revision {REV[:7]}), the tactile values "
             f"and the joints share the frame index, so no re-timing is applied. Task description from the release: "
             f"<i>{task['description']}</i></p>"
             f"<p>Tactile: each Unitree Dex3-1 hand has 9 pressure sensors (a 3-reading fingertip and a 4-reading pad on the thumb, "
             f"index and middle finger, and three 4-reading palm pads; 33 readings per hand). The release's "
             f"<code>observation.tactile.values</code> is shifted by 13 values: the recording code read the pressure block from where "
             f"the odometry starts, so release sensor 1 and the first value of sensor 2 hold odometry, and every other kept value "
             f"belongs to a different sensor than its <code>sensor_id</code> says. This viewer undoes that shift (index arithmetic "
             f"from the release's own recording code, checked frame by frame: every recovered value lands on a reading position of "
             f"its true sensor). Only {nl} left and {nr} right readings survive; the hollow squares are the readings the release "
             f"does not contain (the recording kept the wrong positions of the 12-value rows, and the right hand's palm 2 and 3 fall "
             f"off the end). Which sensor sits on which finger follows the Dex3-1 sensor order thumb pad, thumb tip, middle pad, "
             f"middle tip, index pad, index tip, palm 1-3 as listed in third-party G1 code (Unitree's sensor-map figure could not be "
             f"read); the data agree with it, as sensors 2, 4 and 6 are the only ones with fingertip-type readings. The layout is a "
             f"schematic hand (fingers in a row, thumb lower on the outside, palm pads below, left hand mirrored); the order of "
             f"readings inside a block is their index order, not a documented position, and the palm pads' arrangement is not "
             f"documented. Left and right follow the recording code (the left hand's 9 sensors first) and agree with the hand "
             f"joint angles and the video in the one-handed episodes checked (3422, 8208, 8174; the task description of 8174 names "
             f"the left hand, but the video and joints show the right). With a third of the readings recorded, a hand that visibly "
             f"holds an object can still show no change.</p>"
             f"<p>Values are the raw readings minus each reading's median over the first second (rest); raw readings sit near "
             f"1.01 × 10<sup>5</sup> and are probably absolute pressure in Pa, but the release does not state a unit. The colour "
             f"scale ends at {rng:g} (the episode's 99.5th percentile of the largest reading above rest, rounded up), so it differs "
             f"between episodes. Negative changes are shown as 0 in the grid and kept in the per-sensor plots.</p>"
             f"<p>Not shown: depth and LiDAR (not fetched), IMU, odometry, arm and leg joints and the action targets; the hand joint "
             f"angles are plotted. <code>observation.tactile.sensor_id</code> is used for the index arithmetic above.</p>")
    title = task["task"].split("/", 1)[1].removesuffix("_g1").replace("_", " ")
    title = title[0].upper() + title[1:]
    item = {"id": vid, "title": title, "label": task["category"].replace("_", " ").capitalize() if task["category"] != "HRI" else "HRI",
            "sub": f"{dur:.0f} s · episode {e}", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps({**item, "range": rng, "live": [nl, nr], "peak_t": round(tpk, 2)}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", type=int, nargs="+")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    c.add_argument("--meta", type=Path, default=None, help="folder holding tasks.jsonl (default: <episode>/../meta)")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.episodes)
    else:
        for ep in a.episode:
            ep = ep.expanduser()
            convert(ep, a.site, (a.meta or ep.parent / "meta").expanduser())


if __name__ == "__main__":
    main()
