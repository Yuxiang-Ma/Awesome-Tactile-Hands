#!/usr/bin/env python
"""T-Rex episode -> viewer grid recording (site/data/tr_*.json + site/media/tr_*_<cam>.mp4 + poster).

T-Rex (zekaiwang/trex_dataset, LeRobot v3.0, MIT) stores many episodes per parquet / mp4 file, so nothing is
downloaded whole: `fetch` reads only the parquet row groups and the video time slices of the requested episodes
(HTTP range requests at a pinned revision), `convert` turns one fetched episode into the viewer format and
re-encodes the episode's slice of each RGB camera into site/media (the MIT license permits redistribution).

    python -I ext/trex.py fetch ~/data/ext/trex/eps 2019 557           # needs pyarrow, av, huggingface_hub
    python -I ext/trex.py convert --site site ~/data/ext/trex/eps/ep002019   # needs numpy + ffmpeg

Tactile: each Sharpa Wave hand has five camera-based fingertip sensors. The release stores, per fingertip, the raw
sensor image, an estimated deformation map (240 x 240, uint8, "local skin displacement field") and an estimated
6-axis wrench. The viewer shows all three: the deformation map mean-pooled to POOL x POOL cells per fingertip, the
wrench as an arrow (Fx, Fy) and ring (Fz) on each fingertip block plus per-finger plots, and the raw sensor images as
one 2 x 5 mosaic video.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = "zekaiwang/trex_dataset"
REV = "8b478400a9167d59ede0fdbfea616cb5e9791885"
FPS = 30
FINGERS = ["thumb", "index", "middle", "ring", "pinky"]
REGION = {"pinky": "little"}
CAMS = [("head_left", "Head camera (ZED X Mini, left)"), ("left_wrist", "Left wrist camera"), ("right_wrist", "Right wrist camera")]
POOL = 10          # cells per side of each fingertip block (240 px / 24 px)
GAP = 1
THUMB_DROP = 8     # thumb block sits this many rows below the finger row


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def url(path: str) -> str:
    return f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/{path}"


def video_path(r: dict, key: str) -> str:
    return f"videos/{key}/chunk-{r[f'videos/{key}/chunk_index']:03d}/file-{r[f'videos/{key}/file_index']:03d}.mp4"


# ---------------------------------------------------------------- fetch (pyarrow + av + huggingface_hub)
def decode_gray(r: dict, key: str, n: int) -> np.ndarray:
    """n frames of a lossless gray tactile stream, aligned by pts as in the release's quickstart decode_key."""
    import av
    from_ts = float(r[f"videos/{key}/from_timestamp"])
    start = int(round(from_ts * FPS))
    out = []
    with av.open(url(video_path(r, key))) as c:
        st = c.streams.video[0]
        tb = st.time_base
        if start > 0:
            c.seek(max(int((from_ts - 0.1) / tb), 0), stream=st, backward=True, any_frame=False)
        for fr in c.decode(video=0):
            idx = int(round(float(fr.pts * tb) * FPS))
            if idx < start:
                continue
            assert idx == start + len(out), (key, idx, start, len(out))
            out.append(fr.to_ndarray(format="gray"))
            if len(out) == n:
                break
    assert len(out) == n, (key, len(out), n)
    return np.stack(out)


def fetch(root: Path, eps: list[int], meta_parquet: Path) -> None:
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem
    if not meta_parquet.exists():
        from huggingface_hub import hf_hub_download
        hf_hub_download(REPO, "meta/episodes/chunk-000/file-000.parquet", repo_type="dataset", revision=REV,
                        local_dir=meta_parquet.parents[3])
    cols = [c for c in pq.ParquetFile(meta_parquet).schema_arrow.names if not c.startswith("stats/")]
    meta = {r["episode_index"]: r for r in pq.read_table(meta_parquet, columns=cols).to_pylist() if r["episode_index"] in eps}
    fs = HfFileSystem()
    for e in eps:
        r, n = meta[e], meta[e]["length"]
        out = root / f"ep{e:06d}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "meta.json").write_text(json.dumps(r, indent=1, default=str))
        if not (out / "data.npz").exists():
            p = f"datasets/{REPO}@{REV}/data/chunk-{r['data/chunk_index']:03d}/file-{r['data/file_index']:03d}.parquet"
            with fs.open(p, "rb", block_size=1 << 20) as fh:
                pf = pq.ParquetFile(fh)
                ci = pf.schema_arrow.names.index("index")
                groups = [g for g in range(pf.metadata.num_row_groups)
                          if (s := pf.metadata.row_group(g).column(ci).statistics).max >= r["dataset_from_index"]
                          and s.min < r["dataset_to_index"]]
                t = pf.read_row_groups(groups, columns=["episode_index", "frame_index", "timestamp", "observation.state",
                                                        "action", "observation.tactile_force"]).to_pydict()
            sel = sorted((i for i, v in enumerate(t["episode_index"]) if v == e), key=lambda i: t["frame_index"][i])
            assert [t["frame_index"][i] for i in sel] == list(range(n)), "complete episode"
            arr = lambda k: np.array([t[k][i] for i in sel], np.float32)
            np.savez(out / "data.npz", timestamp=arr("timestamp"), state=arr("observation.state"), action=arr("action"),
                     force=arr("observation.tactile_force"))
        if not (out / "deform.npz").exists():
            keys = [f"observation.images.tactile_{s}_deform_{f}" for s in ("left", "right") for f in FINGERS]
            np.savez_compressed(out / "deform.npz", deform=np.stack([decode_gray(r, k, n) for k in keys]), keys=np.array(keys))
        print(e, "fetched", file=sys.stderr)


# ---------------------------------------------------------------- convert (numpy + ffmpeg)
def layout(key: str) -> tuple[int, int, list[tuple[int, int]]]:
    """Top-left (row, col) of each fingertip block, thumb..pinky. Fingers in a row, thumb lower on the outside:
    the right hand has its thumb on the left, the left hand is mirrored (as in the other glove collections)."""
    step = POOL + GAP
    cols = 5 * step - GAP
    rows = THUMB_DROP + POOL
    rh = [(THUMB_DROP, 0)] + [(0, (k + 1) * step) for k in range(4)]
    if key == "rh":
        return rows, cols, rh
    return rows, cols, [(r, cols - c - POOL) for r, c in rh]


def pooled(deform: np.ndarray) -> np.ndarray:
    """(5, n, 240, 240) uint8 -> (n, 5, POOL, POOL) float32 block means."""
    f, n, h, w = deform.shape
    b = h // POOL
    x = deform.reshape(f, n, POOL, b, POOL, b).astype(np.float32).mean(axis=(3, 5))
    return x.transpose(1, 0, 2, 3)


def hand(p: np.ndarray, key: str, title: str, rng: float, f6: np.ndarray, frng: float) -> dict:
    """f6: (n, 5, 6) wrench of this hand's fingertips; frng: force giving a full-block arrow."""
    rows, cols, origin = layout(key)
    cells, regions = [], []
    for k, (r0, c0) in enumerate(origin):
        rr, cc = np.mgrid[0:POOL, 0:POOL]
        regions.append({"name": REGION.get(FINGERS[k], FINGERS[k]), "cells": list(range(len(cells), len(cells) + POOL * POOL))})
        cells += ((r0 + rr.ravel()) * cols + c0 + cc.ravel()).tolist()
    tax = np.clip(np.round(p.reshape(len(p), -1) / rng * 255), 0, 255).astype(np.uint8)
    return {"key": key, "title": title, "rate": FPS, "rows": rows, "cols": cols, "cells": b64(np.array(cells, np.uint16)),
            "tax": b64(tax), "range": rng, "unit": "deformation map value", "regions": regions,
            "label": "5 fingertip sensors · 10×10 cells each",
            "vectors": {"label": "fingertip force", "unit": "(units not stated)", "range": frng, "axes": "(Fx, Fy)", "zname": "Fz",
                        "items": [{"region": REGION.get(f, f), "data": b64(f6[:, k, :3].astype(np.float32))} for k, f in enumerate(FINGERS)]}}


def transcode(r: dict, cam: str, n: int, dst: Path) -> None:
    key = f"observation.images.{cam}"
    a = float(r[f"videos/{key}/from_timestamp"]) - 0.5 / FPS  # accurate seek; half a frame of slack against rounding
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(a, 0):.4f}", "-i", url(video_path(r, key)), "-frames:v", str(n),
                    "-an", "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(dst)], check=True)


def raw_mosaic(r: dict, n: int, dst: Path) -> None:
    """The 10 raw tactile images (left hand on top, thumb..pinky) as one 800 x 240 H.264 video."""
    ins, fl = [], []
    for k, (s, f) in enumerate((s, f) for s in ("left", "right") for f in FINGERS):
        key = f"observation.images.tactile_{s}_raw_{f}"
        a = float(r[f"videos/{key}/from_timestamp"]) - 0.5 / FPS
        ins += ["-ss", f"{max(a, 0):.4f}", "-i", url(video_path(r, key))]
        fl.append(f"[{k}:v]format=gray,scale=160:120,trim=end_frame={n}[t{k}]")
    lay = "|".join(f"{(k % 5) * 160}_{(k // 5) * 120}" for k in range(10))
    fl.append("".join(f"[t{k}]" for k in range(10)) + f"xstack=inputs=10:layout={lay},format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fl), "-map", "[v]", "-frames:v", str(n), "-an",
                    "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-movflags", "+faststart", str(dst)], check=True)


def convert(ep: Path, site: Path) -> None:
    r = json.loads((ep / "meta.json").read_text())
    z = np.load(ep / "data.npz")
    d = np.load(ep / "deform.npz")
    keys = [str(k) for k in d["keys"]]
    assert keys == [f"observation.images.tactile_{s}_deform_{f}" for s in ("left", "right") for f in FINGERS]
    deform = d["deform"]
    n = int(r["length"])
    assert deform.shape[1] == n == len(z["timestamp"])
    assert np.allclose(z["timestamp"], np.arange(n) / FPS, atol=1e-3), "one row per 30 Hz frame"
    e = int(r["episode_index"])
    vid = f"tr_ep{e:06d}"
    pl, pr = pooled(deform[:5]), pooled(deform[5:])
    hi = float(np.percentile(np.concatenate([pl.ravel(), pr.ravel()]), 99.95))
    rng = float(max(20, 5 * np.ceil(hi / 5)))
    f6 = z["force"].reshape(n, 2, 5, 6)
    fmag = np.linalg.norm(f6[..., :3], axis=-1)
    frng = float(max(2, 2 * np.ceil(np.percentile(fmag, 99.5) / 2)))
    hands = [hand(pl, "lh", "Left hand", rng, f6[:, 0], frng), hand(pr, "rh", "Right hand", rng, f6[:, 1], frng)]

    cols = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#d35400"]
    comp = [("Fz", lambda w: w[..., 2]), ("tangential |(Fx, Fy)|", lambda w: np.hypot(w[..., 0], w[..., 1])),
            ("moment |M|", lambda w: np.linalg.norm(w[..., 3:], axis=-1))]
    series = [{"title": f"{side} hand · fingertip {name} (estimated wrench, units not stated)",
               "lines": [{"name": REGION.get(f, f), "data": b64(fn(f6[:, s, k]).astype(np.float32)), "col": cols[k]}
                         for k, f in enumerate(FINGERS)]}
              for name, fn in comp for s, side in enumerate(("Left", "Right"))]

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    for cam, title in CAMS:
        dst = media / f"{vid}_{cam}.mp4"
        if not dst.exists():
            transcode(r, cam, n, dst)
        videos.append({"key": cam, "title": title, "src": f"media/{vid}_{cam}.mp4", "src_size": [640, 360], "fps_src": FPS})
    dst = media / f"{vid}_tactile_raw.mp4"
    if not dst.exists():
        raw_mosaic(r, n, dst)
    videos.append({"key": "tactile_raw", "title": "Raw fingertip sensor images (top: left hand, bottom: right; thumb → pinky)",
                   "src": f"media/{vid}_tactile_raw.mp4", "src_size": [320, 240], "fps_src": FPS, "wide": True})
    dur = n / FPS
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(media / f"{vid}_head_left.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)

    notes = (f"<p>One row per frame of the release's 30 Hz recording loop: cameras, tactile maps, wrenches and joints share the "
             f"same frame index, so no re-timing is applied. The three camera videos are this episode's slice of the release's "
             f"multi-episode files (revision {REV[:7]}), re-encoded to H.264 for the browser.</p>"
             f"<p>Each Sharpa Wave fingertip is a camera-based tactile sensor. Shown here is the release's estimated deformation map "
             f"(240 × 240 px, 8-bit, described in the paper as the local skin displacement field), averaged over 24 × 24 px "
             f"patches into a {POOL} × {POOL} grid per fingertip. The five fingertip blocks are a schematic hand (fingers in a row, "
             f"thumb lower on the outside, left hand mirrored); each block keeps the map's own pixel orientation, which the release "
             f"does not relate to the finger axis, and is not mirrored. Values are the map's 0–255 units, uncalibrated; the colour "
             f"scale ends at {rng:.0f} (the episode's 99.95th percentile over all cells, rounded up). The deformation maps are not "
             f"tared, so some fingertips show a small constant patch at rest. Region sums add up the {POOL * POOL} cells of a "
             f"fingertip.</p><p>The yellow arrow on each fingertip is (Fx, Fy) and the white ring is Fz of the release's estimated "
             f"6-axis fingertip wrench (<code>observation.tactile_force</code>, tared to zero at rest by the release; units and sensor "
             f"frame not stated). Fx is drawn to the right and Fy up; how these axes sit on the finger is not documented, so the "
             f"arrow shows direction changes, not a direction on the hand. Fz is the largest component and almost never negative, "
             f"so it is probably the normal force, but the release does not say so. A full-block arrow or ring is {frng:g} (the "
             f"episode's 99.5th percentile of |F|, rounded up). The plots show Fz, the tangential magnitude and the moment magnitude "
             f"per finger.</p><p>The mosaic video is the release's raw tactile camera images (320 × 240 gray, lossless in the release), "
             f"scaled to 160 × 120 and re-encoded to H.264. The joint states and targets are not shown.</p>")
    item = {"id": vid, "title": r["caption"], "label": f"{r['motor_primitive'].replace('_', ' ')} · {r['object']}",
            "sub": f"{dur:.0f} s · episode {e}", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": r["caption"], "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(item))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", type=int, nargs="+")
    f.add_argument("--meta", type=Path, default=Path("~/data/ext/trex/meta/episodes/chunk-000/file-000.parquet"))
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.episodes, a.meta.expanduser())
    else:
        for ep in a.episode:
            convert(ep.expanduser(), a.site)


if __name__ == "__main__":
    main()
