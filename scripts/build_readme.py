"""Check data/datasets.json and regenerate the dataset list in README.md (between the LIST markers).

Usage: python3 scripts/build_readme.py [--check]   (--check exits 1 if README.md is stale; used in CI)
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


TRACK = {"vision_estimate": "estimated from video", "optical_mocap": "optical mocap", "optical_tracker": "Vive tracker", "imu": "IMU",
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
    return f"- {head} - {d['summary']} {dens}; {cov}{'; ' + f if f else ''}; {AVAIL[d['availability']]}. {d['venue']} ({links})."


def main() -> None:
    cat = json.loads((ROOT / "data" / "datasets.json").read_text())
    ds = cat["datasets"]
    errs = validate(ds)
    if errs:
        sys.exit("\n".join(errs))
    out = [f"**{len(ds)}** datasets · updated {cat['metadata']['last_updated']}", ""]
    for emb, title in SECTIONS:
        rows = sorted((d for d in ds if d["embodiment"] == emb), key=lambda d: (-d["year"], d["name"].lower()))
        if rows:
            out += [f"## {title}", ""] + [line(d) for d in rows] + [""]
    readme = ROOT / "README.md"
    text = readme.read_text()
    new = re.sub(r"(<!-- BEGIN LIST -->\n).*?(<!-- END LIST -->)", lambda m: m[1] + "\n".join(out) + "\n" + m[2], text, flags=re.S)
    if "--check" in sys.argv:
        sys.exit(0 if new == text else "README.md is stale: run python3 scripts/build_readme.py")
    readme.write_text(new)
    print(f"{len(ds)} datasets")


if __name__ == "__main__":
    main()
