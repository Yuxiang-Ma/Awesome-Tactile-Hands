"""Nightly discovery scan: collect papers, Hugging Face repos and GitHub repos that may be tactile-hand datasets or models
the catalog does not have yet, for the discovery review (pipeline/NIGHTLY.md, flow "discovery").

    python3 scripts/discover.py [--dry-run] [--slices N]

Sources, every night:
- arXiv: 16 queries over the last 21 days, plus one backfill slice (3 months, moving from 2015 to today and starting
  over), so papers that earlier passes missed come up again;
- OpenAlex: 5 title-and-abstract searches over the last 30 days and over a backfill slice of its own (this finds
  journal and conference papers that are not on arXiv), and every work that cites a catalog paper and was published in
  the last 60 days or mentions touch;
- Hugging Face: datasets and models whose names match touch terms (broad terms such as "glove" need a second hand
  or touch word), and the newest repos of every organisation that published a catalog dataset or model;
- GitHub: repositories matching tactile-hand searches.
Candidates already in the catalog (any cited URL) or already reviewed (watch/reviewed.json) are left out. The rest are
scored by keywords and merged into the queue watch/candidates.json, which keeps unreviewed items from earlier nights.

A window that a source did not fully answer is asked again by the next run: the recent window then reaches back to
the last night every query was answered, and the backfill cursor stays where it was. Unanswered requests are listed
under "problems" in the queue file, and the wrapper copies them into the run report.
"""
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from nightly_lib import (ARXIV_WAITS, WATCH, arxiv_id, catalog, dump_json, fetch, get_json, hf_repo, known_keys, load_json, now_iso,
                         url_key, urls_in)

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
OA_QUERIES = [
    '"tactile glove" OR "pressure glove" OR "sensing glove" OR "smart glove" OR "force glove" OR "haptic glove"',
    'tactile AND (dexterous OR "multi-fingered" OR multifingered OR "robot hand" OR "robotic hand" OR "anthropomorphic hand")',
    '(visuotactile OR "visuo-tactile" OR "visual-tactile" OR "vision-tactile") AND hand',
    '("electronic skin" OR "e-skin" OR "tactile skin" OR "tactile array") AND hand AND (grasp OR grasping OR manipulation OR dataset)',
    '(tactile OR touch OR pressure) AND hand AND (dataset OR benchmark) AND (manipulation OR grasp OR grasping)',
]
OA_SELECT = "id,ids,display_name,publication_date,primary_location,locations,authorships,abstract_inverted_index"
GH_QUERIES = ["tactile glove", "tactile dexterous dataset", "tactile hand dataset", "visuotactile dexterous", "tactile world model hand"]
OWN = ("gh:yuxiang-ma/", "hf:datasets/yxma/", "hf:models/yxma/", "hf:spaces/yxma/")  # this catalog's own repositories
QUEUE_MAX = 400
MIN_SCORE = 2.0
MISSED: dict = {}  # source -> requests it did not answer tonight
TRUNCATED: list = []  # OpenAlex lists that stopped at the page limit


def missed(source: str) -> None:
    MISSED[source] = MISSED.get(source, 0) + 1


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
def arxiv_search(query: str, d0: str, d1: str = None):
    """(papers, answered) for one query over submissions from d0 to d1 (to now when d1 is None)."""
    d1 = d1 or time.strftime("%Y-%m-%d", time.gmtime())
    q = f"({query}) AND submittedDate:[{d0.replace('-', '')}0000 TO {d1.replace('-', '')}2359]"
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 200})
    status, _, body = fetch(url, waits=ARXIV_WAITS)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(body) if status == 200 else None
    except ET.ParseError:
        root = None
    if root is None:
        missed("arXiv")
        return [], False
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
    return out, True


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
    else:
        missed("OpenAlex")
    return wid


def oa_list(flt: str, pages: int, select: str = OA_SELECT):
    """(works, every page answered) for an OpenAlex filter, 200 a page. Without an API key OpenAlex gives the machine's
    IP $0.10 a day, a list request costs $0.001, and cursor paging is refused, so pages are numbered and the whole scan
    keeps to about 20 requests."""
    out = []
    for page in range(1, pages + 1):
        status, j = get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(
            {"filter": flt, "per-page": 200, "page": page, "select": select}), max_body=32 << 20)
        if status != 200 or not j:
            missed("OpenAlex")
            return out, False
        res = j.get("results") or []
        out += res
        count = (j.get("meta") or {}).get("count") or 0
        if len(res) < 200 or len(out) >= count:
            return out, True
    TRUNCATED.append(f"{flt[:80]} ({len(out)} of {count})")
    return out, True


def oa_search(query: str, d0: str, d1: str = None):
    """(works, answered) whose title or abstract match query, published from d0 to d1 (no end when d1 is None)."""
    works, ok = oa_list(f"title_and_abstract.search:{query},from_publication_date:{d0}" + (f",to_publication_date:{d1}" if d1 else ""), 3)
    return [oa_item(w) for w in works], ok


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
            missed("Hugging Face")
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
    if status != 200:
        missed("GitHub")
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
    found, log, problems = {}, [], []

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

    def windows(name: str, days: int) -> list:
        """(label, from, to, cursor after it) for the recent window and tonight's backfill slices of one source. The
        recent window reaches back to the last night the source answered every query (at most 120 days)."""
        out = [("recent", max(min(ago(days), cur.get(f"{name}_recent_ok") or today), ago(120)), None, None)]
        start = cur.get(f"{name}_backfill", "2015-01")
        for _ in range(slices):
            end = month_add(start, 3)
            out.append((f"backfill {start}", f"{start}-01", f"{end}-01", end if end <= today[:7] else "2015-01"))
            start = out[-1][3]
        return out

    def sweep(name: str, title: str, days: int, search, queries: list) -> None:
        for label, d0, d1, after in windows(name, days):
            n = miss = 0
            for q in queries:
                items, ok = search(q, d0, d1)
                miss += not ok
                n += add(items, f"{name} {label}")
            log.append(f"{title} {label} ({d0} to {d1 or today}): {n} new" + (f"; {miss} of {len(queries)} queries not answered" if miss else ""))
            if miss:
                problems.append(f"{title}: {miss} of {len(queries)} queries for {d0} to {d1 or today} not answered; the next run asks again")
                if after:
                    break  # the cursor stays on this slice
            else:
                cur[f"{name}_backfill" if after else f"{name}_recent_ok"] = after or today

    sweep("arxiv", "arXiv", 21, arxiv_search, QUERIES)
    sweep("openalex", "OpenAlex search", 30, oa_search, OA_QUERIES)

    # OpenAlex: works citing catalog papers, one filter per 50 papers: those published in the last 60 days, and all
    # those whose title or abstract mention touch
    papers, unresolved = {}, 0
    for kind, items in (("dataset", cat["datasets"]), ("model", cat["models"])):
        for x in items:
            k = url_key((x.get("links") or {}).get("paper") or "")
            if k and k.startswith(("arxiv:", "doi:")):
                if wid := oa_resolve(k, cache):
                    papers.setdefault(wid, f"{kind}:{x['id']}")
                elif k not in cache:
                    unresolved += 1
    wids, n, lists, miss = sorted(papers), 0, 0, 0
    for i in range(0, len(wids), 50):
        cites = "cites:" + "|".join(wids[i:i + 50])
        for flt in (f"{cites},from_publication_date:{ago(60)}", f"{cites},title_and_abstract.search:tactile|touch|haptic|glove"):
            works, ok = oa_list(flt, 10, OA_SELECT + ",referenced_works")
            lists, miss = lists + 1, miss + (not ok)
            for w in works:
                item = oa_item(w)
                for ref in w.get("referenced_works") or []:
                    if owner := papers.get(ref.rsplit("/", 1)[-1]):
                        n += add([dict(item)], f"openalex cites {owner}", bonus=1.5)
    cur.pop("openalex_rotation", None)
    log.append(f"OpenAlex citations of {len(papers)} catalog papers: {n} new" + (f"; {unresolved} papers not looked up" if unresolved else ""))
    if miss or unresolved:
        problems.append(f"OpenAlex citations: {miss} of {lists} lists and {unresolved} paper lookups not answered; the next run asks again")
    if TRUNCATED:
        log.append(f"OpenAlex lists cut at the page limit: {'; '.join(TRUNCATED)}")

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
    for source, k in sorted(MISSED.items()):
        if not any(p.startswith(source) for p in problems):
            problems.append(f"{source}: {k} requests not answered; tonight's results from it are incomplete")
    # a source counts as not reached when it missed three requests (the point where fetch stops asking it)
    out = {"generated": now_iso(), "log": log, "problems": problems, "sources_failed": sorted(k for k, v in MISSED.items() if v >= 3),
           "new_tonight": sum(1 for c in ranked if c.get("first_seen") == today), "queued": len(ranked),
           "dropped_low_score": len(dropped), "candidates": ranked}
    print("\n".join(log + problems) + f"\nqueue: {len(ranked)} ({out['new_tonight']} new tonight, {len(dropped)} dropped below the cap)")
    if "--dry-run" in sys.argv:
        for c in ranked[:40]:
            print(f"  {c['score']:4.1f} {c['key']:<34} {c['title'][:90]}")
        return
    dump_json(WATCH / "candidates.json", out)
    state["cursor"], state["openalex"] = cur, cache
    dump_json(WATCH / "state.json", state)


if __name__ == "__main__":
    main()
