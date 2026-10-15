"""Merge the catalog entry of one or more surveys (pipeline/surveys/<id>.json, key "entry") into data/datasets.json.

A new id is appended; an existing entry is updated field by field, printing every change for review. A null or empty
value in the survey never overwrites a value the catalog already has. The result is validated with the same checks as
scripts/build_readme.py, and nothing is written if they fail.

    python3 pipeline/merge_entry.py pipeline/surveys/humanoid_everyday.json [...] [--dry-run]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_readme import REQUIRED, validate  # noqa: E402


def empty(v) -> bool:
    return v is None or v == [] or v == {} or v == ""


def merge(old: dict, new: dict, path: str) -> None:
    for k, v in new.items():
        if empty(v) and not empty(old.get(k)):
            continue
        if isinstance(v, dict) and isinstance(old.get(k), dict) and k not in ("setup",):
            merge(old[k], v, f"{path}.{k}")
        elif old.get(k) != v:
            print(f"{path}.{k}: {json.dumps(old.get(k), ensure_ascii=False)[:120]} -> {json.dumps(v, ensure_ascii=False)[:120]}")
            old[k] = v


def main() -> None:
    files = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    cat_path = ROOT / "data" / "datasets.json"
    cat = json.loads(cat_path.read_text())
    by = {d["id"]: d for d in cat["datasets"]}
    for f in files:
        e = json.loads(f.read_text())["entry"]
        if e["id"] in by:
            merge(by[e["id"]], e, e["id"])
        else:
            missing = [k for k in REQUIRED if k not in e]
            assert not missing, f"{f}: new entry lacks {missing}"
            cat["datasets"].append(e)
            by[e["id"]] = e
            print(f"{e['id']}: new entry")
    errs = validate(cat["datasets"])
    if errs:
        sys.exit("\n".join(errs))
    if "--dry-run" not in sys.argv:
        cat_path.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {cat_path} ({len(cat['datasets'])} datasets); now run python3 scripts/build_readme.py")


if __name__ == "__main__":
    main()
