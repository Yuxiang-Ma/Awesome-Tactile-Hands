#!/usr/bin/env python
"""TouchScale episode -> viewer grid recording (site/data/ts_*.json + site/media/ts_*_<cam>.mp4 + poster).

TouchScale (2077AIDataFoundation/TouchScale, gated on Hugging Face, CC BY-NC 4.0) ships each episode as ~17 files inside
~2.5 GB WebDataset tar shards. `fetch` looks the episode's shard up in metadata/episodes.parquet, walks that shard's tar
headers with HTTP range requests (512 bytes each) until the episode's members are found, and reads only those byte
ranges, so one episode costs its own size (52-85 MB in the sample) instead of a shard. `convert` turns one fetched episode into
the viewer format and re-encodes the head, wrist and colour-mapped depth videos to H.264 on the head camera's frame clock
(CC BY-NC 4.0 permits non-commercial redistribution with attribution). Episodes over 22 s need --window to stay under 2 MB.

    python -I ext/touchscale.py fetch ~/data/ext/touchscale/raw 5a1ae97d-9456-479a-8a4e-4cd6c7f07773 ...   # needs requests, pyarrow
    python -I ext/touchscale.py convert --site site ~/data/ext/touchscale/raw/5a1ae97d-9456-479a-8a4e-4cd6c7f07773  # numpy, av, cv2

Tactile: each glove has 880 taxels on 15 pads (`tactile_<k>`, k in 0-5, 7-9, 11-13, 15, 16, 18, normal force per taxel
in N) plus two tangential components per taxel (`tf_tactile_x_<k>`, `tf_tactile_y_<k>`), all on the glove's own
timestamps (30-100 Hz depending on the session). Taxels are placed from the release's metadata/glove_geometry_<side>.json
(one square per taxel); tangential components are summed per pad and drawn as one arrow per pad, plus plots.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = "2077AIDataFoundation/TouchScale"
REV = "74914cc2e11d0a7f37ddbe5d57db4fe4e14a0a7e"
MEMBERS = ["json", "rgb_head.mp4", "rgb_head.csv", "depth_head.mkv", "depth_head.csv", "wrist_left.mp4", "wrist_left.csv",
           "wrist_right.mp4", "wrist_right.csv", "left_hand_data.npz", "right_hand_data.npz", "glove_left_calib.json",
           "glove_right_calib.json", "imu.txt", "episode.h5", "head_param.json", "kalibr_parameters.yaml"]


# ---------------------------------------------------------------- fetch (requests + pyarrow)
class Shard:
    """Byte-range reader for one tar shard: resolves the gated resolve URL once (HF token from the local login) and
    reads from the signed CDN location, re-resolving when the signature expires."""

    def __init__(self, path: str):
        import requests
        from huggingface_hub import hf_hub_url
        from huggingface_hub.utils import build_hf_headers
        self.s, self.url, self.auth = requests.Session(), hf_hub_url(REPO, path, repo_type="dataset", revision=REV), build_hf_headers()
        self._resolve()

    def _resolve(self) -> None:
        r = self.s.get(self.url, headers={**self.auth, "Range": "bytes=0-0"}, allow_redirects=False, timeout=60)
        assert r.status_code in (301, 302, 307), f"resolve: HTTP {r.status_code} (access to {REPO} granted?)"
        self.loc = r.headers["location"]

    def read(self, a: int, n: int) -> bytes:
        for _ in range(4):
            try:
                r = self.s.get(self.loc, headers={"Range": f"bytes={a}-{a + n - 1}"}, timeout=300)
                if r.status_code == 206 and len(r.content) == n:
                    return r.content
                print(f"retry: HTTP {r.status_code}, {len(r.content)} of {n} bytes", file=sys.stderr)
            except Exception as e:  # transient network error
                print("retry:", e, file=sys.stderr)
            self._resolve()
        raise RuntimeError("range read failed")


def walk(sh: Shard, want: set[str], cache: Path) -> dict[str, list[tuple[str, int, int]]]:
    """Members (name, data offset, size) of the wanted episode keys, read from the tar headers. The walk stops once every
    wanted key has been seen and a different key follows it (an episode's files are contiguous in the shard). Headers
    walked so far are cached, so a second call on the same shard does not read them again."""
    idx = json.loads(cache.read_text()) if cache.exists() else {"members": [], "next": 0, "eof": False}
    key = lambda name: name.split(".", 1)[0]
    got = lambda: {k for k in want if any(key(m[0]) == k for m in idx["members"])}

    def done() -> bool:
        if idx["eof"] or got() != want:
            return idx["eof"]
        last = max(i for i, m in enumerate(idx["members"]) if key(m[0]) in want)
        return last < len(idx["members"]) - 1

    off, longname = idx["next"], None
    while not done():
        hd = sh.read(off, 512)
        if hd == b"\0" * 512:
            idx["eof"] = True
            break
        name, pre = hd[:100].rstrip(b"\0").decode(), hd[345:500].rstrip(b"\0").decode()
        size, tf = int(hd[124:136].rstrip(b"\0 ").decode() or "0", 8), hd[156:157]
        data = off + 512
        if tf == b"L":
            longname = sh.read(data, size).rstrip(b"\0").decode()
        elif tf in (b"0", b"\0"):
            idx["members"].append((longname or ((pre + "/" if pre else "") + name), data, size))
            longname = None
        off = idx["next"] = data + (size + 511) // 512 * 512
        if len(idx["members"]) % 50 == 0:
            cache.write_text(json.dumps(idx))
    cache.write_text(json.dumps(idx))
    return {k: [tuple(m) for m in idx["members"] if key(m[0]) == k] for k in want}


def fetch(root: Path, eps: list[str], meta_dir: Path) -> None:
    import pyarrow.parquet as pq
    pq_path = meta_dir / "metadata" / "episodes.parquet"
    if not pq_path.exists():
        from huggingface_hub import hf_hub_download
        hf_hub_download(REPO, "metadata/episodes.parquet", repo_type="dataset", revision=REV, local_dir=meta_dir)
        hf_hub_download(REPO, "metadata/glove_geometry_left.json", repo_type="dataset", revision=REV, local_dir=meta_dir)
        hf_hub_download(REPO, "metadata/glove_geometry_right.json", repo_type="dataset", revision=REV, local_dir=meta_dir)
    t = pq.read_table(pq_path, columns=["episode_id", "shard"]).to_pydict()
    shard_of = dict(zip(t["episode_id"], t["shard"]))
    missing = [e for e in eps if e not in shard_of]
    assert not missing, f"not in episodes.parquet: {missing}"
    for shard in sorted({shard_of[e] for e in eps}):
        want = {e for e in eps if shard_of[e] == shard}
        todo = {e for e in want if not all((root / e / m).exists() for m in MEMBERS)}
        if not todo:
            continue
        sh = Shard(shard)
        found = walk(sh, todo, meta_dir / f"index_{Path(shard).stem}.json")
        for e, members in found.items():
            names = sorted(m[0][len(e) + 1:] for m in members)
            assert names == sorted(MEMBERS), f"{e}: members {names}"
            out = root / e
            out.mkdir(parents=True, exist_ok=True)
            for name, a, n in members:
                dst = out / name[len(e) + 1:]
                assert dst.parent == out, name
                if dst.exists() and dst.stat().st_size == n:
                    continue
                dst.write_bytes(sh.read(a, n))
            print(e, shard, f"{sum(m[2] for m in members) / 1e6:.1f} MB", file=sys.stderr)


# ---------------------------------------------------------------- convert (numpy + av + cv2 + ffmpeg)
FPS = 30
PITCH = 0.05       # glove_geometry units per grid cell (the palm pads' taxel pitch)
RANGE = 1.5        # N per taxel drawn as full scale (set from the sampled episodes, see notes)
PADS = [0, 1, 2, 3, 4, 5, 7, 8, 9, 11, 12, 13, 15, 16, 18]
REGION = {0: "thumb", 1: "thumb", 2: "palm", 3: "index", 4: "index", 5: "index", 7: "middle", 8: "middle", 9: "middle",
          11: "ring", 12: "ring", 13: "ring", 15: "little", 16: "little", 18: "palm"}
REGIONS = ["thumb", "index", "middle", "ring", "little", "palm"]
LINE_COLS = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#cb4335", "#7f8c8d"]
VIDEOS = [("rgb_head", "Head camera", 960), ("wrist_left", "Left wrist", 640), ("wrist_right", "Right wrist", 640),
          ("depth_head", "Head depth", 640)]
DEPTH_MM = (200, 1200)   # depth colour range


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def geometry(meta: Path, side: str) -> tuple[dict, np.ndarray]:
    d = json.loads((meta / "metadata" / f"glove_geometry_{side}.json").read_text())
    assert d["columns"][:9] == ["x", "y", "z", "dir_x_x", "dir_x_y", "dir_x_z", "dir_y_x", "dir_y_y", "dir_y_z"]
    a = np.frombuffer(base64.b64decode(d["data_base64"]), d["dtype"]).reshape(-1, d["point_stride"])
    assert len(a) == d["point_count"] == 880
    return d, a


def layout(meta: Path, side: str) -> tuple[int, int, dict[int, np.ndarray], dict[int, tuple[float, float]]]:
    """Grid cell (row * cols + col) of every taxel of each pad, in the pad's storage order (tactile_<k>[t].ravel()).

    The release's glove_geometry_<side>.json gives every taxel an (x, y) in a flat palmar drawing (fingers up). Each pad is
    drawn as its own rows x cols block of squares, one per taxel, oriented like the drawing (tip rows on top, columns in
    the drawing's x order); the block is placed at the pad's (x, y) on a PITCH grid and pushed down when it would touch
    the pad above it (the drawing packs the thumb tip's 16 rows into less height than 16 cells). Returns the grid size,
    the cell index per pad, and per pad the sign that maps tf_tactile_x / _y onto the grid's x right / y up axes."""
    d, a = geometry(meta, side)
    pads, o = {}, 0
    for r in d["regions"]:
        n = r["rows"] * r["cols"]
        pads[r["id"]] = (r["rows"], r["cols"], a[o:o + n].reshape(r["rows"], r["cols"], -1))
        o += n
    assert sorted(pads) == PADS
    X0 = min(p[..., 0].min() for _, _, p in pads.values())
    Y1 = max(p[..., 1].max() for _, _, p in pads.values())
    boxes, sign = {}, {}
    for k in sorted(pads, key=lambda k: -pads[k][2][..., 1].max()):
        R, C, p = pads[k]
        top = int(np.floor(round((Y1 - p[..., 1].max()) / PITCH, 6) + 0.5))
        left = int(np.floor(round((p[..., 0].mean() - X0) / PITCH - (C - 1) / 2, 6) + 0.5))
        while any(top <= b[0] + b[2] and top + R >= b[0] and left < b[1] + b[3] and left + C > b[1] for b in boxes.values()):
            top += 1   # keep one empty row between blocks of the same column
        boxes[k] = (top, left, R, C)
        # tangential axes: geometry dir_x points along increasing stored column, dir_y along decreasing stored row
        sign[k] = (float(np.sign(p[..., 3].mean())), float(np.sign(p[..., 7].mean())))
    c0 = min(b[1] for b in boxes.values())
    rows = max(b[0] + b[2] for b in boxes.values())
    cols = max(b[1] + b[3] for b in boxes.values()) - c0
    cells = {}
    for k, (top, left, R, C) in boxes.items():
        _, _, p = pads[k]
        flip_r = p[-1, 0, 1] > p[0, 0, 1]          # stored row 0 is the proximal end: draw it at the bottom
        flip_c = p[0, -1, 0] < p[0, 0, 0]          # draw columns in increasing x
        rr, cc = np.mgrid[0:R, 0:C]
        dr = R - 1 - rr if flip_r else rr
        dc = C - 1 - cc if flip_c else cc
        cells[k] = ((top + dr) * cols + (left - c0 + dc)).ravel()
    allc = np.concatenate([cells[k] for k in PADS])
    assert len(allc) == 880 and len(np.unique(allc)) == 880, "one grid cell per taxel"
    return rows, cols, cells, sign


def latest(ts: np.ndarray, ticks: np.ndarray) -> np.ndarray:
    """Index of the latest sample at or before each tick (the first sample for ticks before it)."""
    return np.clip(np.searchsorted(ts, ticks, side="right") - 1, 0, len(ts) - 1)


def csv_ts(p: Path) -> np.ndarray:
    rows = [line.split(",") for line in p.read_text().splitlines()[1:] if line.strip()]
    assert [int(r[0]) for r in rows] == list(range(len(rows))), f"{p.name}: frame_index 0..n-1"
    return np.array([float(r[1]) for r in rows])


def encode(ep: Path, key: str, src_idx: np.ndarray, width: int, dst: Path) -> tuple[int, int]:
    """Frames src_idx of one release video re-encoded as H.264 at FPS (depth: colour-mapped)."""
    import av
    import cv2
    want = {int(i) for i in src_idx}
    frames, k = {}, 0
    with av.open(str(ep / (key + (".mkv" if key == "depth_head" else ".mp4")))) as c:
        for fr in c.decode(video=0):
            if k in want:
                if key == "depth_head":
                    dmm = fr.to_ndarray(format="gray16le")
                    v = np.clip((dmm.astype(np.float32) - DEPTH_MM[0]) / (DEPTH_MM[1] - DEPTH_MM[0]), 0, 1)
                    img = cv2.applyColorMap((255 - v * 255).astype(np.uint8), cv2.COLORMAP_TURBO)[..., ::-1]
                    img[dmm == 0] = 0
                    h = int(round(img.shape[0] * width / img.shape[1] / 2) * 2)
                    frames[k] = cv2.resize(np.ascontiguousarray(img), (width, h), interpolation=cv2.INTER_AREA)
                else:
                    h = int(round(fr.height * width / fr.width / 2) * 2)
                    frames[k] = fr.reformat(width=width, height=h, format="rgb24").to_ndarray()
            k += 1
    assert want <= set(frames), f"{key}: missing frames"
    h = next(iter(frames.values())).shape[0]
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{h}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-g", str(FPS), "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", "-an", str(dst)], stdin=subprocess.PIPE)
    for i in src_idx:
        ff.stdin.write(frames[int(i)].tobytes())
    ff.stdin.close()
    assert ff.wait() == 0, "ffmpeg failed"
    return width, h


def glove(ep: Path, side: str) -> dict:
    z = np.load(ep / f"{side}_hand_data.npz", allow_pickle=False)
    ts = z["timestamps"].astype(np.float64)
    out = {"ts": ts, "fn": z["frame_numbers"].astype(np.int64)}
    for k in PADS:
        out[k] = z[f"tactile_{k}"].reshape(len(ts), -1).astype(np.float32)
        out[("x", k)] = z[f"tf_tactile_x_{k}"].reshape(len(ts), -1).astype(np.float32)
        out[("y", k)] = z[f"tf_tactile_y_{k}"].reshape(len(ts), -1).astype(np.float32)
    return out


def glove_checks(g: dict, shapes: dict[int, tuple[int, int]]) -> dict:
    """Timing and signal checks on the native glove stream (the whole file, not only the shown window).

    dead: taxels that never exceed 0.005 N while the mean of their 4 neighbours in the same pad is above 0.2 N for at
    least 1 s of samples. saturated: taxels whose maximum is above 1 N and is held exactly for at least 0.5 s of samples
    (a flat top, as at the end of a calibration curve)."""
    ts, fn = g["ts"], g["fn"]
    dt = np.diff(ts)
    rate = (len(ts) - 1) / (ts[-1] - ts[0])
    skipped = int(((np.diff(fn) - 1) % 256).sum())       # frame_numbers is an 8-bit counter
    allv = np.concatenate([g[k] for k in PADS], axis=1)
    flat_pads = [k for k in PADS if np.abs(g[k]).max() < 0.01 and not np.any(g[("x", k)]) and not np.any(g[("y", k)])]
    dead, sat = [], []
    for k in PADS:
        R, C = shapes[k]
        a = g[k].reshape(len(ts), R, C)
        p = np.pad(a, ((0, 0), (1, 1), (1, 1)), constant_values=np.nan)
        with np.errstate(invalid="ignore"):
            nb = np.nanmean(np.stack([p[:, :-2, 1:-1], p[:, 2:, 1:-1], p[:, 1:-1, :-2], p[:, 1:-1, 2:]]), 0)
        loaded = (nb > 0.2).sum(0)
        dead += [(k, int(r), int(c)) for r, c in zip(*np.nonzero((a.max(0) <= 0.005) & (loaded >= rate)))]
        mx = a.max(0)
        held = (a == mx[None]).sum(0)
        sat += [(k, int(r), int(c)) for r, c in zip(*np.nonzero((mx > 1.0) & (held >= 0.5 * rate)))]
    return {"n": len(ts), "rate": rate, "dt_max": float(dt.max()), "monotonic": bool((dt > 0).all()), "skipped": skipped,
            "nan": int(np.isnan(allv).sum()), "flat_pads": flat_pads, "dead": dead, "saturated": sat,
            "max": float(allv.max()), "min": float(allv.min())}


def convert(ep: Path, site: Path, meta: Path, window: list[float] | None) -> None:
    m = json.loads((ep / "json").read_text())
    eid = m["episode_id"]
    vid = f"ts_{eid.split('-')[0]}"
    ts_cam = {k: csv_ts(ep / f"{k}.csv") for k, _, _ in VIDEOS}
    t0 = ts_cam["rgb_head"][0]
    span = ts_cam["rgb_head"][-1] - t0
    w0, w1 = (0.0, span) if window is None else (max(0.0, window[0]), min(span, window[1]))
    n = int(np.floor((w1 - w0) * FPS + 1e-6)) + 1
    ticks = t0 + w0 + np.arange(n) / FPS                      # clock: head camera, from the window start
    cam_idx = {k: latest(ts_cam[k], ticks) for k in ts_cam}
    cam_lag = {k: float(np.abs(ts_cam[k][cam_idx[k]] - ticks).max()) for k in ts_cam}

    G = {s: glove(ep, s) for s in ("left", "right")}
    shapes = {s: {r["id"]: (r["rows"], r["cols"]) for r in geometry(meta, s)[0]["regions"]} for s in G}
    for s in G:
        z = np.load(ep / f"{s}_hand_data.npz", allow_pickle=False)
        assert all(z[f"tactile_{k}"].shape[1:] == shapes[s][k] for k in PADS), f"{s}: pad shapes differ from the geometry file"
    chk = {s: glove_checks(G[s], shapes[s]) for s in G}
    for s in G:
        assert G[s]["ts"][0] <= ticks[0] + 0.05 and G[s]["ts"][-1] >= ticks[-1] - 0.05, f"{s} glove does not cover the clock"
    hands, series_n, series_t, vec_hi, ratio = [], [], [], [], []
    for s, key in (("left", "lh"), ("right", "rh")):
        g = G[s]
        rows, cols, cells, sign = layout(meta, s)
        gi = latest(g["ts"], ticks)
        order = PADS
        vals = np.concatenate([g[k][gi] for k in order], axis=1)                       # (n, 880) N
        cell = np.concatenate([cells[k] for k in order]).astype(np.uint16)
        tax = np.clip(np.round(vals / RANGE * 255), 0, 255).astype(np.uint8)
        pad_of = np.concatenate([[k] * len(cells[k]) for k in order])
        regions = [{"name": r, "cells": np.flatnonzero([REGION[k] == r for k in pad_of]).tolist()} for r in REGIONS]
        items, reg_t = [], {r: np.zeros((n, 2), np.float32) for r in REGIONS}
        for k in order:
            vx = sign[k][0] * g[("x", k)][gi].sum(1)
            vy = sign[k][1] * g[("y", k)][gi].sum(1)
            v = np.stack([vx, vy, np.zeros(n, np.float32)], 1).astype(np.float32)
            reg_t[REGION[k]] += v[:, :2]
            vec_hi.append(np.hypot(vx, vy))
            items.append({"cells": np.flatnonzero(pad_of == k).tolist(), "data": v, "pad": k})
        hands.append({"key": key, "title": f"{s.capitalize()} glove", "rate": round(chk[s]["rate"]), "rows": rows, "cols": cols,
                      "cells": b64(cell), "tax": b64(tax), "range": RANGE, "unit": "N", "regions": regions,
                      "label": "880 taxels · 15 pads", "_items": items})
        tot = vals.reshape(n, -1)
        series_n.append(tot.sum(1).astype(np.float32))
        series_t.append({r: np.hypot(*reg_t[r].T).astype(np.float32) for r in REGIONS})
        nv = np.concatenate([g[k] for k in PADS], 1)
        tv = np.hypot(np.concatenate([g[("x", k)] for k in PADS], 1), np.concatenate([g[("y", k)] for k in PADS], 1))
        ratio.append(float(np.median(tv[nv > 0.2] / nv[nv > 0.2])) if (nv > 0.2).any() else None)
    vrange = round(float(max(0.05, np.ceil(np.percentile(np.concatenate(vec_hi), 99.5) * 20) / 20)), 2)
    for h in hands:
        h["vectors"] = {"label": "pad tangential force", "unit": "(units not stated)", "range": vrange, "axes": "(tf_x, tf_y) summed per pad",
                        "zname": None, "items": [{"cells": it["cells"], "data": b64(it["data"])} for it in h.pop("_items")]}

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    for k, title, w in VIDEOS:
        dst = media / f"{vid}_{k}.mp4"
        size = encode(ep, k, cam_idx[k], w, dst)
        videos.append({"key": k, "title": title, "src": f"media/{vid}_{k}.mp4", "src_size": list(size), "fps_src": FPS})
    contact = series_n[0] + series_n[1]
    pk = int(np.argmax(contact))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{pk / FPS:.2f}", "-i", str(media / f"{vid}_rgb_head.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)

    imu = np.loadtxt(ep / "imu.txt", comments="#")
    gyro = np.linalg.norm(imu[latest(imu[:, 0], ticks), 4:7], axis=1).astype(np.float32)
    series = [{"title": "Total normal force per glove (N, sum of 880 taxels)",
               "lines": [{"name": "left", "data": b64(series_n[0]), "col": "#2563b0"},
                         {"name": "right", "data": b64(series_n[1]), "col": "#c2501f"}]}]
    for (s, hn) in enumerate(("Left", "Right")):
        series.append({"title": f"{hn} glove · tangential force per region, |sum of (tf_x, tf_y)| (units not stated)",
                       "lines": [{"name": r, "data": b64(series_t[s][r]), "col": LINE_COLS[q]} for q, r in enumerate(REGIONS)]})
    series.append({"title": "Head IMU · |gyro| (rad/s)", "lines": [{"name": "|gyro|", "data": b64(gyro), "col": "#7f8c8d"}]})

    dur = n / FPS
    flat = {s: chk[s]["flat_pads"] for s in chk}
    flat_txt = "; ".join(f"{s} glove pad{'s' if len(v) > 1 else ''} {', '.join(f'tactile_{k}' for k in v)}" for s, v in flat.items() if v)
    name = lambda L: ", ".join(f"tactile_{k} row {r} col {c}" for k, r, c in L)
    dead_txt = "; ".join(f"{s} glove {len(chk[s]['dead'])} ({name(chk[s]['dead'])})" for s in chk if chk[s]["dead"])
    sat_txt = "; ".join(f"{s} glove {len(chk[s]['saturated'])} ({name(chk[s]['saturated'])})" for s in chk if chk[s]["saturated"])
    mono = all(chk[s]["monotonic"] for s in chk)
    nans = sum(chk[s]["nan"] for s in chk)
    qual = (f"<p>Checks on the whole glove files: timestamps {'increase monotonically' if mono else 'are not monotonic'}, "
            f"{'no NaN' if nans == 0 else f'{nans} NaN values'}; largest step between samples "
            f"{max(chk[s]['dt_max'] for s in chk) * 1000:.0f} ms. "
            + ("The glove's 8-bit <code>frame_numbers</code> counter advances by 1 at every stored sample. "
               if chk['left']['skipped'] == chk['right']['skipped'] == 0 else
               f"The glove's 8-bit <code>frame_numbers</code> counter skips {chk['left']['skipped']} (left) and "
               f"{chk['right']['skipped']} (right) values between stored samples; the release does not say whether these are "
               f"dropped packets or the host reading slower than the glove. ")
            + (f"Taxels at 0 N throughout while their neighbours were loaded above 0.2 N for over 1 s (possibly dead): {dead_txt}. "
               if dead_txt else "No taxel stays at 0 N while its neighbours are loaded for over 1 s. ")
            + (f"Taxels that hold their maximum (above 1 N) exactly for over 0.5 s, a flat top as at the end of a calibration "
               f"curve: {sat_txt}." if sat_txt else "No taxel holds a maximum above 1 N for over 0.5 s.") + "</p>")
    win_txt = (f"This is the window {w0:.1f}–{w1:.1f} s of the {span + 1 / FPS:.1f} s episode, cut to keep the page under 2 MB. "
               if window is not None else "")
    notes = (
        f"<p>Episode <code>{eid}</code> ({m['scene']}, {m['actor_id']}, recorded {m['collection_date']}), task {m['task_id']}. "
        f"Instruction from the release: {m['instruction'].split('] ', 1)[-1]}</p>"
        f"<p>{win_txt}One 30 Hz clock on the head camera's frame timestamps (Unix seconds in <code>rgb_head.csv</code>). Every stream "
        f"shows its latest sample at or before each tick: the wrist and depth videos by their own frame timestamps (largest "
        f"offset {max(cam_lag['wrist_left'], cam_lag['wrist_right']) * 1000:.0f} ms), the gloves by their per-sample timestamps "
        f"(left {chk['left']['rate']:.1f} Hz, right {chk['right']['rate']:.1f} Hz native; the release's glove_rate_hz is "
        f"{m['glove_rate_hz']}). All four videos are re-encoded to H.264 from the release's 1280 × 720 files; depth "
        f"(16-bit millimetres, FFV1) is colour-mapped from {DEPTH_MM[0]} mm (red) to {DEPTH_MM[1]} mm (blue), black where "
        f"the camera has no depth.</p>"
        f"<p>Taxels: each glove stores 15 pads (<code>tactile_0</code>–<code>5</code>, <code>7</code>–<code>9</code>, "
        f"<code>11</code>–<code>13</code>, <code>15</code>, <code>16</code>, <code>18</code>), 880 values, normal force per taxel "
        f"in newtons. The dataset card calls the values the glove's calibrated output; the episode file marks the unit as "
        f"<code>newton_assumed_from_vendor_calibrated_output</code>. Each pad is drawn as its rows × columns of squares at the "
        f"position the release's <code>metadata/glove_geometry_&lt;side&gt;.json</code> gives it in a flat palmar view (fingertips up; "
        f"left glove thumb on the right, right glove thumb on the left); pads are spaced apart a little more than in that "
        f"drawing so every taxel gets its own square. Colour is the value in N with {RANGE:g} N as full scale (fixed for the "
        f"collection; 1.5 N is the 99.6th percentile of taxel readings above 0.02 N in the 8 sampled episodes). Regions: thumb = tip and middle "
        f"pads, palm = thenar and hypothenar pads (the release names the thenar pad <code>thumb_base_thenar</code>).</p>"
        f"<p>Tangential components: <code>tf_tactile_x_&lt;k&gt;</code> and <code>tf_tactile_y_&lt;k&gt;</code> per taxel, unit "
        f"not stated. The yellow arrow on each pad is their sum over the pad, drawn along the geometry file's per-taxel "
        f"<code>dir_x</code> / <code>dir_y</code> axes (the release gives these axes but does not say that tf_x and tf_y "
        f"follow them); a full block is {vrange:g}. The plots show the magnitude per region and the total normal force per glove. "
        + "Per taxel, the median ratio of |(tf_x, tf_y)| to the normal force where the normal force is above 0.2 N is "
        + " and ".join(f"{q * 100:.2g}% ({s})" if q is not None else f"not defined ({s} glove never above 0.2 N)" for q, s in zip(ratio, ("left", "right")))
        + " in this episode; across the 8 sampled episodes it ranges from 0.02% to 2.3%.</p>"
        + "<p>In the 9 episodes opened while preparing this sample, some storage positions never read above 0.05 N in either glove: "
        "in every finger's distal pad, row 8 (the last row at the fingertip) columns 2–5 and row 7 columns 1, 2 and 6 (rows counted from 0 at the "
        "proximal end), and most of the thumb tip pad's last four rows. The release counts all 880 positions as taxels; whether these "
        "positions sense is not stated.</p>"
        + (f"<p>Pads with no reading in this episode (|value| below 0.01 N and tangential exactly 0 throughout; untouched or not working, the files cannot tell which): {flat_txt}.</p>" if flat_txt else "")
        + qual
        + f"<p>Not shown: the release's <code>episode.h5</code> (the same glove values as float32, trimmed to the episode, with a "
        f"30 Hz index into each video), IMU acceleration, the glove frame counter, glove calibration tables and camera "
        f"calibration.</p>")
    title = m["task_name"][0].upper() + m["task_name"][1:]
    item = {"id": vid, "title": title, "label": f"{m['scene']} · {m['actor_id'].replace('_', ' ')}",
            "sub": f"{dur:.0f} s · glove {m['glove_rate_hz']:.0f} Hz", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    p = site / "data" / f"{vid}.json"
    p.write_text(json.dumps(out, separators=(",", ":")))
    media_mb = sum((media / f"{vid}_{k}.mp4").stat().st_size for k, _, _ in VIDEOS) / 1e6
    print(json.dumps({**item, "episode": eid, "json_mb": round(p.stat().st_size / 1e6, 3), "media_mb": round(media_mb, 1),
                      "window": [w0, w1], "cam_lag_ms": {k: round(v * 1000) for k, v in cam_lag.items()}, "vrange": vrange,
                      "glove": chk, "contact_peak_s": round(pk / FPS, 2)}, default=float))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", nargs="+", help="episode_id values from metadata/episodes.parquet")
    f.add_argument("--meta", type=Path, default=Path("~/data/ext/touchscale/meta"))
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    c.add_argument("--meta", type=Path, default=Path("~/data/ext/touchscale/meta"))
    c.add_argument("--window", type=float, nargs=2, default=None, metavar=("T0", "T1"),
                   help="seconds from the first head frame to keep (default: whole episode)")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.episodes, a.meta.expanduser())
    else:
        for ep in a.episode:
            convert(ep.expanduser(), a.site, a.meta.expanduser(), a.window)


if __name__ == "__main__":
    main()
