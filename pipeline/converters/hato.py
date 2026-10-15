#!/usr/bin/env python
"""HATO episode -> viewer grid recording (site/data/ha_*.json + site/media/ha_*_<cam>.mp4 + poster).

HATO (Lin et al. 2024) releases one pickle per recorded step (about 10 Hz) holding three RealSense RGB-D frames, the UR5e
arm and Psyonic Ability hand state, the 60 hand touch readings and the teleop command. The release is a set of zip files on
Berkeley Box (no login). `fetch` pulls single episode folders out of those zips with HTTP range requests (the pour and
steak zips are split into parts that are byte-concatenated, so the parts are read as one file); `convert` turns one
extracted folder into the viewer format, building the three camera videos from the pickled RGB frames.

    python -I ext/hato.py fetch ~/data/ext/hato/raw banana bc_data_banana_random/0307_221050
    python -I ext/hato.py convert --site site --task banana ~/data/ext/hato/raw/bc_data_banana_random/0307_221050

The pickles are untrusted: they are read with a restricted unpickler that only rebuilds numpy arrays and plain containers.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import pickle
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

FPS = 10
TASKS = {"banana": "Slippery handover (banana)", "stack": "Tower block stacking", "pour": "Wine pouring", "steak": "Steak serving"}
# Psyonic touch order per hand: index, middle, ring, pinky, thumb, 6 sites each (ability-hand-api plot labels)
PSY_FINGERS = ["index", "middle", "ring", "little", "thumb"]
REGIONS = ["thumb", "index", "middle", "ring", "little"]
# position of Psyonic sites 0..5 in a 3 x 3 block, from the URDF (fsr0..5 on each distal link): 0-1-2 wrap around the
# finger at the distal row (normals 180 / 90 / 0 deg about the finger axis), 3 and 4 are the proximal pair below 0 and 2,
# 5 is the fingertip end. The thumb sites 24..29 follow the same pattern.
SITE_RC = [(1, 0), (1, 1), (1, 2), (2, 0), (2, 2), (0, 1)]
THUMB_DROP = 3
# camera index in base_rgb; robot_l (first half of every bimanual array) carries the right hand
CAMS = [("third", "Third-view camera"), ("wrist_rh", "Right wrist camera"), ("wrist_lh", "Left wrist camera")]
HAND_SLICE = {"rh": slice(0, 30), "lh": slice(30, 60)}
JOINT_SLICE = {"rh": slice(6, 12), "lh": slice(18, 24)}

# Box shared folder of the release (README "Data Files" link) and the file ids from workflow/download_dataset.sh
BOX = "https://berkeley.app.box.com/index.php?rm=box_download_shared_file&shared_name=379cf57zqm1akvr00vdcloxqxi3ucb9g&file_id={}"
ZIPS = {"banana": ["f_1512475235180"], "stack": ["f_1512698219144"],
        "pour": ["f_1513394792580", "f_1513418334040", "f_1513412800402", "f_1513388327963"],
        "steak": ["f_1513478982439", "f_1513509873535", "f_1513526807695", "f_1513547399539", "f_1513550058414",
                  "f_1513544174072", "f_1513541198161"]}

ALLOWED = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"), ("numpy", "ndarray"),
           ("numpy", "dtype"), ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar")}


class SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in ALLOWED:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"refusing {module}.{name}")


def load(p: Path) -> dict:
    with p.open("rb") as f:
        return SafeUnpickler(f).load()


class RemoteZip(io.RawIOBase):
    """Seekable read-only view over the concatenation of Box files, read with HTTP range requests in 1 MB blocks."""
    BLOCK = 1 << 20

    def __init__(self, ids):
        self.parts = [self._resolve(i) for i in ids]
        self.offs = np.cumsum([0] + [n for _, n in self.parts]).tolist()
        self.size, self.pos, self.cache, self.ids = self.offs[-1], 0, {}, list(ids)

    @staticmethod
    def _resolve(fid):
        with urllib.request.urlopen(urllib.request.Request(BOX.format(fid), method="HEAD"), timeout=60) as r:
            return r.geturl(), int(r.headers["Content-Length"])

    def _get(self, k, a, b):
        for _ in range(4):
            try:
                req = urllib.request.Request(self.parts[k][0], headers={"Range": f"bytes={a}-{b - 1}"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    assert r.status == 206
                    return r.read()
            except Exception as e:  # expired download link or a transient error: resolve again
                print("retry", e, file=sys.stderr)
                self.parts[k] = self._resolve(self.ids[k])
        raise RuntimeError("range read failed")

    def _raw(self, a, b):
        return b"".join(self._get(k, max(a, lo) - lo, min(b, hi) - lo)
                        for k, (lo, hi) in enumerate(zip(self.offs, self.offs[1:])) if a < hi and b > lo)

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else max(0, min(n, self.size - self.pos))
        if n > 4 * self.BLOCK:
            out = self._raw(self.pos, self.pos + n)
        else:
            out, p = b"", self.pos
            while len(out) < n:
                i = p // self.BLOCK
                if i not in self.cache:
                    if len(self.cache) > 64:
                        self.cache.clear()
                    self.cache[i] = self._raw(i * self.BLOCK, min(self.size, (i + 1) * self.BLOCK))
                chunk = self.cache[i][p - i * self.BLOCK:p - i * self.BLOCK + n - len(out)]
                out, p = out + chunk, p + len(chunk)
        self.pos += len(out)
        return out

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def fetch(root: Path, task: str, folder: str) -> None:
    z = zipfile.ZipFile(RemoteZip(ZIPS[task]))
    members = [i for i in z.infolist() if i.filename.startswith(folder.rstrip("/") + "/") and i.filename.endswith(".pkl")]
    assert members, f"no {folder}/*.pkl in the {task} zip"
    for i in members:
        rel = Path(i.filename)
        assert not rel.is_absolute() and ".." not in rel.parts
        dst = root / rel
        if dst.exists() and dst.stat().st_size == i.file_size:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(z.read(i))
    print(f"{folder}: {len(members)} steps", file=sys.stderr)


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def layout(key: str) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Top-left of each finger's 3 x 3 block: four fingers in a row, thumb lower on the outside (right hand: thumb on the
    left, left hand mirrored, as in the glove collections)."""
    rows, cols = THUMB_DROP + 3, 5 * 4 - 1
    o = {"thumb": (THUMB_DROP, 0), "index": (0, 4), "middle": (0, 8), "ring": (0, 12), "little": (0, 16)}
    if key == "lh":
        o = {f: (r, cols - 3 - c) for f, (r, c) in o.items()}
    return rows, cols, o


def hand(vals: np.ndarray, key: str, title: str, rng: float) -> dict:
    """vals: (n, 30) in Psyonic order. Cells are stored region by region (thumb, index, ...) so regions are contiguous."""
    rows, cols, o = layout(key)
    cells, cols_src, regions = [], [], []
    for f in REGIONS:
        k = PSY_FINGERS.index(f)
        r0, c0 = o[f]
        regions.append({"name": f, "cells": list(range(len(cells), len(cells) + 6))})
        for s, (r, c) in enumerate(SITE_RC):
            cells.append((r0 + r) * cols + c0 + c)
            cols_src.append(6 * k + s)
    tax = np.clip(np.round(vals[:, cols_src] / rng * 255), 0, 255).astype(np.uint8)
    return {"key": key, "title": title, "rate": FPS, "rows": rows, "cols": cols, "cells": b64(np.array(cells, np.uint16)),
            "tax": b64(tax), "range": rng, "unit": "ADC counts above rest", "regions": regions,
            "label": "30 FSR sites · 6 per finger"}


def glitched(v: np.ndarray) -> np.ndarray:
    """Steps whose touch bytes came through with their top bit forced on. The hand sends the 30 readings as 15 pairs of
    12-bit values packed in 3 bytes; in some steps bytes arrive OR-ed with 0x80, which adds 0x080 to the first value of a
    pair and 0x008 / 0x800 to the second (a dead site then reads 128, 8 or 2056). In the pour sessions this hits most
    steps of the right hand, often only some of the bytes. The lost bit cannot be restored, so a step is flagged when one
    byte position is set in all 15 pairs, or when three or more second values have bit 11 set at once (a single reading
    above 2047 is left alone as a possible hard press). v: (n, 30) -> (n,) bool."""
    v = v.astype(np.int64).reshape(len(v), 15, 2)
    b = [v[..., 0] & 0xFF, (v[..., 0] >> 8) | ((v[..., 1] & 0xF) << 4), v[..., 1] >> 4]
    full = np.any([((x & 0x80) > 0).all(axis=1) for x in b], axis=0)
    return full | (((v[..., 1] >> 11) & 1).sum(axis=1) >= 3)


def hold_glitched(v: np.ndarray) -> int:
    """Replace glitched steps (in place) by the latest clean step before them (the first clean step for a leading run)."""
    g = glitched(v)
    if g.all():
        raise SystemExit("every step of this hand is glitched; pick another episode")
    ok = np.flatnonzero(~g)
    src = ok[np.clip(np.searchsorted(ok, np.arange(len(v)), side="right") - 1, 0, None)]
    v[:] = v[src]
    return int(g.sum())


def stamp(p: Path) -> float:
    return dt.datetime.fromisoformat(p.stem).timestamp()


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("task", choices=sorted(TASKS))
    f.add_argument("folders", nargs="+", help="episode folders inside the zip, e.g. bc_data_banana_random/0307_221050")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, help="extracted episode folder of per-step .pkl files")
    c.add_argument("--site", type=Path, required=True)
    c.add_argument("--task", required=True, choices=sorted(TASKS))
    c.add_argument("--range", type=float, default=None, help="colour range in counts above rest (default: episode p99.9)")
    args = ap.parse_args()
    if args.cmd == "fetch":
        for folder in args.folders:
            fetch(args.root.expanduser(), args.task, folder)
    else:
        convert(args)


def convert(args) -> None:
    ep = args.episode.expanduser()
    files = sorted(ep.glob("*.pkl"), key=stamp)
    empty = [p for p in files if p.stat().st_size == 0]  # the release contains a few zero-byte step files
    files = [p for p in files if p.stat().st_size > 0]
    ts = np.array([stamp(p) for p in files])
    ts -= ts[0]
    n = int(np.floor(ts[-1] * FPS + 1e-6)) + 1
    pick = np.searchsorted(ts, np.arange(n) / FPS + 1e-6, side="right") - 1  # latest step at or before each tick
    vid = f"ha_{args.task}_{ep.name}"
    media = args.site / "media"
    media.mkdir(parents=True, exist_ok=True)

    touch, joints = [], []
    enc = {}
    last, d = -1, None
    for i in range(n):
        if pick[i] != last:
            d, last = load(files[pick[i]]), pick[i]
        rgb = d["base_rgb"]
        if not enc:
            h, w = rgb.shape[1:3]
            for k, (cam, _) in enumerate(CAMS):
                enc[cam] = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                                             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
                                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(media / f"{vid}_{cam}.mp4")],
                                            stdin=subprocess.PIPE)
        for k, (cam, _) in enumerate(CAMS):
            enc[cam].stdin.write(np.ascontiguousarray(rgb[k], np.uint8).tobytes())
        touch.append(np.asarray(d["touch"], np.float32))
        joints.append(np.asarray(d["joint_positions"], np.float32))
    for p in enc.values():
        p.stdin.close()
        assert p.wait() == 0
    touch, joints = np.stack(touch), np.stack(joints)
    assert touch.shape[1] == 60 and joints.shape[1] == 24
    bad = {k: hold_glitched(touch[:, HAND_SLICE[k]]) for k in ("rh", "lh")}

    # per-taxel rest level: 5th percentile over the episode (the sites carry very different offsets, e.g. thumbs ~1000)
    rest = np.percentile(touch, 5, axis=0)
    above = np.clip(touch - rest, 0, None)
    zero = touch.max(axis=0) == 0
    dead = []
    for j in range(0, 60, 6):
        side, finger = "right" if j < 30 else "left", PSY_FINGERS[(j % 30) // 6]
        if zero[j:j + 6].all():
            dead.append(f"{side} {finger} (all six sites)")
        else:
            dead += [f"{side} {finger} site {s}" for s in range(6) if zero[j + s]]
    rng = args.range or float(max(300, 100 * np.ceil(np.percentile(above, 99.9) / 100)))
    hands = [hand(above[:, HAND_SLICE[k]], k, t, rng) for k, t in (("lh", "Left hand"), ("rh", "Right hand"))]

    cols = ["#2e86c1", "#17a589", "#c99a06", "#d35400", "#8e44ad", "#7f8c8d"]
    names = ["index", "middle", "ring", "little", "thumb flex", "thumb rot"]
    series = [{"title": f"{side} hand · joint positions (deg)",
               "lines": [{"name": nm, "data": b64(joints[:, JOINT_SLICE[k]][:, j]), "col": cols[j]} for j, nm in enumerate(names)]}
              for k, side in (("lh", "Left"), ("rh", "Right"))]

    dur = n / FPS
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(media / f"{vid}_third.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)
    h, w = d["base_rgb"].shape[1:3]
    videos = [{"key": cam, "title": t, "src": f"media/{vid}_{cam}.mp4", "src_size": [int(w), int(h)], "fps_src": FPS} for cam, t in CAMS]
    gaps = np.diff(ts)
    notes = (f"<p>The release logs one step about every 100 ms (this episode: {len(files)} steps over {ts[-1]:.1f} s, median gap "
             f"{np.median(gaps) * 1000:.0f} ms, range {gaps.min() * 1000:.0f}–{gaps.max() * 1000:.0f} ms, from the file-name "
             f"timestamps). Everything is shown on a 10 Hz clock from the first step, each tick taking the latest step at or "
             f"before it; the three camera videos are built from the same steps (RealSense RGB, 640 × 480) and re-encoded to "
             f"H.264. Source folder <code>{ep.parent.name}/{ep.name}</code>. The release states no license; the sample videos are re-hosted here for preview with attribution.</p>"
             f"<p>Each Ability hand has six force-sensing sites on each fingertip (12-bit ADC readings; the paper puts no-contact "
             f"readings at roughly 200–400 and contact above 1000). The 3 × 3 block per finger places the six sites as in "
             f"Psyonic's URDF: the middle row wraps around the distal pad (sites 0, 1, 2; 1 faces the palm side), the bottom row "
             f"is the proximal pair (3, 4) and the top cell is the fingertip end (5). Which outer column is the radial side is "
             f"not resolved, and the columns are not mirrored between hands. The finger order index, middle, ring, pinky, thumb "
             f"follows Psyonic's API. The first half of every bimanual array belongs to the arm the HATO code labels "
             f"<code>robot_l - right hand</code>, and it is shown as the right hand. The handover task's third-view camera, "
             f"which sits behind the two arm bases, agrees: that arm is on the image right. The camera position differs "
             f"between tasks.</p>"
             f"<p>Values are counts above each site's rest level, taken as its 5th percentile over the episode (rest levels "
             f"here range {rest.min():.0f}–{rest.max():.0f}); the colour scale ends at {rng:.0f}. "
             + (f"Always zero in this episode: {', '.join(dead)}. " if dead else "")
             + "".join(f"In {b} of {n} ticks the {'right' if k == 'rh' else 'left'} hand's touch words arrived with the top bit "
                       f"forced on in its bytes (a transmission fault in the release: dead sites then read 128, 8 or 2056 and every "
                       f"second site jumps by about 2050); those ticks show the last clean reading instead. " for k, b in bad.items() if b)
             + (f"{len(empty)} zero-byte step file(s) in this folder were skipped. " if empty else "")
             + "Joint positions are the hand's six actuated joints as logged (degrees); the depth images, arm state and teleop "
             "commands are not shown.</p>")
    title = TASKS[args.task]
    item = {"id": vid, "title": title, "label": f"{args.task} · {ep.name}", "sub": f"{dur:.0f} s · {len(files)} steps",
            "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (args.site / "data").mkdir(parents=True, exist_ok=True)
    (args.site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(item), "rest", rest.round(0).tolist(), "range", rng)


if __name__ == "__main__":
    main()
