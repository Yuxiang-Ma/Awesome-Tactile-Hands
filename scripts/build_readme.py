"""Check data/datasets.json and data/hardware.json, derive each dataset's rank and quality, and regenerate the dataset
and hardware lists in README.md.

Usage: python3 scripts/build_readme.py [--check]   (--check exits 1 if README.md or the derived fields are stale; used in CI)

"rank" and "quality" in datasets.json are derived here from the other fields; do not edit them by hand.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["id", "name", "title", "authors", "year", "venue", "summary", "embodiment", "hand", "bimanual", "sensor",
            "modalities", "scale", "availability", "access", "license", "links"]
ENUMS = {
    "embodiment": {"human", "robot", "both"},
    "availability": {"public", "gated", "partial", "announced", "unclear", "not_released"},
    "sensor.type": {"piezoresistive", "capacitive", "vision", "magnetic", "unspecified", "estimated"},
    "sensor.coverage": {"tip", "phalanx", "palm"},
    "sensor.principle": {"piezoresistive", "capacitive", "piezoelectric", "magnetic", "optical", "barometric", "resistive", "unspecified"},
    "modalities": {"hand_pose", "egocentric", "wrist_rgb", "multiview_rgb", "rgb", "depth", "object_pose", "mocap", "robot_action",
                   "language", "emg", "imu", "eye_tracking", "audio", "segmentation"},
}
SECTIONS = [("human", "Human tactile gloves"), ("both", "Human-to-robot (paired human and robot touch)"), ("robot", "Tactile robot hands")]
AVAIL = {"public": "public", "gated": "gated", "partial": "partial", "announced": "release announced", "unclear": "availability unclear",
         "not_released": "not released"}
COVER = {"tip": "fingertips", "phalanx": "finger segments", "palm": "palm"}


HW_REQUIRED = ["id", "name", "maker", "kind", "availability", "region", "principle", "coverage", "specs", "links", "datasets", "sources"]
HW_ENUMS = {
    "kind": {"glove", "robot_hand", "sensor", "tracker"},
    "availability": {"commercial", "open_hardware", "research", "announced", "discontinued"},
    "region": {"CN", "US", "EU", "JP", "KR", "SG", "other"},
    "principle": ENUMS["sensor.principle"],
    "coverage": ENUMS["sensor.coverage"],
}
HW_ROLES = {"tactile glove", "robot hand", "tactile sensor", "hand tracking"}
HW_SECTIONS = [("glove", "Tactile gloves"), ("robot_hand", "Tactile robot hands"), ("sensor", "Add-on tactile sensors"),
               ("tracker", "Hand-tracking gloves used with tactile gloves")]
HW_AVAIL = {"commercial": "commercial", "open_hardware": "open hardware", "research": "research only", "announced": "announced",
            "discontinued": "discontinued"}


def validate_hw(hw: list, dataset_ids: set) -> list:
    errs, seen = [], set()
    for h in hw:
        tag = f"hardware {h.get('id', '?')}"
        errs += [f"{tag}: missing {k}" for k in HW_REQUIRED if k not in h]
        if h.get("id") in seen:
            errs.append(f"{tag}: duplicate id")
        seen.add(h.get("id"))
        for key, allowed in HW_ENUMS.items():
            v = h.get(key)
            for x in v if isinstance(v, list) else [v]:
                if x is not None and x not in allowed:
                    errs.append(f"{tag}: {key} = {x!r} not in {sorted(allowed)}")
        for x in h.get("datasets", []):
            if x.get("id") not in dataset_ids:
                errs.append(f"{tag}: unknown dataset {x.get('id')!r}")
            if x.get("role") not in HW_ROLES:
                errs.append(f"{tag}: role {x.get('role')!r} not in {sorted(HW_ROLES)}")
    return errs


def hw_line(h: dict, names: dict) -> str:
    L = h["links"]
    url = L.get("product") or L.get("project") or L.get("paper") or L.get("code")
    head = f"[{h['name']}]({url})" if url else h["name"]
    bits = [h["maker"] + (f", {h['year']}" if h.get("year") else ""), HW_AVAIL[h["availability"]]]
    if h.get("taxels") is not None:
        bits.append(f"{h['taxels']:,} taxels" + (f" {h['taxels_note']}" if h.get("taxels_note") else ""))
    if h["principle"] != "unspecified":
        bits.append(h["principle"])
    used = ", ".join(names[x["id"]] for x in h["datasets"])
    return f"- {head} - {'; '.join(bits)}." + (f" Used in: {used}." if used else "")


def validate(ds: list) -> list:
    errs, seen = [], set()
    for d in ds:
        tag = d.get("id", "?")
        errs += [f"{tag}: missing {k}" for k in REQUIRED if k not in d]
        if tag in seen:
            errs.append(f"{tag}: duplicate id")
        seen.add(tag)
        for key, allowed in ENUMS.items():
            obj, *rest = key.split(".")
            v = d.get(obj, {}).get(rest[0]) if rest else d.get(obj)
            for x in v if isinstance(v, list) else [v]:
                if x is not None and x not in allowed:
                    errs.append(f"{tag}: {key} = {x!r} not in {sorted(allowed)}")
    return errs


# Ranks follow the evidence ranking of the MIT CDFG survey (code > interactive > demo only), applied to data: can you get
# the data, may you reuse it, and has someone opened the files and checked them against the paper.
RANKS = {1: "Open + checked", 2: "Open", 3: "Restricted", 4: "Paper only"}
RANK_TEXT = {
    1: "public download, license stated, and sample episodes converted and checked in the viewer",
    2: "public download, but the license is not stated or the files have not been checked yet",
    3: "gated, on request, or only a partial sample released",
    4: "announced or described in a paper, no data released",
}
QUALITY = [  # (key, label, test)
    ("calibrated", "touch in physical units (N, kPa)", lambda d: d["sensor"].get("calibrated") is True),
    ("video", "synchronized camera video", lambda d: bool((d.get("setup") or {}).get("cameras"))),
    ("hand_pose", "finger pose or joint tracking", lambda d: any(t["target"] == "fingers" for t in (d.get("setup") or {}).get("tracking") or [])),
    ("scale", "10 h or 1,000 episodes or more", lambda d: (d["scale"].get("hours") or 0) >= 10 or (d["scale"].get("episodes") or 0) >= 1000),
    ("diversity", "10 tasks or 5 environments or more", lambda d: (d["scale"].get("tasks") or 0) >= 10 or (d["scale"].get("scenes") or 0) >= 5),
]
UNCLEAR_LICENSE = ("not stated", "unconfirmed", "unclear")


def rank(d: dict) -> dict:
    av, lic = d["availability"], d["license"].lower()
    clear = not any(u in lic for u in UNCLEAR_LICENSE)
    if av in ("announced", "not_released", "unclear"):
        n, why = 4, [AVAIL[av]]
    elif av in ("gated", "partial"):
        n, why = 3, [AVAIL[av]]
    else:
        why = ["public download"] + ([] if clear else ["license not stated"]) + ([] if d.get("viewer") else ["samples not checked yet"])
        n = 1 if clear and d.get("viewer") else 2
        if n == 1:
            why = ["public download", f"license: {d['license']}", "samples checked in the viewer"]
    return {"n": n, "label": RANKS[n], "why": why}


def quality(d: dict) -> dict:
    flags = {k: f(d) for k, _, f in QUALITY}
    return {"score": sum(flags.values()), "of": len(QUALITY), "flags": flags}


TRACK = {"vision_estimate": "vision", "optical_mocap": "optical mocap", "optical_tracker": "Vive tracker", "imu": "IMU",
         "magnetic": "magnetic", "bend_sensor": "bend sensors", "exoskeleton": "exoskeleton", "robot_proprioception": "joint encoders",
         "teleop_glove": "teleop glove", "other": "other"}
ROLE = {"egocentric": "egocentric", "wrist": "wrist", "third_person": "third-person", "robot_head": "robot head", "other": "other"}


def facts(d: dict) -> str:
    """'20 h, 208 tasks; cameras: egocentric + 2 wrist; tracking: IMU (Rokoko Smartgloves)' from the structured fields."""
    c, u, out = d["scale"], d.get("setup"), []
    size = ", ".join(x for x in (f"{c['hours']:g} h" if c.get("hours") else "", f"{c['tasks']:,} tasks" if c.get("tasks") else "",
                                  f"{c['scenes']} environments" if (c.get("scenes") or 0) > 1 else "") if x)
    if size:
        out.append(size)
    if u:
        n = {}
        for cam in u.get("cameras") or []:
            n[cam["role"]] = n.get(cam["role"], 0) + (cam.get("count") or 1)
        out.append("cameras: " + (" + ".join(f"{k} {ROLE[r]}" if (k > 1 or r != "egocentric") else ROLE[r] for r, k in n.items()) or "none"))
        tr = [f"{TRACK[t['method']]}" + (f" ({t['system'].split(' (')[0]})" if t.get("system") else "")
              for t in u.get("tracking") or [] if t["target"] != "object"]
        out.append("hand tracking: " + ("; ".join(dict.fromkeys(tr)) or "none"))
    return "; ".join(out)


def line(d: dict) -> str:
    s, L = d["sensor"], d["links"]
    n = s.get("taxels_per_hand")
    dens = f"{n:,} taxels/hand" if n else f"{s['sensors_per_hand']} sensors/hand" if s.get("sensors_per_hand") else "taxel count not stated"
    cov = ", ".join(COVER[c] for c in s["coverage"]) or "coverage not stated"
    links = ", ".join(f"[{k}]({L[k]})" for k in ("paper", "project", "data", "code") if L.get(k))
    head = f"[{d['name']}]({L.get('project') or L.get('paper')})"
    f = facts(d)
    r, q = d["rank"], d["quality"]
    return f"- `R{r['n']}` `Q{q['score']}/{q['of']}` {head} - {d['summary']} {dens}; {cov}{'; ' + f if f else ''}; {AVAIL[d['availability']]}. {d['venue']} ({links})."


def main() -> None:
    cat = json.loads((ROOT / "data" / "datasets.json").read_text())
    ds = cat["datasets"]
    hw_path = ROOT / "data" / "hardware.json"
    hw_cat = json.loads(hw_path.read_text())
    hw = hw_cat["hardware"]
    errs = validate(ds) + validate_hw(hw, {d["id"] for d in ds})
    if errs:
        sys.exit("\n".join(errs))
    for d in ds:
        d["rank"], d["quality"] = rank(d), quality(d)
    out = [f"**{len(ds)}** datasets · updated {cat['metadata']['last_updated']}", "", "## Ranks", "",
           "Each entry carries a rank for how open and verified its data is, after the evidence ranking of the "
           "[MIT CDFG survey](https://mit-cdfg.github.io/Survey-AI-for-3D-modeling-Robotics/#sub-manipulation-evaluations), "
           "and a quality score counting " + ", ".join(lbl for _, lbl, _ in QUALITY) + ".", "",
           "| rank | meaning | datasets |", "|---|---|---|"]
    for n, name in RANKS.items():
        ids = sorted((d for d in ds if d["rank"]["n"] == n), key=lambda d: (-d["quality"]["score"], d["name"].lower()))
        out.append(f"| `R{n}` {name} | {RANK_TEXT[n]} | {', '.join(d['name'] for d in ids) or '-'} |")
    out.append("")
    for emb, title in SECTIONS:
        rows = sorted((d for d in ds if d["embodiment"] == emb), key=lambda d: (-d["year"], d["name"].lower()))
        if rows:
            out += [f"## {title}", ""] + [line(d) for d in rows] + [""]
    names = {d["id"]: d["name"] for d in ds}
    out += ["## Hardware", "", f"**{len(hw)}** devices, {sum(1 for h in hw if h['datasets'])} of them used by the datasets above. "
            "Photos, specs and a hardware-to-dataset map are on the [hardware page](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/hardware.html).", ""]
    for kind, title in HW_SECTIONS:
        rows = sorted((h for h in hw if h["kind"] == kind), key=lambda h: (-len(h["datasets"]), h["name"].lower()))
        if rows:
            out += [f"### {title}", ""] + [hw_line(h, names) for h in rows] + [""]
    cat_path = ROOT / "data" / "datasets.json"
    new_cat = json.dumps(cat, indent=1, ensure_ascii=False) + "\n"
    readme = ROOT / "README.md"
    text = readme.read_text()
    new = re.sub(r"(<!-- BEGIN LIST -->\n).*?(<!-- END LIST -->)", lambda m: m[1] + "\n".join(out) + "\n" + m[2], text, flags=re.S)
    if "--check" in sys.argv:
        stale = new != text or new_cat != cat_path.read_text() or json.dumps(hw_cat, indent=1, ensure_ascii=False) + "\n" != hw_path.read_text()
        sys.exit("README.md or the derived rank/quality fields are stale: run python3 scripts/build_readme.py" if stale else 0)
    readme.write_text(new)
    cat_path.write_text(new_cat)
    hw_path.write_text(json.dumps(hw_cat, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(ds)} datasets, {len(hw)} devices")


if __name__ == "__main__":
    main()
