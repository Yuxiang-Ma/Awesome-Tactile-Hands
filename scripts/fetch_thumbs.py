"""Download each dataset's overview figure into assets/thumbs/<id>.jpg (800 px wide) and point `thumb` at it.

Local copies keep the catalog working when a project page moves; `image` keeps the original URL for credit.
Usage: python3 scripts/fetch_thumbs.py [--force]
"""
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "datasets.json"


def main() -> None:
    force = "--force" in sys.argv
    cat = json.loads(DATA.read_text())
    for d in cat["datasets"]:
        out = ROOT / "assets" / "thumbs" / f"{d['id']}.jpg"
        if d.get("image") and (force or not out.exists()):
            with tempfile.NamedTemporaryFile(suffix=Path(d["image"]).suffix.split("?")[0] or ".img") as tmp:
                req = urllib.request.Request(d["image"], headers={"User-Agent": "Mozilla/5.0 (taxel-atlas thumbnail fetch)"})
                try:
                    tmp.write(urllib.request.urlopen(req, timeout=30).read()); tmp.flush()
                except Exception as e:  # keep going; the card falls back to the coverage glyph
                    print(f"{d['id']}: download failed ({e})"); continue
                # flatten transparency onto white, cap the width at 800 px
                r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp.name, "-frames:v", "1", "-filter_complex",
                                    "color=white,format=rgb24[bg];[0:v]scale='min(800,iw)':-2,format=rgba[fg];[bg][fg]scale2ref[bg2][fg2];[bg2][fg2]overlay=shortest=1",
                                    "-q:v", "4", str(out)], capture_output=True, text=True)
                if r.returncode:
                    print(f"{d['id']}: convert failed {r.stderr.strip()[:200]}"); continue
        if out.exists():
            d["thumb"] = f"assets/thumbs/{out.name}"
            print(f"{d['id']}: {out.stat().st_size // 1024} KB")
    DATA.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
