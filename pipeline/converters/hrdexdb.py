#!/usr/bin/env python
"""HRDexDB sequence -> viewer grid recording (site/data/hr_*.json + site/media/hr_*_<cam>.mp4 + poster).

HRDexDB (Lim et al. 2026, arXiv 2604.14944; HRDexDB/HRDexDB on Hugging Face, CC BY-NC 4.0) stores one folder per
sequence, <embodiment>/<object>/<seq>/, with 22-23 camera MP4s (2048 x 1536, MPEG-4 Part 2) and raw .npy robot
streams. `fetch` downloads only what the viewer needs at a pinned revision: the hand's touch streams and their time
files, the video timeline (raw/timestamps), grasp_result.json and two camera views. `convert` re-times the touch
streams onto the video frames and re-encodes the two views to H.264 (CC BY-NC 4.0 permits non-commercial
redistribution with attribution).

    python -I ext/hrdexdb.py fetch ~/data/ext/hrdexdb/eps allegro_v5/yellow_wash_tub/0 inspire_f1/brown_ramen/10 ...
    python -I ext/hrdexdb.py convert --site site ~/data/ext/hrdexdb/eps/allegro_v5/yellow_wash_tub/0 ...

Touch channels, one hand panel per embodiment (all are right hands):
  allegro_v5    raw/hand/tactile.npy (T, 4) int32 + time.npy: one reading per fingertip sensor, raw counts.
  inspire_f1    raw/hand/right_tactile.npy (T,) pickled dicts + right_tactile_time.npy: normal force, tangential force
                and tangential direction for 8 named regions (5 fingertips, 3 palm pads).
  inspire_dftp  raw/hand/force.npy (T, 6) + time.npy: one force reading per actuator (tactile.npy is empty in the
                whole release). Negative values are stored as uint16 wrap-around (65,535 = -1) and are undone here.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = "HRDexDB/HRDexDB"
REV = "98b8f8ea2e361a3c7df38b5d8f3f8395913773f2"   # main on 2026-10-15 (last commit 2026-09-20)
CODE_REV = "b8590393ed7a6f2eb93d9a9ee31d24615a7c239a"  # github.com/snuvclab/HRDexDB, for the URDF / loader references
CAMS = [("23022632", "Camera 23022632 (rig)"), ("22684755", "Camera 22684755 (rig)")]
VIDEO_W = 960
HAND_FILES = {
    "allegro_v5": ["tactile.npy", "time.npy", "position.npy"],
    "inspire_f1": ["right_tactile.npy", "right_tactile_time.npy"],
    "inspire_dftp": ["force.npy", "time.npy", "position.npy", "tactile.npy"],
}
TITLES = {"allegro_v5": "Allegro Hand V5 Plus", "inspire_f1": "Inspire RH56F1", "inspire_dftp": "Inspire RH56DFTP"}
F1_REGIONS = ["thumb", "index", "middle", "ring", "little", "palm_left", "palm_middle", "palm_right"]
SHORT = {"palm_left": "palm L", "palm_middle": "palm M", "palm_right": "palm R"}   # panel / plot names
# Allegro tactile channel order is not documented; this is the hand's own joint order (URDF joint_0..3 index,
# 4..7 middle, 8..11 ring, 12..15 thumb). `allegro_order_check` could not confirm it: in grasps all fingers close
# together, so every column correlates about equally with every finger's flexion.
ALLEGRO_CH = ["index", "middle", "ring", "thumb"]
# Inspire DFTP actuator order of raw/hand/{position,action}.npy, from the official loader
# (inspire_action_to_qpos_dof6: column 5 -> thumb_1 (rotation), 4 -> thumb_2 (bend), 3..0 -> index, middle, ring, little).
DFTP_CH = ["little", "ring", "middle", "index", "thumb", "thumb rotation"]
B, STEP, DROP = 4, 5, 6   # pad block size in grid cells, block pitch, thumb drop below the finger row


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def url(path: str) -> str:
    return f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/{path}"


# ---------------------------------------------------------------- loading (no arbitrary pickles)
class _NumpyOnly(pickle.Unpickler):
    OK = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"), ("numpy", "ndarray"),
          ("numpy", "dtype"), ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar")}

    def find_class(self, module, name):
        if (module, name) in self.OK:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"refusing {module}.{name}")


def load(p: Path):
    """np.load; object arrays (pickled in the release) go through an unpickler that only rebuilds numpy arrays."""
    try:
        return np.load(p, allow_pickle=False)
    except ValueError:
        from numpy.lib import format as F
        f = io.BytesIO(p.read_bytes())
        ver = F.read_magic(f)
        (F.read_array_header_1_0 if ver == (1, 0) else F.read_array_header_2_0)(f)
        return _NumpyOnly(f).load()


# ---------------------------------------------------------------- fetch (huggingface_hub)
def fetch(root: Path, eps: list[str]) -> None:
    from huggingface_hub import hf_hub_download
    for ep in eps:
        emb = ep.split("/")[0]
        files = ["grasp_result.json", "raw/timestamps/timestamp.npy", "raw/timestamps/frame_id.npy"]
        files += [f"raw/hand/{f}" for f in HAND_FILES[emb]] + [f"vid/{c}.mp4" for c, _ in CAMS]
        for f in files:
            if not (root / ep / f).exists():
                hf_hub_download(REPO, f"{ep}/{f}", repo_type="dataset", revision=REV, local_dir=root)
        print(ep, "fetched", file=sys.stderr)


# ---------------------------------------------------------------- timeline
def video_frames(p: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def timeline(ep: Path) -> tuple[np.ndarray, dict]:
    """Unix time of each video frame, as the official loader maps them (raw/timestamps row i <-> video frame
    frame_id[i] - 1). Frames without a row are interpolated; frame ids beyond the video are dropped."""
    ts = np.asarray(load(ep / "raw/timestamps/timestamp.npy"), float)
    fid = np.asarray(load(ep / "raw/timestamps/frame_id.npy"), int)
    nv = min(video_frames(ep / "vid" / f"{c}.mp4") for c, _ in CAMS)
    n = min(nv, int(fid.max()))
    t = np.full(n, np.nan)
    for i, f in enumerate(fid):
        if 1 <= f <= n:
            t[f - 1] = ts[i]
    have = np.isfinite(t)
    missing = int((~have).sum())
    t[~have] = np.interp(np.flatnonzero(~have), np.flatnonzero(have), t[have])
    info = {"rows": len(ts), "video_frames": nv, "n": n, "missing": missing, "dropped_ids": int((fid > n).sum()),
            "reordered": int((np.diff(fid) != 1).sum()), "nonmono": int((np.diff(t) <= 0).sum()),
            "step": float(np.median(np.diff(ts)))}
    return t, info


def latest(t_src: np.ndarray, x: np.ndarray, t_dst: np.ndarray) -> np.ndarray:
    """Latest sample at or before each tick (the first sample before the stream starts)."""
    k = np.clip(np.searchsorted(t_src, t_dst, side="right") - 1, 0, len(t_src) - 1)
    return x[k]


def nice_ceil(x: float) -> float:
    if x <= 0:
        return 1.0
    m = 10 ** np.floor(np.log10(x))
    for s in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if s * m >= x:
            return float(s * m)
    return float(10 * m)


# ---------------------------------------------------------------- layout
def pads(emb: str) -> tuple[int, int, list[tuple[str, int, int, int, int]]]:
    """Schematic right hand seen from the back (thumb on the left, as the other collections draw right hands):
    (name, row0, col0, height, width) per pad, in channel order of the panel."""
    fingers = {"index": 1, "middle": 2, "ring": 3, "little": 4}
    tip = lambda f: (f, 0, fingers[f] * STEP, B, B)
    thumb = ("thumb", DROP, 0, B, B)
    if emb == "allegro_v5":
        return DROP + B, 4 * STEP - 1, [thumb if c == "thumb" else tip(c) for c in ALLEGRO_CH]
    if emb == "inspire_f1":
        palm = {"palm_left": (STEP, 6), "palm_middle": (STEP + 7, 5), "palm_right": (STEP + 13, 6)}
        out = [thumb if r == "thumb" else tip(r) if r in fingers else (SHORT[r], DROP, palm[r][0], B + 1, palm[r][1]) for r in F1_REGIONS]
        return DROP + B + 1, 5 * STEP - 1, out
    if emb == "inspire_dftp":
        out = [thumb if c == "thumb" else ("thumb rotation", DROP + STEP, 0, B, B) if c == "thumb rotation" else tip(c) for c in DFTP_CH]
        return DROP + STEP + B, 5 * STEP - 1, out
    raise ValueError(emb)


def panel(emb: str, vals: np.ndarray, rng: float, unit: str, label: str, vectors: dict | None = None) -> dict:
    """vals: (n, k) values >= 0 per pad, in the order of pads(emb)."""
    rows, cols, pp = pads(emb)
    paint = np.zeros((rows, cols), np.uint16)
    cells = []
    for k, (_, r0, c0, h, w) in enumerate(pp):
        paint[r0:r0 + h, c0:c0 + w] = k + 1
        cells.append((r0 + h // 2) * cols + c0 + w // 2)
    order = ["thumb", "index", "middle", "ring", "little"]
    names = [p[0] for p in pp]
    reg = [{"name": f, "cells": [names.index(f)]} for f in order if f in names]
    reg += [{"name": nm, "cells": [k]} for k, nm in enumerate(names) if nm not in order]
    tax = np.clip(np.round(vals / rng * 255), 0, 255).astype(np.uint8)
    out = {"key": "rh", "title": TITLES[emb], "rate": None, "rows": rows, "cols": cols, "cells": b64(np.array(cells, np.uint16)),
           "tax": b64(tax), "range": rng, "unit": unit, "regions": reg, "paint": b64(paint.ravel()), "label": label}
    if vectors:
        out["vectors"] = vectors
    return out


# ---------------------------------------------------------------- per-embodiment touch
COLS = {"thumb": "#8e44ad", "index": "#2e86c1", "middle": "#17a589", "ring": "#c99a06", "little": "#d35400"}
PALM_COLS = {"palm L": "#7f8c8d", "palm M": "#95a5a6", "palm R": "#5d6d7e", "thumb rotation": "#7f8c8d"}


def col(name: str) -> str:
    return COLS.get(name, PALM_COLS.get(name, "#7f8c8d"))


def allegro(ep: Path, tv: np.ndarray) -> tuple[dict, list, str, np.ndarray]:
    x = np.asarray(load(ep / "raw/hand/tactile.npy"), np.float64)
    th = np.asarray(load(ep / "raw/hand/time.npy"), float)
    assert x.shape[1] == 4 and len(x) == len(th) and np.all(np.diff(th) > 0)
    v = latest(th, x, tv)
    rate = 1 / np.median(np.diff(th))
    rng = nice_ceil(v.max())
    h = panel("allegro_v5", np.clip(v, 0, None), rng, "raw counts (unit not stated)", "4 fingertip sensors · one reading each")
    h["rate"] = round(float(rate))
    note = (f"<p>Touch: <code>raw/hand/tactile.npy</code>, 4 int32 readings per sample at about {rate:.0f} Hz (median step of "
            f"<code>raw/hand/time.npy</code>), one per fingertip sensor of the Allegro Hand V5 Plus. The release does not say "
            f"which column belongs to which finger or what the unit is. The panel assumes the hand's own joint order "
            f"(index, middle, ring, thumb, as in the release's URDF); this could not be confirmed from the data, because all "
            f"fingers close together and each column follows every finger's flexion about equally. Values are raw and "
            f"not tared (rest about 0-40). The colour scale ends at {rng:g} (the episode's maximum, rounded up, so the region plot is not clipped).</p>")
    return h, [], note, v.sum(axis=1)


def f1(ep: Path, tv: np.ndarray) -> tuple[dict, list, str, np.ndarray]:
    d = load(ep / "raw/hand/right_tactile.npy")
    th = np.asarray(load(ep / "raw/hand/right_tactile_time.npy"), float)
    assert len(d) == len(th) and np.all(np.diff(th) > 0)
    keys = [f"{r}_{q}" for r in F1_REGIONS for q in ("normal_force", "tangential_force", "tangential_direction")]
    assert all(set(x) == set(keys) for x in d), "24 values in every sample"
    a = np.array([[x[k] for k in keys] for x in d], np.float64).reshape(len(d), 8, 3)
    a = latest(th, a, tv)
    nf, tf, dr = a[..., 0], a[..., 1], a[..., 2]
    rate = 1 / np.median(np.diff(th))
    rng = nice_ceil(nf.max())
    ang = np.deg2rad(np.where(dr >= 0, dr, 0))
    vx, vy = np.where(dr >= 0, tf * np.cos(ang), 0), np.where(dr >= 0, tf * np.sin(ang), 0)
    frng = nice_ceil(np.percentile(np.hypot(np.hypot(vx, vy), nf), 99.5))
    vec = {"label": "region force", "unit": "(units not stated)", "range": frng, "axes": "tangential force at its direction",
           "zname": "normal force",
           "items": [{"region": SHORT.get(r, r), "data": b64(np.stack([vx[:, k], vy[:, k], nf[:, k]], 1).astype(np.float32))}
                     for k, r in enumerate(F1_REGIONS)]}
    h = panel("inspire_f1", nf, rng, "normal force (unit not stated)", "8 regions · normal + tangential force", vec)
    h["rate"] = round(float(rate))
    nm = lambda r: SHORT.get(r, r)
    series = [{"title": "Inspire RH56F1 · tangential force per region (unit not stated)",
               "lines": [{"name": nm(r), "data": b64(tf[:, k].astype(np.float32)), "col": col(nm(r))} for k, r in enumerate(F1_REGIONS)]},
              {"title": "Inspire RH56F1 · tangential direction per region (0-359, gap = -1 / no load)",
               "lines": [{"name": nm(r), "data": b64(np.where(dr[:, k] >= 0, dr[:, k], np.nan).astype(np.float32)), "col": col(nm(r))}
                         for k, r in enumerate(F1_REGIONS)], "fixed": [0, 360]}]
    flat = [nm(r) for k, r in enumerate(F1_REGIONS) if nf[:, k].max() == 0 and tf[:, k].max() == 0]
    note = (f"<p>Touch: <code>raw/hand/right_tactile.npy</code>, one dict per sample at about {rate:.0f} Hz "
            f"(<code>right_tactile_time.npy</code>) with <code>normal_force</code>, <code>tangential_force</code> and "
            f"<code>tangential_direction</code> for 8 named regions of the RH56F1: the five fingertips and three palm pads "
            f"(<code>palm_left</code>, <code>palm_middle</code>, <code>palm_right</code>, shown as palm L, M, R). Units are not stated. The pads are "
            f"placed on a schematic right hand seen from the back (thumb on the left); the URDF of the release has one force "
            f"sensor link per fingertip and one for the palm, but the release does not say which side <code>palm_left</code> "
            f"and <code>palm_right</code> are on, so they are drawn left to right in name order. Each pad shows the normal force; "
            f"the colour scale ends at {rng:g} (the episode's maximum, rounded up, so the region plot is not clipped).</p>"
            f"<p>The yellow arrow on each pad is the tangential force drawn at <code>tangential_direction</code>, read as degrees "
            f"counter-clockwise from the panel's x axis, and the ring is the normal force; a full-pad arrow or ring is {frng:g}. "
            f"The direction is 0-359 and -1 when there is no tangential load, so degrees is likely, but the release does not "
            f"state the unit or the zero direction: the arrow shows how the direction changes, not a direction on the hand. "
            f"The plots give the tangential force and direction per region.</p>"
            + (f"<p>Flat for the whole clip (0, direction -1): {', '.join(flat)}. In the release the palm regions are near 0 in "
               f"every F1 sequence checked (palm normal force at most 17 in 44 sequences).</p>" if flat else ""))
    return h, series, note, nf.sum(axis=1)


def dftp(ep: Path, tv: np.ndarray) -> tuple[dict, list, str, np.ndarray]:
    raw = np.asarray(load(ep / "raw/hand/force.npy"), np.int64)
    th = np.asarray(load(ep / "raw/hand/time.npy"), float)
    tac = load(ep / "raw/hand/tactile.npy")
    assert tac.size == 0 and raw.shape[1] == 6 and len(raw) == len(th) and np.all(np.diff(th) > 0)
    assert raw.min() >= 0 and raw.max() <= 65535
    f = np.where(raw > 32767, raw - 65536, raw).astype(np.float64)
    pos = np.asarray(load(ep / "raw/hand/position.npy"), np.float64)
    v = latest(th, f, tv)
    p = latest(th, pos, tv)
    rate = 1 / np.median(np.diff(th))
    rng = nice_ceil(v.max())
    h = panel("inspire_dftp", np.clip(v, 0, None), rng, "actuator force (unit not stated)", "6 actuator force readings")
    h["rate"] = round(float(rate))
    series = [{"title": "Inspire RH56DFTP · actuator force, signed (unit not stated)",
               "lines": [{"name": c, "data": b64(v[:, k].astype(np.float32)), "col": col(c)} for k, c in enumerate(DFTP_CH)]},
              {"title": "Inspire RH56DFTP · actuator position (raw, 0-1000)",
               "lines": [{"name": c, "data": b64(p[:, k].astype(np.float32)), "col": col(c)} for k, c in enumerate(DFTP_CH)]}]
    note = (f"<p>Touch: the RH56DFTP's <code>raw/hand/tactile.npy</code> is empty (shape (0,)) here and in every DFTP sequence "
            f"of the release, so the only touch-related signal is <code>raw/hand/force.npy</code>: 6 readings per sample at about "
            f"{rate:.0f} Hz (<code>raw/hand/time.npy</code>), one per actuator. The release stores negative values as unsigned "
            f"16-bit wrap-around (65,535 = -1); they are converted back here (min {v.min():.0f} in this clip). The unit and the "
            f"column order are not documented. The panel uses the actuator order of <code>raw/hand/position.npy</code> that the "
            f"official loader applies (little, ring, middle, index, thumb bend, thumb rotation) and assumes force uses the same "
            f"order. Each actuator is drawn as one pad on its finger of a schematic right hand seen from the back; the thumb "
            f"rotation actuator sits at the thumb base. There is one reading per actuator, not per contact area. Pads show the force clipped at 0; the colour scale ends at {rng:g} (the episode's "
            f"maximum, rounded up). The plots give the signed force and the actuator positions.</p>")
    return h, series, note, np.clip(v, 0, None).sum(axis=1)


def allegro_order_check(ep: Path) -> None:
    """Print, for each tactile column, how strongly it co-varies with the flexion of each finger's joints (URDF order)."""
    x = np.asarray(load(ep / "raw/hand/tactile.npy"), float)
    th = np.asarray(load(ep / "raw/hand/time.npy"), float)
    q = np.asarray(load(ep / "raw/hand/position.npy"), float)
    flex = np.stack([q[:, 4 * f + 1:4 * f + 4].sum(1) for f in range(4)], 1)  # joints 1-3 of each finger (curl)
    print("corr(tactile col, finger curl) rows=cols 0-3, cols=index middle ring thumb", file=sys.stderr)
    print(np.round(np.corrcoef(x.T, flex.T)[:4, 4:], 2), file=sys.stderr)


# ---------------------------------------------------------------- convert
def transcode(src: Path, n: int, fps: float, dst: Path) -> None:
    """First n frames, re-timed to the recording's frame clock (frame k at k / fps), H.264."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", str(n), "-an",
                    "-vf", f"setpts=N/({fps}*TB),scale={VIDEO_W}:-2", "-r", f"{fps}",
                    "-c:v", "libx264", "-crf", "28", "-g", "30", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(dst)], check=True)


def convert(ep: Path, site: Path) -> None:
    emb, obj, seq = ep.parts[-3:]
    tv, info = timeline(ep)
    n = info["n"]
    fps = round(1 / info["step"], 2)
    h, series, tnote, total = {"allegro_v5": allegro, "inspire_f1": f1, "inspire_dftp": dftp}[emb](ep, tv)
    vid = f"hr_{emb}_{obj}_{seq}"
    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    for cam, title in CAMS:
        dst = media / f"{vid}_{cam}.mp4"
        if not dst.exists():
            transcode(ep / "vid" / f"{cam}.mp4", n, fps, dst)
        videos.append({"key": f"c{cam}", "title": title, "src": f"media/{vid}_{cam}.mp4", "src_size": [2048, 1536], "fps_src": fps})
    dur = n / fps
    k = int(np.argmax(total))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{k / fps:.3f}", "-i", str(media / f"{vid}_{CAMS[0][0]}.mp4"),
                    "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)
    gr = json.loads((ep / "grasp_result.json").read_text())
    ok = {True: "grasp succeeded", False: "grasp failed"}.get(gr.get("grasp_success"), "grasp outcome not recorded")
    objname = obj.replace("_", " ")
    title = f"Grasp and lift the {objname}"
    notes = (f"<p>{TITLES[emb]} on an xArm6, teleoperated (MANUS gloves for the fingers, a Vive tracker for the wrist) to "
             f"reproduce a human grasp of the same object; sequence <code>{emb}/{obj}/{seq}</code> of the release (revision "
             f"{REV[:7]}), {ok} according to <code>grasp_result.json</code>"
             + (f", reference human sequence <code>human/{obj}/{gr['human_paired_episode']}</code>"
                if gr.get("human_paired_episode") is not None else "")
             + ".</p>"
             f"<p>Clock: one tick per video frame. <code>raw/timestamps</code> gives each video frame a time (row i belongs to "
             f"frame <code>frame_id[i]</code>, as in the official loader); the touch streams are sampled at the latest reading at "
             f"or before that time. The frame times step by a median {info['step'] * 1000:.1f} ms, so the clock runs at "
             f"{fps:g} ticks per second and plays in real time, although the MP4s are tagged 30 fps. "
             f"{info['rows']} timestamp rows, {info['video_frames']} video frames, {n} ticks"
             + (f"; {info['dropped_ids']} rows name frames beyond the end of the videos and are dropped" if info["dropped_ids"] else "")
             + (f"; {info['missing']} frame(s) without a row interpolated" if info["missing"] else "")
             + (f"; frame ids are locally out of order at {info['reordered']} row(s)" if info["reordered"] else "")
             + (f", so {info['nonmono']} frame time(s) step backwards (kept as the loader maps them)" if info["nonmono"] else "")
             + ".</p>" + tnote +
             f"<p>The two views are rig cameras {CAMS[0][0]} and {CAMS[1][0]} of the release's 21-camera rig (2048 × 1536 MPEG-4 "
             f"Part 2), cut to the {n} ticks, re-timed to the clock above and re-encoded to H.264 at {VIDEO_W} px. Not shown: the "
             f"other views, arm and hand joint streams"
             + (" (except the DFTP actuator positions)" if emb == "inspire_dftp" else "")
             + ", teleoperation streams, object 6D poses and camera calibration.</p>")
    item = {"id": vid, "title": title, "label": f"{TITLES[emb]} · {objname}", "sub": f"{dur:.0f} s · {emb}/{obj}/{seq}",
            "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": fps, "duration": dur, "videos": videos, "hands": [h],
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps({**item, "timeline": info}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", nargs="+", help="<embodiment>/<object>/<seq>")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="<root>/<embodiment>/<object>/<seq> written by fetch")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.episodes)
    else:
        for ep in a.episode:
            convert(ep.expanduser(), a.site)


if __name__ == "__main__":
    main()
