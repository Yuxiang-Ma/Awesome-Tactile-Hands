#!/usr/bin/env python
"""OSMO tactile glove sample -> viewer grid recording (site/data/os_00.json + site/media/os_00_*.mp4 + poster).

OSMO (Yin et al. 2025, arXiv 2512.08920) releases one sample demonstration: a public Google Drive folder "00" with four
Python pickles, each a list of 211 items aligned by list index (data/README.md of jessicayin/osmo_tactile_glove):

  mags_public.pkl      (timestamp_ns, 30 floats) per frame: index, middle, ring, pinky, thumb x (mag0, mag1) x (x, y, z)
  rgbs_public.pkl      720 x 1280 x 3 uint8, BGR (static RealSense D435 colour camera)
  left_ir_public.pkl   720 x 1280 uint8 (left IR imager, masked with white outside a region of interest)
  right_ir_public.pkl  720 x 1280 uint8 (right IR imager, masked the same way)

Google Drive has no release revision, so the converter pins the file ids and their sha256 instead and refuses other
bytes. The pickles are untrusted: they are read with restricted unpicklers (tuples/lists/numbers only for mags; for the
images only the numpy array reconstructors are allowed). The data license is not stated (no LICENSE, package.xml says
"TODO"), so the catalog re-hosts the transcoded videos under the label "License not stated".

    python -I ext/osmo.py fetch ~/data/ext/osmo/00                      # needs requests
    python -I ext/osmo.py convert --site site ~/data/ext/osmo/00        # needs numpy + ffmpeg
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np

FOLDER = "https://drive.google.com/drive/folders/1-tTdTRFNsCrTGjS2buRs-TcOSad3Dbmo"
FILES = {  # name: (Google Drive file id, sha256)
    "mags_public.pkl": ("1HbItKCHGw7IqF3jaMSK06-K0zLcfMJ14", "f134a72c821279e3e8e8583e57dc1668171637f98e612f7ba668434462f1409d"),
    "rgbs_public.pkl": ("1OONLF0aPixpwPJWMrTNXMabtYz2lyoFI", "8c407c195a729486136a85c9848b394d1a89e9c31c951ded895f52a0607c5400"),
    "left_ir_public.pkl": ("1Ha09vxpKm_h4Qi-iM1D9DuGEJiGB6sBE", "e741d65a64ad6b6865e5b117c62bdd3ed3f6a8cfa4da3b6d74ee77f135b57238"),
    "right_ir_public.pkl": ("1-IB4oDPBPhcsN0WuQIBRgY8uFRBdHzuj", "88b6e9bc7d5133f926defdfc77de7bca75194fd7e6dbcff0bf988291fa45a796"),
}
FPS = 25           # ROS2 bag logging rate (paper); the release stores no image timestamps
REST = 10          # frames averaged as the no-contact reference (the clip starts before the sponge is touched)
ORDER = ["index", "middle", "ring", "pinky", "thumb"]       # storage order (data/README.md)
FINGERS = ["thumb", "index", "middle", "ring", "pinky"]     # viewer region order
REGION = {"pinky": "little"}
# one cell per fingertip taxel, placed after the paper's Fig. 5A "Taxel Locations" (right hand, palm side, thumb on the
# right; one grid unit ~ 45 px of that figure). The seven palm taxels in the figure are not in the release.
ROWS, COLS = 6, 13
CELL = {"little": (4, 1), "ring": (1, 3), "middle": (0, 5), "index": (0, 7), "thumb": (5, 11)}
COL = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#d35400"]
XYZ = ["#2e86c1", "#17a589", "#c99a06"]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- restricted unpickling
class _Plain(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"global {module}.{name} not allowed")


class _Arrays(pickle.Unpickler):
    def find_class(self, module, name):
        from numpy._core import multiarray, numeric
        ok = {("numpy.core.multiarray", "_reconstruct"): multiarray._reconstruct,
              ("numpy._core.multiarray", "_reconstruct"): multiarray._reconstruct,
              ("numpy.core.numeric", "_frombuffer"): numeric._frombuffer,
              ("numpy._core.numeric", "_frombuffer"): numeric._frombuffer,
              ("numpy", "ndarray"): np.ndarray, ("numpy", "dtype"): np.dtype}
        if (module, name) not in ok:
            raise pickle.UnpicklingError(f"global {module}.{name} not allowed")
        return ok[(module, name)]


def load_mags(p: Path) -> tuple[np.ndarray, np.ndarray]:
    with p.open("rb") as f:
        d = _Plain(f).load()
    ts = np.array([int(x[0]) for x in d], np.int64)
    m = np.array([[float(v) for v in x[1]] for x in d], np.float64)
    assert m.shape == (len(d), 30)
    return ts, m.reshape(-1, 5, 2, 3)


def load_frames(p: Path, shape: tuple) -> list[np.ndarray]:
    with p.open("rb") as f:
        d = _Arrays(f).load()
    assert isinstance(d, list) and all(isinstance(a, np.ndarray) and a.dtype == np.uint8 and a.shape == shape for a in d), p
    return d


# ---------------------------------------------------------------- fetch
def fetch(root: Path) -> None:
    import requests
    root.mkdir(parents=True, exist_ok=True)
    for name, (fid, digest) in FILES.items():
        dst = root / name
        if not (dst.exists() and sha256(dst) == digest):
            url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dst.with_suffix(".part"), "wb") as f:
                    for chunk in r.iter_content(1 << 22):
                        f.write(chunk)
            dst.with_suffix(".part").rename(dst)
        assert sha256(dst) == digest, f"{name}: sha256 differs from the pinned release"
        print(name, "ok", file=sys.stderr)


# ---------------------------------------------------------------- convert
def encode(frames: list[np.ndarray], pix: str, width: int, dst: Path) -> None:
    h, w = frames[0].shape[:2]
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
                          "-vf", f"scale={width}:-2", "-an", "-c:v", "libx264", "-crf", "28", "-g", str(FPS), "-preset", "veryfast", "-pix_fmt", "yuv420p",
                          "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
    for a in frames:
        p.stdin.write(np.ascontiguousarray(a).tobytes())
    p.stdin.close()
    assert p.wait() == 0, dst


def convert(ep: Path, site: Path) -> None:
    for name, (_, digest) in FILES.items():
        assert sha256(ep / name) == digest, f"{name}: not the pinned release file"
    ts, m = load_mags(ep / "mags_public.pkl")
    n = len(ts)
    t = (ts - ts[0]) / 1e9
    dt = np.diff(t)
    assert (dt > 0).all()
    drift = float(np.abs(t - np.arange(n) / FPS).max())
    vid = f"os_{ep.name}"

    # differential signal per taxel (mag0 - mag1, as the paper does before its encoder), minus its no-contact rest value
    d = m[:, :, 0] - m[:, :, 1]                                   # (n, 5 storage order, 3)
    dev = d - d[:REST].mean(0)
    perm = [ORDER.index(f) for f in FINGERS]
    dev = dev[:, perm].astype(np.float32)                         # (n, 5 viewer order, 3)
    raw = (m - m[:REST].mean(0))[:, perm].astype(np.float32)      # (n, 5, 2, 3), each magnetometer minus its own rest
    noise = float(np.abs(dev[:REST]).max())
    mag = np.linalg.norm(dev, axis=-1)
    rng = float(100 * np.ceil(np.percentile(mag, 99.5) / 100))
    vrng = float(100 * np.ceil(np.percentile(mag, 99.5) / 200))  # half the colour scale: typical contact ~ one block

    cells = np.array([CELL[REGION.get(f, f)][0] * COLS + CELL[REGION.get(f, f)][1] for f in FINGERS], np.uint16)
    tax = np.clip(np.round(mag / rng * 255), 0, 255).astype(np.uint8)
    regions = [{"name": REGION.get(f, f), "cells": [k]} for k, f in enumerate(FINGERS)]
    hand = {"key": "rh", "title": "Right glove (OSMO)", "rate": FPS, "rows": ROWS, "cols": COLS, "cells": b64(cells), "tax": b64(tax),
            "range": rng, "unit": "µT as stated, |differential − rest|", "regions": regions,
            "label": "5 fingertip taxels (palm taxels not released)",
            "vectors": {"label": "fingertip differential field", "unit": "µT (as stated)", "range": vrng, "axes": "(x, y)", "zname": "z",
                        "items": [{"region": REGION.get(f, f), "data": b64(dev[:, k])} for k, f in enumerate(FINGERS)]}}

    series = [{"title": f"Fingertip differential signal · {a} (mag0 − mag1 minus rest, µT as stated)",
               "lines": [{"name": REGION.get(f, f), "data": b64(dev[:, k, c]), "col": COL[k]} for k, f in enumerate(FINGERS)]}
              for c, a in enumerate("xyz")]
    for k, f in enumerate(FINGERS):
        series.append({"title": f"{f.capitalize()} · raw magnetometers minus their rest value (mag0 solid, mag1 dashed; µT as stated)",
                       "lines": [{"name": f"mag{j} {a}", "data": b64(raw[:, k, j, c]), "col": XYZ[c], "dash": bool(j)}
                                 for j in (0, 1) for c, a in enumerate("xyz")],
                       "legendText": "x, y, z: blue, green, yellow"})

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    rgb = load_frames(ep / "rgbs_public.pkl", (720, 1280, 3))
    assert len(rgb) == n
    if not (media / f"{vid}_rgb.mp4").exists():
        encode(rgb, "bgr24", 960, media / f"{vid}_rgb.mp4")
    poster = rgb[int(np.argmax(mag.sum(1)))]
    del rgb
    for side in ("left", "right"):
        dst = media / f"{vid}_{side}_ir.mp4"
        if not dst.exists():
            ir = load_frames(ep / f"{side}_ir_public.pkl", (720, 1280))
            assert len(ir) == n
            encode(ir, "gray", 640, dst)
            del ir
    import cv2
    small = cv2.resize(poster, (240, 135), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(media / f"{vid}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 80])

    videos = [{"key": "rgb", "title": "Scene camera · RealSense D435 colour", "src": f"media/{vid}_rgb.mp4", "src_size": [1280, 720], "fps_src": FPS},
              {"key": "left_ir", "title": "Left IR (masked by the authors)", "src": f"media/{vid}_left_ir.mp4", "src_size": [1280, 720], "fps_src": FPS},
              {"key": "right_ir", "title": "Right IR (masked by the authors)", "src": f"media/{vid}_right_ir.mp4", "src_size": [1280, 720], "fps_src": FPS}]
    dur = n / FPS
    peak = {REGION.get(f, f): float(mag[:, k].max()) for k, f in enumerate(FINGERS)}
    notes = (f"<p>The only demonstration OSMO releases (Google Drive folder <a href=\"{FOLDER}\">00</a>, four Python pickles). Every stream is "
             f"a list of {n} items aligned by list index; only the tactile list carries timestamps (ROS2 receive times, spaced "
             f"{dt.min() * 1000:.0f}–{dt.max() * 1000:.0f} ms, mean {dt.mean() * 1000:.2f} ms). Here one row is one list index on a uniform "
             f"{FPS} Hz clock (the paper's logging rate), which differs from the recorded times by at most {drift * 1000:.0f} ms. "
             f"The colour and IR images are re-encoded to H.264 (960 and 640 px wide); the IR pair was masked with white by the "
             f"authors outside a region of interest. The colour images are stored in BGR order and converted to RGB.</p>"
             f"<p>Tactile: the release has the five fingertip taxels of the 12-taxel glove (palm taxels are not in it), each read by "
             f"two magnetometers (mag0, mag1) in x, y, z: 30 values per frame, unit given as µT by the paper (raw magnetic flux; "
             f"the firmware forwards the sensor values unscaled, and no force calibration is released). As in the paper's policy "
             f"input, each taxel is shown as the differential signal mag0 − mag1; the mean of the first {REST} frames (before the "
             f"sponge is touched, deviation there ≤ {noise:.0f}) is subtracted as rest. A cell's colour is the magnitude of that "
             f"deviation, scale 0–{rng:.0f} (the episode's 99.5th percentile, rounded up). The yellow arrow is its (x, y) and the "
             f"ring its z, in the magnetometer's own axes, whose orientation on the finger is not documented; a full-block arrow is "
             f"{vrng:.0f}. In this clip the change is almost entirely along y, so the arrows point up; z barely moves. Peak "
             + ", ".join(f"{k} {v:.0f}" for k, v in peak.items()) + ".</p>"
             f"<p>The five cells are placed after the paper's Fig. 5A taxel map (right hand seen from the palm, thumb on the "
             f"right); the release itself has no layout file. The plots show the differential x, y, z per finger and, per finger, "
             f"all six raw magnetometer channels minus their own rest value. Not in the release, so not shown: palm taxels, the "
             f"per-sensor IMU quaternions, depth, hand pose and the retargeted robot joints.</p>")
    title = "Wiping a marker pattern off a whiteboard with a sponge"
    item = {"id": vid, "title": title, "label": f"right hand · sample demonstration {ep.name}",
            "sub": f"{dur:.0f} s · the only released episode", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": [hand],
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(item))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("episode", type=Path, help="folder to download the four pickles into, e.g. ~/data/ext/osmo/00")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, help="folder holding the four pickles")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.episode.expanduser())
    else:
        convert(a.episode.expanduser(), a.site)


if __name__ == "__main__":
    main()
