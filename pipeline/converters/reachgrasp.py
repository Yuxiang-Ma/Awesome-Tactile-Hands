#!/usr/bin/env python
"""Reach&Grasp recording -> viewer grid recording (site/data/re_*.json + a tactile poster in site/media).

Reach&Grasp (Di Domenico et al., Scientific Data 12:233, 2025; IIT Dataverse doi:10.48557/L6OWMM, version 1.0, CC BY 4.0)
is a BIDS-like tree of headerless CSVs, one recording per subject and task (~10 repetitions each): the Bielefeld tactile
glove (58 piezoresistive taxels, 100 Hz), the CyberGlove I inside it (18 joint angles, 100 Hz), Vicon joint angles
(31 channels, 100 Hz) and two EMG systems (2 kHz). Column 0 of every CSV is time in s; channel names are in the
matching _channels.tsv. There is no video in the release.

The analysis-code repository (github.com/DarioDiDomenico/SData_ReachGrasp, MIT) holds what the viewer needs besides
the data: glove_mapping.JPG (the paper's Fig. 2A drawing of the 58 taxel pads, a palmar view of the right hand),
Curser_Reach&Grasp.mat (one hand-picked image position per taxel, in reverse CSV-column order, as Figure_9.m uses
them) and Events_Reach&Grasp.mat (start / end sample of every repetition).

    python -I ext/reachgrasp.py fetch ~/data/ext/reachgrasp sub-05_task-HC sub-03_task-Sph ...
    python -I ext/reachgrasp.py convert --site site ~/data/ext/reachgrasp sub-05_task-HC sub-03_task-Sph ...

`fetch` downloads, per recording, the tactile, CyberGlove and Vicon CSV / channels.tsv / json sidecar from the pinned
Dataverse version (md5-checked against the version's file listing) plus the three code-repo files at a pinned commit.
EMG (190 MB per recording on average) is not fetched or shown.

Shown per recording: the 58 taxels painted onto their pads of glove_mapping.JPG (segmented here, see `pad_map`), sums
per finger / palm, the three palm groups of Supplementary Table 5, CyberGlove joint angles and Vicon arm angles as
plots, and the repetitions of Events_Reach&Grasp.mat as task steps.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

DOI = "doi:10.48557/L6OWMM"
DV = "https://dataverse.iit.it"
VERSION = "1.0"                                   # released 2025-01-22, the only version
CODE_REPO = "DarioDiDomenico/SData_ReachGrasp"
CODE_SHA = "1536ba660fc7d75c2c08494fe6e0ff8fac32c4dc"   # main on 2025-04-24
CODE_FILES = ["code/glove_mapping.JPG", "code/Curser_Reach&Grasp.mat", "code/Events_Reach&Grasp.mat"]
FPS = 100                                          # every motion and tactile CSV: SamplingFrequency 100
TOP = 4000.0                                       # colour scale end (uncalibrated units), same for every recording
GROW = 5                                           # px a pad is grown into the drawn borders around it
PITCH = 10                                         # px of glove_mapping.JPG per viewer cell
# windows of the sample plan (survey): cut at a repetition boundary of Events_Reach&Grasp.mat
WINDOWS = {"sub-01_task-Screw": (0.0, 60.0), "sub-02_task-Pour": (0.0, 60.0), "sub-07_task-EatFruit": (0.0, 59.0)}
# paper Table 2 / Supplementary Table 1 wording, shortened; sidecar TaskDescription is shown as well
TASKS = {"HO": "Hand opening", "HC": "Hand closing", "WP": "Wrist pronation", "WS": "Wrist supination", "WF": "Wrist flexion",
         "WE": "Wrist extension", "Cyl": "Cylindrical grasp (glass)", "Sph": "Spherical grasp (tennis ball)",
         "Trid": "Tri-digital grasp (ping-pong ball)", "Thumb": "Thumb opposition", "FroRea": "Frontal reaching",
         "ReaCyl": "Reach and grasp the glass", "ReaSph": "Reach and grasp the tennis ball",
         "Pour": "Reach, grasp and pour with the glass", "Screw": "Reach, grasp and screw a bottle cap",
         "EatFruit": "Reach, grasp and bring the ball to the mouth"}
# Supplementary Table 5: hardware taxel ID of each CSV column (IDs 49, 50, 52, 53, 56, 64, 65 are unused)
HW_ID = list(range(1, 49)) + [51, 54, 55, 57, 58, 59, 60, 61, 62, 63]
FINGERS = ["thumb", "index", "middle", "ring", "little"]
FIRST = {"t": "thumb", "i": "index", "m": "middle", "r": "ring", "l": "little", "p": "palm"}
PALM_GROUPS = {"pd": "PalmFinger", "pt": "PalmThumb", "pc": "PalmWrist"}   # name prefix -> Supplementary Table 5 group
MALFUNCTION = ["rdd", "rdo", "rdm"]                # paper: "excluding sensor 9, 11, and 14 due malfunctions"
STOPS = np.array([[22, 35, 51], [20, 87, 104], [33, 169, 174], [107, 218, 162], [241, 227, 112], [255, 130, 78]], np.float32)  # viewer ramp
COLS6 = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#cb4335", "#7f8c8d", "#5d6d7e", "#a04000"]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- fetch
def listing(root: Path) -> list[dict]:
    p = root / f"files_v{VERSION}.json"
    if not p.exists():
        url = f"{DV}/api/datasets/:persistentId/versions/{VERSION}/files?persistentId={DOI}"
        print("listing", url, file=sys.stderr)
        urllib.request.urlretrieve(url, p)
    return json.loads(p.read_text())["data"]


def wanted(name: str, ep: str) -> bool:
    return name.startswith(ep + "_acq-") and any(f"_acq-{a}_" in name for a in ("tactileglove", "cyberglove", "vicon"))


def fetch(root: Path, episodes: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    files = listing(root)
    for ep in episodes:
        sel = [f for f in files if wanted(f["dataFile"]["filename"], ep)]
        assert len(sel) == 9, f"{ep}: expected tactile + CyberGlove + Vicon csv/tsv/json, got {[f['dataFile']['filename'] for f in sel]}"
        for f in sel:
            d = f["dataFile"]
            dst = root / f["directoryLabel"] / d["filename"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            cached = root / "tactile" / d["filename"]          # the survey downloaded every tactile file flat
            if not dst.exists() and cached.exists() and md5(cached) == d["md5"]:
                shutil.copyfile(cached, dst)
            if not dst.exists():
                url = f"{DV}/api/access/datafile/{d['id']}"
                print("downloading", d["filename"], url, file=sys.stderr)
                urllib.request.urlretrieve(url, dst)
            assert md5(dst) == d["md5"], f"{dst}: md5 differs from Dataverse version {VERSION}"
        print(ep, "ok", file=sys.stderr)
    for rel in CODE_FILES:
        dst = root / "code" / Path(rel).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            url = f"https://raw.githubusercontent.com/{CODE_REPO}/{CODE_SHA}/{urllib.request.quote(rel)}"
            print("downloading", url, file=sys.stderr)
            urllib.request.urlretrieve(url, dst)


# ---------------------------------------------------------------- layout
def pad_map(root: Path, names: list[str]) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Viewer layout from the release's own drawing: every taxel is painted over its pad of glove_mapping.JPG.

    Curser_Reach&Grasp.mat holds one point per taxel in Figure_9.m's axes (the image spans x 0..4, y 0.25..-0.25), in
    reverse CSV-column order (Figure_9.m flips it). The pads are the black regions of the image; each point picks the
    pad under it (holes left by the printed ID filled in; nearest pad if the point sits on a label). Thumb pads tdo/tdm
    touch in the JPEG and are split between their two points by distance. Pads are grown by GROW px into the white
    borders around them, then the image is sampled every PITCH px:
    a viewer cell belongs to the taxel owning most of its pixels if pads cover at least half of it.
    Returns cells (one representative cell per taxel: the one holding its point), paint (rows x cols, taxel + 1 or 0)."""
    import cv2
    import scipy.io as sio
    from scipy import ndimage as ndi
    img = cv2.imread(str(root / "code" / "glove_mapping.JPG"), cv2.IMREAD_GRAYSCALE)
    H, W = img.shape
    cur = sio.loadmat(str(root / "code" / "Curser_Reach&Grasp.mat"), squeeze_me=True, struct_as_record=False)["curser"]
    P = np.array([c.Position for c in cur], float)[::-1]
    assert P.shape == (len(names), 2)
    px, py = P[:, 0] / 4 * W, (0.25 - P[:, 1]) / 0.5 * H
    lab, _ = ndi.label(img < 40)
    sz = np.bincount(lab.ravel())
    full = np.zeros_like(lab)
    for c in np.flatnonzero(sz > 300):
        if c == 0:
            continue
        sl = ndi.find_objects((lab == c).astype(int))[0]
        full[sl][ndi.binary_fill_holes(lab[sl] == c)] = c
    pad = []
    for k in range(len(names)):
        x, y = int(round(px[k])), int(round(py[k]))
        l = full[y, x]
        if l == 0:
            yy, xx = np.nonzero(full[y - 40:y + 41, x - 40:x + 41])
            j = ((yy - 40) ** 2 + (xx - 40) ** 2).argmin()
            l = full[y - 40 + yy[j], x - 40 + xx[j]]
        pad.append(l)
    pad = np.array(pad)
    own = np.full((H, W), -1, np.int16)
    yy, xx = np.mgrid[:H, :W]
    for c in set(pad.tolist()):
        ks, m = np.flatnonzero(pad == c), full == c
        if len(ks) == 1:
            own[m] = ks[0]
        else:
            d = np.stack([(xx[m] - px[k]) ** 2 + (yy[m] - py[k]) ** 2 for k in ks])
            own[m] = ks[d.argmin(0)]
    assert sorted(set(own[own >= 0].tolist())) == list(range(len(names))), "every taxel owns a pad"
    # close the drawn white borders (~4 px) and digit cuts: pixels within GROW px of a pad join the nearest pad, so thin
    # pads stay solid on the grid and neighbours touch (the viewer draws the border between two taxels as a line)
    dist, (iy, ix) = ndi.distance_transform_edt(own < 0, return_indices=True)
    own = np.where(dist <= GROW, own[iy, ix], -1).astype(np.int16)
    ys, xs = np.nonzero(own >= 0)
    x0, y0 = xs.min(), ys.min()
    rows, cols = (ys.max() - y0) // PITCH + 1, (xs.max() - x0) // PITCH + 1
    paint = np.zeros((rows, cols), np.uint16)
    for r in range(rows):
        for q in range(cols):
            blk = own[y0 + r * PITCH:y0 + (r + 1) * PITCH, x0 + q * PITCH:x0 + (q + 1) * PITCH]
            v = blk[blk >= 0]
            if v.size * 2 >= blk.size:
                paint[r, q] = np.bincount(v).argmax() + 1
    cells = np.zeros(len(names), np.uint16)
    for k in range(len(names)):
        r, q = int((py[k] - y0) // PITCH), int((px[k] - x0) // PITCH)
        if not (0 <= r < rows and 0 <= q < cols and paint[r, q] == k + 1):   # point on the pad edge: the pad's cell nearest to it
            rr, qq = np.nonzero(paint == k + 1)
            assert len(rr), f"taxel {names[k]} has no cell at pitch {PITCH}"
            j = ((rr - r) ** 2 + (qq - q) ** 2).argmin()
            r, q = rr[j], qq[j]
        cells[k] = r * cols + q
    assert len(set(cells.tolist())) == len(names)
    return cells, paint, int(rows), int(cols)


def poster(frame: np.ndarray, paint: np.ndarray, out: Path, w: int = 240, h: int = 180) -> None:
    """No video in the release: the poster is the painted glove at the frame of largest total reading, in the viewer ramp."""
    x = np.clip(frame / TOP, 0, 1) * (len(STOPS) - 1)
    i = np.minimum(len(STOPS) - 2, np.floor(x).astype(int))
    rgb = (STOPS[i] + (STOPS[i + 1] - STOPS[i]) * (x - i)[:, None]).astype(np.uint8)
    rows, cols = paint.shape
    cs = max(1, min((w - 8) // cols, (h - 8) // rows))
    img = np.empty((h, w, 3), np.uint8)
    img[:] = (14, 23, 28)
    ox, oy = (w - cols * cs) // 2, (h - rows * cs) // 2
    for r in range(rows):
        for q in range(cols):
            k = int(paint[r, q])
            if k:
                img[oy + r * cs:oy + (r + 1) * cs, ox + q * cs:ox + (q + 1) * cs] = rgb[k - 1]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-", "-frames:v", "1",
                    "-q:v", "3", str(out)], input=img.tobytes(), check=True)


# ---------------------------------------------------------------- convert
def read(root: Path, ep: str, sub: str, acq: str, kind: str) -> tuple[np.ndarray, list[str], dict]:
    import pandas as pd
    d = root / sub / ("tactile" if acq == "tactileglove" else "motion")
    a = pd.read_csv(d / f"{ep}_acq-{acq}_{kind}.csv", header=None).to_numpy(np.float64)
    names = [l.split("\t")[0] for l in (d / f"{ep}_acq-{acq}_channels.tsv").read_text().splitlines()[1:] if l.strip()]
    side = json.loads((d / f"{ep}_acq-{acq}_{kind}.json").read_text())
    assert a.shape[1] == len(names) + 1, f"{ep} {acq}: {a.shape[1] - 1} columns, {len(names)} channel names"
    return a, names, side


def events(root: Path, sub: str, task: str) -> np.ndarray:
    import scipy.io as sio
    e = sio.loadmat(str(root / "code" / "Events_Reach&Grasp.mat"), squeeze_me=True, struct_as_record=False)["Events_ReachGrasp"]
    s = [x for x in e.subjects if x.subject_name == sub]
    t = [x for x in s[0].tasks if x.task_name == task]
    return np.asarray(t[0].time2cut, np.int64).reshape(-1, 2)


def convert(root: Path, ep: str, site: Path, layout) -> dict:
    sub, task = ep.split("_task-")
    vid = f"re_{ep}"
    tac, names, tside = read(root, ep, sub, "tactileglove", "tactile")
    cyb, cnames, _ = read(root, ep, sub, "cyberglove", "motion")
    vic, vnames, _ = read(root, ep, sub, "vicon", "motion")
    assert len(names) == 58 and tside["SamplingFrequency"] == FPS and tside["TaskName"] == task
    N0 = len(tac)
    assert len(cyb) == N0 and len(vic) == N0, f"{ep}: tactile {N0}, CyberGlove {len(cyb)}, Vicon {len(vic)} rows"
    assert np.allclose(cyb[:, 0], tac[:, 0], atol=1e-6) and np.allclose(vic[:, 0], tac[:, 0], atol=1e-6), "shared time column"
    assert abs(tac[0, 0]) < 1e-9 and np.abs(np.diff(tac[:, 0]) - 1 / FPS).max() < 1e-5, "time from 0 in steps of 0.01 s"
    assert np.isfinite(tac).all()
    w0, w1 = WINDOWS.get(ep, (0.0, N0 / FPS))
    i0, i1 = int(round(w0 * FPS)), min(N0, int(round(w1 * FPS)))
    T = tac[i0:i1, 1:]
    n = len(T)
    cells, paint, rows, cols = layout

    reg = {f: [k for k, nm in enumerate(names) if FIRST[nm[0]] == f] for f in FINGERS + ["palm"]}
    regions = [{"name": f, "cells": reg[f]} for f in FINGERS + ["palm"]]
    assert [len(reg[f]) for f in FINGERS + ["palm"]] == [7, 9, 8, 8, 9, 17], "paper Fig. 2 counts"
    tax = np.clip(np.round(np.maximum(T, 0) / TOP * 255), 0, 255).astype(np.uint8)
    dead = [nm for k, nm in enumerate(names) if not np.any(T[:, k] != 0)]
    neg = float((T < 0).mean() * 100)
    over = float((T > TOP).mean() * 100)
    hands = [{"key": "rh", "title": "Right hand · tactile glove", "label": "58 taxels on the pads of the paper's Fig. 2A",
              "rate": FPS, "rows": rows, "cols": cols, "cells": b64(cells), "paint": b64(paint.ravel()),
              "tax": b64(tax), "range": TOP, "unit": "uncalibrated (released as N)", "regions": regions}]

    f32 = lambda a: np.asarray(a, np.float32)
    clip = lambda a: np.maximum(a, 0)
    pg = [{"name": g, "data": b64(f32(clip(T[:, [k for k, nm in enumerate(names) if nm.startswith(p)]]).sum(1))), "col": COLS6[5 + q]}
          for q, (p, g) in enumerate(PALM_GROUPS.items())]
    assert sum(sum(1 for nm in names if nm.startswith(p)) for p in PALM_GROUPS) == 17
    C = {nm: cyb[i0:i1, 1 + k] for k, nm in enumerate(cnames)}
    V = {nm: vic[i0:i1, 1 + k] for k, nm in enumerate(vnames)}
    line = lambda src, nm, lab, col, dash=False: {"name": lab, "data": b64(f32(src[nm])), "col": col, **({"dash": True} if dash else {})}
    series = [
        {"title": "Palm groups · sum of taxels (uncalibrated, negatives as 0)", "lines": pg,
         "legendText": "Supplementary Table 5 groups: PalmFinger (6 taxels), PalmThumb (6), PalmWrist (5)"},
        {"title": "CyberGlove · finger flexion (deg): MCP solid, PIP / thumb IP dashed",
         "lines": [line(C, a, f + " MCP", COLS6[k]) for k, (f, a) in enumerate(zip(FINGERS, ["ThumbMPJ", "IndexMPJ", "MiddleMPJ", "RingMIJ", "PinkieMPJ"]))]
                + [line(C, a, f + (" IP" if f == "thumb" else " PIP"), COLS6[k], True)
                   for k, (f, a) in enumerate(zip(FINGERS, ["ThumbIJ", "IndexPIJ", "MiddlePIJ", "RingPIJ", "PinkiePIJ"]))],
         "legendText": "thumb, index, middle, ring, little: purple, blue, green, yellow, red"},
        {"title": "CyberGlove · thumb, abduction, palm arch, wrist (deg)",
         "lines": [line(C, a, lab, COLS6[k], k >= 5) for k, (a, lab) in enumerate([
             ("ThumbRotate", "thumb rotation"), ("ThumbAb", "thumb abduction"), ("MiddleIndexAb", "middle-index abd."),
             ("RingMiddleAb", "ring-middle abd."), ("PinkieRingAb", "little-ring abd."), ("PalmArch", "palm arch"),
             ("WristPitch", "wrist pitch"), ("WristYaw", "wrist yaw")])]},
        {"title": "Vicon · right arm joint angles (deg, Plug-in Gait)",
         "lines": [line(V, a, lab, COLS6[k % 5], k >= 4) for k, (a, lab) in enumerate([
             ("RShoulder_X", "shoulder X"), ("RShoulder_Y", "shoulder Y"), ("RShoulder_Z", "shoulder Z"), ("RElbow_X", "elbow X"),
             ("RWrist_X", "wrist X"), ("RWrist_Y", "wrist Y"), ("RWrist_Z", "wrist Z")])],
         "legendText": "shoulder X, Y, Z and elbow X solid; wrist X, Y, Z dashed"}]

    ev = events(root, sub, task)
    steps = []
    for k, (s, e) in enumerate(ev):
        a, b = (s - 1) / FPS - w0, (e - 1) / FPS - w0       # MATLAB 1-based sample index at 100 Hz -> s in the window
        if b <= 0 or a >= n / FPS:
            continue
        assert a >= 0 and b <= n / FPS + 1e-9, f"{ep}: repetition {k + 1} cut by the window"
        if steps:   # the viewer reads a gap between steps as "after the annotated window", so pauses are steps too
            steps.append({"start": steps[-1]["end"], "end": round(a, 2), "text": f"Pause between repetitions {k} and {k + 1}"})
        steps.append({"start": round(a, 2), "end": round(b, 2), "text": f"Repetition {k + 1} of {len(ev)} (Events_Reach&Grasp.mat)"})
    nrep = sum(x["text"].startswith("Repetition") for x in steps)
    tname = f"{task}: {TASKS[task]}"
    taskobj = {"task": tname, "start": steps[0]["start"], "end": steps[-1]["end"], "steps": steps}

    dur = n / FPS
    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    poster(np.maximum(T[int(np.maximum(T, 0).sum(1).argmax())], 0), paint, media / f"{vid}.jpg")
    win = (f"This is the window {w0:.0f}–{w1:.0f} s of the {N0 / FPS:.1f} s recording (rows {i0}–{i1 - 1}), cut at a repetition "
           f"boundary; it holds repetitions 1–{nrep} of {len(ev)}." if ep in WINDOWS else
           f"The whole {N0 / FPS:.1f} s recording is shown ({N0} rows).")
    notes = (
        f"<p>Recording <code>{ep}</code> of <a href=\"https://doi.org/10.48557/L6OWMM\">Reach&amp;Grasp</a> (IIT Dataverse, version {VERSION}, "
        f"CC BY 4.0; Di Domenico et al., <a href=\"https://doi.org/10.1038/s41597-025-04552-5\">Scientific Data 2025</a>). Sidecar task "
        f"description: “{tside['TaskDescription']}”. The release has no video (sessions were filmed, but video is only available on request). "
        f"The clock is the 100 Hz row index shared by the tactile, CyberGlove and Vicon CSVs (same row count and time column, checked). {win} "
        f"The step band marks the repetitions from the code repository's <code>Events_Reach&amp;Grasp.mat</code> (segmented by the authors "
        f"from the joint kinematics, by hand where needed; sample indices read as 1-based at 100 Hz); the time between two repetitions is marked as a pause.</p>"
        "<p><b>Layout.</b> Each of the 58 taxels is painted over its own pad of <code>glove_mapping.JPG</code> from the authors' code "
        "repository, the paper's Fig. 2A drawing: a palmar view of the right hand, little finger on the left, thumb on the right. "
        "The pad of each CSV column is found from the authors' taxel positions in <code>Curser_Reach&amp;Grasp.mat</code> (reverse column "
        "order, as their <code>Figure_9.m</code> uses it); the pads were segmented from the image here, grown over the drawn borders and sampled on a "
        f"{rows} × {cols} grid ({PITCH} image px per cell). Column → hardware ID → finger follows Supplementary Table 5: thumb 7 "
        "(tip 4, proximal 3), index 9, middle 8, ring 8, little 9, palm 17. The three palm groups of that table (PalmFinger, PalmThumb, "
        "PalmWrist) are plotted separately below.</p>"
        f"<p><b>Values.</b> The glove is not calibrated: the paper says the readings cannot be related to N or Pa (they reflect the "
        f"resistance of the piezoresistive lining, i.e. contact geometry and force together), although <code>channels.tsv</code> labels them N. "
        f"The colour scale ends at {TOP:.0f} in every recording (the release's values go up to 4,906); {over:.2f}% of this recording's samples "
        f"are above it. {neg:.1f}% of the samples are negative (down to {T.min():.0f}); they are drawn and summed as 0. Bending or "
        "stretching the fabric also produces readings without contact (paper). "
        + (f"Taxels that read exactly 0 throughout: {', '.join(dead)}. " if dead else "")
        + f"The paper reports {', '.join(MALFUNCTION)} (IDs 9, 11, 14, ring fingertip) as malfunctioning; they are drawn as recorded.</p>"
        "<p>Not shown: the two EMG systems (64-channel HD-sEMG and 10 bipolar channels at 2 kHz, 150–250 MB per recording) and the Vicon "
        "thorax and finger MCP angles (the CyberGlove covers the fingers). All 18 CyberGlove angles and the Vicon shoulder, elbow and "
        "wrist angles are plotted.</p>")
    item = {"id": vid, "title": TASKS[task], "label": f"{sub} · {task}", "sub": f"{dur:.0f} s · {nrep} repetitions",
            "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": TASKS[task], "n": n, "fps": FPS, "duration": dur, "videos": [], "hands": hands,
           "series": series, "notes": notes, "task": taskobj, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    p = site / "data" / f"{vid}.json"
    p.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{vid}: {p.stat().st_size / 1e6:.2f} MB, n={n}, dead={len(dead)}, neg={neg:.1f}%, over={over:.2f}%", file=sys.stderr)
    return item


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", nargs="+", help="sub-XX_task-YY")
    c = sub.add_parser("convert")
    c.add_argument("root", type=Path)
    c.add_argument("episodes", nargs="+", help="sub-XX_task-YY")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    root = a.root.expanduser()
    if a.cmd == "fetch":
        fetch(root, a.episodes)
        return
    first = a.episodes[0]
    _, names, _ = read(root, first, first.split("_task-")[0], "tactileglove", "tactile")
    layout = pad_map(root, names)
    for ep in a.episodes:
        _, nm, _ = read(root, ep, ep.split("_task-")[0], "tactileglove", "tactile")
        assert nm == names, f"{ep}: channel names differ from {first}"
        print(json.dumps(convert(root, ep, a.site, layout)))


if __name__ == "__main__":
    main()
