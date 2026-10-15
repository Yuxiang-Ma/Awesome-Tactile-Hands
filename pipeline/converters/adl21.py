#!/usr/bin/env python
"""ADL-21 trial -> viewer grid recording (site/data/ad_*.json + a tactile poster in site/media).

ADL-21 (Cepria-Bernal and Perez-Gonzalez, Sensors 21(8):2594, 2021; Zenodo record 4607289, CC BY 4.0) is one MATLAB
v7.3 file, dataset.mat, holding a 21 (task) x 22 (subject) struct array. Each trial has the Tekscan Grip 4256E pressure
map of the right hand at 50 Hz (presRaw, N x 725 kPa, 361 active sensels, gaps = -1) plus four products of the authors'
processing on a 101-step normalized, cross-subject time-warped timeline: presInterpSync (101 x 725 kPa), GF (total grip
force, N), CGF (per-region share of GF, 18 regions) and the warp parameters indexSync. There is no video.

The whole release is a single 49.5 MB file, so `fetch` downloads it (and sensor.png) once and checks the Zenodo md5;
`convert` reads it with h5py.

    python -I ext/adl21.py fetch ~/data/ext/adl21
    python -I ext/adl21.py convert --site site ~/data/ext/adl21/dataset.mat t01_s08 t04_s01 ...

Shown per trial: presRaw on the release's own sensor map (sensor.png = a palmar view of the right hand, as in the paper's
Figure 5), presInterpSync as a second panel and GF / CGF as plots. The 101-step products are put on the 50 Hz clock by
inverting the documented three-segment time warp (see `sync_rows`); that mapping is derived here, not stored in the release.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

RECORD = "4607289"
FILES = {"dataset.mat": "b1c5d467036bbc71cb9f900ad2588b89", "sensor.png": "4e92e178e9c9ee9827e577161156db55"}
FPS = 50                      # paper: "the sensor recorded the pressure in each sensel at a sampling rate of 50 Hz"
ROWS, COLS = 29, 25           # manufacturer matrix (Dataset description.pdf, sensor.png)
AREA = 0.016                  # N per kPa: 16 mm^2 per sensel (paper section 2.3)
SAT = 75 * 6.894757           # 0-75 psi sensor map = 0-517.1 kPa (paper section 2.2)
TOP = 250.0                   # colour scale end, kPa, same for every trial: the sampled trials' 99.9th percentiles are 113-343 kPa
FINGERS = ["thumb", "index", "middle", "ring", "little"]
# paper Table 3 (region numbers are 1-based, same order as iColRegion)
REGION_NAMES = ["thumb distal", "thumb proximal",
                "index distal", "index middle", "index proximal", "middle distal", "middle middle", "middle proximal",
                "ring distal", "ring middle", "ring proximal", "little distal", "little middle", "little proximal",
                "distal palm (2nd metacarpal)", "distal palm (3rd-5th metacarpal)", "thenar", "hypothenar"]
FINGER_OF = [0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 5]   # 5 = palm
SETUP = {**{t: 1 for t in (1, 2)}, **{t: 2 for t in range(3, 8)}, **{t: 3 for t in range(8, 13)},
         **{t: 4 for t in range(13, 17)}, **{t: 5 for t in range(17, 20)}, **{t: 6 for t in (20, 21)}}
SEATED = set(range(4, 13))    # paper Table 1
# paper Table 2, sequence of actions per task
ACTIONS = {
    1: "Taking a key from the table; inserting it in the lock; twisting it 180° clockwise; twisting it 180° counter-clockwise; extracting the key from the lock; leaving the key on the table",
    2: "Grasping the handle; twisting it completely to open; opening the door; closing the door; returning the handle to the initial position and releasing it",
    3: "Grasping a book from a shelf; moving the book to the table; leaving the book on the table with the cover facing up",
    4: "Grasping the pen from the table; writing the text “EN UN LUGAR DE LA MANCHA DE CUYO NOMBRE NO QUIERO ACORDARME” in the paper; leaving the pen on the table",
    5: "Picking up the phone with the right hand; moving the handset to the right ear; waiting for about three seconds; hanging up the phone",
    6: "Dialing the sequence of numbers 917,352 by pressing the phone keys with the index finger",
    7: "Using the keyboard with both hands to write the text “EN UN LUGAR DE LA MANCHA DE CUYO NOMBRE NO QUIERO ACORDARME”",
    8: "Grasping the bottle with the left hand; opening the cap with the right hand; leaving the cap on the table; pouring water in a glass with the right hand to fill half of the glass; leaving the bottle on the table",
    9: "Grasping the glass filled of water from the table; drinking glass content; leaving the glass on the table",
    10: "Grasping the spoon from the table; simulating taking three tablespoons; leaving the spoon in the plate",
    11: "Grasping the knife with the right hand and the fork with the left hand from the table; cutting three pieces of play-dough; leaving the knife and fork in the plate",
    12: "Grasping the fork; pricking a piece of clay and moving it to the mouth to simulate eating (three times); leaving the fork in the plate",
    13: "Opening the tab for two seconds; closing the tab; releasing the tab",
    14: "Grasping the toothbrush from a glass; brushing the teeth for five seconds; leaving the toothbrush in the glass",
    15: "Grasping the tube of toothpaste with the right hand; switching the tube to the left hand; unscrewing the cap with the right hand; switching the tube back to the right hand; grasping the toothbrush with the left hand; serving the toothpaste; leaving the tube",
    16: "Opening a drawer with the right hand; grasping a comb from the drawer; combing for five seconds; leaving the comb; closing the drawer",
    17: "Grasping glass cleaner pistol from the table; spraying three times on the vertical glass; leaving the glass cleaner pistol on the table",
    18: "Grasping the cloth; cleaning the glass; leaving the cloth",
    19: "Grasping the insecticide; spraying for half a second; leaving insecticide",
    20: "Grasping the iron from the table; ironing for five seconds; leaving the iron in the table",
    21: "Grasping the briefcase from the ground; lifting it to the table level; releasing it lying down on the table"}
LINE_COLS = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#cb4335", "#7f8c8d", "#5d6d7e", "#a04000", "#1f618d"]
STOPS = np.array([[22, 35, 51], [20, 87, 104], [33, 169, 174], [107, 218, 162], [241, 227, 112], [255, 130, 78]], np.float32)  # viewer ramp


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


# ---------------------------------------------------------------- fetch
def fetch(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, md5 in FILES.items():
        dst = root / name
        if not dst.exists():
            url = f"https://zenodo.org/api/records/{RECORD}/files/{name}/content"
            print("downloading", url, file=sys.stderr)
            urllib.request.urlretrieve(url, dst)
        h = hashlib.md5(dst.read_bytes()).hexdigest()
        assert h == md5, f"{name}: md5 {h} != Zenodo record {md5}"
        print(name, "ok", h, file=sys.stderr)


# ---------------------------------------------------------------- convert
class Mat:
    """dataset.mat via h5py: MATLAB stores arrays transposed, so the struct array is (subject, task) here."""

    def __init__(self, path: Path):
        import h5py
        self.f = h5py.File(path, "r")
        self.d = self.f["dataset"]
        self.col_sensel = self.f["colSensel"][()].T.astype(int)          # (725, 2) 1-based (row, col)
        sc = self.f["senselCol"][()].T.astype(int)                         # (29, 25)
        assert all(sc[r - 1, c - 1] == k + 1 for k, (r, c) in enumerate(self.col_sensel)), "senselCol / colSensel disagree"
        self.tasks = ["".join(map(chr, self.f[r][()].ravel())) for r in self.f["tasks"][()].ravel()]

    def get(self, key: str, t: int, s: int) -> np.ndarray:
        return self.f[self.d[key][s - 1, t - 1]][()]

    def text(self, key: str, t: int, s: int) -> str:
        return "".join(map(chr, self.get(key, t, s).ravel()))

    def regions(self, t: int, s: int) -> list[np.ndarray]:
        return [self.f[r][()].ravel().astype(int) - 1 for r in self.get("iColRegion", t, s).ravel()]


def sync_rows(ix: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """For each 50 Hz tick of the trial, the step (0..100) of the synchronized timeline in effect, and its position.

    Paper section 2.3.1: the trial's recorded time is normalized to 0..1 and resampled at steps of 0.01; the subject's
    curve is cut at t1, t2 and each piece is warped so that t1 -> t1ref and t2 -> t2ref. indexSync = [i1ref, i2ref, i1,
    i2] are those instants as 1-based rows of the 101-step grid. So synced step k shows the subject at normalized time
    w(k/100), with w piecewise linear through (0, 0), (t1ref, t1), (t2ref, t2), (1, 1). Inverting w puts every 50 Hz
    tick (normalized time j / (n - 1)) on the synced grid; the step shown is the latest one at or before it."""
    i1r, i2r, i1, i2 = (float(v) for v in ix)
    tau = np.arange(n) / (n - 1)
    pos = np.interp(tau, [0, (i1 - 1) / 100, (i2 - 1) / 100, 1], [0, (i1r - 1) / 100, (i2r - 1) / 100, 1]) * 100
    return np.clip(np.floor(pos + 1e-9), 0, 100).astype(np.uint16), pos


def layout(mat: Mat, active: np.ndarray, regs: list[np.ndarray]) -> tuple[np.ndarray, list[dict]]:
    """Viewer cell of every active column: the manufacturer matrix as drawn in the release's sensor.png (matrix column
    25 on the left, column 1 on the right), which is a palmar view of the right hand: little finger left, thumb right."""
    rc = mat.col_sensel[active]
    cells = ((rc[:, 0] - 1) * COLS + (COLS - rc[:, 1])).astype(np.uint16)
    pos = {c: k for k, c in enumerate(active.tolist())}
    groups = [[] for _ in range(6)]
    for q, cols in enumerate(regs):
        groups[FINGER_OF[q]] += [pos[c] for c in cols.tolist()]
    regions = [{"name": nm, "cells": sorted(g)} for nm, g in zip(FINGERS + ["palm"], groups)]
    assert sum(len(r["cells"]) for r in regions) == len(active) == 361
    return cells, regions


def quant(kpa: np.ndarray) -> np.ndarray:
    return np.clip(np.round(kpa / TOP * 255), 0, 255).astype(np.uint8)


def poster(frame_kpa: np.ndarray, cells: np.ndarray, out: Path, w: int = 240, h: int = 180) -> None:
    """No video in the release: the poster is the pressure map at the frame of largest total force, in the viewer ramp."""
    x = np.clip(frame_kpa / TOP, 0, 1) * (len(STOPS) - 1)
    i = np.minimum(len(STOPS) - 2, np.floor(x).astype(int))
    rgb = (STOPS[i] + (STOPS[i + 1] - STOPS[i]) * (x - i)[:, None]).astype(np.uint8)
    img = np.empty((h, w, 3), np.uint8)
    img[:] = (11, 18, 27)
    cs, gap = 5, 1
    x0, y0 = (w - (COLS * (cs + gap) - gap)) // 2, (h - (ROWS * (cs + gap) - gap)) // 2
    for k, c in enumerate(cells.tolist()):
        r, q = divmod(c, COLS)
        img[y0 + r * (cs + gap):y0 + r * (cs + gap) + cs, x0 + q * (cs + gap):x0 + q * (cs + gap) + cs] = rgb[k]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-", "-frames:v", "1",
                    "-q:v", "3", str(out)], input=img.tobytes(), check=True)


def convert(mat: Mat, ep: str, site: Path) -> dict:
    m = re.fullmatch(r"t(\d\d)_s(\d\d)", ep)
    assert m, f"episode ids look like t01_s08 (task 1, subject 8), got {ep}"
    t, s = int(m[1]), int(m[2])
    vid = f"ad_{ep}"
    raw = mat.get("presRaw", t, s).T                 # (n, 725)
    syn = mat.get("presInterpSync", t, s).T          # (101, 725)
    gf = mat.get("GF", t, s).ravel()                 # (101,)
    cgf = mat.get("CGF", t, s).T                     # (101, 18)
    ix = mat.get("indexSync", t, s).ravel()
    ref = int(mat.get("refSubj", t, s).item())
    task = mat.text("task", t, s)
    assert task == mat.tasks[t - 1]
    n = len(raw)
    active = np.flatnonzero(raw[0] >= 0)
    assert len(active) == 361 and (raw[:, active] >= 0).all() and (raw[:, np.setdiff1d(np.arange(725), active)] == -1).all()
    assert (syn[:, active] >= 0).all() and syn.shape == (101, 725) and cgf.shape == (101, 18)
    assert np.allclose(gf, AREA * syn[:, active].sum(1), atol=1e-9), "GF = 0.016 x sum of presInterpSync"
    regs = mat.regions(t, s)
    assert sorted(np.concatenate(regs).tolist()) == active.tolist()
    cells, regions = layout(mat, active, regs)
    rk, pos = sync_rows(ix, n)

    P = raw[:, active]
    S = syn[:, active]
    sat_raw = int((P > SAT).sum())
    rng = round(TOP * AREA, 3)                        # colour range in N per sensel
    over = float((P > TOP).mean() * 100)
    common = {"rate": FPS, "rows": ROWS, "cols": COLS, "cells": b64(cells), "range": rng,
              "unit": "N per sensel (kPa × 16 mm²)", "regions": regions}
    hands = [{"key": "rh", "title": "Right hand · presRaw", "label": "361 sensels", **common, "tax": b64(quant(P))},
             {"key": "sync", "title": "Right hand · presInterpSync", "label": "101 time-warped steps, held", **common,
              "tax": b64(quant(S)), "index": b64(rk)}]
    hands[1]["rate"] = None

    tt = lambda a: a.astype(np.float32)
    held = lambda a: a[rk]
    grip = [{"name": "Σ presRaw × 16 mm² (50 Hz)", "data": b64(tt(AREA * P.sum(1))), "col": "#cb4335"},
            {"name": "GF (release, warped steps held)", "data": b64(tt(held(gf))), "col": "#2e86c1"}]
    fing = np.zeros((101, 5))
    for q in range(14):
        fing[:, FINGER_OF[q]] += cgf[:, q]
    cg_lines = ([{"name": f, "data": b64(tt(held(fing[:, k]))), "col": LINE_COLS[k]} for k, f in enumerate(FINGERS)]
                + [{"name": nm, "data": b64(tt(held(cgf[:, q]))), "col": LINE_COLS[5 + q - 14], "dash": True}
                   for q, nm in zip(range(14, 18), ["palm 2nd MC", "palm 3rd–5th MC", "thenar", "hypothenar"])])
    series = [{"title": "Grip force (N): from presRaw at 50 Hz and the release's GF", "lines": grip},
              {"title": "CGF · share of grip force per region (release, warped steps held)", "lines": cg_lines, "fixed": [0, 1],
               "legendText": "fingers solid (thumb, index, middle, ring, little: phalanx regions summed); palm regions dashed "
                             "(2nd MC, 3rd–5th MC, thenar, hypothenar)"}]

    dur = n / FPS
    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    poster(P[int(P.sum(1).argmax())], cells, media / f"{vid}.jpg")
    i1r, i2r, i1, i2 = (int(v) for v in ix)
    dead = int((P.max(0) <= 0).sum())
    cg0 = int((gf <= 0).sum())
    notes = (
        f"<p>Trial <code>dataset({t},{s})</code> of <code>dataset.mat</code> (task {t}, subject {s}) from "
        f"<a href=\"https://zenodo.org/records/{RECORD}\">Zenodo record {RECORD}</a> (CC BY 4.0, Cepriá-Bernal and Pérez-González, "
        f"<a href=\"https://doi.org/10.3390/s21082594\">Sensors 2021</a>). The release has no video. The clock is the sensor's 50 Hz "
        f"sampling (paper), one row of <code>presRaw</code> per tick: {n} rows, {dur:.2f} s. "
        f"Protocol for this task (paper Table 2): {ACTIONS[t]}. Setup {SETUP[t]}, subject {'seated' if t in SEATED else 'standing'}.</p>"
        "<p><b>Layout.</b> The 361 active sensels of the Tekscan Grip 4256E are drawn at their cell of the 29 × 25 manufacturer matrix, "
        "exactly as the release's <code>sensor.png</code> draws it (matrix column 25 on the left, column 1 on the right). That drawing is a "
        "palmar view of the right hand and matches the paper's Figure 5: little finger on the left, thumb on the right beside the palm, "
        "each finger as distal / middle / proximal pads (4 + 3 + 3 rows × 4 columns), distal palm across the finger bases, thenar and "
        "hypothenar pads at the bottom. Gaps in the matrix (stored as −1) stay empty. Regions follow the release's <code>iColRegion</code> "
        "(paper Table 3): each finger sums its three phalanx regions (the thumb its two), and 'palm' sums regions 15–18.</p>"
        f"<p><b>Values.</b> Pressures are kPa in the release; the panels show force per sensel (kPa × 16 mm², the paper's sensel area), "
        f"so region sums are forces in N. The colour scale ends at {TOP:.0f} kPa = {rng} N per sensel in every trial (the sensor map goes to 517 kPa); "
        f"{over:.2f}% of this trial's sensel samples are above it and are drawn, and summed per region, at {TOP:.0f} kPa. The grip-force "
        f"plot uses the unclipped values. "
        f"<code>presRaw</code> is unfiltered: it has single-frame spikes and {sat_raw} sample(s) above the sensor map in this trial "
        f"(max {P.max():.0f} kPa); the paper median-filtered the data and discarded "
        f"saturated sensels. {dead} of the 361 sensels read 0 throughout this trial.</p>"
        "<p><b>Time-warped products.</b> <code>presInterpSync</code> (second panel), <code>GF</code> and <code>CGF</code> exist only on the "
        f"authors' 101-step timeline, normalized to the trial and time-warped to the task's reference subject (here subject {ref}). "
        f"<code>indexSync</code> = [{i1r}, {i2r}, {i1}, {i2}]: steps {i1} and {i2} of this trial were moved to steps {i1r} and {i2r}. "
        "They are put on the 50 Hz clock here by inverting that three-segment linear warp (paper section 2.3.1); each tick shows the "
        "latest step at or before it. This mapping is derived, not stored in the release: over all 462 trials, the grip force of "
        "<code>presRaw</code> (median-filtered over 3 samples, as in the paper) resampled at the warped times correlates with the release's GF at a median r = 0.95 (0.50 without the warp), so it is "
        "close but not sample-exact; the authors' filtering is not fully specified. GF equals 0.016 × the sum of "
        "<code>presInterpSync</code> (checked), so the second panel's total is GF wherever no sensel is above the colour scale. CGF is each of the 18 regions' share of GF; the plot "
        "sums the phalanx regions per finger and shows the four palm regions separately"
        + (f"; it is 0 in all regions at the {cg0} step(s) where GF is 0" if cg0 else "") + ".</p>"
        "<p>Not shown: <code>subjectSex</code>, <code>refSubj</code> and <code>indexSync</code> are trial metadata (used above). "
        "Only the right hand was instrumented.</p>")
    title = task
    item = {"id": vid, "title": title, "label": f"Setup {SETUP[t]} · subject {s}",
            "sub": f"{dur:.1f} s · {'seated' if t in SEATED else 'standing'}", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": [], "hands": hands,
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    return item


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    c = sub.add_parser("convert")
    c.add_argument("mat", type=Path, help="dataset.mat of the release")
    c.add_argument("episodes", nargs="+", help="t<task>_s<subject>, e.g. t01_s08")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser())
    else:
        mat = Mat(a.mat.expanduser())
        for ep in a.episodes:
            print(json.dumps(convert(mat, ep, a.site)))


if __name__ == "__main__":
    main()
