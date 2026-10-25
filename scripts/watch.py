"""Nightly status scan: fingerprint every link of every dataset and model in the catalog, compare with the last scan, and
list what changed for the status check (pipeline/NIGHTLY.md, flow "status").

    python3 scripts/watch.py [--only id,id] [--dry-run]

Reads data/datasets.json and data/models.json; writes watch/state.json (fingerprints) and watch/signals.json (tonight's
changes, plus the entries not yet fully released that get a deeper check tonight). Nothing in data/ is changed.
Fingerprints: Hugging Face repos (commit sha, gate, license, file count), GitHub repos (README sha, latest release,
license, last push), arXiv papers (version, journal reference, comment) and web pages (links to data hosts, release
phrases such as "coming soon", a hash of the visible text).
"""
import re
import sys
import time
import xml.etree.ElementTree as ET

from nightly_lib import (WATCH, arxiv_id, catalog, dump_json, fetch, get_json, gh_repo, hf_repo, load_json, now_iso,
                         page_print)

STATUS_ONLY = ("drive.google.com", "docs.google.com", "forms.gle", "doi.org", "pan.baidu.com", "1drv.ms", "onedrive.live.com",
               "sharepoint.com", "dropbox.com", "mega.nz")
ROTATION = 3  # entries not yet fully released get a deeper check every ROTATION nights


def released(kind: str, x: dict) -> bool:
    if kind == "dataset":
        return x.get("availability") == "public"
    r = x.get("release") or {}
    return r.get("code") == "released" and r.get("weights") == "released"


def entry_urls(kind: str, x: dict) -> list:
    L = x.get("links") or {}
    urls = [L.get(k) for k in ("data", "code", "weights", "project", "paper")] + [(x.get("gate") or {}).get("url")]
    return [u for u in dict.fromkeys(urls) if isinstance(u, str) and u.startswith("http")]


def probe_arxiv(ids: list) -> dict:
    out, ns = {}, {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        status, _, body = fetch(f"https://export.arxiv.org/api/query?id_list={','.join(chunk)}&max_results={len(chunk)}")
        if status != 200:
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            continue
        for e in root.findall("a:entry", ns):
            full = (e.findtext("a:id", "", ns) or "").rsplit("/abs/", 1)[-1]
            if "v" not in full:
                continue
            aid, ver = full.rsplit("v", 1)
            out[aid] = {"kind": "arxiv", "status": 200, "version": int(ver), "updated": e.findtext("a:updated", "", ns)[:10],
                        "journal_ref": (e.findtext("x:journal_ref", "", ns) or "").strip() or None,
                        "comment": " ".join((e.findtext("x:comment", "", ns) or "").split()) or None}
    return out


def probe_hf(kind: str, repo: str) -> dict:
    status, j = get_json(f"https://huggingface.co/api/{kind}/{repo}")
    fp = {"kind": "hf", "status": status}
    if status == 200 and j:
        lic = (j.get("cardData") or {}).get("license") or next((t[8:] for t in j.get("tags", []) if t.startswith("license:")), None)
        fp.update(id=j.get("id"), sha=j.get("sha"), last_modified=j.get("lastModified"), gated=j.get("gated"), private=j.get("private"),
                  disabled=j.get("disabled"), license=lic if isinstance(lic, str) else str(lic) if lic else None,
                  files=len(j.get("siblings") or []))
    return fp


def probe_gh(owner: str, repo: str) -> dict:
    status, j = get_json(f"https://api.github.com/repos/{owner}/{repo}")
    fp = {"kind": "gh", "status": status}
    if status == 200 and j:
        fp.update(full_name=j.get("full_name"), pushed_at=j.get("pushed_at"), archived=j.get("archived"),
                  license=(j.get("license") or {}).get("spdx_id"), size_kb=j.get("size"))
        s, r = get_json(f"https://api.github.com/repos/{owner}/{repo}/readme")
        fp["readme_sha"] = (r or {}).get("sha") if s == 200 else None
        s, r = get_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        fp["release"] = f"{r.get('tag_name')} {str(r.get('published_at'))[:10]}" if s == 200 and r else None
    elif status == 403:
        fp["status"] = None  # rate limited: keep the last fingerprint
    return fp


def probe_page(url: str) -> dict:
    """A web page: its data links, release phrases and text. A data file: its size only, because ETag and Last-Modified
    differ between the CDN nodes that answer (GitHub Pages, Zenodo). Redirect and sharing hosts: the status only."""
    status, headers, body = fetch(url)
    fp = {"kind": "page", "status": status}
    host = url.split("/")[2].lower()
    ctype = headers.get("Content-Type", "")
    if status == 200 and any(h in host for h in STATUS_ONLY):
        pass
    elif status == 200 and body and re.search(r"html|xml|text", ctype):
        fp.update(page_print(url, body))
    elif status == 200 and not re.search(r"html|json|xml|text", ctype):
        fp["length"] = headers.get("Content-Length")
    return fp


def probe(url: str, arx: dict) -> dict:
    if a := arxiv_id(url):
        return arx.get(a, {"kind": "arxiv", "status": None})
    if h := hf_repo(url):
        return probe_hf(*h)
    if g := gh_repo(url):
        if "github.io" not in url:
            return probe_gh(*g)
    return probe_page(url)


def diff(old: dict, new: dict, open_: bool) -> list:
    """[(priority, type, detail)]: 1 = likely release or access change, 2 = the source was updated, 3 = minor."""
    out = []
    o, n = old.get("status"), new.get("status")
    if o == 200 and n != 200:
        out.append((1, "gone", f"HTTP {o} -> {n} on two scans in a row"))
        return out
    if o != 200 and n == 200:
        out.append((1, "appeared", f"HTTP {o} -> 200"))
        return out
    k = new.get("kind")
    if k == "hf":
        for f, p in (("gated", 1), ("private", 1), ("disabled", 1), ("license", 1), ("id", 2)):
            if old.get(f) != new.get(f):
                out.append((p, f"hf_{f}", f"{old.get(f)} -> {new.get(f)}"))
        if old.get("sha") != new.get("sha"):
            out.append((2 if open_ else 1, "hf_commit", f"files {old.get('files')} -> {new.get('files')}, last modified {new.get('last_modified')}"))
    elif k == "gh":
        if old.get("release") != new.get("release"):
            out.append((1, "gh_release", f"{old.get('release')} -> {new.get('release')}"))
        if old.get("readme_sha") != new.get("readme_sha"):
            out.append((2 if open_ else 1, "gh_readme", "README changed"))
        for f in ("license", "archived", "full_name"):
            if old.get(f) != new.get(f):
                out.append((2, f"gh_{f}", f"{old.get(f)} -> {new.get(f)}"))
        if old.get("pushed_at") != new.get("pushed_at") and not open_ and not out:
            out.append((3, "gh_push", f"last push {new.get('pushed_at')}"))
    elif k == "arxiv":
        for f in ("version", "journal_ref", "comment"):
            if old.get(f) != new.get(f):
                out.append((2, f"arxiv_{f}", f"{old.get(f)} -> {new.get(f)}"))
    elif k == "page":
        added = sorted(set(new.get("links") or []) - set(old.get("links") or []))
        gone = sorted(set(old.get("links") or []) - set(new.get("links") or []))
        if added:
            out.append((1, "links_added", " ".join(added[:12])))
        lost = sorted(set(old.get("phrases") or []) - set(new.get("phrases") or []))
        if lost:
            out.append((1 if not open_ else 2, "phrase_removed", " | ".join(lost[:4])))
        if gone:
            out.append((3, "links_removed", " ".join(gone[:12])))
        new_ph = sorted(set(new.get("phrases") or []) - set(old.get("phrases") or []))
        if new_ph:
            out.append((3, "phrase_added", " | ".join(new_ph[:4])))
        if not out and old.get("text_sha") and old.get("text_sha") != new.get("text_sha"):
            out.append((3, "page_text", f"text length {old.get('text_len')} -> {new.get('text_len')}"))
        if old.get("length") and new.get("length") and old["length"] != new["length"]:
            out.append((2, "file_size", f"{old['length']} -> {new['length']} bytes"))
    return out


def main() -> None:
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv[1:] if a.startswith("--only=")), None)
    cat = catalog()
    entries = [("dataset", d) for d in cat["datasets"]] + [("model", m) for m in cat["models"]]
    if only:
        entries = [(k, x) for k, x in entries if x["id"] in only]
    state = load_json(WATCH / "state.json", {"version": 1, "urls": {}})
    urls = {}
    for kind, x in entries:
        for u in entry_urls(kind, x):
            urls.setdefault(u, []).append((kind, x))
    t0 = time.time()
    arx = probe_arxiv(sorted({a for u in urls if (a := arxiv_id(u))}))
    signals, errors, fresh = [], [], {}
    for u, owners in urls.items():
        new = probe(u, arx)
        old = state["urls"].get(u)
        if new.get("status") is None:
            errors.append({"url": u, "error": "unreachable or rate limited"})
            if old:
                fresh[u] = old
            continue
        if old and old.get("status") == 200 and new.get("status") != 200 and not old.get("failing"):
            fresh[u] = dict(old, failing=new.get("status"))  # wait for a second scan before calling it gone
            continue
        new["seen"] = now_iso()[:10]
        fresh[u] = new
        if not old:
            continue
        for kind, x in owners:
            for prio, typ, detail in diff(old, new, released(kind, x)):
                signals.append({"kind": kind, "id": x["id"], "name": x["name"], "url": u, "priority": prio, "type": typ, "detail": detail,
                                "availability": x.get("availability") or x.get("release")})
    # keep fingerprints of URLs outside --only
    merged = dict(state["urls"]) if only else {}
    merged.update(fresh)
    pending = sorted({(k, x["id"]) for k, x in entries if not released(k, x)})
    day = int(time.strftime("%j", time.gmtime()))
    tonight = [{"kind": k, "id": i} for n, (k, i) in enumerate(pending) if n % ROTATION == day % ROTATION]
    signals.sort(key=lambda s: (s["priority"], s["kind"], s["id"]))
    out = {"generated": now_iso(), "baseline": not state["urls"], "urls_checked": len(urls), "seconds": round(time.time() - t0),
           "signals": signals, "deep_check_tonight": tonight, "not_fully_released": len(pending), "errors": errors}
    print(f"{len(urls)} URLs, {len(signals)} signals ({sum(s['priority'] == 1 for s in signals)} priority 1), {len(errors)} errors, "
          f"{len(tonight)} of {len(pending)} unreleased entries for a deep check, {out['seconds']} s")
    if "--dry-run" in sys.argv:
        for s in signals:
            print(f"  P{s['priority']} {s['kind']} {s['id']}: {s['type']} {s['detail'][:140]}")
        return
    dump_json(WATCH / "state.json", {"version": 1, "updated": out["generated"], "urls": dict(sorted(merged.items())),
                                     **{k: v for k, v in state.items() if k not in ("version", "updated", "urls")}})
    dump_json(WATCH / "signals.json", out)


if __name__ == "__main__":
    main()
