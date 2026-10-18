"""Check data/datasets.json and data/hardware.json, derive each dataset's rank and contents score, and regenerate the dataset
and hardware lists in README.md.

Usage: python3 scripts/build_readme.py [--check]   (--check exits 1 if README.md or the derived fields are stale; used in CI)

"rank" and "contents" in datasets.json are derived here from the other fields; do not edit them by hand. "integrity" (faults
found in the sample episodes converted for the viewer) and "gate" (how to apply for access) are written by hand.
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


def check_zh(x: dict, tag: str) -> list:
    """Optional Chinese original: zh = {name, title, maker, en: official | translated, note}."""
    z = x.get("zh")
    if z is None:
        return []
    errs = [] if z.get("en") in ("official", "translated") else [f"{tag}: zh.en must be 'official' or 'translated'"]
    return errs + ([] if z.get("name") or z.get("title") or z.get("maker") else [f"{tag}: zh needs a name, title or maker"])


def zh_suffix(x: dict) -> str:
    z = x.get("zh") or {}
    return f" ({z['name']}{'; English name translated by the catalog' if z.get('en') == 'translated' else ''})" if z.get("name") else ""


def validate_hw(hw: list, dataset_ids: set) -> list:
    errs, seen = [], set()
    for h in hw:
        tag = f"hardware {h.get('id', '?')}"
        errs += [f"{tag}: missing {k}" for k in HW_REQUIRED if k not in h] + check_zh(h, tag)
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
    head = (f"[{h['name']}]({url})" if url else h["name"]) + zh_suffix(h)
    bits = [h["maker"] + (f", {h['year']}" if h.get("year") else ""), HW_AVAIL[h["availability"]]]
    if h.get("taxels") is not None:
        bits.append(f"{h['taxels']:,} taxels" + (f" {h['taxels_note']}" if h.get("taxels_note") else ""))
    if h["principle"] != "unspecified":
        bits.append(h["principle"])
    used = ", ".join(names[x["id"]] for x in h["datasets"])
    return f"- {head} - {'; '.join(bits)}." + (f" Used in: {used}." if used else "")


def validate_access(d: dict, tag: str) -> list:
    errs, i, g = [], d.get("integrity"), d.get("gate")
    if (i is None) != (not d.get("viewer")):
        errs.append(f"{tag}: a dataset with viewer samples needs an integrity record, and only such a dataset may have one")
    for f in (i or {}).get("faults", []):
        if f.get("check") not in CHECKS or f.get("severity") not in ("defect", "minor") or not f.get("text"):
            errs.append(f"{tag}: integrity fault needs check in {sorted(CHECKS)}, severity defect|minor and text: {f}")
    if d.get("availability") == "gated" and not g:
        errs.append(f"{tag}: a gated dataset needs a gate record (kind, approval, url)")
    if g and (g.get("kind") not in GATE_KIND or g.get("approval") not in GATE_APPROVAL or not g.get("url")):
        errs.append(f"{tag}: gate needs kind in {sorted(GATE_KIND)}, approval in {sorted(GATE_APPROVAL)} and url")
    return errs


def validate(ds: list) -> list:
    errs, seen = [], set()
    for d in ds:
        tag = d.get("id", "?")
        errs += [f"{tag}: missing {k}" for k in REQUIRED if k not in d] + check_zh(d, tag)
        if not isinstance((d.get("sensor") or {}).get("coverage"), list) or not isinstance(d.get("modalities"), list):
            errs.append(f"{tag}: sensor.coverage and modalities must be lists ([] when not stated)")
        if tag in seen:
            errs.append(f"{tag}: duplicate id")
        seen.add(tag)
        errs += validate_access(d, tag)
        for key, allowed in ENUMS.items():
            obj, *rest = key.split(".")
            v = d.get(obj, {}).get(rest[0]) if rest else d.get(obj)
            for x in v if isinstance(v, list) else [v]:
                if x is not None and x not in allowed:
                    errs.append(f"{tag}: {key} = {x!r} not in {sorted(allowed)}")
    return errs


# The rank depends on two things only: how open the data is (availability, plus the gate in front of it) and whether
# sample episodes opened in the viewer passed the integrity checks. The license does not enter it; it is shown beside it.
RANKS = {1: "Open, checked", 2: "Open, not checked", 3: "Open, defects found", 4: "Apply for access", 5: "Sample only", 6: "Paper only"}
RANK_TEXT = {
    1: "public download; sample episodes opened in the viewer and every integrity check passed",
    2: "public download; the files have not been opened yet",
    3: "public download; sample episodes opened and at least one integrity check failed",
    4: "the data downloads after a form, a Hugging Face gate or the authors' approval",
    5: "only a sample or part of the data is released",
    6: "announced or described in a paper; no data released",
}
CHECKS = {  # key: (label, what passes)
    "files": ("Files open", "every sampled file opens in its documented format"),
    "streams": ("Streams present", "tactile and every listed stream are in the files, none empty"),
    "time": ("Time base", "timestamps or a stated rate align the streams"),
    "tactile": ("Tactile intact", "tactile channels and frames are not lost or corrupted"),
}
CHECK_RULE = ("A check fails when a fault affects more than 5% of a stream's recordings, channels or frames, or when the release "
              "has neither timestamps nor a stated rate; smaller faults are listed as minor. Recordings missing against the "
              "paper's count are scope, not integrity, and are listed in the caveats.")
CONTENTS = [  # (key, label, test): what the data holds; shown, not used for the rank
    ("calibrated", "touch in physical units (N, kPa)", lambda d: d["sensor"].get("calibrated") is True),
    ("video", "synchronized camera video", lambda d: bool((d.get("setup") or {}).get("cameras"))),
    ("hand_pose", "finger pose or joint tracking", lambda d: any(t["target"] == "fingers" for t in (d.get("setup") or {}).get("tracking") or [])),
    ("scale", "10 h or 1,000 episodes or more", lambda d: (d["scale"].get("hours") or 0) >= 10 or (d["scale"].get("episodes") or 0) >= 1000),
    ("diversity", "10 tasks or 5 environments or more", lambda d: (d["scale"].get("tasks") or 0) >= 10 or (d["scale"].get("scenes") or 0) >= 5),
]
GATE_KIND = {"hf_gate": "Hugging Face gate", "form": "access form", "request": "request to the authors", "purchase": "purchase"}
GATE_APPROVAL = {"automatic", "manual", "immediate", "not stated"}


def gate_text(g: dict) -> str:
    return GATE_KIND[g["kind"]] + ("" if g["approval"] == "not stated" else f", {g['approval']} approval")


def integrity(d: dict) -> str:
    """'passed', 'failed' or 'not checked'; checked means sample episodes were converted for the viewer."""
    i = d.get("integrity")
    if i is None:
        return "not checked"
    return "failed" if any(f["severity"] == "defect" for f in i["faults"]) else "passed"


def rank(d: dict, episodes: dict) -> dict:
    av, st = d["availability"], integrity(d)
    if st != "not checked":
        failed = sorted({f["check"] for f in d["integrity"]["faults"] if f["severity"] == "defect"}, key=list(CHECKS).index)
        minor = sum(f["severity"] == "minor" for f in d["integrity"]["faults"])
        n_ep = episodes.get(d["id"], 0)
        chk = [f"{n_ep} sample episode{'s' * (n_ep != 1)} opened in the viewer",
               "failed: " + ", ".join(CHECKS[c][0] for c in failed) if failed else f"all {len(CHECKS)} integrity checks passed"]
        chk += [f"{minor} minor fault{'s' * (minor != 1)} listed"] if minor else []
    else:
        failed, chk = [], ["files not opened yet"]
    if av == "public":
        n = {"passed": 1, "not checked": 2, "failed": 3}[st]
        why = ["public download"] + chk
    elif av == "gated":
        n, why = 4, [f"download after an application: {gate_text(d['gate'])}"] + chk
    elif av == "partial":
        n, why = 5, ["only a sample or part released"] + ([f"application: {gate_text(d['gate'])}"] if d.get("gate") else []) + chk
    else:
        n, why = 6, [AVAIL[av]]
    return {"n": n, "label": RANKS[n], "integrity": st, "failed": failed, "why": why}


def contents(d: dict) -> dict:
    flags = {k: f(d) for k, _, f in CONTENTS}
    return {"score": sum(flags.values()), "of": len(CONTENTS), "flags": flags}


def viewer_episodes() -> dict:
    """Sample episodes per dataset id, from the viewer manifest."""
    m = json.loads((ROOT / "viewer" / "data" / "manifest.json").read_text())
    return {s["id"]: len(s.get("items", [])) for s in m["sources"]}


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
    url = L.get("project") or L.get("paper") or L.get("data")
    head = (f"[{d['name']}]({url})" if url else d["name"]) + zh_suffix(d)
    f = facts(d)
    lic = "license not stated" if d["license"] in ("not stated", "unconfirmed") else f"license: {d['license']}"
    return f"- `R{d['rank']['n']}` {head} - {d['summary']} {dens}; {cov}{'; ' + f if f else ''}; {AVAIL[d['availability']]}; {lic}. {d['venue']} ({links})."


def main() -> None:
    cat = json.loads((ROOT / "data" / "datasets.json").read_text())
    ds = cat["datasets"]
    hw_path = ROOT / "data" / "hardware.json"
    hw_cat = json.loads(hw_path.read_text())
    hw = hw_cat["hardware"]
    errs = validate(ds) + validate_hw(hw, {d["id"] for d in ds})
    if errs:
        sys.exit("\n".join(errs))
    episodes = viewer_episodes()
    for d in ds:
        d.pop("quality", None)
        d["rank"], d["contents"] = rank(d, episodes), contents(d)
    out = [f"**{len(ds)}** datasets · updated {cat['metadata']['last_updated']}", "", "## Ranks", "",
           "The rank follows how open the data is and whether its files passed four integrity checks. "
           "The license does not change the rank; each entry states it separately.", "",
           "| rank | meaning | datasets |", "|---|---|---|"]
    for n, name in RANKS.items():
        ids = sorted((d for d in ds if d["rank"]["n"] == n), key=lambda d: d["name"].lower())
        out.append(f"| `R{n}` {name} | {RANK_TEXT[n]} | {', '.join(d['name'] for d in ids) or '-'} |")
    out += ["", "The integrity checks run on the sample episodes converted for the "
            "[viewer](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/viewer/):", ""]
    out += [f"- **{lbl}**: {what}." for lbl, what in CHECKS.values()]
    out += ["", CHECK_RULE, "", "Failed checks:", ""]
    for d in sorted((d for d in ds if d["rank"]["integrity"] == "failed"), key=lambda d: d["name"].lower()):
        out += [f"- {d['name']}, {CHECKS[f['check']][0].lower()}: {f['text']}" for f in d["integrity"]["faults"] if f["severity"] == "defect"]
    gated = sorted((d for d in ds if d.get("gate")), key=lambda d: (d["rank"]["n"], d["name"].lower()))
    out += ["", "## Access by application", "", f"{len(gated)} datasets need a form, a gate, a request or a purchase before download.", "",
            "| dataset | how | approval | where |", "|---|---|---|---|"]
    for d in gated:
        g = d["gate"]
        out.append(f"| {d['name']} | {GATE_KIND[g['kind']]}{' (' + g['note'] + ')' if g.get('note') else ''} | {g['approval']} | [link]({g['url']}) |")
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
        sys.exit("README.md or the derived rank/contents fields are stale: run python3 scripts/build_readme.py" if stale else 0)
    readme.write_text(new)
    cat_path.write_text(new_cat)
    hw_path.write_text(json.dumps(hw_cat, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(ds)} datasets, {len(hw)} devices")


if __name__ == "__main__":
    main()
