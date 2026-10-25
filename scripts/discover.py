"""Nightly discovery scan: collect papers, Hugging Face repos and GitHub repos that may be tactile-hand datasets or models
the catalog does not have yet, for the discovery review (pipeline/NIGHTLY.md, flow "discovery").

    python3 scripts/discover.py [--dry-run] [--slices N]

Sources, every night:
- arXiv: 16 queries over the last 21 days, plus one backfill slice (3 months, moving from 2015 to today and starting
  over), so papers that earlier passes missed come up again;
- OpenAlex: works citing any catalog paper, published in the last 60 days, plus the full citing set of one tenth of
  the catalog papers in rotation;
- Hugging Face: datasets and models whose names match touch terms (broad terms such as "glove" need a second hand
  or touch word), and the newest repos of every organisation that published a catalog dataset or model;
- GitHub: repositories matching tactile-hand searches.
Candidates already in the catalog (any cited URL) or already reviewed (watch/reviewed.json) are left out. The rest are
scored by keywords and merged into the queue watch/candidates.json, which keeps unreviewed items from earlier nights.
"""
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from nightly_lib import WATCH, arxiv_id, catalog, dump_json, fetch, get_json, hf_repo, known_keys, load_json, now_iso, url_key, urls_in

QUERIES = [
    'abs:"tactile glove"',
    'abs:tactile AND abs:glove AND abs:hand',
    'abs:tactile AND abs:"dexterous hand"',
    'abs:tactile AND abs:dexterous AND (abs:dataset OR abs:benchmark)',
    'abs:tactile AND abs:hand AND (abs:dataset OR abs:benchmark) AND abs:manipulation',
    '(abs:visuotactile OR abs:visuo-tactile OR abs:"visual-tactile" OR abs:"vision-tactile") AND abs:hand',
    'abs:tactile AND (abs:"multi-fingered" OR abs:multifingered OR abs:"multi-finger")',
    'abs:tactile AND abs:hand AND (abs:"world model" OR abs:pretraining OR abs:pretrained OR abs:"foundation model")',
    'abs:tactile AND abs:human AND abs:hand AND (abs:egocentric OR abs:demonstration OR abs:demonstrations)',
    '(abs:"pressure glove" OR abs:"force glove" OR abs:"sensing glove" OR abs:"smart glove" OR abs:"haptic glove" OR abs:"e-glove")',
    '(abs:"e-skin" OR abs:"electronic skin" OR abs:"tactile skin") AND abs:hand AND abs:manipulation',
    'abs:taxel AND abs:hand',
    'abs:tactile AND abs:hand AND abs:policy AND abs:dexterous',
    'abs:touch AND abs:hand AND abs:dataset AND (abs:pressure OR abs:force)',
    'abs:tactile AND (abs:pretrained OR abs:pretraining OR abs:foundation) AND abs:manipulation',
    'abs:glove AND (abs:force OR abs:contact OR abs:pressure) AND (abs:dataset OR abs:datasets) AND abs:manipulation',
]
TOUCH = re.compile(r"tactile|touch|haptic|taxel|pressure|force[- ]?sens|e-?skin|electronic skin|piezoresist|capacitive sens", re.I)
HAND = re.compile(r"\bhands?\b|glove|finger|dexter|palm|grasp|in-hand|humanoid|manipulat", re.I)
POS = [(r"tactile glove|sensing glove|pressure glove|haptic glove|smart glove|force glove|e-glove", 4, "glove"),
       (r"dexterous (robot(ic)? )?hand|multi-?finger(ed)? (robot(ic)? )?hand|anthropomorphic hand|humanoid hand|five-finger", 2.5, "hand"),
       (r"\b(datasets?|data sets?|benchmarks?|corpus|corpora)\b", 2, "dataset"),
       (r"\b(release|open[- ]source|publicly available|made available|will be available|download)|https?://|github\.com|huggingface", 1, ""),
       (r"\btactile\b", 1, ""),
       (r"visuo-?tactile|visual-tactile|vision-tactile", 1.5, ""),
       (r"world model|foundation model|pre-?train|representation learning|encoder", 1, "model"),
       (r"\bpolicy|policies|imitation learning|reinforcement learning", 0.5, "model"),
       (r"egocentric|human demonstration|teleoperat", 1, ""),
       (r"taxel|tactile array|tactile skin|tactile sensors? (on|across|covering)|full-hand|whole-hand", 1.5, ""),
       (r"\bhours\b|\d[- ]hours?\b|episodes|trajectories|demonstrations", 0.5, "")]
NEG = [(r"parallel[- ]jaw|two-finger(ed)? gripper|\bgripper", -1.5), (r"prosthe", -1), (r"braille", -2),
       (r"haptic feedback|vibrotactile|haptic rendering|haptic display", -1.5), (r"surgical|surgery", -1),
       (r"texture classification|material classification|material recognition", -1), (r"\blidar\b|autonomous driving", -2)]
GH_QUERIES = ["tactile glove", "tactile dexterous dataset", "tactile hand dataset", "visuotactile dexterous", "tactile world model hand"]
OWN = ("gh:yuxiang-ma/", "hf:datasets/yxma/", "hf:models/yxma/", "hf:spaces/yxma/")  # this catalog's own repositories
QUEUE_MAX = 400
MIN_SCORE = 2.0


def score(text: str, bonus: float = 0.0, base: float = None):
    """Keyword score of a title and abstract. Papers need a touch word and a hand word; repository names are short, so
    repository candidates come with a base score from the filter that found them instead."""
    if base is None and not (TOUCH.search(text) and HAND.search(text)):
        return 0.0, []
    s, hints = bonus + (base or 0.0), []
    for pat, w, hint in POS:
        if re.search(pat, text, re.I):
            s += w
            if hint and hint not in hints:
                hints.append(hint)
    for pat, w in NEG:
        if re.search(pat, text, re.I):
            s += w
    return round(s, 1), hints


# ---------- arXiv ----------
def arxiv_search(query: str, d0: str, d1: str) -> list:
    q = f"({query}) AND submittedDate:[{d0.replace('-', '')}0000 TO {d1.replace('-', '')}2359]"
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 200})
    status, _, body = fetch(url)
    if status != 200:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", ns):
        aid = arxiv_id(e.findtext("a:id", "", ns) or "")
        if not aid:
            continue
        authors = [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)]
        out.append({"key": f"arxiv:{aid}", "title": " ".join((e.findtext("a:title", "", ns) or "").split()),
                    "url": f"https://arxiv.org/abs/{aid}", "date": (e.findtext("a:published", "", ns) or "")[:10],
                    "authors": (authors[0] + (" et al." if len(authors) > 1 else "")) if authors else None,
                    "abstract": " ".join((e.findtext("a:summary", "", ns) or "").split())})
    return out


def month_add(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    m += n
    return f"{y + (m - 1) // 12}-{(m - 1) % 12 + 1:02d}"


# ---------- OpenAlex ----------
def oa_abstract(inv) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def oa_item(w: dict) -> dict:
    ids = w.get("ids") or {}
    aid = None
    for loc in [w.get("primary_location") or {}] + (w.get("locations") or []):
        aid = aid or arxiv_id((loc or {}).get("landing_page_url") or "")
    doi = (ids.get("doi") or "").replace("https://doi.org/", "")
    key = f"arxiv:{aid}" if aid else url_key(f"https://doi.org/{doi}") if doi else f"openalex:{w['id'].rsplit('/', 1)[-1]}"
    au = [a.get("author", {}).get("display_name") for a in w.get("authorships") or []]
    return {"key": key, "title": w.get("display_name") or w.get("title") or "", "date": w.get("publication_date"),
            "url": f"https://arxiv.org/abs/{aid}" if aid else (f"https://doi.org/{doi}" if doi else w["id"]),
            "authors": (au[0] + (" et al." if len(au) > 1 else "")) if au and au[0] else None,
            "abstract": oa_abstract(w.get("abstract_inverted_index"))[:3000]}


def oa_resolve(key: str, cache: dict):
    if key in cache:
        return cache[key]
    ref = f"doi:10.48550/arXiv.{key[6:]}" if key.startswith("arxiv:") else key if key.startswith("doi:") else None
    if not ref:
        return None
    status, j = get_json(f"https://api.openalex.org/works/{ref}?select=id")
    wid = j["id"].rsplit("/", 1)[-1] if status == 200 and j else None
    if status in (200, 404):
        cache[key] = wid
    return wid


def oa_citing(wid: str, since: str = None) -> list:
    flt = f"cites:{wid}" + (f",from_publication_date:{since}" if since else ",title_and_abstract.search:tactile|touch|haptic|glove")
    out, cursor = [], "*"
    for _ in range(5):
        status, j = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(
            {"filter": flt, "per-page": 200, "cursor": cursor,
             "select": "id,ids,display_name,publication_date,primary_location,locations,authorships,abstract_inverted_index"}))
        if status != 200 or not j:
            break
        out += [oa_item(w) for w in j.get("results", [])]
        cursor = (j.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
    return out


# ---------- Hugging Face, GitHub ----------
HF_SPECIFIC = ["tactile", "haptic", "taxel", "visuotactile", "visuo-tactile"]   # every hit is a candidate
HF_BROAD = ["glove", "touch", "dexterous", "dexhand"]                           # hits need a second hand or touch word
HF_SECOND = re.compile(r"tactil|touch|glove|dex|hand|finger|grasp|manip|force|pressure|human|ego|humanoid|robot", re.I)
NOT_HAND = re.compile(r"glove[._-]?(\d+b|twitter|wiki|\d+d)|word2vec|embedding|msmarco|mteb|pretok|touche20|beir|touchdown|touchpad|"
                      r"touchscreen|goalkeeper|chemical-resistant", re.I)
BIG_ORGS = {"facebook", "meta", "nvidia", "google", "microsoft", "amazon", "apple", "openai", "allenai", "huggingface", "bigscience",
            "lerobot", "ibm", "intel", "salesforce", "tencent", "alibaba", "baidu", "bytedance", "deepmind"}


def hf_item(kind: str, r: dict, bonus: float = 0.0) -> dict:
    rid = r.get("id") or ""
    tags = " ".join(t for t in r.get("tags", []) if not t.startswith(("region:", "size_categories:", "format:", "library:", "modality:")))
    path = f"datasets/{rid}" if kind == "datasets" else rid
    return {"key": f"hf:{kind}/{rid}".lower(), "title": rid, "url": f"https://huggingface.co/{path}", "date": (r.get("createdAt") or "")[:10],
            "authors": rid.split("/")[0], "abstract": tags[:600], "base": 3.0 + bonus}


def hf_list(kind: str, params: dict, pages: int = 1) -> list:
    url, out = f"https://huggingface.co/api/{kind}?" + urllib.parse.urlencode(params), []
    for _ in range(pages):
        status, headers, body = fetch(url, accept="application/json")
        if status != 200:
            break
        try:
            out += json.loads(body)
        except ValueError:
            break
        nxt = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link", "") or headers.get("link", ""))
        if not nxt:
            break
        url = nxt.group(1)
    return out


def hf_search(kind: str, term: str, pages: int = 1) -> list:
    """Hugging Face repos whose name matches a touch or hand term (the search matches names only)."""
    out = []
    for r in hf_list(kind, {"search": term, "sort": "createdAt", "direction": -1, "limit": 100}, pages):
        rid = r.get("id") or ""
        text = f"{rid} {' '.join(r.get('tags', []))}"
        if rid.lower().startswith("yxma/") or NOT_HAND.search(rid) or (term in HF_BROAD and not HF_SECOND.search(rid.split("/", 1)[-1].replace(term, ""))):
            continue
        out.append(hf_item(kind, r))
    return out


def hf_publishers(cat: dict) -> list:
    """Organisations that published a catalog dataset or model on Hugging Face: their newest repos, which is where a
    second release or a renamed copy shows up first."""
    orgs = set()
    for x in cat["datasets"] + cat["models"]:
        for u in urls_in(x.get("links") or {}):
            if (h := hf_repo(u)) and h[0] in ("datasets", "models"):
                orgs.add(h[1].split("/")[0])
    out = []
    for org in sorted(orgs):
        for kind in ("datasets", "models"):
            for r in hf_list(kind, {"author": org, "sort": "createdAt", "direction": -1, "limit": 30}):
                rid = r.get("id") or ""
                if org.lower() in BIG_ORGS and not re.search(r"tactil|touch|haptic|skin|glove", rid, re.I):
                    continue
                out.append(hf_item(kind, r, bonus=1.0))
    return out


GH_ML = re.compile(r"dataset|data\b|benchmark|model|policy|learning|manipulat|teleop|demonstrat|pretrain|awesome", re.I)


def gh_search(q: str) -> list:
    """Repositories whose name, description or topics also mention data or learning; hardware-only glove projects are left out."""
    status, j = get_json("https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": "updated", "order": "desc", "per_page": 50}))
    out = []
    for r in ((j or {}).get("items") or []) if status == 200 else []:
        text = " ".join(filter(None, [r["full_name"], r.get("description") or "", " ".join(r.get("topics") or [])]))
        if GH_ML.search(text):
            out.append({"key": f"gh:{r['full_name']}".lower(), "title": r["full_name"], "url": r["html_url"], "date": (r.get("created_at") or "")[:10],
                        "authors": r["full_name"].split("/")[0], "abstract": text[len(r["full_name"]) + 1:][:600]})
    return out


def main() -> None:
    slices = next((int(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--slices=")), 1)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    ago = lambda days: time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    cat = catalog()
    known = known_keys(cat)
    # a "later" decision is offered again after 30 days; every other decision is final
    reviewed = {k: v for k, v in load_json(WATCH / "reviewed.json", {}).items() if v.get("decision") != "later" or (v.get("date") or "") > ago(30)}
    state = load_json(WATCH / "state.json", {"version": 1, "urls": {}})
    cur = state.setdefault("cursor", {})
    cache = state.setdefault("openalex", {})
    found, log = {}, []

    def add(items: list, source: str, bonus: float = 0.0):
        n = 0
        for c in items:
            k = c["key"]
            if not k or k in known or k in reviewed or k.startswith(OWN):
                continue
            if k in found:
                if source not in found[k]["found_by"]:
                    found[k]["found_by"].append(source)
                    found[k]["score"] = round(found[k]["score"] + 0.5 + bonus, 1)
                continue
            s, hints = score(f"{c['title']} {c.get('abstract') or ''}", bonus, c.pop("base", None))
            if s >= MIN_SCORE:
                found[k] = dict(c, score=s, hints=hints, found_by=[source])
                n += 1
        return n

    # arXiv: recent window and backfill slices
    windows = [("recent", ago(21), today)]
    start = cur.get("arxiv_backfill", "2015-01")
    for _ in range(slices):
        end = month_add(start, 3)
        windows.append((f"backfill {start}", f"{start}-01", time.strftime("%Y-%m-%d", time.strptime(f"{end}-01", "%Y-%m-%d"))))
        start = end if end <= today[:7] else "2015-01"
    for label, d0, d1 in windows:
        n = sum(add(arxiv_search(q, d0, d1), f"arxiv {label}") for q in QUERIES)
        log.append(f"arXiv {label} ({d0} to {d1}): {n} new")
    cur["arxiv_backfill"] = start

    # OpenAlex: works citing catalog papers
    papers = {}
    for kind, items in (("dataset", cat["datasets"]), ("model", cat["models"])):
        for x in items:
            k = url_key((x.get("links") or {}).get("paper") or "")
            if k and k.startswith(("arxiv:", "doi:")):
                papers.setdefault(k, f"{kind}:{x['id']}")
    rot = cur.get("openalex_rotation", 0)
    n_recent = n_full = 0
    for i, (k, owner) in enumerate(sorted(papers.items())):
        wid = oa_resolve(k, cache)
        if not wid:
            continue
        n_recent += add(oa_citing(wid, since=ago(60)), f"openalex cites {owner}", bonus=1.5)
        if i % 10 == rot % 10:
            n_full += add(oa_citing(wid), f"openalex cites {owner}", bonus=1.5)
    cur["openalex_rotation"] = rot + 1
    log.append(f"OpenAlex: {len(papers)} catalog papers, {n_recent} new from recent citations, {n_full} from the full sets of 1/10 of them")

    pages = 1 if cur.get("hf_backfilled") else 5  # the first night reads deeper into the older repos
    n = sum(add(hf_search(kind, t, pages if t in HF_SPECIFIC else 1), f"hf {kind} '{t}'") for kind in ("datasets", "models")
            for t in HF_SPECIFIC + HF_BROAD)
    n_pub = add(hf_publishers(cat), "hf publisher of a catalog entry")
    cur["hf_backfilled"] = True
    log.append(f"Hugging Face: {n} new from name searches, {n_pub} new from publishers of catalog entries")
    n = sum(add(gh_search(q), f"github '{q}'") for q in GH_QUERIES)
    log.append(f"GitHub: {n} new")

    # merge with the queue from earlier nights
    old = load_json(WATCH / "candidates.json", {}).get("candidates", [])
    queue = {c["key"]: c for c in old if c["key"] not in reviewed and c["key"] not in known and not c["key"].startswith(OWN)}
    for k, c in found.items():
        if k in queue:
            queue[k]["found_by"] = sorted(set(queue[k]["found_by"]) | set(c["found_by"]))
            queue[k]["score"] = max(queue[k]["score"], c["score"])
        else:
            queue[k] = dict(c, first_seen=today)
    ranked = sorted(sorted(queue.values(), key=lambda c: c.get("date") or "", reverse=True), key=lambda c: -c["score"])
    dropped = ranked[QUEUE_MAX:]
    ranked = ranked[:QUEUE_MAX]
    for c in ranked:
        c["abstract"] = (c.get("abstract") or "")[:1500]
    out = {"generated": now_iso(), "log": log, "new_tonight": sum(1 for c in ranked if c.get("first_seen") == today),
           "queued": len(ranked), "dropped_low_score": len(dropped), "candidates": ranked}
    print("\n".join(log) + f"\nqueue: {len(ranked)} ({out['new_tonight']} new tonight, {len(dropped)} dropped below the cap)")
    if "--dry-run" in sys.argv:
        for c in ranked[:40]:
            print(f"  {c['score']:4.1f} {c['key']:<34} {c['title'][:90]}")
        return
    dump_json(WATCH / "candidates.json", out)
    state["cursor"], state["openalex"] = cur, cache
    dump_json(WATCH / "state.json", state)


if __name__ == "__main__":
    main()
