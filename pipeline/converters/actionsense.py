#!/usr/bin/env python
"""ActionSense activity instance -> viewer grid recording (site/data/ac_*.json + site/media/ac_*_<cam>.mp4 + poster).

ActionSense (DelPreto et al., NeurIPS 2022 Datasets & Benchmarks; data CC BY-NC-SA 4.0) records one continuous HDF5 file of
all wearable streams per subject and recording split, plus separate egocentric (Pupil Core world camera, MJPEG mp4) and
FLIR camera (MPEG-4 avi + one timestamp line per frame) files. An episode here is one labelled activity instance
(Start/Stop rows of experiment-activities/activities), so nothing is downloaded whole: `fetch` reads the instance's
slice of the HDF5 over HTTP range requests (data.csail.mit.edu serves Accept-Ranges) and the FLIR timestamp files,
`convert` cuts the instance out of the world video and two FLIR videos with ffmpeg over HTTP, re-times every frame to the
30 Hz episode clock from the release's own per-frame timestamps and re-encodes to H.264.

    python -I ext/actionsense.py fetch ~/data/ext/actionsense/eps            # all sampled instances (or list ids)
    python -I ext/actionsense.py convert --site site ~/data/ext/actionsense/eps/S00_2022-06-07_18-11-37_act028

The release has no versioned snapshot; fetch records Content-Length and Last-Modified of every file it reads.

Tactile layout. Each glove is a 32 x 32 matrix of conductive threads (paper sec. 4.4: "32 threads in each direction
that are routed to form a 23x19 grid on the palm, a 5x9 grid on the thumb, an 11x4 grid on the little finger, and a
13x4 grid on each other finger"). The supplement says a matrix-to-hand map is in the metadata, but the released HDF5
attributes hold only Description and Range, so the map below is read off the data: matrix entries that are not a
thread crossing never move (99.5th percentile 1-4 counts above rest over a whole session) and form exactly the
stated grids, identically on both gloves of every subject checked:
    palm   rows 0-22 x cols 0-18 (23 x 19)      thumb  rows 23-31 x cols 6-10 (9 x 5)
    little rows 0-3, ring 6-9, middle 11-14, index 19-22, each x cols 19-31 (13), except little x cols 19-29 (11)
Which finger owns which 4-row band and that col 31 is the distal end are inferences (little = the band with 11 crossings
= the shortest finger, so the missing cols 30-31 are its distal end; the thumb then sits on palm cols 6-10, near the
wrist), recorded in the notes.

Faulty crossings. A few right-glove crossings (21, 31), (22, 31), (21, 11), (21, 12), (22, 11), (22, 12) do not respond like the
film: they jump between rest (~565) and ~1018 with almost no samples in between while their neighbours stay quiet, or sit at
~1018 for most of a span. faulty_cells flags them per episode from the data (over the instance +- MARGIN_S); they are drawn as
"inactive" (hollow) and left out of the region sums, the top-20 contact metric and the colour range.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

BASE = "https://data.csail.mit.edu/ActionNet/"
DATA_PAGE = "https://action-sense.csail.mit.edu/data.html"
FPS = 30
CONTACT = 30.0            # survey contact rule: mean of the 20 most raised crossings above rest by this many counts
MARGIN_S = 150.0          # rest level = per-cell median over the instance +- this many seconds (the survey's contact rule)
CAMS = [("world", "Egocentric camera (Pupil Core world camera)"), ("PG3", "FLIR camera above the table"),
        ("PG4", "FLIR camera, side view")]

# the sampled instances (survey pipeline/surveys/actionsense.json, sample.episodes): HDF5 split, 0-based index into the
# list of Start/Stop pairs of experiment-activities/activities, label times (epoch s), optional window after label start
SPLITS = {
    "S00_2022-06-07_18-11-37": "wearable_data/2022-06-07_experiment_S00/2022-06-07_18-10-55_actionNet-wearables_S00/2022-06-07_18-11-37",
    "S02_2022-06-13_22-35-11": "wearable_data/2022-06-13_experiment_S02/2022-06-13_22-34-45_actionNet-wearables_S02/2022-06-13_22-35-11",
    "S03_2022-06-14_13-52-57": "wearable_data/2022-06-14_experiment_S03/2022-06-14_13-52-21_actionNet-wearables_S03/2022-06-14_13-52-57",
    "S04_2022-06-14_16-38-43": "wearable_data/2022-06-14_experiment_S04/2022-06-14_16-38-18_actionNet-wearables_S04/2022-06-14_16-38-43",
    "S05_2022-06-14_20-46-12": "wearable_data/2022-06-14_experiment_S05/2022-06-14_20-45-43_actionNet-wearables_S05/2022-06-14_20-46-12",
}
EPISODES = {
    "S00_2022-06-07_18-11-37_act028": (28, (1654641882.591, 1654641892.693), None),
    "S04_2022-06-14_16-38-43_act032": (32, (1655241417.676, 1655241426.13), None),
    "S02_2022-06-13_22-35-11_act016": (16, (1655174703.729, 1655174714.36), None),
    "S03_2022-06-14_13-52-57_act002": (2, (1655229400.062, 1655229428.062), None),
    "S04_2022-06-14_16-38-43_act007": (7, (1655240415.361, 1655240453.91), None),
    "S05_2022-06-14_20-46-12_act012": (12, (1655255126.971, 1655255180.239), None),
    "S05_2022-06-14_20-46-12_act058": (58, (1655256868.238, 1655257024.025), (10.0, 55.0)),
}

# episode-specific remarks appended to the tactile notes
REMARKS = {
    "S04_2022-06-14_16-38-43_act032": (
        "The contact is weak: the left glove's most raised crossings (palm and middle finger) sit only a little above +30 "
        "counts, and the right glove passes +30 only briefly. All 15 jar instances of the subjects with tactile data (S00, S02, "
        "S03, S04, S05) were checked with the faulty crossings left out; this is the only one above +30 for a continuous "
        "second or more (longest run in the other 14: 0.97 s; some peak higher, up to +85, but for under a second). An S00 "
        "jar instance used before reached +30 only through the faulty right-glove crossings and was replaced."),
}

# ---- matrix layout (see module docstring): (row range, col range) per region of the 32 x 32 matrix
FINGER_ROWS = {"index": range(19, 23), "middle": range(11, 15), "ring": range(6, 10), "little": range(0, 4)}
REGIONS = [("thumb", range(23, 32), range(6, 11))] + \
          [(f, FINGER_ROWS[f], range(19, 30) if f == "little" else range(19, 32)) for f in ("index", "middle", "ring", "little")] + \
          [("palm", range(0, 23), range(0, 19))]
GRID = 33                 # display grid: 32 matrix rows + 1 gap before the thumb; 13 finger + 1 gap + 19 palm cols


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def mask() -> np.ndarray:
    m = np.zeros((32, 32), bool)
    for _, rr, cc in REGIONS:
        m[np.ix_(list(rr), list(cc))] = True
    return m


FAULT_HI, FAULT_MID, FAULT_NB = 950, 700, 20.0


def faulty_cells(d: np.ndarray, m: np.ndarray, rest: np.ndarray) -> dict:
    """Thread crossings that toggle between two states instead of responding to pressure. d: (frames, 32, 32) counts over
    the instance +- MARGIN_S, rest: per-cell median over the same span. A crossing is flagged when its samples are bimodal
    (at least max(10, 0.5 %) of them above FAULT_HI, and at most a fifth as many between FAULT_MID and FAULT_HI) and its
    neighbouring crossings stay quiet while it is high (the largest median rise above rest over the 4-neighbours that are
    crossings and not themselves bimodal is below FAULT_NB counts). Real pressure on the film passes through the middle
    range or raises the neighbours; these cells jump between rest (~565) and ~1018 with neither. Cells that are high only
    together with more than 3 crossings of their own matrix row are left out: those are one-frame bursts in which a run of a
    row reads ~1018 (seen on the left glove outside the sampled windows), counted separately by line_bursts."""
    n = len(d)
    hi, mid = d > FAULT_HI, (d > FAULT_MID) & (d <= FAULT_HI)
    nh, nm = hi.sum(0), mid.sum(0)
    cand = (nh >= max(10, 0.005 * n)) & (nm <= 0.2 * nh)
    out = {}
    for r, c in zip(*np.where(cand & m)):
        sel, rises = hi[:, r, c], []
        if np.median(hi[sel, r, :].sum(1)) > 3:
            continue        # high together with a run of its matrix row: a read-out line burst, not a single faulty cell
        for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= rr < 32 and 0 <= cc < 32 and m[rr, cc] and not cand[rr, cc]:
                rises.append(float(np.median(d[sel, rr, cc].astype(np.float32) - rest[rr, cc])))
        if not rises or max(rises) < FAULT_NB:
            out[(int(r), int(c))] = {"share_hi": float(nh[r, c] / n), "n_mid": int(nm[r, c]), "rest": float(rest[r, c]),
                                     "nb_rise": round(max(rises), 1) if rises else None}
    return out


def line_bursts(d: np.ndarray, m: np.ndarray, bad: np.ndarray) -> np.ndarray:
    """Per frame: True when more than 3 crossings of one matrix row (not counting flagged faulty cells) read above FAULT_HI."""
    hi = (d > FAULT_HI) & m & ~bad
    return hi.sum(2).max(1) > 3


def display_pos(r: int, c: int, key: str) -> int:
    """Matrix (row, col) -> display row*GRID + col. Display x runs along the matrix rows (little ... index, gap, thumb);
    display y is the matrix col reversed (col 31 = distal finger end on top, 1 empty row between fingers and palm).
    Left hand: thumb on the right; right hand mirrored (as the other glove collections)."""
    u = r if r < 23 else r + 1
    x = u if key == "lh" else GRID - 1 - u
    y = 31 - c if c >= 19 else 32 - c
    return y * GRID + x


# ---------------------------------------------------------------- fetch (requests + h5py over HTTP range reads)
class RemoteFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests, 1 MiB blocks, cached."""
    BLOCK = 1 << 20

    def __init__(self, url: str):
        import requests
        self.url, self.s = url, requests.Session()
        h = self.s.head(url, allow_redirects=True)
        h.raise_for_status()
        self.size = int(h.headers["Content-Length"])
        self.last_modified = h.headers.get("Last-Modified")
        self.pos, self.cache, self.fetched = 0, {}, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def _block(self, i):
        if i not in self.cache:
            a = i * self.BLOCK
            r = self.s.get(self.url, headers={"Range": f"bytes={a}-{min(self.size, a + self.BLOCK) - 1}"})
            r.raise_for_status()
            self.cache[i] = r.content
            self.fetched += len(r.content)
        return self.cache[i]

    def readinto(self, buf):
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        out, p = bytearray(), self.pos
        while len(out) < n:
            i = p // self.BLOCK
            take = self._block(i)[p - i * self.BLOCK:p - i * self.BLOCK + n - len(out)]
            out += take
            p += len(take)
        buf[:n] = out
        self.pos += n
        return n


def head(url: str) -> dict:
    import requests
    h = requests.head(url, allow_redirects=True)
    h.raise_for_status()
    return {"url": url, "size": int(h.headers["Content-Length"]), "last_modified": h.headers.get("Last-Modified")}


def pair_activities(f) -> list[dict]:
    """Start/Stop rows -> instances, in the order their Stop rows appear (the survey's activity_index)."""
    rows = f["experiment-activities/activities/data"][()]
    ts = f["experiment-activities/activities/time_s"][()].ravel()
    open_, out = {}, []
    for row, t in zip(rows, ts):
        name, ss, valid, notes = [x.decode() for x in row[:4]]
        if ss == "Start":
            open_[name] = (float(t), valid, notes)
        elif name in open_:
            t0, v0, n0 = open_.pop(name)
            out.append({"name": name, "start": t0, "stop": float(t), "valid": valid or v0, "notes": " ".join(x for x in (n0, notes) if x)})
    return out


def window(f, grp: str, a: float, b: float, rows: bool = True):
    t = f[grp + "/time_s"][()].ravel()
    i0, i1 = int(np.searchsorted(t, a, "right")) - 1, int(np.searchsorted(t, b, "right"))
    i0 = max(i0, 0)
    return (f[grp + "/data"][i0:i1] if rows else None), t[i0:i1]


def pg_splits(page: Path) -> dict:
    links = re.findall(r'href="(https://data\.csail\.mit\.edu/ActionNet/external_data/[^"]+)"', page.read_text())
    out = {}
    for u in links:
        m = re.search(r"/(\d{4}-\d\d-\d\d)_experiment_(S\d\d)/(PG\d)_([\d-]+)\.(avi|txt)$", u)
        if m:
            out.setdefault((m.group(2), m.group(3)), {}).setdefault(m.group(4), {})[m.group(5)] = u
    return out


def fetch(root: Path, ids: list[str]) -> None:
    import h5py
    import requests
    page = root.parent / "data.html"
    if not page.exists():
        page.write_text(requests.get(DATA_PAGE).text)
    pgs = pg_splits(page)
    for eid in ids:
        split = eid.rsplit("_act", 1)[0]
        k, (l0, l1), win = EPISODES[eid]
        t0, t1 = (l0 + win[0], l0 + win[1]) if win else (l0, l1)
        out = root / eid
        out.mkdir(parents=True, exist_ok=True)
        if (out / "meta.json").exists():
            print(eid, "already fetched", file=sys.stderr)
            continue
        url = BASE + SPLITS[split] + f"_streamLog_actionNet-wearables_{split[:3]}.hdf5"
        rf = RemoteFile(url)
        f = h5py.File(io.BufferedReader(rf, buffer_size=1 << 16), "r")
        acts = pair_activities(f)
        act = acts[k]
        assert abs(act["start"] - l0) < 1e-3 and abs(act["stop"] - l1) < 1e-3, (eid, act)
        arrays = {}
        for side in ("left", "right"):
            d, t = window(f, f"tactile-glove-{side}/tactile_data", t0 - MARGIN_S, t1 + MARGIN_S)
            assert d.shape[1:] == (32, 32) and np.isfinite(d).all() and (d == np.round(d)).all()
            arrays[f"tac_{side}"], arrays[f"tac_{side}_t"] = d.astype(np.uint16), t
            d, t = window(f, f"myo-{side}/emg", t0 - 1, t1 + 1)
            arrays[f"emg_{side}"], arrays[f"emg_{side}_t"] = d.astype(np.int16), t
        d, t = window(f, "xsens-foot-contacts/foot_contact_points", t0 - 1, t1 + 1)
        arrays["foot"], arrays["foot_t"] = d.astype(np.uint8), t
        arrays["world_t"] = f["eye-tracking-video-world/frame_timestamp/time_s"][()].ravel()
        _, ws = window(f, "tactile-calibration-scale/weight_g", t0, t1)
        ws = ws[(ws >= t0) & (ws <= t1)]
        notes = f["experiment-notes/notes"]
        nt = notes["time_s"][()].ravel()
        nsel = [(float(a), b[0].decode()) for a, b in zip(nt, notes["data"][()]) if t0 - 5 <= a <= t1 + 5]
        attrs = {k2: str(v) for k2, v in f["tactile-glove-left/tactile_data"].attrs.items()}
        foot_head = str(f["xsens-foot-contacts/foot_contact_points"].attrs.get("Data headings", ""))
        np.savez_compressed(out / "streams.npz", **arrays)
        f.close()
        world = BASE + SPLITS[split] + f"_{split[:3]}_eye-tracking-video-world_frame.mp4"
        files = {"hdf5": {"url": url, "size": rf.size, "last_modified": rf.last_modified, "fetched_bytes": rf.fetched},
                 "world": head(world)}
        for cam, _ in CAMS[1:]:
            cands = pgs[(split[:3], cam)]
            for stamp, u in sorted(cands.items()):
                txt = out / f"{cam}_{stamp}.txt"
                if not txt.exists():
                    txt.write_bytes(requests.get(u["txt"]).content)
                ts = np.loadtxt(txt)
                ts = ts[:, 0] + ts[:, 1] / 1e9
                if ts[0] <= t0 and ts[-1] >= t1:
                    files[cam] = {**head(u["avi"]), "txt": u["txt"], "txt_local": txt.name}
                    break
            assert cam in files, (eid, cam)
        meta = {"id": eid, "split": split, "activity_index": k, "activity": act, "t0": t0, "t1": t1, "window": win,
                "scale_readings_in_window": int(len(ws)), "experiment_notes": nsel, "tactile_attrs": attrs,
                "foot_headings": foot_head, "files": files}
        (out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(eid, f"fetched {rf.fetched / 1e6:.0f} MB of the HDF5", file=sys.stderr)


# ---------------------------------------------------------------- convert (numpy + ffmpeg)
def latest(t_src: np.ndarray, t_clock: np.ndarray) -> np.ndarray:
    """index of the latest source sample at or before each clock tick (0 if none)"""
    return np.clip(np.searchsorted(t_src, t_clock, "right") - 1, 0, len(t_src) - 1)


def retime_video(src: str, pts: np.ndarray, ftimes: np.ndarray, clock: np.ndarray, width: int, dst: Path, src_size) -> None:
    """Write one output frame per clock tick: the latest source frame whose own timestamp (ftimes, epoch s) is at or before
    the tick. pts[i] is the container pts (s) of source frame i. Every decoded frame is identified by its own pts (read from
    showinfo, with -copyts and -vsync passthrough), not by counting: ffmpeg 4.4's default CFR conversion duplicates frames
    of the variable-rate world video, and its input -ss lands a few frames off on that MJPEG stream, so a counting loop
    drifted up to 0.33 s behind the clock. H.264, 30 fps, a keyframe every second (with x264's default 250-frame GOP,
    headless Chrome left the viewer's three seeked videos black past ~4 s)."""
    k = latest(ftimes, clock)
    w, h = width, int(round(src_size[1] * width / src_size[0] / 2) * 2)
    dec = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-ss", f"{max(pts[k[0]] - 0.5, 0):.4f}",
                            "-copyts", "-i", src, "-vsync", "passthrough", "-enc_time_base", "-1", "-vf", f"showinfo,scale={w}:{h}",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stamps: queue.Queue = queue.Queue()

    def read_log() -> None:
        tb = None
        for line in io.TextIOWrapper(dec.stderr, errors="replace"):
            if "config in time_base:" in line:
                n, d = line.split("config in time_base:")[1].split(",")[0].strip().split("/")
                tb = int(n) / int(d)
            elif "Parsed_showinfo" in line and " pts:" in line:
                stamps.put(int(line.split(" pts:")[1].split()[0]) * tb)
        stamps.put(None)

    threading.Thread(target=read_log, daemon=True).start()
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS),
                            "-i", "-", "-an", "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-g", str(FPS), "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
    size, buf, cur, pend, lag = w * h * 3, None, -1, None, []

    def next_frame():
        b = dec.stdout.read(size)
        if len(b) < size:
            return None
        t = stamps.get()
        i = int(np.argmin(np.abs(pts - t)))
        assert abs(pts[i] - t) < 0.004, (dst, t, pts[i])      # every decoded frame is a known source frame
        return b, i

    for want in k:
        while True:
            if pend is None:
                pend = next_frame()
                if pend is None:
                    break
            if pend[1] > want:
                break
            buf, cur = pend
            pend = None
        assert buf is not None, (dst, want)
        lag.append(want - cur)
        enc.stdin.write(buf)
    enc.stdin.close()
    dec.kill()
    dec.wait()
    assert enc.wait() == 0, dst
    lag = np.array(lag)
    print(f"{dst.name}: ticks showing an older frame than wanted {int((lag > 0).sum())}/{len(lag)} (max {int(lag.max())} frames)",
          file=sys.stderr)


def first_pts(url: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "packet=pts_time", "-read_intervals",
                        "%+#1", "-of", "csv=p=0", url], capture_output=True, text=True, check=True)
    return float(r.stdout.split()[0])


def hand(tac: np.ndarray, rest: np.ndarray, key: str, title: str, rng: float, ix: np.ndarray, m: np.ndarray, bad: np.ndarray) -> dict:
    """tac: (frames, 32, 32) counts; the 682 thread crossings in m become taxels, ordered by region, except the suspected
    faulty ones in bad, which are listed as "inactive" (hollow squares) and left out of the stored values and region sums."""
    cells, regions, order, inactive = [], [], [], []
    for name, rr, cc in REGIONS:
        first = len(cells)
        for r in rr:
            for c in cc:
                if bad[r, c]:
                    inactive.append(display_pos(r, c, key))
                    continue
                cells.append(display_pos(r, c, key))
                order.append(r * 32 + c)
        regions.append({"name": name, "cells": list(range(first, len(cells)))})
    assert len(order) + len(inactive) == int(m.sum()) == 682 and len(set(cells + inactive)) == len(cells) + len(inactive)
    exc = (tac.reshape(len(tac), -1)[:, order].astype(np.float32) - rest.reshape(-1)[order])
    tax = np.clip(np.round(exc / rng * 255), 0, 255).astype(np.uint8)
    out = {"key": key, "title": title, "rate": 6, "rows": GRID, "cols": GRID, "cells": b64(np.array(cells, np.uint16)),
           "tax": b64(tax), "index": b64(ix.astype(np.uint16)), "range": rng, "unit": "counts above rest", "regions": regions,
           "label": "682 thread crossings" + (f" ({len(inactive)} suspected faulty, hollow)" if inactive else "")
                    + " · palm 23×19, thumb 9×5, fingers 13×4 (little 11×4)"}
    if inactive:
        out["inactive"] = sorted(inactive)
    return out


def convert(ep: Path, site: Path) -> None:
    meta = json.loads((ep / "meta.json").read_text())
    z = np.load(ep / "streams.npz")
    eid, act = meta["id"], meta["activity"]
    vid = f"ac_{eid}"
    t0, t1 = meta["t0"], meta["t1"]
    n = int(round((t1 - t0) * FPS))
    clock = t0 + np.arange(n) / FPS
    m = mask()

    # tactile: per-cell rest = median over the instance +- MARGIN_S; values = counts above rest, clipped at 0
    # suspected faulty crossings (faulty_cells, over the same span) are not drawn as taxels and are left out of every metric
    tac, rests, ixs, checks, bads = {}, {}, {}, {}, {}
    for side in ("left", "right"):
        d, t = z[f"tac_{side}"], z[f"tac_{side}_t"]
        rests[side] = np.median(d, axis=0).astype(np.float32)
        inw = (t >= t0) & (t <= t1)
        fc = faulty_cells(d, m, rests[side])
        bads[side] = np.zeros_like(m)
        for (r, c), v in fc.items():
            bads[side][r, c] = True
            v["hi_in_episode"], v["frames_in_episode"] = int((d[inw, r, c] > FAULT_HI).sum()), int(inw.sum())
        ok = m & ~bads[side]
        ex = d.astype(np.float32) - rests[side]
        q = np.percentile(ex, 99.5, axis=0)    # per matrix entry, over the instance +- MARGIN_S
        checks[side] = {"outside_p995": float(np.median(q[~m])), "inside_p995": float(np.median(q[ok])),
                        "rate_hz": float((len(t) - 1) / (t[-1] - t[0])),
                        "hot": [[int(a), int(b)] for a, b in zip(*np.where((rests[side] > 900) & ~bads[side]))],
                        "sat_samples": int((d[inw][:, ok] >= 1023).sum()),
                        "faulty": [{"cell": [r, c], **v} for (r, c), v in fc.items()],
                        "line_bursts_in_episode": int(line_bursts(d[inw], m, bads[side]).sum())}
        mw = ex[inw].mean(axis=0)
        twostate = ((d > FAULT_HI).sum(0) >= max(10, 0.005 * len(d))) & (((d > FAULT_MID) & (d <= FAULT_HI)).sum(0) <= 0.2 * (d > FAULT_HI).sum(0))
        checks[side]["outside_raised"] = [[int(a), int(b), int(round(mw[a, b])), bool(twostate[a, b])] for a, b in zip(*np.where((mw > 30) & ~m))]
        k = latest(t, clock)
        tac[side], ixs[side] = d[k[0]:k[-1] + 1], k - k[0]
    p995 = max(float(np.percentile((tac[s].astype(np.float32) - rests[s])[:, m & ~bads[s]], 99.5)) for s in ("left", "right"))
    rng = float(max(60, 20 * np.ceil(p995 / 20)))
    hands = [hand(tac["left"], rests["left"], "lh", "Left glove", rng, ixs["left"], m, bads["left"]),
             hand(tac["right"], rests["right"], "rh", "Right glove", rng, ixs["right"], m, bads["right"])]

    series = []
    top = {}
    for side in ("left", "right"):
        ex = (tac[side].astype(np.float32) - rests[side])[:, m & ~bads[side]]
        top[side] = np.sort(ex, axis=1)[:, -20:].mean(axis=1)[ixs[side]].astype(np.float32)
        above = top[side] > CONTACT
        run = best = 0
        for a in above:
            run = run + 1 if a else 0
            best = max(best, run)
        checks[side]["contact"] = {"top20_mean": round(float(top[side].mean()), 1), "top20_peak": round(float(top[side].max()), 1),
                                   "above_s": round(float(above.sum()) / FPS, 1), "longest_run_s": round(best / FPS, 1)}
    anybad = any(bads[s].any() for s in bads)
    series.append({"title": "Mean of the 20 most raised cells (counts above rest" + (", suspected faulty cells left out)" if anybad else ")"),
                   "lines": [{"name": "left", "data": b64(top["left"]), "col": "#2e86c1"},
                             {"name": "right", "data": b64(top["right"]), "col": "#d35400"}]})
    lines = []
    for side, col in (("left", "#2e86c1"), ("right", "#d35400")):
        e, t = z[f"emg_{side}"].astype(np.float32), z[f"emg_{side}_t"]
        rms = np.sqrt((e ** 2).mean(axis=1))
        env = np.array([np.sqrt(np.mean(rms[(t > c - 0.1) & (t <= c)] ** 2)) if ((t > c - 0.1) & (t <= c)).any() else np.nan for c in clock], np.float32)
        lines.append({"name": side, "data": b64(env), "col": col})
    series.append({"title": "Forearm EMG · RMS over 8 channels and 100 ms (Myo, normalized units)", "lines": lines})
    fo, ft = z["foot"], z["foot_t"]
    fk = latest(ft, clock)
    heads = ["left heel", "left toe", "right heel", "right toe"]
    series.append({"title": "Foot-ground contact estimated by Xsens (0/1, stacked)", "fixed": [0, 8],
                   "lines": [{"name": h, "data": b64((fo[fk, q].astype(np.float32) * 1.6 + 2 * (3 - q))), "col": c}
                             for q, (h, c) in enumerate(zip(heads, ["#8e44ad", "#c99a06", "#17a589", "#7f8c8d"]))]})

    # videos: cut + re-time from the release's per-frame timestamps
    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    F = meta["files"]
    dst = media / f"{vid}_world.mp4"
    wt = z["world_t"]
    if not dst.exists():
        retime_video(F["world"]["url"], wt - wt[0] + first_pts(F["world"]["url"]), wt, clock, 960, dst, (1280, 720))
    videos.append({"key": "world", "title": CAMS[0][1], "src": f"media/{vid}_world.mp4", "src_size": [1280, 720], "fps_src": 30})
    for cam, title in CAMS[1:]:
        dst = media / f"{vid}_{cam}.mp4"
        ts = np.loadtxt(ep / F[cam]["txt_local"])
        ts = ts[:, 0] + ts[:, 1] / 1e9
        if not dst.exists():
            retime_video(F[cam]["url"], np.arange(len(ts)) / 22.0, ts, clock, 640, dst, (1600, 1200))
        videos.append({"key": cam, "title": title, "src": f"media/{vid}_{cam}.mp4", "src_size": [1600, 1200], "fps_src": 22})
    dur = n / FPS
    ref = float(np.argmax(top["left"] + top["right"])) / FPS
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ref:.2f}", "-i", str(media / f"{vid}_world.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)

    win = meta["window"]
    label_len = act["stop"] - act["start"]
    step = (f"{act['name']} (label {label_len:.1f} s; shown: {win[0]:.0f}–{win[1]:.0f} s after its start)" if win
            else f"{act['name']} (whole labelled instance, rated {act['valid']})")
    task = {"task": act["name"], "start": 0.0, "end": dur, "steps": [{"start": 0.0, "end": dur, "text": step}]}
    hot = {s: checks[s]["hot"] for s in checks if checks[s]["hot"]}
    hot_txt = ("; ".join(f"{s} glove matrix " + ", ".join(f"({a}, {b})" for a, b in v) for s, v in hot.items())) if hot else ""
    sat = {s: checks[s]["sat_samples"] for s in checks if checks[s]["sat_samples"]}
    faulty_txt = ""
    if anybad:
        def where(r: int, c: int) -> str:
            name = next(nm for nm, rr, cc in REGIONS if r in rr and c in cc)
            return name if name in ("palm", "thumb") else f"{name} finger" + (", distal end" if c >= 29 else "")
        parts = []
        for sd in ("left", "right"):
            fl = checks[sd]["faulty"]
            if fl:
                parts.append(f"{sd} glove " + ", ".join(
                    f"({v['cell'][0]}, {v['cell'][1]}) [{where(*v['cell'])}; above {FAULT_HI} in {100 * v['share_hi']:.1f} % of the span, "
                    f"{v['hi_in_episode']} of {v['frames_in_episode']} frames in the episode]" for v in fl))
        allf = [v for sd in checks for v in checks[sd]["faulty"]]
        nbr = max((v["nb_rise"] for v in allf if v["nb_rise"] is not None), default=0)
        stuck = [v for v in allf if v["rest"] > 900]
        stuck_txt = ", ".join(f"({v['cell'][0]}, {v['cell'][1]})" for v in stuck)
        faulty_txt = (
            f"Suspected faulty or intermittent crossings, drawn as hollow squares and left out of the region sums, the top-20 "
            f"plot and the colour scale (finger names as in the layout assumed above): {'; '.join(parts)}. Over the episode ± {MARGIN_S:.0f} s each of them is two-state: it "
            f"reads either about its neighbours' rest level (~565) or ~1000–1023 (mostly ~1018), with {sum(v['n_mid'] for v in allf)} "
            f"samples between {FAULT_MID} and {FAULT_HI} in all, while the neighbouring crossings rise by at most +{nbr:.0f} counts "
            f"when it is high. Pressure on the film would pass through the middle range and raise the neighbours, so these are "
            f"read-out faults that toggle between rest and ~1018, not contact (rule: <code>faulty_cells</code> in the converter). "
            + (f"{stuck_txt} sit at ~1018 for most of this span, so their median 'rest' is the faulty state. " if stuck else ""))
    notes = (
        f"<p>One 30 Hz clock that starts at the {'label start' if not win else f'window start ({win[0]:.0f} s after the label start)'} "
        f"(epoch {t0:.3f} s, the system clock all ActionSense streams are stamped with). Each stream shows its latest sample at or "
        f"before the tick: the gloves arrive at about {checks['left']['rate_hz']:.1f} / {checks['right']['rate_hz']:.1f} Hz "
        f"(left / right; irregular), the world camera at ~29.7 fps, the FLIR cameras at 22 fps, EMG at ~200 Hz, Xsens at 60 Hz. "
        f"The videos are this instance's slice of the release's per-split files (world camera MJPEG mp4, FLIR MPEG-4 avi), each "
        f"frame placed on the clock by its own timestamp in the release (HDF5 <code>eye-tracking-video-world</code>, FLIR "
        f"<code>PG*.txt</code>) and re-encoded to H.264. The release has no versioned snapshot; files as served by "
        f"data.csail.mit.edu (HDF5 last modified {F['hdf5']['last_modified']}).</p>"
        f"<p>Tactile: each glove is a 32 × 32 matrix of conductive threads on a piezoresistive film. Only the 682 thread crossings "
        f"are drawn (the paper's grids: palm 23 × 19, thumb 5 × 9, little finger 11 × 4, other fingers 13 × 4); the other 342 "
        f"matrix entries are not sensors. The release does not ship the matrix-to-hand map the supplement mentions, so the "
        f"placement is read off the data: the entries that barely respond over a whole session form exactly these blocks (palm = matrix rows 0–22 × "
        f"cols 0–18; thumb = rows 23–31 × cols 6–10; four 4-row finger bands rows 0–3, 6–9, 11–14, 19–22 × cols 19–31, the first "
        f"one only to col 29). Around this episode (± {MARGIN_S:.0f} s) the median matrix entry's 99.5th percentile above rest is "
        f"{checks['left']['outside_p995']:.0f} / {checks['right']['outside_p995']:.0f} counts outside these blocks vs "
        f"{checks['left']['inside_p995']:.0f} / {checks['right']['inside_p995']:.0f} inside (left / right). Assumed, not documented: the 11-wide band is the little "
        f"finger (shortest), the bands follow in order little, ring, middle, index, matrix col 31 is the distal end, and the thumb "
        f"block is drawn sideways next to the lower palm, where palm cols 6–10 lie. Hands are drawn fingers up, left thumb on the "
        f"right and right hand mirrored, as in the other glove collections; the sensors do not reach the fingertips (open-finger "
        f"gloves).</p>"
        f"<p>Values are raw ADC counts minus each cell's rest level (its median over the instance ± {MARGIN_S:.0f} s; rest is "
        f"~555–570 counts), clipped at 0; there is no force calibration (the release's scale-calibration periods are for that). "
        f"The colour scale ends at {rng:.0f} counts (the 99.5th percentile of the more loaded glove in this episode, rounded up; "
        f"brighter cells clip). "
        + (f"Cells near the 1023 ceiling at rest ({hot_txt}) cannot rise further and read 0 here. " if hot else "")
        + faulty_txt
        + (f"Samples at 1023 inside the episode: {', '.join(f'{s} {v}' for s, v in sat.items())}. " if sat else "")
        + "".join(f"The {sd} glove's matrix entries " + ", ".join(f"({a}, {b})" for a, b, _, _ in raised)
                  + f", which are not thread crossings, read up to {max(v for _, _, v, _ in raised)} counts above rest on average in "
                  + "this episode; they are not drawn. "
                  + (("Of these, " + ", ".join(f"({a}, {b})" for a, b, _, b2 in raised if b2) + " jump between rest and ~1018 with "
                      "almost nothing in between (a read-out fault, not pressure)"
                      + ("; the others are probably crosstalk in the matrix read-out. " if not all(b2 for *_, b2 in raised) else ". "))
                     if any(b2 for *_, b2 in raised) else "They are probably crosstalk in the matrix read-out. ")
                  for sd in ("left", "right") for raised in [checks[sd]["outside_raised"]] if raised)
        + f"The region values sum the counts above rest of a region's cells. "
        + "Contact in this episode (mean of the 20 most raised crossings" + (", suspected faulty ones left out" if anybad else "")
        + f", above +{CONTACT:.0f} counts): " + " / ".join(
            f"{checks[sd]['contact']['above_s']:.1f} s" for sd in ("left", "right"))
        + f" of {dur:.1f} s (left / right), longest run " + " / ".join(f"{checks[sd]['contact']['longest_run_s']:.1f} s" for sd in ("left", "right"))
        + ", peak +" + " / +".join(f"{checks[sd]['contact']['top20_peak']:.0f}" for sd in ("left", "right")) + " counts. "
        + REMARKS.get(eid, "") + "</p>"
        f"<p>Also shown: forearm EMG envelope (Myo armbands) and the Xsens foot-ground contact estimate (body suit, not hand touch). "
        f"The Dymo scale stream (<code>tactile-calibration-scale/weight_g</code>) has {meta['scale_readings_in_window']} readings "
        f"in this episode: it is used only in the calibration periods. Not shown: Xsens body and Manus finger segments and joints, "
        f"Myo IMU, eye tracking (gaze, pupil), the gaze-overlay video, microphones, and the other three FLIR cameras. "
        f"Data: ActionSense, DelPreto et al. 2022, CC BY-NC-SA 4.0 (non-commercial; re-encoded and cut here).</p>")
    if meta["experiment_notes"]:
        notes += "<p>Experimenter notes near this episode: " + "; ".join(f"{x[1]}" for x in meta["experiment_notes"]) + "</p>"
    subj, stamp = meta["split"][:3], meta["split"][4:]
    item = {"id": vid, "title": act["name"].split(":")[0], "label": f"{subj} · split {stamp[11:]}",
            "sub": f"{dur:.0f} s" + (f" of {label_len:.0f} s" if win else ""), "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": act["name"].split(":")[0], "n": n, "fps": FPS, "duration": dur, "videos": videos,
           "hands": hands, "series": series, "notes": notes, "task": task, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    p = site / "data" / f"{vid}.json"
    p.write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps({**item, "json_mb": round(p.stat().st_size / 1e6, 2), "range": rng, "checks": checks}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", nargs="*", help="episode ids (default: all sampled)")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.episodes or list(EPISODES))
    else:
        for ep in a.episode:
            convert(ep.expanduser(), a.site)


if __name__ == "__main__":
    main()
