#!/usr/bin/env python
"""T-Dex recording -> viewer grid recording (site/data/td_*.json + site/media/td_*_<cam>.mp4 + poster).

T-Dex (Guzey et al., CoRL 2023, https://tactile-dexterity.github.io/) releases two zips on a public Google Drive
folder (play_data.zip 31.4 GB, evaluation.zip 18.9 GB), one folder per recording with one HDF5 per stream, an
MPEG-4 Part 2 AVI per camera and a pickled timestamp list per camera. Nothing is downloaded whole: `fetch` reads the
zip's central directory from its tail and then only the requested members (HTTP range requests on the Drive file;
depth, which is 83 % of the release, is never fetched). `convert` turns one fetched recording into the viewer format.

    python -I ext/tdex.py fetch ~/data/ext/tdex/raw evaluation/bowl_unstacking/demonstration_2 play_data/demonstration_10
    python -I ext/tdex.py convert --site site ~/data/ext/tdex/raw/evaluation/bowl_unstacking/demonstration_2

Tactile: 15 XELA uSkin pads (4 per finger, 3 on the thumb), 4 x 4 taxels each, every taxel a 3-axis (x, y, z) reading,
uncalibrated, at ~98.5 Hz. The viewer shows each taxel's |(x, y, z)| in the release's own pad layout (the 4 x 4 grid of
pads that the authors' visualization code, tactile image and the release's preview videos use: one column per finger, the thumb's three pads in the
first column under an empty slot), the per-pad sum of (x, y, z) as an arrow + ring on each pad, and per-finger plots of
the normal (z) and tangential sums. The Allegro hand's joint efforts (the PD controller's torque output, measured and
commanded) and the Kinova arm's joint efforts are plotted as the release's other force-like channels.
"""

from __future__ import annotations

import argparse
import base64
import json
import pickle
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np

# The release has no version tags; pin the Drive files by id, size and md5 (as listed by the Drive API on 2026-10-15).
DRIVE_FOLDER = "148ycBmuvqkdESvAhStlhYJ7ISMgelEvL"
ZIPS = {"evaluation": {"name": "evaluation.zip", "id": "1L9f91Y_BaA8rLAMga-XBKvRDxJZDgMiw", "size": 18892434443,
                       "md5": "8c9c64a560f63fa2a10340457e24c583"},
        "play_data": {"name": "play_data.zip", "id": "1jS8OYR_17KODGOZSylacpTFFIpL70IGf", "size": 31444621919,
                      "md5": "dee430f2215158bbe355c3c961acd36a"}}
STREAMS = ["touch_sensor_values.h5", "allegro_joint_states.h5", "allegro_commanded_joint_states.h5", "kinova_joint_states.h5"]
FPS = 30                      # viewer clock; the cameras record at ~30 Hz
PAD = 4                       # taxels per pad side
PGAP, FGAP = 1, 2             # empty grid rows between pads of a finger / columns between fingers
# The release's pad layout (tactile_dexterity/utils/visualization.py dump_tactile_state, tactile_image.py
# get_whole_hand_tactile_image): a 4 x 4 grid of pad slots, column c holds pads c*4 + r - 1 for r = 0..3, slot (0, 0) empty.
COLS = [[None, 0, 1, 2], [3, 4, 5, 6], [7, 8, 9, 10], [11, 12, 13, 14]]
REGION_NAMES = ["thumb pads", "finger 1", "finger 2", "finger 3"]    # the code titles the columns 'Finger: 0..3'
# Allegro joint offsets per finger, from Holo-Dex (the teleoperation stack T-Dex records with), holodex/constants.py
ALLEGRO_FINGERS = [("index", 0), ("middle", 4), ("ring", 8), ("thumb", 12)]
COLORS = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#d35400", "#7f8c8d"]
CAM_W, CAM_H = 960, 540


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


class _NoObjects(pickle.Unpickler):
    """The camera .metadata files are pickled dicts of plain values; refuse anything that would import code."""
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"refusing {module}.{name}")


def load_meta(p: Path) -> dict:
    with open(p, "rb") as f:
        return _NoObjects(f).load()


# ---------------------------------------------------------------- fetch (requests)
def _get(zipkey: str, off: int, n: int) -> bytes:
    import requests
    z = ZIPS[zipkey]
    r = requests.get("https://drive.usercontent.google.com/download", params={"id": z["id"], "export": "download", "confirm": "t"},
                     headers={"Range": f"bytes={off}-{off + n - 1}"}, timeout=120)
    assert r.status_code == 206, (r.status_code, r.headers.get("content-type"))
    total = int(r.headers["Content-Range"].rsplit("/", 1)[1])
    assert total == z["size"], f"{z['name']} is {total} bytes, pinned {z['size']}: the release changed"
    assert len(r.content) == n, (len(r.content), n)
    return r.content


def central_directory(zipkey: str, cache: Path) -> dict:
    if cache.exists():
        return {e["name"]: e for e in json.loads(cache.read_text())}
    size = ZIPS[zipkey]["size"]
    tail = _get(zipkey, size - 65558, 65558)
    i = tail.rfind(b"PK\x05\x06")
    cdsize, cdoff = struct.unpack("<II", tail[i + 12:i + 20])
    j = tail.rfind(b"PK\x06\x07")
    if j >= 0:                                            # ZIP64 end of central directory
        z = _get(zipkey, struct.unpack("<Q", tail[j + 8:j + 16])[0], 56)
        cdsize, cdoff = struct.unpack("<QQ", z[40:56])
    cd, p, ents = _get(zipkey, cdoff, cdsize), 0, []
    while cd[p:p + 4] == b"PK\x01\x02":
        (meth, crc, csz, usz, nl, el, cl, lho) = (struct.unpack("<H", cd[p + 10:p + 12])[0], *struct.unpack("<III", cd[p + 16:p + 28]),
                                                  *struct.unpack("<HHH", cd[p + 28:p + 34]), struct.unpack("<I", cd[p + 42:p + 46])[0])
        name = cd[p + 46:p + 46 + nl].decode()
        extra, q = cd[p + 46 + nl:p + 46 + nl + el], 0
        while q + 4 <= len(extra):
            hid, hl = struct.unpack("<HH", extra[q:q + 4])
            if hid == 1:                                  # ZIP64 extra: 8-byte values for the fields stored as 0xFFFFFFFF
                vals = iter(struct.unpack(f"<{hl // 8}Q", extra[q + 4:q + 4 + hl - hl % 8]))
                usz = next(vals) if usz == 0xFFFFFFFF else usz
                csz = next(vals) if csz == 0xFFFFFFFF else csz
                lho = next(vals) if lho == 0xFFFFFFFF else lho
            q += 4 + hl
        ents.append({"name": name, "method": meth, "crc": crc, "csize": csz, "usize": usz, "lho": lho})
        p += 46 + nl + el + cl
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(ents))
    return {e["name"]: e for e in ents}


def fetch_member(zipkey: str, e: dict, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size == e["usize"]:
        return
    h = _get(zipkey, e["lho"], 30)
    assert h[:4] == b"PK\x03\x04"
    nl, el = struct.unpack("<HH", h[26:30])
    off, left, crc = e["lho"] + 30 + nl + el, e["csize"], 0
    dec = zlib.decompressobj(-15) if e["method"] == 8 else None
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with open(tmp, "wb") as f:
        while left:
            n = min(left, 32 << 20)
            raw = _get(zipkey, off, n)
            out = dec.decompress(raw) if dec else raw
            crc = zlib.crc32(out, crc)
            f.write(out)
            off, left = off + n, left - n
        if dec:
            out = dec.flush()
            crc = zlib.crc32(out, crc)
            f.write(out)
    assert tmp.stat().st_size == e["usize"] and crc == e["crc"], f"{e['name']}: size or CRC mismatch"
    tmp.rename(dst)
    print("ok", e["name"], e["usize"], file=sys.stderr)


def fetch(root: Path, recordings: list[str]) -> None:
    for rec in recordings:
        zipkey = rec.split("/")[0]
        cd = central_directory(zipkey, root / f"{zipkey}.cd.json")
        names = [m for m in cd if m.startswith(rec + "/") and (m.rsplit("/", 1)[1] in STREAMS or
                 (m.rsplit("/", 1)[1].startswith("cam_") and m.endswith(("_rgb_video.avi", "_rgb_video.metadata"))))]
        assert any(m.endswith("touch_sensor_values.h5") for m in names), rec
        for m in sorted(names):
            fetch_member(zipkey, cd[m], root / m)


# ---------------------------------------------------------------- convert (numpy + h5py + av + ffmpeg)
def latest(ts: np.ndarray, clock: np.ndarray) -> np.ndarray:
    """Index of the latest sample at or before each clock tick (the first sample before the stream starts)."""
    return np.clip(np.searchsorted(ts, clock, side="right") - 1, 0, len(ts) - 1)


def layout() -> tuple[int, int, list[int], list[list[int]], list[list[int]]]:
    """Grid cell of every taxel (pad-major, taxel row-major from the pad's top left, as the authors' plot code draws it)."""
    rows, cols = 4 * PAD + 3 * PGAP, 4 * PAD + 3 * FGAP
    pos = [0] * (15 * 16)
    for c, col in enumerate(COLS):
        for r, pad in enumerate(col):
            if pad is None:
                continue
            for t in range(16):
                pos[pad * 16 + t] = (r * (PAD + PGAP) + t // PAD) * cols + c * (PAD + FGAP) + t % PAD
    regions = [[p * 16 + t for p in col if p is not None for t in range(16)] for col in COLS]
    pads = [list(range(p * 16, p * 16 + 16)) for p in range(15)]
    return rows, cols, pos, regions, pads


def frame_count(avi: Path) -> int:
    import av
    with av.open(str(avi)) as c:
        return c.streams.video[0].frames


def camera(avi: Path, stamps: np.ndarray, clock: np.ndarray, dst: Path) -> None:
    """Re-time the AVI to the clock (nearest recorded frame per tick, by the release's per-frame timestamps) and encode H.264.
    Some AVIs hold one frame more than their timestamp list; frame i is taken to have timestamp i (the extra one is last)."""
    import av
    want = np.clip(np.searchsorted(stamps, clock), 1, len(stamps) - 1)
    want = np.where(np.abs(stamps[want - 1] - clock) <= np.abs(stamps[want] - clock), want - 1, want)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{CAM_W}x{CAM_H}",
                            "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-g", str(FPS),
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
    k, n = 0, 0
    with av.open(str(avi)) as c:
        for fr in c.decode(video=0):
            if k < len(want) and want[k] == n:
                img = fr.reformat(width=CAM_W, height=CAM_H, format="rgb24").to_ndarray().tobytes()
                while k < len(want) and want[k] == n:
                    enc.stdin.write(img)
                    k += 1
            n += 1
    enc.stdin.close()
    assert enc.wait() == 0
    assert 0 <= n - len(stamps) <= 1, f"{avi.name}: {n} frames decoded, {len(stamps)} timestamps"
    assert k == len(want), (k, len(want))


def convert(ep: Path, site: Path) -> None:
    import h5py
    parts = ep.parts
    split = "play_data" if "play_data" in parts else "evaluation"
    task = "play" if split == "play_data" else parts[-2]
    num = parts[-1].rsplit("_", 1)[1]
    vid = f"td_{task}_{num}"
    title = "Teleoperated play" if task == "play" else task.replace("_", " ").capitalize()

    with h5py.File(ep / "touch_sensor_values.h5", "r") as f:
        tv, tts = f["sensor_values"][()], f["timestamps"][()]
    eff = {}
    for s in STREAMS[1:]:
        with h5py.File(ep / s, "r") as f:
            eff[s] = (f["efforts"][()], f["timestamps"][()])
    cams = sorted(p.name.split("_rgb")[0] for p in ep.glob("cam_*_rgb_video.metadata"))
    stamps = {c: np.asarray(load_meta(ep / f"{c}_rgb_video.metadata")["timestamps"], np.float64) / 1000 for c in cams}
    assert tv.shape[1:] == (15, 16, 3) and np.isfinite(tv).all()

    # clock: from the first touch sample (the cameras start 2.3-2.9 s earlier) to the end of the shortest of touch and cameras
    t0 = float(tts[0])
    t1 = min([float(tts[-1])] + [float(s[-1]) for s in stamps.values()])
    n = int(np.floor((t1 - t0) * FPS)) + 1
    clock = t0 + np.arange(n) / FPS
    ti = latest(tts, clock)
    v = tv[ti].reshape(n, 240, 3)                               # pad-major taxels, (x, y, z)
    mag = np.linalg.norm(v, axis=-1)
    hi = float(np.percentile(mag, 99.5))
    rng = float(max(500, 250 * np.ceil(hi / 250)))
    tax = np.clip(np.round(mag / rng * 255), 0, 255).astype(np.uint8)

    rows, cols, pos, regions, pads = layout()
    padsum = v.reshape(n, 15, 16, 3).sum(2)                    # the authors' 'sumpool' representation, (n, 15, 3)
    vecs = padsum * np.array([1, -1, 1], np.float32)           # y down in the release's plots -> y up in the viewer
    vmag = np.linalg.norm(padsum, axis=-1)
    vr = float(max(1000, 1000 * np.ceil(np.percentile(vmag, 99.5) / 1000)))
    dead = [(p, t) for p in range(15) for t in range(16) if not np.any(tv[:, p, t, :])]
    # dead taxels (constant zero on all axes for the whole recording) are left out of "cells" and drawn hollow ("inactive")
    keep = [k for k in range(240) if (k // 16, k % 16) not in dead]
    cell_of = {k: i for i, k in enumerate(keep)}
    sel = lambda ks: [cell_of[k] for k in ks if k in cell_of]

    hand = {"key": "rh", "title": "Allegro hand · XELA uSkin", "rate": FPS, "rows": rows, "cols": cols,
            "cells": b64(np.array([pos[k] for k in keep], np.uint16)), "tax": b64(tax[:, keep]), "range": rng,
            "unit": "|(x, y, z)|, uncalibrated",
            "regions": [{"name": nm, "cells": sel(reg)} for nm, reg in zip(REGION_NAMES, regions)],
            "label": "15 pads · 4×4 taxels · 3-axis",
            "vectors": {"label": "pad sum of the 16 taxels", "unit": "(uncalibrated)", "range": vr, "axes": "(x, y)", "zname": "z",
                        "items": [{"region": REGION_NAMES[next(c for c, col in enumerate(COLS) if p in col)], "cells": sel(pads[p]),
                                   "data": b64(vecs[:, p].astype(np.float32))} for p in range(15)]}}
    if dead:
        hand["inactive"] = [pos[p * 16 + t] for p, t in dead]

    fsum = [np.stack([padsum[:, p] for p in col if p is not None]).sum(0) for col in COLS]           # (n, 3) per finger column
    ftan = [np.stack([np.hypot(padsum[:, p, 0], padsum[:, p, 1]) for p in col if p is not None]).sum(0) for col in COLS]
    series = [{"title": "XELA · normal: sum of z over the pads of each finger column (uncalibrated)",
               "lines": [{"name": nm, "data": b64(fsum[c][:, 2].astype(np.float32)), "col": COLORS[c]} for c, nm in enumerate(REGION_NAMES)]},
              {"title": "XELA · tangential: sum over the pads of |(Σx, Σy)| per pad, per finger column (uncalibrated)",
               "lines": [{"name": nm, "data": b64(ftan[c].astype(np.float32)), "col": COLORS[c]} for c, nm in enumerate(REGION_NAMES)]}]
    am, at = eff["allegro_joint_states.h5"]
    ac, act = eff["allegro_commanded_joint_states.h5"]
    am, ac = am[latest(at, clock)], ac[latest(act, clock)]
    for fname, j0 in ALLEGRO_FINGERS:
        lines = []
        for k in range(4):
            lines.append({"name": f"j{j0 + k}", "data": b64(am[:, j0 + k].astype(np.float32)), "col": COLORS[k]})
            lines.append({"name": f"j{j0 + k} cmd", "data": b64(ac[:, j0 + k].astype(np.float32)), "col": COLORS[k], "dash": True})
        series.append({"title": f"Allegro {fname} finger · joint efforts (PD torque output, units not stated)",
                       "lines": lines, "legendText": f"joints {j0}–{j0 + 3}: purple, blue, green, yellow · solid = joint state, dashed = commanded"})
    km, kt = eff["kinova_joint_states.h5"]
    km = km[latest(kt, clock)]
    series.append({"title": "Kinova Jaco · joint efforts (units not stated)",
                   "lines": [{"name": f"j{k}", "data": b64(km[:, k].astype(np.float32)), "col": COLORS[k]} for k in range(km.shape[1])]})

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    for c in cams:
        dst = media / f"{vid}_{c}.mp4"
        if not dst.exists():
            camera(ep / f"{c}_rgb_video.avi", stamps[c], clock, dst)
        videos.append({"key": c, "title": f"Camera {c[-1]} (static RealSense, RGB)", "src": f"media/{vid}_{c}.mp4",
                       "src_size": [1280, 720], "fps_src": round(float(1 / np.median(np.diff(stamps[c]))), 1)})
    peak = int(np.argmax(mag.sum(1)))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{peak / FPS:.2f}", "-i", str(media / f"{vid}_{cams[0]}.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)

    rate = (len(tts) - 1) / (tts[-1] - tts[0])
    lead = {c: t0 - s[0] for c, s in stamps.items()}
    extra = [c for c in cams if frame_count(ep / f"{c}_rgb_video.avi") != len(stamps[c])]
    end_dev = float(np.abs(tv[-max(1, int(round(rate))):]).max())
    dur = n / FPS
    dead_txt = (f"Constant zero on all three axes for the whole recording (dead taxel, drawn as a hollow square and left out of the sums): "
                + ", ".join(f"pad {p} taxel {t}" for p, t in dead) + ". ") if dead else ""
    notes = (
        f"<p>One {FPS} Hz clock starts at the first touch sample; the cameras start {min(lead.values()):.1f}–{max(lead.values()):.1f} s earlier "
        f"and that lead-in (no touch data) is cut. The clock ends with the shortest of the touch and camera streams. Native rates: "
        f"XELA {rate:.1f} Hz, Allegro joint states ~300 Hz, Kinova joint states 50 Hz, cameras ~30 Hz; each panel and plot shows the "
        f"latest sample at or before the cursor. Each camera frame is placed by the release's own per-frame timestamp (the "
        f"<code>.metadata</code> pickle; nearest frame per tick), decoded from the release's MPEG-4 Part 2 AVI (1280×720) and "
        f"re-encoded to H.264 at {CAM_W}×{CAM_H}. "
        + (f"The AVI of {', '.join(extra)} holds one frame more than its timestamp list; frames are matched to timestamps from "
           f"the first frame on, so the last frame is dropped (an offset of at most one frame, 33 ms, if the extra frame is the first). "
           if extra else "")
        + "Depth is not fetched or shown.</p>"
        f"<p>Touch: <code>touch_sensor_values.h5</code> <code>sensor_values</code> (N, 15, 16, 3) — 15 XELA uSkin pads (paper: '4 on each "
        f"finger and 3 on the thumb'), 4 × 4 taxels per pad, a tri-axial (x, y, z) reading per taxel, uncalibrated (the paper: "
        f"'susceptible to hysterisis' and affected by nearby magnets or metals). The readings start near zero in every recording, so "
        f"they are offsets from the state at the start. Each cell's colour is the taxel's |(x, y, z)|; the colour scale ends at "
        f"{rng:g} (the episode's 99.5th percentile over all taxels and ticks, rounded up; the most loaded taxels saturate). {dead_txt}</p>"
        f"<p>Layout: the release's own pad layout, from the authors' code (github.com/irmakguzey/tactile-dexterity at 4e0af42: <code>utils/visualization.py</code> <code>dump_tactile_state</code>, "
        f"which titles the columns 'Finger: 0–3', and <code>tactile_image.py</code>) and its <code>visualization.mp4</code> previews: "
        f"pads are drawn in a 4 × 4 grid of slots, column c holding pads 4c−1 … 4c+2 top to bottom, with slot (0, 0) empty. The "
        f"paper builds its tactile image the same way ('each of the finger's … sensors are stacked into a column … a 12x4 image for "
        f"the thumb … constant padding for the shorter thumb'), so column 0 (pads 0–2) is the thumb. Which of the Allegro's index, "
        f"middle and ring fingers columns 1–3 are, and which slot of a column is the fingertip, is not documented, so the columns are "
        f"named finger 1–3 as in the code. Within a pad, taxels run row-major from the top left, as that plot code draws "
        f"them. The panel is this schematic, not a drawing of the hand.</p>"
        f"<p>Arrows: per pad, the sum of (x, y, z) over its 16 taxels (the authors' 'sumpool' representation). The authors' plot "
        f"code says 'x and y represents the position, z represents the pressure' and shifts each taxel's dot in proportion to (x, y) in image "
        f"coordinates (y down); y is negated here so the arrow points the way that dot moves. The ring is z. A full-size arrow or "
        f"ring is {vr:g} (the episode's 99.5th percentile of the pad-sum magnitude, rounded up). The plots show, per finger column, "
        f"the summed z (normal) and the summed per-pad tangential magnitude |(Σx, Σy)|, and the region sums add up the taxel "
        f"magnitudes.</p>"
        f"<p>Force-like channels besides touch: the Allegro hand has no joint torque sensors (paper); <code>allegro_joint_states</code> "
        f"<code>efforts</code> is the torque output of its low-level PD position controller, which the paper's NN-Torque baseline uses "
        f"as a force proxy. It is plotted per finger (joint groups from Holo-Dex <code>holodex/constants.py</code> at 3a5c201: index 0–3, middle 4–7, ring 8–11, thumb 12–15) "
        f"together with <code>allegro_commanded_joint_states</code> <code>efforts</code> (dashed); the two nearly coincide. The Kinova "
        f"Jaco's 6 joint efforts are plotted as well. Units of both are not stated.</p>"
        + ("" if task == "play" else
           f"<p>The readings do not return to rest at the end of this demonstration (largest |value| in the last second: {end_dev:.0f}); "
           f"the recording stops while the hand still holds the object, or the sensor drifts (hysteresis); the release does not say which.</p>")
        + "<p>Not shown: joint positions and velocities, commanded joint positions, fingertip positions, the Kinova end-effector pose, "
          "depth, the subsampling index files and the release's preview videos.</p>")
    label = ("play recording" if task == "play" else "task demonstration") + f" {num}"
    item = {"id": vid, "title": title, "label": label, "sub": f"{dur:.0f} s · {len(cams)} camera{'s' if len(cams) > 1 else ''}",
            "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": [hand],
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    p = site / "data" / f"{vid}.json"
    p.write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps({**item, "json_mb": round(p.stat().st_size / 1e6, 2), "range": rng, "vrange": vr, "dead": dead}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("recordings", nargs="+", help="e.g. evaluation/bowl_unstacking/demonstration_2 or play_data/demonstration_10")
    c = sub.add_parser("convert")
    c.add_argument("recording", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.recordings)
    else:
        for ep in a.recording:
            convert(ep.expanduser(), a.site.expanduser())


if __name__ == "__main__":
    main()
