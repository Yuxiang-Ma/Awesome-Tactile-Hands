#!/usr/bin/env python
"""VTDexManip sequence -> viewer grid recording (site/data/vt_*.json + site/media/vt_*_ego.mp4 + poster).

VTDexManip (Liu et al., ICLR 2025; data CC BY-NC-SA 4.0) is released on a password-protected OneDrive share as one
tar.gz of per-frame PNGs per subject (sub1..sub5, 9.5-16 GB each) plus tactile.tar.gz (all 2,032 tactile arrays, 37 MB)
and info.tar.gz (task labels). The share serves HTTP Range requests but only ~0.5 MB/s per connection, so `fetch` does
not stream a whole archive: it finds a sequence's directory by bisection (inflating ~450 kB from a deflate block found
near each probe offset; see "random access into a gzip stream" below), downloads only that stretch (~50 MB per
sequence instead of a 12 GB archive), and recovers the few bytes that depend on the unknown preceding window from the
PNG structure. Every PNG is checked (signature, every chunk CRC) before it is written.

    python -I ext/vtdexmanip.py fetch ~/data/ext/vtdexmanip/eps 501084 502047 ...    # needs requests + numpy
    python -I ext/vtdexmanip.py convert --site site ~/data/ext/vtdexmanip/eps/501084  # needs numpy + ffmpeg

Tactile: a right-hand glove with 20 piezoresistive pads, stored per sequence as a (T, 4, 5) array of pad voltages, one
frame per video frame. The pads are placed on the hand from the authors' own visualization (vitac_pretrain/visualize.py,
dot positions over hand.png), quantised to a 10 px grid.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np

SHARE = "https://1drv.ms/f/c/9054151f0ba654c9/EslUpgsfFVQggJB7AQAAAAABSp31p8Fft1mtHyOwJNqmoA"
PASSWORD = "vtdexmanip"  # published in the GitHub README (github.com/LQTS/VTDexManip)
SITE_API = "https://onedrive.live.com/personal/9054151f0ba654c9"
# The share has no release tag; these are the files as listed on 2026-10-15 (size, ETag), checked before streaming.
PINNED = {"tactile.tar.gz": (37422433, '"{0BA654C9-151F-2054-8090-7E0100000000},2"'),
          "info.tar.gz": (9013, '"{C5BDE455-87E1-4CF4-9AED-68056BA44737},3"'),
          "sub1.tar.gz": (15951810312, '"{0BA654C9-151F-2054-8090-830100000000},3"'),
          "sub2.tar.gz": (10027714157, '"{0BA654C9-151F-2054-8090-7F0100000000},3"'),
          "sub3.tar.gz": (10238053056, '"{0BA654C9-151F-2054-8090-820100000000},3"'),
          "sub4.tar.gz": (9477919907, '"{0BA654C9-151F-2054-8090-800100000000},3"'),
          "sub5.tar.gz": (11964712307, '"{0BA654C9-151F-2054-8090-810100000000},3"')}
FPS = 30            # not stated in the release; the authors' visualize.py writes its videos at 30 fps
RAIL = 3.3          # ADC rail of the glove (V); also the colour range
CONTACT_V = 0.2     # the authors' binarisation threshold (visualize.py, preprocess_tactile_binary(0.2, ...))
TASKS = {1: "PickUp", 2: "ScrewBottles", 3: "InHandOrientation", 4: "Unstacking", 5: "Articulated", 6: "Peg-in-hole",
         7: "Pouring", 8: "TableTopManipulation", 9: "Scissors", 10: "Pressing"}
TITLES = {1: "Pick up an object", 2: "Screw a bottle cap", 3: "In-hand orientation", 4: "Unstack bowls", 5: "Articulated object",
          6: "Peg in hole", 7: "Pour water", 8: "Tabletop manipulation", 9: "Use scissors", 10: "Press buttons"}
# visualize.py draw_points: sensor_pose_list[row, col] = (x, y) px on hand.png (173 x 194, right hand, palm view, thumb right)
POS = np.array([[[18, 55], [48, 30], [78, 15], [105, 22], [152, 66]],
                [[28, 68], [54, 47], [80, 35], [106, 41], [141, 90]],
                [[38, 78], [60, 64], [82, 55], [104, 60], [131, 100]],
                [[48, 88], [66, 81], [84, 75], [103, 78], [70, 120]]])
CELL_PX = 10
# columns of the (4, 5) array: little, ring, middle, index, thumb; rows tip -> base; [3, 4] is the palm pad
REGIONS = [("thumb", [(0, 4), (1, 4), (2, 4)]), ("index", [(r, 3) for r in range(4)]), ("middle", [(r, 2) for r in range(4)]),
           ("ring", [(r, 1) for r in range(4)]), ("little", [(r, 0) for r in range(4)]), ("palm", [(3, 4)])]


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


# ---------------------------------------------------------------- fetch (requests)
def session():
    import requests
    from urllib.parse import parse_qs, urljoin, urlparse
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    r = s.get(SHARE, timeout=60)
    action = html.unescape(re.search(r'<form method="post" action="([^"]+)"', r.text).group(1))
    fields = {k: html.unescape(v) for k, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', r.text)}
    fields["txtPassword"] = PASSWORD
    r2 = s.post(urljoin(r.url, action), data=fields, timeout=60)
    assert "FedAuth" in s.cookies, "password form did not grant access"
    folder = parse_qs(urlparse(r2.url).query)["spopath"][0]
    return s, folder


def listing(s, folder: str) -> dict:
    from urllib.parse import quote
    r = s.get(f"{SITE_API}/_api/web/GetFolderByServerRelativePath(decodedurl='{quote(folder)}')/Files",
              headers={"Accept": "application/json;odata=nometadata"}, timeout=60)
    r.raise_for_status()
    return {x["Name"]: x for x in r.json()["value"]}


def get_range(s, url: str, a: int, b: int, threads: int = 6, piece: int = 4 << 20) -> bytes:
    """Bytes [a, b) of url, fetched as parallel Range requests with retries (the share serves ~0.5 MB/s per connection)."""
    import requests
    from concurrent.futures import ThreadPoolExecutor

    def one(lo: int) -> bytes:
        hi = min(b, lo + piece)
        ss = requests.Session()
        ss.cookies.update(s.cookies)
        ss.headers.update(s.headers)
        for attempt in range(20):
            try:
                r = ss.get(url, headers={"Range": f"bytes={lo}-{hi - 1}"}, timeout=120)
                if r.status_code == 206 and len(r.content) == hi - lo:
                    return r.content
                print(f"  range {lo}: status {r.status_code}, {len(r.content)} bytes; retrying", file=sys.stderr)
            except Exception as e:  # noqa: BLE001 - any network error: retry the piece
                print(f"  range {lo}: {e!r:.80}; retrying", file=sys.stderr)
        raise RuntimeError(f"range {lo}-{hi} failed")

    with ThreadPoolExecutor(threads) as ex:
        return b"".join(ex.map(one, range(a, b, piece)))


# ---- random access into a gzip stream ---------------------------------------------------------------------------------
# The archives are single gzip members (deflate, 32 KiB window). Raw inflate can start at any deflate block boundary;
# the only unknowns are bytes copied from the 32 KiB that precede it. Inflating three times with different preset
# dictionaries (zeros, low byte of the window index, high byte + 1) marks every output byte that depends on the unknown
# window and names the window byte it was copied from. In these archives such bytes sit almost only in the 8-byte IDAT
# chunk headers of the PNGs (libpng writes 8192-byte IDATs), whose values are known, which pins the window bytes; the
# rest are solved against the chunk CRC. Every extracted PNG is then checked: signature, every chunk CRC, full decode.
WIN = 32768
DICTS = (bytes(WIN), bytes(w & 0xFF for w in range(WIN)), bytes((w >> 8) + 1 for w in range(WIN)))
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def shifted(buf: bytes, r: int) -> bytes:
    if r == 0:
        return bytes(buf)
    a = np.frombuffer(buf, np.uint8).astype(np.uint16)
    return ((a[:-1] >> r) | ((a[1:] << (8 - r)) & 0xFF)).astype(np.uint8).tobytes()


def tar_ok(h: bytes) -> bool:
    if len(h) < 512 or h[257:262] != b"ustar":
        return False
    try:
        chk = int(h[148:156].split(b"\0")[0].strip() or b"-1", 8)
    except ValueError:
        return False
    return chk == sum(h[:148]) + 256 + sum(h[156:512])


def tar_headers(out: bytes) -> list[int]:
    res, i = [], out.find(b"ustar")
    while i >= 0:
        if i >= 257 and tar_ok(out[i - 257:i + 255]):
            res.append(i - 257)
        i = out.find(b"ustar", i + 1)
    return res


def find_boundary(buf: bytes, search: int, need: int = 250_000) -> int | None:
    """First bit offset < 8 * search where raw inflate runs for >= need bytes and yields a valid tar header."""
    import zlib
    sh = [shifted(buf, r) for r in range(8)]
    for bit in range(8 * search):
        q, r = divmod(bit, 8)
        s = sh[r]
        if (s[q] >> 1) & 3 != 2:  # BTYPE = dynamic Huffman (zlib emits these for this data)
            continue
        d = zlib.decompressobj(-15, zdict=DICTS[0])
        try:
            out = d.decompress(s[q:q + 2048])
            if len(out) < 500:
                continue
            out += d.decompress(s[q + 2048:], need)
        except zlib.error:
            continue
        if len(out) >= need and tar_headers(out):
            return bit
    return None


def inflate_at(buf: bytes, bit: int):
    """(bytes with unknown-window bytes as 0, dependent mask, window index or -1)."""
    import zlib
    q, r = divmod(bit, 8)
    s = shifted(buf[q:], r)
    outs = [np.frombuffer(zlib.decompressobj(-15, zdict=dz).decompress(s), np.uint8) for dz in DICTS]
    n = min(len(o) for o in outs)
    z, a, b = (o[:n] for o in outs)
    dep = b != z
    w = np.where(dep, a.astype(np.int32) + ((b.astype(np.int32) - 1) << 8), -1)
    return bytearray(z.tobytes()), dep, w


def tar_members(out: bytes, p: int) -> list[tuple[str, int, int]]:
    res = []
    while p + 512 <= len(out) and tar_ok(out[p:p + 512]):
        h = out[p:p + 512]
        size = int(h[124:136].split(b"\0")[0].strip() or b"0", 8)
        res.append((h[:100].split(b"\0")[0].decode(), p + 512, size))
        p += 512 + (size + 511) // 512 * 512
    return res


def png_chunks(png: bytes, dep: np.ndarray) -> list[tuple[int, int, bytes]]:
    pos, res, size = 8, [], len(png)
    while pos + 12 <= size:
        if pos + 12 == size:
            L, t = 0, b"IEND"
        elif pos == 8:
            L, t = 13, b"IHDR"
        elif dep[pos:pos + 8].any():
            rest = size - 12 - pos - 12
            L, t = (8192 if rest > 8192 else rest), b"IDAT"
        else:
            L, t = int.from_bytes(png[pos:pos + 4], "big"), png[pos + 4:pos + 8]
        res.append((pos, L, t))
        pos += 12 + L
    return res


def repair(out: bytearray, dep: np.ndarray, w: np.ndarray, spans) -> dict[str, bool]:
    import zlib
    from collections import Counter, defaultdict
    votes: dict[int, Counter] = defaultdict(Counter)

    def pin(i: int, v: int) -> None:
        votes[int(w[i])][v] += 1

    for _, a, size in spans:
        dp = dep[a:a + size]
        for i in np.flatnonzero(dp[:8]):
            pin(a + i, PNG_SIG[i])
        for pos, L, t in png_chunks(bytes(out[a:a + size]), dp):
            hdr = L.to_bytes(4, "big") + t
            for i in np.flatnonzero(dp[pos:pos + 8]):
                pin(a + pos + i, hdr[i])
    # majority vote; a wrong guess only leaves a chunk failing its CRC, which is reported
    known = {k: c.most_common(1)[0][0] for k, c in votes.items()}
    status: dict[str, bool] = {}
    for _ in range(3):
        idx = np.flatnonzero(dep)
        for i in idx:
            if int(w[i]) in known:
                out[i] = known[int(w[i])]
        for name, a, size in spans:
            png, dp, ok = bytes(out[a:a + size]), dep[a:a + size], True
            for pos, L, t in png_chunks(png, dp):
                body, crc = bytearray(png[pos + 4:pos + 8 + L]), int.from_bytes(png[pos + 8 + L:pos + 12 + L], "big")
                if zlib.crc32(body) == crc:
                    continue
                js = np.flatnonzero(dp[pos + 4:pos + 8 + L])
                unk = sorted({int(w[a + pos + 4 + j]) for j in js} - set(known))
                if not 0 < len(unk) <= 2:
                    ok = False
                    continue
                for v in range(256 ** len(unk)):
                    for m, k in enumerate(unk):
                        for j in js:
                            if int(w[a + pos + 4 + j]) == k:
                                body[j] = (v >> (8 * m)) & 0xFF
                    if zlib.crc32(body) == crc:
                        for m, k in enumerate(unk):
                            known[k] = (v >> (8 * m)) & 0xFF
                        out[a + pos + 4:a + pos + 8 + L] = body
                        break
                else:
                    ok = False
            status[name] = ok and png[:8] == PNG_SIG
        if all(status.values()):
            break
    return status


def png_valid(png: bytes) -> bool:
    import zlib
    if png[:8] != PNG_SIG:
        return False
    pos = 8
    while pos + 12 <= len(png):
        L = int.from_bytes(png[pos:pos + 4], "big")
        if zlib.crc32(png[pos + 4:pos + 8 + L]) != int.from_bytes(png[pos + 8 + L:pos + 12 + L], "big"):
            return False
        if png[pos + 4:pos + 8] == b"IEND":
            return pos + 12 == len(png)
        pos += 12 + L
    return False


def probe(s, url: str, off: int, size: int) -> tuple[int, str] | None:
    """Sequence id of the first tar member found by inflating from just after byte `off`."""
    buf = get_range(s, url, off, min(size, off + 450_000), threads=2, piece=225_000)
    bit = find_boundary(buf, 150_000)
    if bit is None:
        return None
    out, _, _ = inflate_at(buf, bit)
    hs = tar_headers(bytes(out))
    return (off + bit // 8, out[hs[0]:hs[0] + 100].split(b"\0")[0].decode().split("/")[0]) if hs else None


def locate(s, url: str, size: int, sid: str, cache: dict[int, str]) -> int:
    """Byte offset a few MB before directory `sid` starts, by bisection (the archives list directories in id order;
    every probe result is checked against that)."""
    def at(off: int) -> str:
        if off not in cache:
            for k in range(5):
                p = probe(s, url, off + k * 300_000, size)
                if p is not None:
                    cache[off] = p[1]
                    break
            else:
                raise RuntimeError(f"no deflate block found near {off}")
        return cache[off]
    lo, hi = 0, size - 500_000
    if at(lo) >= sid:
        return 0
    while hi - lo > 3_000_000:
        mid = (lo + hi) // 2
        if at(mid) < sid:
            lo = mid
        else:
            hi = mid
    pts = sorted(cache.items())
    assert all(a[1] <= b[1] for a, b in zip(pts, pts[1:])), f"directories not in id order: {pts}"
    return lo


def fetch_one(s, url: str, size: int, sid: str, n: int, dst: Path, cache: dict[int, str]) -> int:
    """Extract the n PNGs of sequence sid into dst; returns compressed bytes downloaded."""
    off = locate(s, url, size, sid, cache)
    est = int(n * 115_000) + 6_000_000
    buf, total = b"", 0
    while True:
        end = min(size, off + est)
        buf += get_range(s, url, off + len(buf), end)
        total = len(buf)
        bit = find_boundary(buf[:1_000_000], 300_000)
        out, dep, w = inflate_at(buf, bit)
        hs = tar_headers(bytes(out[:400_000]))
        mem = tar_members(bytes(out), hs[0])
        mine = [m for m in mem if m[0].startswith(f"{sid}/") and m[0].endswith(".png") and m[1] + m[2] <= len(out)]
        past = any(m[0].split("/")[0] > sid for m in mem)
        if len(mine) >= n or past or end == size:
            break
        est = int(est * 1.3)
    assert mine and mine[0] is not mem[0], f"{sid}: decoding must start before the directory"
    status = repair(out, dep, w, mine)
    for name, a, sz in mine:
        png = bytes(out[a:a + sz])
        if not (status[name] and png_valid(png)):
            raise RuntimeError(f"{name}: could not be recovered")
        (dst / Path(name).name).write_bytes(png)
    print(f"{sid}: {len(mine)} PNGs from {total / 1e6:.1f} MB at offset {off} (dependent bytes {int(dep.sum())})", file=sys.stderr)
    return total


def fetch(root: Path, ids: list[str], tactile_tgz: Path | None) -> None:
    s, folder = session()
    files = listing(s, folder)
    for name, (size, etag) in PINNED.items():
        assert int(files[name]["Length"]) == size, (name, files[name]["Length"])
        if files[name].get("ETag") != etag:
            print(f"warning: {name} ETag {files[name].get('ETag')} differs from the pinned {etag}", file=sys.stderr)
    dl = lambda name: f"{SITE_API}/_layouts/15/download.aspx?UniqueId={files[name]['UniqueId']}"

    # tactile arrays (read from the json copies, not the pickles) for every requested id
    if tactile_tgz is None or not tactile_tgz.exists():
        tactile_tgz = root / "tactile.tar.gz"
        if not tactile_tgz.exists():
            root.mkdir(parents=True, exist_ok=True)
            tactile_tgz.write_bytes(get_range(s, dl("tactile.tar.gz"), 0, PINNED["tactile.tar.gz"][0]))
    want: dict[str, np.ndarray | None] = {i: None for i in ids}
    with tarfile.open(tactile_tgz) as tf:
        for m in tf:
            stem = Path(m.name).stem
            if m.isfile() and m.name.endswith(".json") and stem in want:
                arr = np.array(json.loads(tf.extractfile(m).read()), np.float64)
                assert arr.ndim == 3 and arr.shape[1:] == (4, 5), (stem, arr.shape)
                want[stem] = arr
    for i, a in want.items():
        assert a is not None, f"no tactile for {i}"
        (root / i / "frames").mkdir(parents=True, exist_ok=True)
        np.save(root / i / "tactile.npy", a)

    caches: dict[str, dict[int, str]] = {}
    total = 0
    for i in ids:
        frames = root / i / "frames"
        n = len(want[i])
        if len(list(frames.glob("*.png"))) == n:
            continue
        name = f"sub{i[0]}.tar.gz"
        total += fetch_one(s, dl(name), PINNED[name][0], i, n, frames, caches.setdefault(name, {}))
        got = sorted(int(p.stem.split("=")[-1]) for p in frames.glob("*.png"))
        assert got == list(range(n)), f"{i}: PNG indices {got[:3]}... for {n} tactile frames"
    print(f"downloaded {total / 1e6:.0f} MB of frame archives", file=sys.stderr)


# ---------------------------------------------------------------- convert (numpy + ffmpeg)
def grid() -> tuple[int, int, np.ndarray]:
    """(rows, cols, cell index of every pad in storage order (row-major over the (4, 5) array))."""
    x, y = POS[..., 0], POS[..., 1]
    r = np.round((y - y.min()) / CELL_PX).astype(int)
    c = np.round((x - x.min()) / CELL_PX).astype(int)
    rows, cols = int(r.max()) + 1, int(c.max()) + 1
    cells = (r * cols + c).ravel()
    assert len(set(cells.tolist())) == 20, "two pads on one cell"
    return rows, cols, cells.astype(np.uint16)


def encode_video(frames: Path, n: int, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-start_number", "0",
                    "-i", str(frames / f"{frames.parent.name}_idx=%d.png"), "-frames:v", str(n), "-an",
                    "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(dst)], check=True)


def convert(ep: Path, site: Path) -> None:
    sid = ep.name
    v = np.load(ep / "tactile.npy")
    n = len(v)
    pngs = sorted(int(p.stem.split("=")[-1]) for p in (ep / "frames").glob("*.png"))
    assert pngs == list(range(n)), f"{sid}: PNG indices are not 0..{n - 1}"
    task_id, subject = int(sid[1:3]), int(sid[0])
    vid = f"vt_{sid}"
    rows, cols, cells = grid()
    flat = v.reshape(n, 20)
    assert flat.min() >= -0.05, f"{sid}: negative voltages"
    tax = np.clip(np.round(flat / RAIL * 255), 0, 255).astype(np.uint8)
    idx = lambda rc: rc[0] * 5 + rc[1]
    regions = [{"name": name, "cells": [idx(rc) for rc in pads]} for name, pads in REGIONS]
    hands = [{"key": "rh", "title": "Right glove", "rate": None, "rows": rows, "cols": cols, "cells": b64(cells), "tax": b64(tax),
              "range": RAIL, "unit": "V", "regions": regions,
              "label": "20 piezoresistive pads · 4 per finger, 3 on the thumb, 1 palm"}]

    cols_f = ["#8e44ad", "#2e86c1", "#17a589", "#c99a06", "#d35400", "#7f8c8d"]
    contact = (flat >= CONTACT_V)
    tips = [("thumb", (0, 4)), ("index", (0, 3)), ("middle", (0, 2)), ("ring", (0, 1)), ("little", (0, 0))]
    series = [
        {"title": "Fingertip pads · voltage (V)", "fixed": [0, RAIL],
         "lines": [{"name": f, "data": b64(flat[:, idx(rc)].astype(np.float32)), "col": cols_f[k]} for k, (f, rc) in enumerate(tips)]
         + [{"name": "palm", "data": b64(flat[:, idx((3, 4))].astype(np.float32)), "col": cols_f[5]}]},
        {"title": f"Contact · pads at or above {CONTACT_V} V (the authors' binarisation threshold), per region",
         "lines": [{"name": r["name"], "data": b64(contact[:, r["cells"]].sum(1).astype(np.float32)), "col": cols_f[k]}
                   for k, r in enumerate(regions)]},
    ]

    media = site / "media"
    media.mkdir(parents=True, exist_ok=True)
    dst = media / f"{vid}_ego.mp4"
    if not dst.exists():
        encode_video(ep / "frames", n, dst)
    videos = [{"key": "ego", "title": "Egocentric camera (HoloLens 2)", "src": f"media/{vid}_ego.mp4", "src_size": [424, 240], "fps_src": FPS}]
    # poster: the frame with the most pads in contact
    k = int(np.argmax(contact.sum(1) * 10 + flat.sum(1)))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ep / "frames" / f"{sid}_idx={k}.png"), "-vf", "scale=240:-2", "-q:v", "5",
                    str(media / f"{vid}.jpg")], check=True)

    dur = n / FPS
    rail = float((flat >= 3.2).mean() * 100)
    notes = (f"<p>The release pairs every egocentric frame with one glove frame (sequence {sid}: {n} PNGs and a ({n}, 4, 5) tactile "
             f"array, index for index), so no re-timing is applied. It has no timestamps and no frame rate; the paper says the "
             f"glove and the HoloLens 2 were recorded synchronously and that the glove transmits at 200 Hz, not how glove samples "
             f"were matched to frames. The clock here assumes {FPS} fps, the rate the authors' <code>visualize.py</code> writes its "
             f"videos at, so times and durations are approximate. The video is the release's 424 × 240 PNG frames encoded to "
             f"H.264 (CC BY-NC-SA 4.0, re-hosted under the same license).</p>"
             f"<p>Each cell is one piezoresistive pad, shown as the released pad voltage (V). The colour scale ends at {RAIL} V, "
             f"the ceiling the readings reach in the release; pads rest near 0.1 V. In this sequence {rail:.1f}% of pad-frames are "
             f"at or above 3.2 V, i.e. saturated. The paper's calibration U = 0.7216 F<sup>0.5025</sup> + 0.0398 was fitted on "
             f"0.5-7.5 N (up to about 2.0 V), so it is not applied. Pads are placed as in the authors' visualization "
             f"(<code>vitac_pretrain/visualize.py</code>, dot positions over <code>hand.png</code>, a right hand seen from the "
             f"palm, thumb on the right), quantised to a {CELL_PX} px grid: four pads per finger from tip to base, three on the "
             f"thumb, one on the palm. That the glove is on the right hand is read from the frames, not stated per sequence. "
             f"Region sums add up pad voltages. The contact plot counts pads at or above {CONTACT_V} V, the threshold the authors "
             f"binarise at.</p><p>Task: the class in <code>info/{sid[:3]}_labels.json</code> (digits 2-3 of the sequence id); "
             f"subject {subject} is the first digit. The release has no object labels, hand pose or depth, so nothing else is "
             f"left out.</p>")
    title = TITLES[task_id]
    item = {"id": vid, "title": title, "label": f"{TASKS[task_id]} · subject {subject}",
            "sub": f"{n} frames (~{dur:.0f} s) · sequence {sid}", "poster": f"media/{vid}.jpg"}
    out = {"id": vid, "kind": "grid", "title": title, "n": n, "fps": FPS, "duration": dur, "videos": videos, "hands": hands,
           "series": series, "notes": notes, "item": item}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / f"{vid}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps(item))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("root", type=Path)
    f.add_argument("ids", nargs="+", help="6-digit sequence ids (<subject><task 01-10><index>)")
    f.add_argument("--tactile", type=Path, default=None, help="an already downloaded tactile.tar.gz")
    c = sub.add_parser("convert")
    c.add_argument("episode", type=Path, nargs="+", help="directories written by fetch")
    c.add_argument("--site", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.root.expanduser(), a.ids, a.tactile.expanduser() if a.tactile else None)
    else:
        for ep in a.episode:
            convert(ep.expanduser(), a.site)


if __name__ == "__main__":
    main()
