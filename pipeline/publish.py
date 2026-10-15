#!/usr/bin/env python
"""Publish converted public-dataset samples: data/media files to the media dataset repo, then the page + manifest to the
Space and into this catalog checkout's viewer/ (not committed or pushed).

    python pipeline/publish.py eg_ et_ [--site ~/src/human-mcap-viewer/site]

The viewer source (site/index.html, make_manifest.py) lives in the human-mcap-viewer working tree, whose ext/ is a symlink
to pipeline/converters, so make_manifest.py picks up every converters/<name>.meta.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

CATALOG = Path(__file__).resolve().parent.parent
MEDIA_REPO = "yxma/human-mcap-viewer-media"
SPACE = "yxma/human-mcap-viewer"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefixes", nargs="+")
    ap.add_argument("--site", type=Path, default=Path("~/src/human-mcap-viewer/site"))
    args = ap.parse_args()
    SITE = args.site.expanduser()
    # the manifest must point at the media repo, never at local files
    subprocess.run(["python3", str(SITE.parent / "make_manifest.py"), "--site", str(SITE), "--originflow",
                    str(Path("~/data/originflow").expanduser())], check=True)
    files = sorted(p.relative_to(SITE).as_posix() for pre in args.prefixes for d in ("data", "media") for p in (SITE / d).glob(pre + "*"))
    assert files, "nothing to upload"
    api = HfApi()
    print(api.create_commit(MEDIA_REPO, [CommitOperationAdd(f, str(SITE / f)) for f in files], repo_type="dataset",
                            commit_message=f"Samples: {' '.join(args.prefixes)} ({len(files)} files)").oid)
    # list only items whose data file is already in the media repo (other conversions may be in progress locally)
    remote = set(api.list_repo_files(MEDIA_REPO, repo_type="dataset"))
    man = json.loads((SITE / "data" / "manifest.json").read_text())
    for src in man["sources"]:
        if src.get("group") == "public":
            src["items"] = [it for it in src["items"] if f"data/{it['id']}.json" in remote]
    man["sources"] = [src for src in man["sources"] if src["items"]]
    (SITE / "data" / "manifest.json").write_text(json.dumps(man, indent=1))
    print({src["id"]: len(src["items"]) for src in man["sources"]})
    print(api.create_commit(SPACE, [CommitOperationAdd(f, str(SITE / f)) for f in ("index.html", "data/manifest.json")],
                            repo_type="space", commit_message=f"Viewer + manifest ({' '.join(args.prefixes)})").oid)
    cat = CATALOG
    shutil.copy(SITE / "index.html", cat / "viewer" / "index.html")
    shutil.copy(SITE / "data" / "manifest.json", cat / "viewer" / "data" / "manifest.json")
    print(f"{len(files)} files uploaded; viewer copied into {cat}/viewer")


if __name__ == "__main__":
    main()
