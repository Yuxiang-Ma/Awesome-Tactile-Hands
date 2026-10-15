#!/usr/bin/env python
"""Tactile textiles (Luo et al., Nature Electronics 2021) -> viewer grid recordings (site/data/se_*.json + posters).

The release is two zip archives in the project's open Dropbox folder (data_classification.zip, data_sensing_correction.zip)
holding one HDF5 file per recording: 'pressure' (frames x 32 x 32 uint16, raw 10-bit ADC counts, rising with pressure),
'ts' (int64 microseconds since the Unix epoch) and 'frame_count' (valid rows; the arrays are preallocated). Scale
recordings hold 'scale' (int32 raw counts) instead of 'pressure'. There is no video.

`fetch` reads the zips' central directories over HTTP range requests and extracts only the members a sampled episode
needs (plus the glove layout CSVs); members already on disk are kept. `convert` writes one episode per argument:

    python -I ext/senstextile.py fetch ~/data/ext/senstextile EPISODE ...
    python -I ext/senstextile.py convert --site site ~/data/ext/senstextile EPISODE[@t0] ...

EPISODE is the release path without extension, e.g. glove_objclaassification_26obj/mug/mug_1,
glove_calibration/rec_2019-12-17_18-40-25, vest_calibration/rec_2019-12-14_15-17-58. '@t0' sets the start of the
45 s window in seconds after the glove file's first timestamp (default: the windows in SAMPLE).

Layout: the glove is drawn with the release's own visualizer files (visualization/glove/glove_right_vis_sensor.csv,
20 quadrilateral patches mapping 32x32 readout cells onto a palm-side drawing of the right hand), placed exactly as the
authors' sensing_correction/visualizer.py (commit b3ac601) places them; each taxel then paints the part of the hand
drawing nearest to it. The vest is drawn with visualization/vest/vest_back_vis_sensor.csv (one quad mapping the whole
32x32 grid row-major onto the back view: row 0 on top, column 0 on the left), as the authors' vest calibration loads it
(visualizer('vest', 'back')). The KUKA sleeve is drawn from visualization/kuka/Sensor_info.txt (630 sleeve cells, each with
a 3-D position and normal on the link_1_origin.obj mesh; the authors' sleeve mask): unrolled around the link's vertical
axis (cylindrical projection, seen from outside), each taxel painting the nearby part of the unrolled sheet. The other
394 readout cells are not part of the sleeve and are only counted.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

CODE = "https://github.com/YunzhuLi/senstextile/tree/b3ac6013b09a681fe63a68fb749ae8c3cb017c29"
PROJECT = "https://senstextile.csail.mit.edu/"
PAPER = "https://doi.org/10.1038/s41928-021-00558-0"
FOLDER = "https://www.dropbox.com/sh/g70n60jfutzd0l5/AACnOgtLUG8tHbU8TLn5MBFba?dl=0"
ZIPS = {   # per-file links of the project page's shared folder; they answer HTTP Range requests
    "data_classification": ("https://www.dropbox.com/scl/fo/64ban5axg6sojhm308lo7/AD790YivcRn7NhTlAI9Fn3Q/"
                            "data_classification.zip?rlkey=87c1dzhggtql20akgejjhvo2g&dl=1", 451237552),
    "data_sensing_correction": ("https://www.dropbox.com/scl/fo/64ban5axg6sojhm308lo7/AGMyBUd_JvmW_YFM-fZ5e-E/"
                                "data_sensing_correction.zip?rlkey=87c1dzhggtql20akgejjhvo2g&dl=1", 222448110)}
LAYOUT = "data_sensing_correction/visualization/glove/glove_right_vis_sensor.csv"
VEST_LAYOUT = "data_sensing_correction/visualization/vest/vest_back_vis_sensor.csv"
KUKA_LAYOUT = "data_sensing_correction/visualization/kuka/Sensor_info.txt"
KUKA_PITCH = 0.0025    # m per viewer cell of the unrolled sleeve
KUKA_PAINT = 0.007     # m: viewer cells within this distance of a sleeve taxel are painted by the nearest one
KUKA_AXIS_Z = 0.04     # m: cells below this height fit the link's cylinder (axis and radius of the unrolling)
SAMPLE = {   # survey pipeline/surveys/senstextile.json: 45 s windows, seconds after the glove file's first ts
    "glove_objclaassification_26obj/mug/mug_1": 32,
    "glove_objclaassification_26obj/chain/chain_2": 111,
    "glove_objclaassification_26obj/scissors/scissors_3": 95,
    "glove_objclaassification_26obj/ball/ball_4": 73,
    "glove_objclaassification_26obj/pen/pen_4": 68,
    "glove_calibration/rec_2019-12-17_18-40-25": 399,
    "vest_calibration/rec_2019-12-14_15-17-58": 860,
    "kuka_calibration/rec_2019-12-12_17-17-46": 1740}
WIN = 45.0
THRESH = 1000          # authors: readings above 1000 are artifacts (utils.filter_artifact_in_touch, thresh=1000)
T_WIN, S_NB = 5, 1     # their temporal window and neighbourhood
# per-cell rest level, a percentile over the whole recording, as the authors' clip_base_response: 50 for the glove,
# the KUKA sleeve and (no baseline in their classification code) the object recordings, 5 for the vest
REST_PCT = {"glove": 50, "kuka": 50, "vest": 5}
TOPS = {"object": 100.0, "scale": 200.0, "vest": 200.0, "kuka": 200.0}   # colour scale end, counts above rest: object
# recordings are light holds (99.5th percentile of the readings above rest 65-98 counts in the sampled windows), the
# calibration recordings press hard (150-181); one fixed end per kind
SCALE_DROP = 1_000_000  # authors: scale readings below 1e6 are dropouts (utils.filter_artifact_in_scale, thresh=1e6)
ACT = 50               # counts above rest that count a cell as responding (rest noise is a few counts; survey contact test)
PITCH = 0.06           # hand-drawing units per viewer cell (taxels are ~0.1 apart across a finger, ~0.4 along it)
GROW = 0.1             # drawing units the patches are grown by, so edge taxels (centres on the patch edge) get area
# patch index (4 rows each in the CSV) -> region; fingers from the drawing (palm-side right hand: thumb on the right,
# longest finger = middle); 14-19 are the palm
PATCH_REGION = {0: "little", 1: "little", 2: "ring", 3: "ring", 4: "ring", 5: "middle", 6: "middle", 7: "middle",
                8: "index", 9: "index", 10: "index", 11: "thumb", 12: "thumb", 13: "thumb",
                14: "palm", 15: "palm", 16: "palm", 17: "palm", 18: "palm", 19: "palm"}
REGIONS = ["thumb", "index", "middle", "ring", "little", "palm"]
STOPS = np.array([[22, 35, 51], [20, 87, 104], [33, 169, 174], [107, 218, 162], [241, 227, 112], [255, 130, 78]], np.float32)


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


# ---------------------------------------------------------------- fetch
class RangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (enough for zipfile)."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206, f"no range support ({r.status})"
            data = r.read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def layouts(ep: str) -> list[str]:
    """Layout files an episode needs besides the glove's."""
    return [VEST_LAYOUT] if ep.startswith("vest_") else [KUKA_LAYOUT] if ep.startswith("kuka_") else []


def members(ep: str) -> list[str]:
    if ep.startswith("glove_objclaassification_26obj/"):
        return [f"data_classification/{ep}.hdf5"]
    d = f"data_sensing_correction/{ep}"
    if ep.startswith("glove_calibration/"):
        return [f"{d}/touch.hdf5", f"{d}/None.hdf5"]
    return [f"{d}/touch_1.hdf5", f"{d}/touch_0.hdf5"]


def local(root: Path, member: str) -> Path:
    """Where a zip member lives: the survey unpacked data_classification under cls/ and data_sensing_correction under sc/."""
    return root / ("cls" if member.startswith("data_classification/") else "sc") / member


def fetch(root: Path, eps: list[str]) -> None:
    want = {LAYOUT} | {m for ep in eps for m in members(ep) + layouts(ep)}
    for z, (url, size) in ZIPS.items():
        todo = sorted(m for m in want if m.startswith(z + "/") and not local(root, m).exists())
        if not todo:
            continue
        zf = zipfile.ZipFile(io.BufferedReader(RangeFile(url, size), buffer_size=1 << 20))
        for m in todo:
            dst = local(root, m)
            dst.parent.mkdir(parents=True, exist_ok=True)
            print("extracting", m, file=sys.stderr)
            with zf.open(m) as s, open(dst.with_suffix(".part"), "wb") as d:
                while chunk := s.read(1 << 22):
                    d.write(chunk)
            dst.with_suffix(".part").rename(dst)
    for m in sorted(want):
        assert local(root, m).exists(), m
        print("ok", m, file=sys.stderr)


# ---------------------------------------------------------------- layout
def _line(p1, p2):
    return p1[1] - p2[1], p2[0] - p1[0], -(p1[0] * p2[1] - p2[0] * p1[1])


def _inter(L1, L2):
    D = L1[0] * L2[1] - L1[1] * L2[0]
    return (L1[2] * L2[1] - L1[1] * L2[2]) / D, (L1[0] * L2[2] - L1[2] * L2[0]) / D


def glove_points(csv: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[np.ndarray]]:
    """visualizer.init_vis_glove(side='right'), verbatim in effect: every 4 CSV rows are the corners of one patch
    (drawing x, y, readout row, readout col); the patch's readout cells are placed by intersecting the lines between
    proportional points on opposite edges. The per-patch inclusive/exclusive ranges are the authors' (they give 722 cells).
    Returns readout index (row*32 + col), drawing x, y, patch id per cell, and the patch quads."""
    rows = [l.strip().split(",") for l in csv.read_text().splitlines() if l.strip()]
    assert len(rows) == 80
    idx, X, Y, P, quads = [], [], [], [], []
    for p in range(20):
        q = rows[4 * p:4 * p + 4]
        xg = [float(r[0]) for r in q]
        yg = [float(r[1]) for r in q]
        xs = [int(r[2]) for r in q]
        ys = [int(r[3]) for r in q]
        if p in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 17, 18):
            a, b, c, d = xs[0], xs[2], ys[0], ys[1] + 1
        elif p in (14, 15):
            a, b, c, d = xs[0], xs[2], ys[0], ys[1]
        elif p == 16:
            a, b, c, d = xs[0], xs[2] + 1, ys[0], ys[1]
        else:                                   # 13, 19
            a, b, c, d = xs[0], xs[2] + 1, ys[0], ys[1] + 1
        for xx in range(a, b):
            for yy in range(c, d):
                u = (yy - ys[0]) / float(ys[1] - ys[0])
                v = (xx - xs[0]) / float(xs[2] - xs[0])
                p0 = [(xg[1] - xg[0]) * u + xg[0], (yg[1] - yg[0]) * u + yg[0]]
                p1 = [(xg[2] - xg[1]) * v + xg[1], (yg[2] - yg[1]) * v + yg[1]]
                p2 = [(xg[2] - xg[3]) * u + xg[3], (yg[2] - yg[3]) * u + yg[3]]
                p3 = [(xg[3] - xg[0]) * v + xg[0], (yg[3] - yg[0]) * v + yg[0]]
                x, y = _inter(_line(p0, p2), _line(p1, p3))
                idx.append(xx * 32 + yy)
                X.append(x)
                Y.append(y)
                P.append(p)
        quads.append(np.array([xg, yg]).T)
    idx = np.array(idx)
    assert len(idx) == 722 and len(set(idx.tolist())) == 722, "the authors' right-glove mask has 722 cells"
    return idx, np.array(X), np.array(Y), np.array(P), quads


def glove_layout(csv: Path) -> dict:
    """Painted glove: every viewer cell inside the (grown) patch quads belongs to the nearest taxel."""
    import cv2
    from scipy.spatial import cKDTree
    idx, X, Y, P, quads = glove_points(csv)
    allq = np.concatenate(quads)
    x0, x1 = allq[:, 0].min() - GROW - PITCH, allq[:, 0].max() + GROW + PITCH
    y0, y1 = allq[:, 1].min() - GROW - PITCH, allq[:, 1].max() + GROW + PITCH
    cols, rows = int(math.ceil((x1 - x0) / PITCH)), int(math.ceil((y1 - y0) / PITCH))
    SS = 4                                          # supersampled raster for the quads
    inside = np.zeros((rows * SS, cols * SS), np.uint8)
    for q in quads:
        pts = np.stack([(q[:, 0] - x0) / PITCH * SS, (y1 - q[:, 1]) / PITCH * SS], 1)
        cv2.fillPoly(inside, [np.round(pts).astype(np.int32)], 1)
    k = int(round(GROW / PITCH * SS)) * 2 + 1
    inside = cv2.dilate(inside, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    cover = inside.reshape(rows, SS, cols, SS).mean((1, 3))
    rr, cc = np.nonzero(cover >= 0.5)
    cx, cy = x0 + (cc + 0.5) * PITCH, y1 - (rr + 0.5) * PITCH
    _, own = cKDTree(np.stack([X, Y], 1)).query(np.stack([cx, cy], 1))
    paint = np.zeros((rows, cols), np.uint16)
    paint[rr, cc] = own + 1
    tr = np.clip(((y1 - Y) / PITCH).astype(int), 0, rows - 1)
    tc = np.clip(((X - x0) / PITCH).astype(int), 0, cols - 1)
    for k_ in range(len(idx)):                      # a taxel with no cell takes the cell under its point
        if not (paint == k_ + 1).any():
            paint[tr[k_], tc[k_]] = k_ + 1
    cells = np.zeros(len(idx), np.uint16)
    for k_ in range(len(idx)):
        if paint[tr[k_], tc[k_]] == k_ + 1:
            cells[k_] = tr[k_] * cols + tc[k_]
        else:
            r_, c_ = np.nonzero(paint == k_ + 1)
            j = ((r_ - tr[k_]) ** 2 + (c_ - tc[k_]) ** 2).argmin()
            cells[k_] = r_[j] * cols + c_[j]
    assert len(set(cells.tolist())) == len(idx)
    assert sorted(set(paint[paint > 0].tolist())) == list(range(1, len(idx) + 1)), "every taxel paints at least one cell"
    regions = [{"name": nm, "cells": [k_ for k_ in range(len(idx)) if PATCH_REGION[int(P[k_])] == nm]} for nm in REGIONS]
    mask = np.zeros(1024, bool)
    mask[idx] = True
    return {"idx": idx, "patch": P, "rows": rows, "cols": cols, "cells": cells, "paint": paint, "regions": regions,
            "mask": mask.reshape(32, 32)}


def vest_layout(csv: Path) -> dict:
    """visualizer.init_vis_vest(side='back'): one quad whose corners carry grid (row, col) (0,0), (0,31), (31,31), (31,0);
    the authors' inclusive ranges put all 1,024 cells on the vest. Checked here: row 0 is the top edge, column 0 the left
    edge, so the readout matrix drawn row 0 on top is the back view of the file (cells drawn square; the quad is not)."""
    rows = [l.strip().split(",") for l in csv.read_text().splitlines() if l.strip()]
    assert len(rows) == 4
    xg = np.array([float(r[0]) for r in rows])
    yg = np.array([float(r[1]) for r in rows])
    rc = [(int(r[2]), int(r[3])) for r in rows]
    assert rc == [(0, 0), (0, 31), (31, 31), (31, 0)], rc
    assert xg[1] > xg[0] and xg[2] > xg[3] and yg[0] > yg[3] and yg[1] > yg[2], "row 0 on top, column 0 on the left"
    return {"mask": np.ones((32, 32), bool), "w": float(xg[1] - xg[0]), "h": float(yg[0] - yg[3])}


def kuka_layout(txt: Path) -> dict:
    """visualizer.init_vis_kuka: every line is 'row col x y z nx ny nz' of one sleeve cell on the link mesh (metres); the
    listed cells are the authors' sleeve mask. The file states no unit; positions are read as metres. Unrolled here for a flat drawing: the link's vertical axis and radius are
    fitted (least-squares circle) to the cells below KUKA_AXIS_Z, each cell is placed at (angle around that axis x radius,
    height z), seen from outside (angle increasing to the right), cut in the empty sector between the sheet's two edges.
    Viewer cells within KUKA_PAINT of a taxel are painted by the nearest one."""
    from scipy.spatial import cKDTree
    a = np.array([[float(v) for v in l.split()] for l in txt.read_text().splitlines() if l.strip()])
    assert a.shape == (630, 8), a.shape
    r, c, P = a[:, 0].astype(int), a[:, 1].astype(int), a[:, 2:5]
    idx = r * 32 + c
    assert len(set(idx.tolist())) == 630
    low = P[:, 2] < KUKA_AXIS_Z
    x, y = P[low, 0], P[low, 1]
    cx, cy, k = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones_like(x)], x ** 2 + y ** 2, rcond=None)[0]
    R = float(np.sqrt(k + cx ** 2 + cy ** 2))
    th = np.arctan2(P[:, 1] - cy, P[:, 0] - cx)
    s = np.sort(th)
    gaps = np.diff(np.r_[s, s[0] + 2 * np.pi])
    g = int(gaps.argmax())                         # widest empty sector: the sheet's open seam
    cut = s[g] + gaps[g] / 2
    th = np.where(th > cut, th - 2 * np.pi, th)
    U, V = th * R, P[:, 2]
    x0, x1 = U.min() - KUKA_PAINT - KUKA_PITCH, U.max() + KUKA_PAINT + KUKA_PITCH
    y0, y1 = V.min() - KUKA_PAINT - KUKA_PITCH, V.max() + KUKA_PAINT + KUKA_PITCH
    cols, rows = int(math.ceil((x1 - x0) / KUKA_PITCH)), int(math.ceil((y1 - y0) / KUKA_PITCH))
    gy, gx = np.mgrid[0:rows, 0:cols]
    cxs, cys = x0 + (gx.ravel() + 0.5) * KUKA_PITCH, y1 - (gy.ravel() + 0.5) * KUKA_PITCH
    d, own = cKDTree(np.stack([U, V], 1)).query(np.stack([cxs, cys], 1))
    paint = np.where(d <= KUKA_PAINT, own + 1, 0).astype(np.uint16)
    tcell = ((y1 - V) / KUKA_PITCH).astype(int) * cols + ((U - x0) / KUKA_PITCH).astype(int)
    for _ in range(10):                            # taxels closer than a viewer cell: give each its own cell
        cnt = np.bincount(paint, minlength=631)[1:]
        lost = np.flatnonzero(cnt == 0)
        if not len(lost):
            break
        for t in lost:
            cnt = np.bincount(paint, minlength=631)[1:]
            free = (paint == 0) | (cnt[np.maximum(paint.astype(int) - 1, 0)] >= 2)
            cand = np.flatnonzero(free)
            j = cand[((cxs[cand] - U[t]) ** 2 + (cys[cand] - V[t]) ** 2).argmin()]
            paint[j] = t + 1
    assert sorted(set(paint[paint > 0].tolist())) == list(range(1, 631)), "every sleeve taxel paints a cell"
    cells = np.zeros(630, np.uint16)
    for t in range(630):
        if paint[tcell[t]] == t + 1:
            cells[t] = tcell[t]
        else:
            m = np.flatnonzero(paint == t + 1)
            cells[t] = m[((cxs[m] - U[t]) ** 2 + (cys[m] - V[t]) ** 2).argmin()]
    mask = np.zeros(1024, bool)
    mask[idx] = True
    return {"idx": idx, "rows": rows, "cols": cols, "cells": cells, "paint": paint, "mask": mask.reshape(32, 32),
            "R": R, "w3": (P.max(0) - P.min(0)).tolist(), "seam": float(np.degrees(gaps[g])), "w": float(U.max() - U.min()), "h": float(V.max() - V.min()),
            "row0_right": bool(U[r == 0].mean() > U[r == 31].mean())}


# ---------------------------------------------------------------- data
def load(path: Path, key: str) -> tuple[np.ndarray, np.ndarray]:
    import h5py
    with h5py.File(path, "r") as f:
        fc = int(f["frame_count"][0])
        ts = f["ts"][:fc].astype(np.int64)
        a = f[key][:fc]
    assert (np.diff(ts) > 0).all(), f"{path}: ts not increasing"
    return a, ts


def filter_artifacts(raw: np.ndarray, rows: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, int]:
    """utils.filter_artifact_in_touch(thresh=1000, t_win=5, s_neighbor=1) for the frames `rows` of raw (n x 32 x 32):
    a mask cell with a reading > 1000 anywhere in frames [i-5, i+5) is replaced at frame i by the mean of the mask cells
    of its 3x3 neighbourhood (itself included) that read <= 1000 at frame i, or of its 5x5 neighbourhood if there are
    none. Cells outside the mask are left as they are; a cell with no valid neighbour in 5x5 keeps its reading (the
    authors' code divides by zero there). Returns the filtered frames and the number of replaced readings."""
    from scipy.ndimage import correlate
    out = raw[rows].astype(np.float32)
    big = (raw > THRESH)
    n_rep = 0
    k3, k5 = np.ones((3, 3), np.float32), np.ones((5, 5), np.float32)
    for j, i in enumerate(rows.tolist()):
        flag = big[max(0, i - T_WIN):min(len(raw), i + T_WIN)].any(0) & mask
        if not flag.any():
            continue
        fr = raw[i].astype(np.float32)
        ok = (mask & (fr <= THRESH)).astype(np.float32)
        s3, c3 = correlate(fr * ok, k3, mode="constant"), correlate(ok, k3, mode="constant")
        s5, c5 = correlate(fr * ok, k5, mode="constant"), correlate(ok, k5, mode="constant")
        rep = np.where(c3 > 0, s3 / np.maximum(c3, 1), np.where(c5 > 0, s5 / np.maximum(c5, 1), fr))
        out[j][flag] = rep[flag]
        n_rep += int(flag.sum())
    return out, n_rep


def quant(v: np.ndarray, top: float) -> np.ndarray:
    return np.clip(np.round(v / top * 255), 0, 255).astype(np.uint8)


def ramp(v: np.ndarray, top: float) -> np.ndarray:
    x = np.clip(v / top, 0, 1) * (len(STOPS) - 1)
    i = np.minimum(len(STOPS) - 2, np.floor(x).astype(int))
    return (STOPS[i] + (STOPS[i + 1] - STOPS[i]) * (x - i)[..., None]).astype(np.uint8)


def poster(vals: np.ndarray, top: float, paint: np.ndarray, out: Path, w: int = 240, h: int = 180) -> None:
    """No video in the release: the poster is the painted glove at the frame of largest total reading, in the viewer ramp."""
    import cv2
    rgb = ramp(vals, top)
    img = np.zeros(paint.shape + (3,), np.uint8)
    img[:] = (14, 23, 28)
    img[paint > 0] = rgb[paint[paint > 0].astype(int) - 1]
    s = min((w - 8) / paint.shape[1], (h - 8) / paint.shape[0])
    sm = cv2.resize(img, (max(1, int(paint.shape[1] * s)), max(1, int(paint.shape[0] * s))), interpolation=cv2.INTER_AREA)
    can = np.zeros((h, w, 3), np.uint8)
    can[:] = (14, 23, 28)
    oy, ox = (h - sm.shape[0]) // 2, (w - sm.shape[1]) // 2
    can[oy:oy + sm.shape[0], ox:ox + sm.shape[1]] = sm
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-",
                    "-frames:v", "1", "-q:v", "3", str(out)], input=can.tobytes(), check=True)


def describe(ep: str) -> tuple[str, str, str, str]:
    """(kind, title, label, what) of an episode id."""
    parts = ep.split("/")
    if parts[0] == "glove_objclaassification_26obj":
        obj, rnd = parts[1], parts[2].rsplit("_", 1)[1]
        return "object", f"{obj.capitalize()}", f"Object set · round {rnd}", f"object recording '{obj}', round {rnd}"
    if parts[0] == "glove_calibration":
        return "scale", "Pressing on a digital scale", "Glove calibration", "glove calibration against a digital scale"
    if parts[0] == "vest_calibration":
        return "vest", "Pressing on the tactile vest", "Vest calibration", "vest calibration with the glove"
    return "kuka", "Pressing on the KUKA arm sleeve", "Sleeve calibration", "KUKA arm sleeve calibration with the glove"


def convert(root: Path, ep: str, t0: float, site: Path, lay: dict) -> dict:
    kind, title, label, what = describe(ep)
    TOP = TOPS[kind]
    mem = members(ep)
    vid = "se_" + (ep.split("/")[-1] if kind == "object" else f"{kind}_{ep.split('/')[-1].replace('rec_', '')}")
    raw, ts = load(local(root, mem[0]), "pressure")
    raw = raw.reshape(len(raw), 32, 32)
    mask = lay["mask"]
    start = ts[0] + int(round(t0 * 1e6))
    end = start + int(WIN * 1e6)
    inwin = (ts >= start) & (ts < end)
    rate = (inwin.sum() - 1) / ((ts[inwin][-1] - ts[inwin][0]) / 1e6)
    fps = int(math.ceil(rate))
    n = int(round(WIN * fps))
    tick = start + np.round(np.arange(n) * 1e6 / fps).astype(np.int64)
    row = np.searchsorted(ts, tick, "right") - 1
    assert row.min() >= 0 and row.max() < len(ts)
    gap = float(np.diff(ts[inwin]).max() / 1e6)
    urow, inv = np.unique(row, return_inverse=True)
    dup = n - len(urow)
    dropped = int(inwin.sum()) - int(((urow >= np.flatnonzero(inwin)[0]) & (urow <= np.flatnonzero(inwin)[-1])).sum())

    rest = np.percentile(raw.reshape(len(raw), -1), REST_PCT["glove"], axis=0).reshape(32, 32).astype(np.float32)
    filt, n_rep = filter_artifacts(raw, urow, mask)
    above = np.clip(filt - rest, 0, None)[inv]                              # n x 32 x 32 counts above rest
    rawwin = raw[row].astype(np.float32)
    n_big = int((rawwin > THRESH).sum())
    n_big_frames = int((rawwin > THRESH).any((1, 2)).sum())
    flat = above.reshape(n, 1024)
    G = flat[:, lay["idx"]]                                                 # n x 722, CSV order
    off = ~mask.reshape(-1)
    offsum = np.clip(rawwin.reshape(n, 1024)[:, off] - rest.reshape(-1)[off], 0, None)
    off_active = np.flatnonzero(off)[((offsum > ACT).sum(0) >= 15)].tolist()   # responding: > ACT above rest in >= 15 frames
    neg = int((rawwin.reshape(n, 1024)[:, ~off] < rest.reshape(-1)[~off] - 100).sum())
    over = float((G > TOP).mean() * 100)

    common = {"rate": round(float(rate), 2), "unit": "counts above rest"}
    hands = [{"key": "rh", "title": "Glove", "label": "722 taxels on the release's right-glove drawing", **common,
              "rows": lay["rows"], "cols": lay["cols"], "cells": b64(lay["cells"]), "paint": b64(lay["paint"]),
              "tax": b64(quant(G, TOP)), "range": TOP, "regions": lay["regions"]}]
    allcells = np.arange(1024, dtype=np.uint16)
    garment = None
    if kind == "object":
        hands.append({"key": "mx", "title": "Glove · 32×32 readout matrix", **common, "rows": 32, "cols": 32,
                      "label": "all 1,024 cells (302 outside the glove drawing; these are not filtered)",
                      "cells": b64(allcells), "tax": b64(quant(np.where(mask.reshape(-1), flat, np.clip(rawwin.reshape(n, 1024) - rest.reshape(-1), 0, None)), TOP)),
                      "range": TOP, "regions": []})
    series = []
    extra_notes = ""
    if kind in ("vest", "kuka"):
        graw, gts = load(local(root, mem[1]), "pressure")
        graw = graw.reshape(len(graw), 32, 32)
        grow_ = np.searchsorted(gts, tick, "right") - 1
        assert grow_.min() >= 0
        gu, ginv = np.unique(grow_, return_inverse=True)
        grest = np.percentile(graw.reshape(len(graw), -1), REST_PCT[kind], axis=0).reshape(32, 32).astype(np.float32)
        glay = vest_layout(local(root, VEST_LAYOUT)) if kind == "vest" else kuka_layout(local(root, KUKA_LAYOUT))
        gmask = glay["mask"]
        gfilt, g_rep = filter_artifacts(graw, gu, gmask)
        gabove = np.clip(gfilt - grest, 0, None)[ginv].reshape(n, 1024)
        grawwin = graw[grow_].astype(np.float32)
        gwin = (gts >= start) & (gts < end)
        grate = (gwin.sum() - 1) / ((gts[gwin][-1] - gts[gwin][0]) / 1e6)
        gname = "Vest (back)" if kind == "vest" else "KUKA arm sleeve"
        if kind == "vest":
            hands.append({"key": kind, "title": f"{gname} · 32×32", "rate": round(float(grate), 2),
                          "unit": "counts above rest", "label": "1,024 cells · back view from vest_back_vis_sensor.csv",
                          "rows": 32, "cols": 32, "cells": b64(allcells), "tax": b64(quant(gabove, TOP)), "range": TOP,
                          "regions": []})
            gsel = np.arange(1024)
            goff_cnt = None
        else:
            gsel = glay["idx"]
            hands.append({"key": kind, "title": f"{gname} · unrolled", "rate": round(float(grate), 2),
                          "unit": "counts above rest", "label": "630 sleeve taxels from Sensor_info.txt · seen from outside, link base at the bottom",
                          "rows": glay["rows"], "cols": glay["cols"], "cells": b64(glay["cells"]), "paint": b64(glay["paint"]),
                          "tax": b64(quant(gabove[:, gsel], TOP)), "range": TOP, "regions": []})
            goff = ~gmask.reshape(-1)
            goffv = np.clip(grawwin.reshape(n, 1024)[:, goff] - grest.reshape(-1)[goff], 0, None)
            goff_cnt = (goffv > ACT).sum(1).astype(np.float32)
            gstd = graw.reshape(len(graw), 1024).astype(np.float32).std(0)
            glay["off_active"] = np.flatnonzero(goff)[((goffv > ACT).sum(0) >= 1)].tolist()
            glay["off_std"] = float(np.median(gstd[goff]))
            glay["on_std"] = float(np.median(gstd[~goff]))
        gin = gabove[:, gsel]
        gsum, gl = gin.sum(1), G.sum(1)
        r = float(np.corrcoef(gsum, gl)[0, 1])
        series.append({"title": "Readings above 1,000 (count per frame, before filtering)", "lines": [
            {"name": "glove", "data": b64((rawwin > THRESH).sum((1, 2)).astype(np.float32)), "col": "#cb4335"},
            {"name": gname.split(" (")[0].lower() + ("" if kind == "vest" else " (630 taxels)"),
             "data": b64((grawwin.reshape(n, 1024)[:, gsel] > THRESH).sum(1).astype(np.float32)), "col": "#2e86c1"}]})
        garment = dict(name=gname, rate=grate, rep=g_rep, big=int((grawwin > THRESH).sum()), r=r,
                       big_in=int((grawwin.reshape(n, 1024)[:, gsel] > THRESH).sum()),
                       start_diff=(gts[0] - ts[0]) / 1e6, file=mem[1].split("/")[-1], lay=glay, n_cells=len(gsel),
                       count=(gin > ACT).sum(1).astype(np.float32), off_count=goff_cnt,
                       over=float((gin > TOP).mean() * 100))
    else:
        series.append({"title": "Readings above 1,000 (count per frame, before filtering)", "lines": [
            {"name": "glove", "data": b64((rawwin > THRESH).sum((1, 2)).astype(np.float32)), "col": "#cb4335"}]})
    scale = None
    if kind == "scale":
        sc, sts = load(local(root, mem[1]), "scale")
        sc = sc.astype(np.float64)
        # authors (data.py): synchronize to touch frames, subtract the mean of the first 20 synced readings after
        # replacing dropouts (< 1e6) from valid neighbours; here: rest = mean of the first 20 valid readings at or after
        # the glove's first frame
        valid = sc >= SCALE_DROP
        first = np.flatnonzero(valid & (sts >= ts[0]))[:20]
        srest = float(sc[first].mean())
        srow = np.searchsorted(sts, tick, "right") - 1
        assert srow.min() >= 0
        sv = np.where(valid[srow], sc[srow] - srest, np.nan).astype(np.float32)
        swin = (sts >= start) & (sts < end)
        srate = (swin.sum() - 1) / ((sts[swin][-1] - sts[swin][0]) / 1e6)
        ndrop = int((~valid[swin]).sum())
        nzero = int((sc[swin] == 0).sum())
        gl = G.sum(1)
        ok = np.isfinite(sv)
        r = float(np.corrcoef(gl[ok], sv[ok])[0, 1])
        series.insert(0, {"title": "Digital scale · reading minus rest (raw scale counts, unit not stated)", "lines": [
            {"name": "scale", "data": b64(sv), "col": "#17a589"}]})
        scale = dict(rest=srest, rate=srate, ndrop=ndrop, nzero=nzero, r=r, lead=(ts[0] - sts[0]) / 1e6, n=int(swin.sum()))
    series.append({"title": f"Cells more than {ACT} counts above rest (count per frame)", "lines": [
        {"name": "722 glove taxels", "data": b64((G > ACT).sum(1).astype(np.float32)), "col": "#2e86c1"},
        {"name": "302 cells outside the drawing (unfiltered)", "data": b64((offsum > ACT).sum(1).astype(np.float32)), "col": "#7f8c8d"}]
        + ([{"name": f"{garment['name'].split(' (')[0].lower()} ({garment['n_cells']:,} {'cells' if kind == 'vest' else 'taxels'})", "data": b64(garment["count"]), "col": "#cb4335"}] if garment else [])
        + ([{"name": "394 readout cells off the sleeve (unfiltered)", "data": b64(garment["off_count"]), "col": "#e67e22", "dash": True}]
           if garment and garment["off_count"] is not None else [])})

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    peak = int(G.sum(1).argmax())
    poster(G[peak], TOP, lay["paint"], media / f"{vid}.jpg")

    rc = lambda c: f"({c // 32}, {c % 32})"
    p = [f"<p>Recording <code>{mem[0].split('/', 1)[1]}</code> of the release ({what}; "
         f"<a href=\"{PROJECT}\">project page</a>, <a href=\"{PAPER}\">Luo et al., Nature Electronics 2021</a>, data from the "
         f"project's <a href=\"{FOLDER}\">Dropbox folder</a>; license not stated). The release has no video, hand pose or task "
         f"description{'; the object recordings are labelled only by the object' if kind == 'object' else ''}. "
         f"Shown: a {WIN:.0f} s window starting {t0:g} s after the file's first timestamp "
         f"(the recording is {(ts[-1] - ts[0]) / 1e6:.0f} s long). The glove samples at {rate:.2f} Hz on average in this "
         f"window (largest gap {gap:.2f} s); the clock runs at {fps} Hz and every tick shows the latest frame at or before it "
         f"({dup} frames shown twice, {dropped} not shown).</p>"]
    p.append("<p><b>Layout.</b> The glove is drawn with the release's own visualization file "
             "<code>visualization/glove/glove_right_vis_sensor.csv</code>: 20 patches (little finger 2, ring, middle, index and "
             "thumb 3 each, palm 6) that map readout cells onto a palm-side drawing of the right hand (thumb on the right). The 722 "
             f"taxels are placed exactly as the authors' <a href=\"{CODE}/sensing_correction/visualizer.py\"><code>visualizer.py</code></a> "
             "places them, and each paints the part of the drawing nearest to it (patches grown slightly so edge taxels have area). "
             "Regions follow the patches; the finger names are read from the drawing (longest finger = middle). ")
    if kind == "object":
        p[-1] += ("The release documents this layout for the calibration glove only; using it for the October 2019 object "
                  "recordings is an inference: across the 111 object files the readout columns that only the left-glove layout uses "
                  "(0–3) are almost silent, so the right-glove layout fits. A few cells outside it do respond"
                  + (f" in this window (readout row, column: {', '.join(rc(c) for c in off_active[:12])}{' …' if len(off_active) > 12 else ''})"
                     if off_active else "") +
                  "; the second panel shows the whole 32×32 readout matrix so they stay visible, and the last plot counts them.</p>")
    else:
        p[-1] += ("The authors' calibration code applies this right-glove layout (722 cells) to this recording. Cells outside it "
                  "are counted in the last plot" + (f" (responding here, readout row, column: {', '.join(rc(c) for c in off_active[:12])})" if off_active else "")
                  + ".</p>")
    p.append(f"<p><b>Values.</b> Raw 10-bit ADC counts, uncalibrated; the reading rises with pressure from a rest level of about "
             f"{np.median(rest[mask]):.0f} counts. Each cell's rest level, the median of its readings over the whole recording "
             f"(as the authors' <code>clip_base_response</code> does for the glove), is subtracted and readings below it are drawn as 0; "
             f"sensor noise (a few counts) therefore still shows as faint cells and adds a floor to the sums"
             f"{f'; {neg} glove readings in this window are more than 100 counts below rest' if neg else ''}. The colour scale ends at {TOP:.0f} "
             f"counts above rest ({'all object recordings' if kind == 'object' else 'all calibration recordings'}); {over:.2f}% of the glove readings in this window are above it. Readings above 1,000 "
             f"are treated as artifacts as in the authors' code (<code>utils.filter_artifact_in_touch</code>, threshold 1,000, ±5 frames, "
             f"3×3 then 5×5 neighbours inside the glove layout): {n_big} raw readings above 1,000 in {n_big_frames} of the {n} shown frames, "
             f"{n_rep} glove cell-frames replaced. Isolated one-frame readings just under 1,000 are not filtered. The per-region plot "
             f"sums counts above rest over each region's taxels; the last plot counts cells more than {ACT} counts above rest.</p>")
    if scale:
        p.append(f"<p><b>Scale.</b> <code>None.hdf5</code> holds the digital scale's readings (raw counts, unit not stated) on its own "
                 f"clock, {scale['rate']:.2f} Hz here, starting {scale['lead']:.1f} s before the glove; each tick shows the latest reading at or "
                 f"before it. The plot subtracts the rest level {scale['rest']:,.0f} (mean of the first 20 valid readings after the glove "
                 f"starts, as the authors zero it). Readings below 1,000,000 are dropouts (the authors replace them from neighbours) and "
                 f"are left as gaps: {scale['ndrop']} of the {scale['n']} readings in the window, {scale['nzero']} of them exactly 0. The scale "
                 f"measures the total load of the hand pressing through 3D-printed shapes (paper Methods), not a sensor on the glove; "
                 f"in this window it correlates with the glove's total at r = {scale['r']:.2f}.</p>")
    if garment:
        gl_ = garment["lay"]
        p.append(f"<p><b>{garment['name']}.</b> <code>{garment['file']}</code> is the garment's own 32×32 sensing matrix, recorded with "
                 f"the glove (<code>touch_1.hdf5</code>; the file starts {garment['start_diff']:+.2f} s from the glove's) at "
                 f"{garment['rate']:.2f} Hz; it is put on the same clock by its own timestamps. ")
        if kind == "vest":
            p[-1] += (f"Layout: the release's <code>visualization/vest/vest_back_vis_sensor.csv</code>, which the authors' vest "
                      f"calibration loads (<code>visualizer('vest', 'back')</code>), maps the whole 32×32 grid with one quad: row 0 "
                      f"along the top edge, column 0 at the left, row 31 / column 31 at the bottom right, so all 1,024 cells are vest "
                      f"sensors and the panel draws them row-major, row 0 on top, as the back view. The quad is "
                      f"{gl_['w']:.2f} × {gl_['h']:.2f} drawing units (wider than tall by {gl_['w'] / gl_['h']:.2f}); the panel draws the "
                      f"cells square. The vest outline (<code>vest_vis_outline.csv</code>) and the front-view file (the same quad, "
                      f"mirrored by the code) are not drawn. ")
        else:
            p[-1] += (f"Layout: the release's <code>visualization/kuka/Sensor_info.txt</code> lists the 630 readout cells that are "
                      f"sleeve sensors, each with a 3-D position and surface normal on the arm-link mesh "
                      f"<code>link_1_origin.obj</code>; the authors' visualizer draws them as discs on that mesh and their sleeve "
                      f"calibration uses the same 630 cells as its mask. The file states no unit; the positions are read as "
                      f"metres (they span {gl_['w3'][0]:.2f} × {gl_['w3'][1]:.2f} × {gl_['w3'][2]:.2f}), so the lengths below are in that reading. The panel unrolls those positions (this unrolling is ours): a "
                      f"vertical axis and radius ({gl_['R'] * 1000:.1f} mm) are fitted to the cells within {KUKA_AXIS_Z * 1000:.0f} mm of "
                      f"the link's base, each taxel is placed at its angle around that axis times the radius (horizontal, seen from "
                      f"outside) and its height (vertical, base at the bottom), and the sheet is cut at its open seam (a "
                      f"{gl_['seam']:.0f}° sector with no cells); readout row 0 is at the {'right' if gl_['row0_right'] else 'left'} edge "
                      f"and the columns run up the link. The sheet is {gl_['w'] * 1000:.0f} mm around by {gl_['h'] * 1000:.0f} mm high; "
                      f"where the sleeve bends over the top of the link the cylinder projection squeezes the taxels together. Each "
                      f"taxel paints the part of the sheet within {KUKA_PAINT * 1000:.0f} mm that is nearest to it, so the uneven "
                      f"spacing of the knit (about 5 to 35 mm between neighbouring rows) stays visible. The other 394 readout cells "
                      f"are not sleeve sensors: they are not drawn, and the last plot counts those more than {ACT} counts above rest "
                      f"(dashed; {len(gl_['off_active'])} of them pass it at least once in this window). Over the whole recording their "
                      f"median per-cell standard deviation is {gl_['off_std']:.2f} counts, against {gl_['on_std']:.2f} for the sleeve taxels. ")
        p[-1] += (f"Rest level: per-cell {REST_PCT[kind]}th percentile over the recording, as the authors' code "
                  f"for this garment. Artifact filter as for the glove, with the garment's mask ({garment['n_cells']:,} cells): "
                  f"{garment['big_in']} raw readings above 1,000 on {'the vest' if kind == 'vest' else 'sleeve taxels'} "
                  f"({garment['big']} on all 1,024 cells), {garment['rep']:,} cell-frames replaced; {garment['over']:.2f}% of the "
                  f"{'vest' if kind == 'vest' else 'sleeve'} readings are above the colour scale's end. The glove presses on the "
                  f"garment, so their totals correlate (r = {garment['r']:.2f} in this window).</p>")
    p.append("<p>Not shown: <code>ts</code> and <code>frame_count</code> (used for the clock). Rows beyond "
             "<code>frame_count</code> are preallocated zeros and are not read.</p>")
    notes = "".join(p)

    dur = n / fps
    sub = f"{dur:.0f} s of {(ts[-1] - ts[0]) / 1e6:.0f} s"
    item = {"id": vid, "title": title, "label": label, "sub": sub, "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": fps, "duration": dur, "videos": [], "hands": hands,
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    f = site / "data" / f"{vid}.json"
    f.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{vid}: n={n} fps={fps} rate={rate:.2f} json={f.stat().st_size / 1e6:.2f} MB peak_t={peak / fps:.1f}s "
          f"over={over:.2f}% p99.5={np.percentile(G[G > 0], 99.5) if (G > 0).any() else 0:.0f} big={n_big} rep={n_rep} "
          f"off_active={[rc(c) for c in off_active]}", file=sys.stderr)
    return item


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", nargs="*", help="default: the sampled episodes")
    c = sub.add_parser("convert")
    c.add_argument("root", type=Path)
    c.add_argument("episodes", nargs="*", help="EPISODE[@t0]; default: the sampled episodes")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    root = a.root.expanduser()
    eps = a.episodes or list(SAMPLE)
    if a.cmd == "fetch":
        fetch(root, [e.split("@")[0] for e in eps])
        return
    lay = glove_layout(local(root, LAYOUT))
    for e in eps:
        ep, _, t = e.partition("@")
        print(json.dumps(convert(root, ep, float(t) if t else SAMPLE[ep], a.site.expanduser(), lay)))


if __name__ == "__main__":
    main()
