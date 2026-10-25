"""Download each dataset's overview figure into assets/thumbs/<id>.jpg (800 px wide), and each device photo in
data/hardware.json into assets/hw/<id>.jpg (640 px wide), and point `thumb` at it.

Local copies keep the catalog working when a project page moves; `image` keeps the original URL for credit.
Usage: python3 scripts/fetch_thumbs.py [--force] [--only=id,id]   (--only: these entries only; the nightly runs pass their new ids)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from nightly_lib import fetch as fetch_url, public_url

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [("datasets.json", "datasets", "thumbs", 800), ("hardware.json", "hardware", "hw", 640)]  # file, list key, folder, width


def main() -> None:
    force = "--force" in sys.argv
    only = next((set(a.split("=", 1)[1].split(",")) for a in sys.argv[1:] if a.startswith("--only=")), None)
    for name, key, folder, width in TARGETS:
        fetch(ROOT / "data" / name, key, folder, width, force, only)


def fetch(path: Path, key: str, folder: str, width: int, force: bool, only: set = None) -> None:
    cat = json.loads(path.read_text())
    (ROOT / "assets" / folder).mkdir(exist_ok=True)
    for d in cat[key]:
        if only is not None and d["id"] not in only:
            continue
        out = ROOT / "assets" / folder / f"{d['id']}.jpg"
        if d.get("image") and (force or not out.exists()):
            if not public_url(d["image"]):
                print(f"{d['id']}: image URL is not a public http(s) address"); continue
            with tempfile.NamedTemporaryFile(suffix=Path(d["image"]).suffix.split("?")[0] or ".img") as tmp:
                status, _, body = fetch_url(d["image"], text_only=False, max_body=40 << 20)
                # only real image files reach ffmpeg: PNG, JPEG, GIF, WebP
                if status != 200 or not (body[:8] == b"\x89PNG\r\n\x1a\n" or body[:3] == b"\xff\xd8\xff" or body[:4] == b"GIF8"
                                         or body[:4] == b"RIFF" and body[8:12] == b"WEBP"):
                    print(f"{d['id']}: download failed or not an image (HTTP {status})"); continue  # the card falls back to the coverage glyph
                tmp.write(body); tmp.flush()
                # flatten transparency onto white, cap the width
                r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp.name, "-frames:v", "1", "-filter_complex",
                                    f"color=white,format=rgb24[bg];[0:v]scale='min({width},iw)':-2,format=rgba[fg];[bg][fg]scale2ref[bg2][fg2];[bg2][fg2]overlay=shortest=1",
                                    "-q:v", "4", str(out)], capture_output=True, text=True)
                if r.returncode:
                    print(f"{d['id']}: convert failed {r.stderr.strip()[:200]}"); continue
        if out.exists():
            d["thumb"] = f"assets/{folder}/{out.name}"
            print(f"{d['id']}: {out.stat().st_size // 1024} KB")
    path.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
