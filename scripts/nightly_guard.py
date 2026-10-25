"""Check a nightly change set before it is committed or published: it may touch catalog data only, never removes an
entry, and leaves the fields that only a person or build_readme.py writes as they were.

    python3 scripts/nightly_guard.py [--base origin/main]

Compares the working tree (committed or not) with --base. Exit 1 with the reasons when a rule is broken.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_readme import validate, validate_hw, validate_models, validate_changes  # noqa: E402

ALLOWED = [r"data/(datasets|models|hardware)\.json", r"data/changes/\d{4}-\d{2}-\d{2}-(discovery|status)\.json",
           r"pipeline/surveys/[a-z0-9_]+\.json", r"watch/(state|signals|candidates|reviewed)\.json",
           r"watch/runs/\d{4}-\d{2}-\d{2}-(discovery|status)\.json", r"assets/(thumbs|hw)/[a-z0-9_]+\.jpg"]
# fields that come from the viewer pipeline, from a person, or from build_readme.py
FROZEN = {"datasets": ["viewer", "integrity", "thumb", "rank", "contents", "used_by"], "hardware": ["thumb", "image"], "models": []}
DERIVED_NEW = {"datasets": ["viewer", "integrity", "rank", "contents", "used_by"], "hardware": [], "models": []}
MAX_NEW = {"datasets": 10, "models": 15, "hardware": 10}


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def base_json(base: str, path: str):
    try:
        return json.loads(git("show", f"{base}:{path}"))
    except subprocess.CalledProcessError:
        return None


def main() -> None:
    base = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--base=")), "origin/main")
    errs = []
    changed = [ln.split("\t") for ln in git("diff", "--name-status", "--no-renames", base).splitlines() if ln]
    changed += [["A", p] for p in git("ls-files", "--others", "--exclude-standard").splitlines() if p]
    new_ids = set()
    cur = {}
    for name in ("datasets", "models", "hardware"):
        p = ROOT / "data" / f"{name}.json"
        cur[name] = json.loads(p.read_text()) if p.exists() else {"metadata": {}, name: []}
        old = base_json(base, f"data/{name}.json") or {"metadata": {}, name: []}
        by_old = {x["id"]: x for x in old[name]}
        ids = [x["id"] for x in cur[name][name]]
        if len(ids) != len(set(ids)):
            errs.append(f"{name}: duplicate ids")
        gone = sorted(set(by_old) - set(ids))
        if gone:
            errs.append(f"{name}: entries removed: {', '.join(gone)}")
        if cur[name].get("metadata") != old.get("metadata") and old.get("metadata"):
            errs.append(f"{name}: metadata changed (the publish step sets last_updated)")
        added = [x for x in cur[name][name] if x["id"] not in by_old]
        new_ids |= {x["id"] for x in added}
        if len(added) > MAX_NEW[name]:
            errs.append(f"{name}: {len(added)} new entries in one run (limit {MAX_NEW[name]})")
        for x in cur[name][name]:
            o = by_old.get(x["id"])
            if o is None:
                errs += [f"{name} {x['id']}: new entries may not set {k}" for k in DERIVED_NEW[name] if k in x]
                continue
            errs += [f"{name} {x['id']}: {k} changed (written by a person or build_readme.py only)" for k in FROZEN[name] if o.get(k) != x.get(k)]
    for status, path in changed:
        if not any(re.fullmatch(p, path) for p in ALLOWED):
            errs.append(f"{path}: outside the paths a nightly run may change")
        elif status.startswith("D"):
            errs.append(f"{path}: deleted")
        elif path.startswith("assets/") and Path(path).stem not in new_ids:
            errs.append(f"{path}: images may be added for new entries only")
    ds_ids = {d["id"] for d in cur["datasets"]["datasets"]}
    errs += validate(cur["datasets"]["datasets"]) + validate_hw(cur["hardware"]["hardware"], ds_ids)
    errs += validate_models(cur["models"]["models"], ds_ids)
    errs += validate_changes({"dataset": ds_ids, "model": {m["id"] for m in cur["models"]["models"]},
                              "hardware": {h["id"] for h in cur["hardware"]["hardware"]}})
    if errs:
        sys.exit("nightly guard failed:\n" + "\n".join(f"- {e}" for e in errs))
    print(f"nightly guard passed: {len(changed)} changed files, {len(new_ids)} new entries")


if __name__ == "__main__":
    main()
