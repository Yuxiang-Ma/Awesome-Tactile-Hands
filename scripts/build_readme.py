"""Check data/datasets.json, data/models.json and data/hardware.json, derive each dataset's rank, contents score and
used_by list, and regenerate the dataset, model and hardware lists in README.md.

Usage: python3 scripts/build_readme.py [--check | --validate]
  --check     exit 1 if README.md or a derived file is stale (CI)
  --validate  run every check and derivation without writing anything (nightly runs)

"rank", "contents" and "used_by" in datasets.json are derived here; do not edit them by hand ("used_by" comes from the
models in data/models.json plus a dataset's hand-written "used_by_other"). "integrity" (faults found in the sample
episodes converted for the viewer) and "gate" (how to apply for access) are written by hand. data/changes.json (the
change log) and data/status.json (the last nightly runs) are collected from data/changes/*.json and watch/runs/*.json.
"""
import datetime
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


M_REQUIRED = ["id", "name", "title", "authors", "year", "venue", "kind", "summary", "embodiment", "touch", "uses", "release",
              "license", "links", "sources", "checked"]
M_KIND = {"world_model": "world model", "policy": "policy", "representation": "tactile representation", "estimation": "estimation",
          "generation": "touch generation", "other": "other"}
M_SECTIONS = {"world_model": "World models", "policy": "Policies", "representation": "Tactile representations",
              "estimation": "Estimation (touch from other signals, or state from touch)", "generation": "Touch generation", "other": "Other"}
M_ROLE = ("pretraining", "training", "fine-tuning", "evaluation")
M_RELEASE = {"released": "released", "announced": "announced", "not_released": "not released"}
CHANGE_KIND = ("added", "updated", "released", "withdrawn")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def validate_models(ms: list, dataset_ids: set) -> list:
    errs, seen = [], set()
    for m in ms:
        tag = f"model {m.get('id', '?')}"
        errs += [f"{tag}: missing {k}" for k in M_REQUIRED if k not in m]
        if not re.fullmatch(r"[a-z0-9_]+", str(m.get("id"))) or m.get("id") in seen:
            errs.append(f"{tag}: id must be unique and [a-z0-9_]+")
        seen.add(m.get("id"))
        for key, allowed in (("kind", M_KIND), ("embodiment", ("human", "robot", "both")), ("touch", ("input", "output", "both"))):
            if m.get(key) not in allowed:
                errs.append(f"{tag}: {key} = {m.get(key)!r} not in {sorted(allowed)}")
        r, L = m.get("release") or {}, m.get("links") or {}
        for k in ("code", "weights"):
            if r.get(k) not in M_RELEASE:
                errs.append(f"{tag}: release.{k} = {r.get(k)!r} not in {sorted(M_RELEASE)}")
            elif r[k] == "released" and not L.get(k):
                errs.append(f"{tag}: release.{k} is released, so links.{k} must point at it")
        for u in m.get("uses") or []:
            if u.get("id") not in dataset_ids or u.get("role") not in M_ROLE:
                errs.append(f"{tag}: uses needs a catalog dataset id and a role in {list(M_ROLE)}: {u}")
        if m.get("dataset") is not None and m["dataset"] not in dataset_ids:
            errs.append(f"{tag}: dataset {m['dataset']!r} is not in the catalog")
        if not DATE.fullmatch(str(m.get("checked"))):
            errs.append(f"{tag}: checked must be YYYY-MM-DD")
    return errs


def change_files() -> list:
    return sorted((ROOT / "data" / "changes").glob("*.json"))


def validate_changes(ids: dict) -> list:
    """ids: {"dataset": {...}, "model": {...}, "hardware": {...}}. One file per run: data/changes/<date>-<flow>.json."""
    errs = []
    for f in change_files():
        try:
            c = json.loads(f.read_text())
        except ValueError as e:
            errs.append(f"data/changes/{f.name}: {e}")
            continue
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-(discovery|status|manual)", f.stem)
        if not m or c.get("date") != m[1] or c.get("flow") != m[2]:
            errs.append(f"data/changes/{f.name}: name must be <date>-<discovery|status|manual>.json and match its date and flow")
        for x in c.get("changes", []):
            if x.get("kind") not in CHANGE_KIND or x.get("id") not in ids.get(x.get("target"), ()) or not x.get("text"):
                errs.append(f"data/changes/{f.name}: a change needs kind in {list(CHANGE_KIND)}, target dataset|model|hardware, "
                            f"an id in the catalog and text: {x}")
    return errs


def collect_changes() -> dict:
    """Every change, newest first, from data/changes/*.json."""
    out = []
    for f in change_files():
        c = json.loads(f.read_text())
        out += [dict(x, date=c["date"], flow=c["flow"]) for x in c.get("changes", [])]
    out.sort(key=lambda x: x["date"], reverse=True)
    return {"changes": out}


def collect_runs() -> dict:
    """The newest run report of each nightly flow, from watch/runs/<date>-<flow>.json."""
    runs = {}
    for f in sorted((ROOT / "watch" / "runs").glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        runs[r.get("flow", f.stem[11:])] = r
    return {"runs": runs}


def derive_used_by(ds: list, ms: list) -> None:
    """used_by of each dataset: the models in data/models.json that use it, then its hand-written used_by_other."""
    by = {}
    for m in sorted(ms, key=lambda m: (-m["year"], m["name"].lower())):
        L = m["links"]
        for u in m["uses"]:
            by.setdefault(u["id"], []).append({"name": f"{m['name']}, {m['venue']}", "url": L.get("paper") or L.get("project") or L.get("code"),
                                               "note": u.get("note"), "model": m["id"], **({"own": True} if m.get("dataset") == u["id"] else {})})
    for d in ds:
        ub = by.get(d["id"], []) + d.get("used_by_other", [])
        if ub:
            d["used_by"] = ub
        else:
            d.pop("used_by", None)


def model_line(m: dict, names: dict) -> str:
    L, r = m["links"], m["release"]
    url = L.get("project") or L.get("paper") or L.get("code")
    head = (f"[{m['name']}]({url})" if url else m["name"])
    uses = ", ".join(f"{names[u['id']]} ({u['role']})" for u in m["uses"])
    links = ", ".join(f"[{k}]({L[k]})" for k in ("paper", "code", "weights") if L.get(k))
    return (f"- {head} - {M_KIND[m['kind']]}. {m['summary']} Uses {uses or 'no catalog dataset'}; code {M_RELEASE[r['code']]}, "
            f"weights {M_RELEASE[r['weights']]}. {m['venue']}{f' ({links})' if links else ''}.")


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
    m_path = ROOT / "data" / "models.json"
    m_cat = json.loads(m_path.read_text()) if m_path.exists() else {"metadata": {}, "models": []}
    ms = m_cat["models"]
    ids = {"dataset": {d["id"] for d in ds}, "model": {m["id"] for m in ms}, "hardware": {h["id"] for h in hw}}
    errs = validate(ds) + validate_hw(hw, ids["dataset"]) + validate_models(ms, ids["dataset"]) + validate_changes(ids)
    if errs:
        sys.exit("\n".join(errs))
    episodes = viewer_episodes()
    for d in ds:
        d.pop("quality", None)
        d["rank"], d["contents"] = rank(d, episodes), contents(d)
    derive_used_by(ds, ms)
    changes, runs = collect_changes(), collect_runs()
    out = [f"**{len(ds)}** datasets and **{len(ms)}** models · updated {cat['metadata']['last_updated']}", ""]
    if changes["changes"]:
        newest = changes["changes"][0]["date"]
        cut = (datetime.date.fromisoformat(newest) - datetime.timedelta(days=30)).isoformat()
        recent = [x for x in changes["changes"] if x["date"] >= cut][:30]
        out += ["## Recent changes", "", "Found by the nightly checks ([pipeline/NIGHTLY.md](pipeline/NIGHTLY.md)); newest first.", ""]
        out += [f"- {x['date']}: {x['text']}" for x in recent] + [""]
    out += ["## Ranks", "",
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
    if ms:
        code = sum(m["release"]["code"] == "released" for m in ms)
        wts = sum(m["release"]["weights"] == "released" for m in ms)
        out += ["## Models", "", f"**{len(ms)}** models trained or evaluated on touch recorded across a hand; {code} released code and "
                f"{wts} released weights. Filters and the datasets each one uses are on the "
                "[models page](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/models.html).", ""]
        for kind, title in M_SECTIONS.items():
            rows = sorted((m for m in ms if m["kind"] == kind), key=lambda m: (-m["year"], m["name"].lower()))
            if rows:
                out += [f"### {title}", ""] + [model_line(m, names) for m in rows] + [""]
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
    dump = lambda x: json.dumps(x, indent=1, ensure_ascii=False) + "\n"
    outputs = {readme: new, cat_path: new_cat, hw_path: dump(hw_cat), ROOT / "data" / "changes.json": dump(changes),
               ROOT / "data" / "status.json": dump(runs)}
    if m_path.exists():
        outputs[m_path] = dump(m_cat)
    if "--validate" in sys.argv:
        print(f"valid: {len(ds)} datasets, {len(ms)} models, {len(hw)} devices, {len(changes['changes'])} logged changes")
        return
    if "--check" in sys.argv:
        stale = [p.relative_to(ROOT).as_posix() for p, t in outputs.items() if not p.exists() or p.read_text() != t]
        sys.exit(f"stale: {', '.join(stale)}; run python3 scripts/build_readme.py" if stale else 0)
    for p, t in outputs.items():
        p.write_text(t)
    print(f"{len(ds)} datasets, {len(ms)} models, {len(hw)} devices, {len(changes['changes'])} logged changes")


if __name__ == "__main__":
    main()
