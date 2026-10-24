#!/usr/bin/env python
"""Robotic Origami Challenge episode -> viewer grid recording (site/data/ro_*.json + site/media/ro_* + poster).

The official release (SharpaIT/Robotic_Origami_Challenge, gated on Hugging Face, CC BY 4.0) stores each collection
season twice, as a LeRobot v3.0 root and, for most seasons, a LeRobot v2.1 root with one parquet and one mp4 per stream
per episode. `fetch` reads the v2.1 files of one episode at a pinned revision: the whole episode parquet (~6-10 MB) and,
for each of the six videos, only the sampled window (ffmpeg seeking over HTTP range requests on the signed file URL),
re-encoded to local H.264 clips (the deformation video losslessly, since it is pooled into the hand grid). `convert`
turns one fetched episode into the viewer format and writes the re-encoded media (CC BY 4.0 permits redistribution).

    python -I ext/sharpa_origami.py fetch ~/data/ext/sharpa_origami/eps \
        season_POC22061_2026_05_26_13_55_16_train:4:4:49           # season:episode:t0:t1; needs pyarrow, huggingface_hub
    python -I ext/sharpa_origami.py convert --site site ~/data/ext/sharpa_origami/eps/<id>   # needs numpy + ffmpeg

Downloads need a Hugging Face login whose account has accepted the dataset's gate.

Tactile: each Sharpa Wave hand has five camera-based fingertip sensors. Per frame the release stores a 6-axis fingertip
wrench (observation.tactile, 60 values), one 1600 x 480 video tiling the ten raw sensor images (320 x 240 each) and one
1200 x 480 video tiling the ten deformation maps (240 x 240 each). The viewer shows all three: the deformation maps
mean-pooled to POOL x POOL cells per fingertip, the wrench as an arrow (Fx, Fy) and ring (Fz) on each fingertip block
plus per-finger plots, and both tiled videos as mosaics re-arranged to left hand on top, thumb -> little.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = "SharpaIT/Robotic_Origami_Challenge"
REV = "8194af6b9341dac7686c2f29704ff893e6f2f95e"
FPS = 30
FINGERS = ["thumb", "index", "middle", "ring", "little"]
KEYS = ["head_left", "head_right", "wrist_left", "wrist_right", "tactile_raw", "tactile_deform"]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def episode_id(season: str, ep: int) -> str:
    """season_POC22061_2026_05_26_13_55_16_train, 4 -> ro_poc22061_20260526_1355_ep4"""
    p = season.split("_")
    return f"ro_{p[1].lower()}_{p[2]}{p[3]}{p[4]}_{p[5]}{p[6]}_ep{ep}"


# ---------------------------------------------------------------- fetch (pyarrow + huggingface_hub + ffmpeg)
def signed(path: str) -> tuple[str, int]:
    """Resolve a gated file to its signed CDN URL (no token on the ffmpeg command line) and its size."""
    from huggingface_hub import get_hf_file_metadata, hf_hub_url
    m = get_hf_file_metadata(hf_hub_url(REPO, path, repo_type="dataset", revision=REV))
    return m.location, m.size


def fetch(root: Path, specs: list[str]) -> None:
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    for spec in specs:
        season, e, t0, t1 = spec.split(":")
        e, t0, t1 = int(e), float(t0), float(t1)
        out = root / episode_id(season, e)
        (out / "clips").mkdir(parents=True, exist_ok=True)
        base = f"{season}/lerobotv2.1"
        pq_rel = f"{base}/data/chunk-000/episode_{e:06d}.parquet"
        src = Path(hf_hub_download(REPO, pq_rel, repo_type="dataset", revision=REV, local_dir=out / "src"))
        epmeta = [json.loads(x) for x in Path(hf_hub_download(REPO, f"{base}/meta/episodes.jsonl", repo_type="dataset", revision=REV,
                                                                local_dir=out / "src")).read_text().splitlines() if x.strip()]
        length = next(x["length"] for x in epmeta if x["episode_index"] == e)
        t = pq.read_table(src)
        assert t.num_rows == length and t.column("frame_index").to_pylist() == list(range(length)), "complete episode"
        f0, n = int(round(t0 * FPS)), int(round((t1 - t0) * FPS))
        assert 0 <= f0 and f0 + n <= length, (f0, n, length)
        col = lambda k: np.array(t.column(k).to_pylist()[f0:f0 + n])
        np.savez(out / "data.npz", timestamp=col("timestamp").astype(np.float64), frame_index=col("frame_index"),
                 tactile=col("observation.tactile").astype(np.float32), state=col("observation.state").astype(np.float32),
                 action=col("action").astype(np.float32), joint_torque=col("observation.state.joint_torque").astype(np.float32),
                 tcp=col("observation.state.tcp").astype(np.float32))
        sizes = {}
        for k in KEYS:
            rel = f"{base}/videos/chunk-000/observation.images.{k}/episode_{e:06d}.mp4"
            u, sizes[k] = signed(rel)
            dst = out / "clips" / f"{k}.mp4"
            if dst.exists():
                continue
            # accurate input seek to frame f0 (half a frame of slack against rounding), exactly n frames
            enc = ["-c:v", "libx264", "-qp", "0", "-preset", "veryfast", "-pix_fmt", "yuv420p"] if k == "tactile_deform" else \
                  ["-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(f0 - 0.5, 0) / FPS:.4f}", "-i", u, "-frames:v", str(n), "-an",
                            *enc, str(dst)], check=True)
        meta = {"season": season, "episode_index": e, "length": length, "window": [t0, t1], "f0": f0, "n": n, "revision": REV,
                "parquet": pq_rel, "video_bytes": sizes, "station": season.split("_")[1],
                "start": "{}-{}-{} {}:{}:{}".format(*season.split("_")[2:8])}
        (out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(out.name, "fetched", file=sys.stderr)


# ---------------------------------------------------------------- convert (numpy + ffmpeg)
POOL = 8           # cells per side of each fingertip block (240 px / 30 px)
GAP = 1
THUMB_DROP = 6     # thumb block sits this many rows below the finger row
CAMS = [("head_left", "Head camera, left"), ("head_right", "Head camera, right"), ("wrist_left", "Left wrist camera"),
        ("wrist_right", "Right wrist camera")]


def frames_gray(path: Path, w: int, h: int):
    """Yield the frames of a local video as (h, w) uint8 luma arrays."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    while True:
        b = p.stdout.read(w * h)
        if len(b) < w * h:
            break
        yield np.frombuffer(b, np.uint8).reshape(h, w)
    p.wait()


def pooled_deform(path: Path, n: int) -> np.ndarray:
    """1200 x 480 deformation video (2 rows x 5 tiles of 240 x 240) -> (n, 2, 5, POOL, POOL) float32 block means.
    Tile (row, column) = (hand, finger): row 0 left, row 1 right; columns thumb, index, middle, ring, little."""
    b = 240 // POOL
    out = np.stack([f.reshape(2, 240, 5, 240).transpose(0, 2, 1, 3).reshape(2, 5, POOL, b, POOL, b).astype(np.float32).mean(axis=(3, 5))
                    for f in frames_gray(path, 1200, 480)])
    assert len(out) == n, (len(out), n)
    return out


def layout(key: str) -> tuple[int, int, list[tuple[int, int]]]:
    """Top-left (row, col) of each fingertip block, thumb..little. Fingers in a row, thumb lower on the outside:
    the right hand has its thumb on the left, the left hand is mirrored (as in the other collections)."""
    step = POOL + GAP
    cols = 5 * step - GAP
    rows = THUMB_DROP + POOL
    rh = [(THUMB_DROP, 0)] + [(0, (k + 1) * step) for k in range(4)]
    if key == "rh":
        return rows, cols, rh
    return rows, cols, [(r, cols - c - POOL) for r, c in rh]


def hand(p: np.ndarray, key: str, title: str, rng: float, f6: np.ndarray, frng: float) -> dict:
    """p: (n, 5, POOL, POOL) pooled deformation of this hand; f6: (n, 5, 6) wrench; frng: |F| drawn as a full block."""
    rows, cols, origin = layout(key)
    cells, regions = [], []
    for k, (r0, c0) in enumerate(origin):
        rr, cc = np.mgrid[0:POOL, 0:POOL]
        regions.append({"name": FINGERS[k], "cells": list(range(len(cells), len(cells) + POOL * POOL))})
        cells += ((r0 + rr.ravel()) * cols + c0 + cc.ravel()).tolist()
    tax = np.clip(np.round(p.reshape(len(p), -1) / rng * 255), 0, 255).astype(np.uint8)
    return {"key": key, "title": title, "rate": FPS, "rows": rows, "cols": cols, "cells": b64(np.array(cells, np.uint16)),
            "tax": b64(tax), "range": rng, "unit": "deformation map value", "regions": regions,
            "label": f"5 fingertip sensors · {POOL}×{POOL} cells each",
            "vectors": {"label": "fingertip force", "unit": "(units not stated)", "range": frng, "axes": "(Fx, Fy)", "zname": "Fz",
                        "items": [{"region": f, "data": b64(f6[:, k, :3].astype(np.float32))} for k, f in enumerate(FINGERS)]}}


def encode(src: Path, dst: Path, vf: str | None = None, crf: int = 28) -> None:
    """H.264 for the browser, a keyframe every 2 s so seeking stays cheap."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *(["-vf", vf] if vf else []), "-an", "-c:v", "libx264", "-crf", str(crf),
                    "-preset", "veryfast", "-g", str(2 * FPS), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)], check=True)


def convert(ep: Path, site: Path) -> None:
    m = json.loads((ep / "meta.json").read_text())
    z = np.load(ep / "data.npz")
    n, f0, e = int(m["n"]), int(m["f0"]), int(m["episode_index"])
    assert len(z["timestamp"]) == n and (z["frame_index"] == np.arange(f0, f0 + n)).all(), "window rows"
    assert np.allclose(z["timestamp"], (f0 + np.arange(n)) / FPS, atol=1e-3), "one row per 30 Hz frame"
    vid = ep.name
    assert vid == episode_id(m["season"], e)

    pd = pooled_deform(ep / "clips" / "tactile_deform.mp4", n)
    hi = float(np.percentile(pd, 99.95))
    rng = float(max(20, 5 * np.ceil(hi / 5)))
    f6 = z["tactile"].reshape(n, 2, 5, 6)
    fmag = np.linalg.norm(f6[..., :3], axis=-1)
    frng = float(max(2, 2 * np.ceil(np.percentile(fmag, 99.5) / 2)))
    hands = [hand(pd[:, 0], "lh", "Left hand", rng, f6[:, 0], frng), hand(pd[:, 1], "rh", "Right hand", rng, f6[:, 1], frng)]

    cols = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#d35400"]
    comp = [("Fz", lambda w: w[..., 2]), ("tangential |(Fx, Fy)|", lambda w: np.hypot(w[..., 0], w[..., 1])),
            ("moment |(Tx, Ty, Tz)|", lambda w: np.linalg.norm(w[..., 3:], axis=-1))]
    series = [{"title": f"{side} hand · fingertip {name} (6-axis wrench, units not stated)",
               "lines": [{"name": f, "data": b64(fn(f6[:, s, k]).astype(np.float32)), "col": cols[k]} for k, f in enumerate(FINGERS)]}
              for name, fn in comp for s, side in enumerate(("Left", "Right"))]

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    videos = []
    for cam, title in CAMS:
        dst = media / f"{vid}_{cam}.mp4"
        if not dst.exists():
            encode(ep / "clips" / f"{cam}.mp4", dst, crf=26)
        videos.append({"key": cam, "title": title, "src": f"media/{vid}_{cam}.mp4", "src_size": [480, 480], "fps_src": FPS})
    # the release's tiles are already in viewer order (row 0 left hand, row 1 right; thumb to little), so only scale
    for key, title, size, vf, crf in [
            ("tactile_raw", "Raw fingertip sensor images (top: left hand, bottom: right; thumb to little)", [320, 240], "scale=960:288", 23),
            ("tactile_deform", "Fingertip deformation maps (top: left hand, bottom: right; thumb to little)", [240, 240], "scale=960:384", 23)]:
        dst = media / f"{vid}_{key}.mp4"
        if not dst.exists():
            encode(ep / "clips" / f"{key}.mp4", dst, vf, crf)
        videos.append({"key": key, "title": title, "src": f"media/{vid}_{key}.mp4", "src_size": size, "fps_src": FPS, "wide": True})
    dur = n / FPS
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", str(media / f"{vid}_head_left.mp4"), "-frames:v", "1",
                    "-vf", "scale=240:-2", "-q:v", "5", str(media / f"{vid}.jpg")], check=True)

    t0, t1 = m["window"]
    notes = (f"<p>Window {t0:g}–{t1:g} s of a {m['length'] / FPS:.0f} s episode (season {m['season']}, v2.1 episode {e}; "
             f"official release revision {REV[:7]}). Cameras, tactile videos, wrenches and joints share one frame index at the release's "
             f"30 Hz, so no re-timing is applied; every video here is this window's slice of the release's per-episode "
             f"file, cut at frame {f0} and re-encoded to H.264. In 19 of the 25 loaded fingertip tiles of the four sampled windows the "
             f"wrench correlates best with the deformation tile of the previous frame, so it trails the images by about 33 ms; the "
             f"gain over zero lag is small (median correlation +0.002), and no shift is applied.</p>"
             f"<p>Each Sharpa Wave fingertip is a camera-based tactile sensor. The release tiles the ten fingertips into one raw video "
             f"(320 × 240 per tile) and one deformation video (240 × 240 per tile) without documenting the tile order; row 0 is the "
             f"left hand and columns run thumb, index, middle, ring, little, found by correlating each tile with the ten fingertip "
             f"wrenches (r 0.73–0.99, median 0.92, for the 25 loaded fingertips in the four sampled windows). The hand panels show the deformation "
             f"map averaged over 30 × 30 px patches into a {POOL} × {POOL} grid per fingertip, on a schematic hand (fingers in a "
             f"row, thumb lower on the outside, left hand mirrored); each block keeps the map's pixel orientation, which the release "
             f"does not relate to the finger axis. Values are the video's 0–255 luma, uncalibrated and H.264-compressed in the "
             f"release; the colour scale ends at {rng:.0f} (the window's 99.95th percentile over all cells, rounded up).</p>"
             f"<p>The yellow arrow on each fingertip is (Fx, Fy) and the white ring is Fz of the release's 6-axis fingertip signal "
             f"(<code>observation.tactile</code>, fx fy fz tx ty tz per fingertip, near zero at rest; units and sensor frame not "
             f"stated). Fx is drawn to the right and Fy up; how these axes sit on the finger is not documented. A full-block arrow or "
             f"ring is {frng:g} (the window's 99.5th percentile of |F|, rounded up). The plots show Fz, the tangential magnitude and "
             f"the moment magnitude per finger.</p><p>The two mosaic videos are the release's tactile videos scaled to 960 px "
             f"wide. Not shown: the 65 joint states, actions and joint torques, and "
             f"<code>observation.state.tcp</code>, which is zero in every frame.</p>")
    date = m["start"].split(" ")[0]
    item = {"id": vid, "title": "Fold a paper airplane", "label": f"{m['station']} · {date}",
            "sub": f"{dur:.0f} s of {m['length'] / FPS:.0f} s · season {m['start'].split(' ')[1][:5]}, episode {e}",
            "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": "Fold a paper airplane", "n": n, "fps": FPS, "duration": dur, "videos": videos,
           "hands": hands, "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(item))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("episodes", nargs="+", help="season:episode:t0:t1 (window in seconds on the episode clock)")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.episodes)
    else:
        for ep in a.episode:
            convert(ep.expanduser(), a.site)


if __name__ == "__main__":
    main()
