"""Read-only lookups for the nightly review (pipeline/NIGHTLY.md). Prints raw facts from APIs, so numbers in the catalog
come from the source and not from a page summary. Nothing is written.

    python3 scripts/nightly_tool.py hf <repo URL or org/name> [--model]   repo card, gate, license, files and sizes
    python3 scripts/nightly_tool.py hf-commits <repo URL or org/name> [--model]
    python3 scripts/nightly_tool.py gh <repo URL or owner/name>          repo, latest release, top-level files, README
    python3 scripts/nightly_tool.py arxiv <id or URL>                    metadata, versions, comment, abstract
    python3 scripts/nightly_tool.py page <URL>                           links to data hosts, release phrases, text
    python3 scripts/nightly_tool.py find <text>                          catalog entries that cite or name it
    python3 scripts/nightly_tool.py key <URL>                            the key a URL is recorded under in watch/reviewed.json
"""
import json
import re
import sys
import xml.etree.ElementTree as ET

from nightly_lib import arxiv_id, catalog, fetch, get_json, gh_repo, hf_repo, page_print, url_key, urls_in

SAFE = re.compile(r"^[\w.\-/:?=&%#~+@,]+$")


def human(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024


def hf_target(arg: str, model: bool):
    h = hf_repo(arg) if "huggingface.co" in arg or "hf.co" in arg else (("models" if model else "datasets"), arg.strip("/"))
    if not h or not re.fullmatch(r"[\w.\-]+/[\w.\-]+", h[1]):
        sys.exit(f"not a Hugging Face repo: {arg}")
    return h


def cmd_hf(arg: str, model: bool) -> None:
    kind, repo = hf_target(arg, model)
    status, j = get_json(f"https://huggingface.co/api/{kind}/{repo}?expand[]=gated&expand[]=sha&expand[]=lastModified&expand[]=createdAt"
                         f"&expand[]=cardData&expand[]=tags&expand[]=usedStorage&expand[]=private&expand[]=disabled&expand[]=downloads")
    print(f"HTTP {status}  https://huggingface.co/{'datasets/' if kind == 'datasets' else ''}{repo}")
    if status != 200 or not j:
        return
    card = j.get("cardData") or {}
    for k in ("id", "createdAt", "lastModified", "sha", "gated", "private", "disabled", "downloads"):
        print(f"{k}: {j.get(k)}")
    print(f"used storage: {human(j.get('usedStorage'))}")
    print(f"license (card): {card.get('license')}   tags: {', '.join(t for t in j.get('tags', []) if not t.startswith(('region:',)))[:400]}")
    status, tree = get_json(f"https://huggingface.co/api/{kind}/{repo}/tree/main")
    if status == 200 and isinstance(tree, list):
        print(f"top level ({len(tree)} entries):")
        for t in tree[:80]:
            print(f"  {t.get('type'):9} {human(t.get('size')) if t.get('type') == 'file' else '':>10}  {t.get('path')}")
    status, _, body = fetch(f"https://huggingface.co/{'datasets/' if kind == 'datasets' else ''}{repo}/raw/main/README.md")
    if status == 200:
        print("--- README.md (first 6000 characters) ---")
        print(body.decode("utf-8", "replace")[:6000])


def cmd_hf_commits(arg: str, model: bool) -> None:
    kind, repo = hf_target(arg, model)
    status, j = get_json(f"https://huggingface.co/api/{kind}/{repo}/commits/main")
    print(f"HTTP {status}")
    for c in (j or [])[:25]:
        print(f"{str(c.get('date'))[:10]}  {c.get('id', '')[:8]}  {' '.join(str(c.get('title') or '').split())[:140]}")


def cmd_gh(arg: str) -> None:
    g = gh_repo(arg) if "github.com" in arg else tuple(arg.strip("/").split("/")[:2])
    if not g or len(g) != 2 or not all(re.fullmatch(r"[\w.\-]+", x) for x in g):
        sys.exit(f"not a GitHub repo: {arg}")
    o, r = g
    status, j = get_json(f"https://api.github.com/repos/{o}/{r}")
    print(f"HTTP {status}  https://github.com/{o}/{r}")
    if status != 200 or not j:
        return
    for k in ("full_name", "description", "created_at", "pushed_at", "archived", "size", "stargazers_count", "homepage"):
        print(f"{k}: {j.get(k)}")
    print(f"license: {(j.get('license') or {}).get('spdx_id')}")
    status, rel = get_json(f"https://api.github.com/repos/{o}/{r}/releases?per_page=5")
    for x in (rel or [])[:5] if status == 200 else []:
        assets = ", ".join(f"{a['name']} ({human(a.get('size'))})" for a in x.get("assets", [])[:6])
        print(f"release {x.get('tag_name')} {str(x.get('published_at'))[:10]}: {assets}")
    status, top = get_json(f"https://api.github.com/repos/{o}/{r}/contents/")
    if status == 200 and isinstance(top, list):
        print("top level: " + "  ".join(f"{t['name']}{'/' if t.get('type') == 'dir' else ''}" for t in top[:80]))
    status, _, body = fetch(f"https://api.github.com/repos/{o}/{r}/readme", accept="application/vnd.github.raw")
    if status == 200:
        print("--- README (first 8000 characters) ---")
        print(body.decode("utf-8", "replace")[:8000])


def cmd_arxiv(arg: str) -> None:
    aid = arxiv_id(arg) or arg.strip()
    if not re.fullmatch(r"\d{4}\.\d{4,5}|[a-z\-]+(\.[A-Z]{2})?/\d{7}", aid):
        sys.exit(f"not an arXiv id: {arg}")
    status, _, body = fetch(f"https://export.arxiv.org/api/query?id_list={aid}")
    print(f"HTTP {status}")
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    try:
        e = ET.fromstring(body).find("a:entry", ns)
    except ET.ParseError:
        e = None
    if e is None:
        return
    au = [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)]
    print(f"id: {e.findtext('a:id', '', ns)}")
    print(f"title: {' '.join(e.findtext('a:title', '', ns).split())}")
    print(f"authors ({len(au)}): {', '.join(au[:12])}{' ...' if len(au) > 12 else ''}")
    print(f"published: {e.findtext('a:published', '', ns)[:10]}   updated: {e.findtext('a:updated', '', ns)[:10]}")
    print(f"comment: {' '.join((e.findtext('x:comment', '', ns) or '').split())}")
    print(f"journal_ref: {e.findtext('x:journal_ref', '', ns)}")
    print(f"abstract: {' '.join(e.findtext('a:summary', '', ns).split())}")


def cmd_page(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        sys.exit("give a full http(s) URL")
    status, headers, body = fetch(url)
    print(f"HTTP {status}  {headers.get('Content-Type', '')}  {headers.get('Content-Length') or len(body)} bytes")
    if status != 200 or not body:
        return
    fp = page_print(url, body)
    print("links to data hosts and files:")
    for link in fp["links"]:
        print(f"  {link}")
    print("release phrases:")
    for p in fp["phrases"]:
        print(f"  {p}")
    text = re.sub(r"\s+", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", body.decode("utf-8", "replace"), flags=re.S | re.I))
    print(f"--- text (first 5000 of {len(text)} characters) ---\n{text[:5000]}")


def cmd_find(text: str) -> None:
    cat, key, t = catalog(), url_key(text) if "://" in text else None, text.lower()
    hits = 0
    for kind, items in (("dataset", cat["datasets"]), ("model", cat["models"]), ("hardware", cat["hardware"])):
        for x in items:
            keys = {url_key(u) for u in urls_in(x)}
            blob = json.dumps({k: x.get(k) for k in ("id", "name", "title", "authors", "venue", "maker")}, ensure_ascii=False).lower()
            if (key and key in keys) or t in blob or (not key and any(t in (k or "") for k in keys)):
                hits += 1
                print(f"{kind} {x['id']}: {x['name']} ({x.get('venue') or x.get('maker')})")
    print(f"{hits} match{'es' * (hits != 1)}")


def main() -> None:
    if len(sys.argv) < 3 or not SAFE.match(sys.argv[2]) and sys.argv[1] != "find":
        sys.exit(__doc__)
    cmd, arg, model = sys.argv[1], sys.argv[2], "--model" in sys.argv
    {"hf": lambda: cmd_hf(arg, model), "hf-commits": lambda: cmd_hf_commits(arg, model), "gh": lambda: cmd_gh(arg),
     "arxiv": lambda: cmd_arxiv(arg), "page": lambda: cmd_page(arg), "find": lambda: cmd_find(" ".join(sys.argv[2:])),
     "key": lambda: print(url_key(arg))}.get(
        cmd, lambda: sys.exit(__doc__))()


if __name__ == "__main__":
    main()
