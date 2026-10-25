"""Shared helpers for the nightly scan (scripts/watch.py, scripts/discover.py): polite HTTP, URL keys, page fingerprints.

Standard library only, so the scan runs on a bare GitHub Actions runner and in a cloud session alike.
"""
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "watch"
UA = "taxel-atlas-watch/1.0 (+https://github.com/Yuxiang-Ma/Awesome-Tactile-Hands)"
GAP = {"export.arxiv.org": 3.2, "arxiv.org": 1.0, "api.openalex.org": 0.15, "api.github.com": 0.4, "huggingface.co": 0.25}
MAX_BODY = 4 << 20
_last: dict = {}


def public_url(url: str) -> bool:
    """True for an http(s) URL whose host resolves only to public addresses. Catalog links and lookups are written by an
    unattended session, so nothing here may reach this machine, the local network or a cloud metadata service."""
    s = urllib.parse.urlsplit(url)
    if s.scheme not in ("http", "https") or not s.hostname:
        return False
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(s.hostname, s.port or (443 if s.scheme == "https" else 80))}
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    return bool(addrs) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_url(newurl):
            raise urllib.error.URLError(f"redirect to a non-public address refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_PublicRedirects)


def fetch(url: str, accept: str = "", timeout: int = 30, tries: int = 3, text_only: bool = True, max_body: int = MAX_BODY):
    """GET url -> (status | None, headers, body bytes). Bodies are read only for text, HTML and JSON, capped at 4 MB, so a
    link to a data archive costs one request and no download. status is None when the host could not be reached or is
    not a public address."""
    if not public_url(url):
        return None, {}, b"not a public http(s) address"
    host = urllib.parse.urlsplit(url).hostname or ""
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    if host == "api.github.com":
        headers["Accept"] = accept or "application/vnd.github+json"
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    if host == "huggingface.co" and os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
    err = ""
    for k in range(tries):
        wait = _last.get(host, 0) + GAP.get(host, 0.5) - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                body = r.read(max_body) if not text_only or re.search(r"text|html|json|xml", ctype) else b""
                return r.status, dict(r.headers), body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and k < tries - 1:
                time.sleep(float(e.headers.get("Retry-After") or 0) or 5 * (k + 1))
                continue
            try:
                body = e.read(65536)
            except Exception:
                body = b""
            return e.code, dict(e.headers or {}), body
        except Exception as e:  # DNS, TLS, timeout, reset
            err = f"{type(e).__name__}: {e}"
            if k < tries - 1:
                time.sleep(4 * (k + 1))
        finally:
            _last[host] = time.time()
    return None, {}, err.encode()


def get_json(url: str, **kw):
    status, _, body = fetch(url, accept=kw.pop("accept", "application/json"), **kw)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


# ---------- URL keys: one key per paper, repository or Hugging Face repo, whatever URL form points at it ----------
ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.I)
HF = re.compile(r"(?:huggingface\.co|hf\.co)/(datasets/|spaces/)?([\w.\-]+)/([\w.\-]+)", re.I)
GH = re.compile(r"github\.com/([\w.\-]+)/([\w.\-]+)", re.I)
DOI = re.compile(r"(?:doi\.org/|doi:)(10\.\d{4,9}/[^\s?#]+)", re.I)
HF_NOT_REPOS = {"docs", "blog", "papers", "settings", "login", "join", "collections", "organizations", "tasks", "learn", "posts"}
GH_NOT_REPOS = {"orgs", "topics", "features", "sponsors", "settings", "marketplace", "about", "login"}


def arxiv_id(url: str):
    m = ARXIV.search(url or "")
    return m.group(1) if m else None


def hf_repo(url: str):
    """('datasets' | 'models' | 'spaces', 'org/name') for a Hugging Face repo URL, else None."""
    m = HF.search(url or "")
    if not m or m.group(2).lower() in HF_NOT_REPOS:
        return None
    kind = {"datasets/": "datasets", "spaces/": "spaces"}.get((m.group(1) or "").lower(), "models")
    name = re.sub(r"\.git$", "", m.group(3))
    return kind, f"{m.group(2)}/{name}"


def gh_repo(url: str):
    m = GH.search(url or "")
    if not m or m.group(1).lower() in GH_NOT_REPOS:
        return None
    return m.group(1), re.sub(r"\.git$", "", m.group(2))


def url_key(url: str):
    """'arxiv:2607.07287', 'hf:datasets/org/name', 'gh:owner/repo', 'doi:10....' or a normalized URL."""
    if not url:
        return None
    if a := arxiv_id(url):
        return f"arxiv:{a}"
    if h := hf_repo(url):
        return f"hf:{h[0]}/{h[1]}".lower()
    if g := gh_repo(url):
        if not re.search(r"github\.io", url):
            return f"gh:{g[0]}/{g[1]}".lower()
    if d := DOI.search(url):
        doi = d.group(1).lower().rstrip(".")
        m = re.match(r"10\.48550/arxiv\.(.+)", doi)
        return f"arxiv:{m.group(1)}" if m else f"doi:{doi}"
    return norm_url(url)


def norm_url(url: str) -> str:
    s = urllib.parse.urlsplit(url.strip())
    q = "&".join(p for p in s.query.split("&") if p and not p.lower().startswith(("utm_", "ref=", "fbclid")))
    path = re.sub(r"/(index\.html?)?$", "", s.path) or ""
    return urllib.parse.urlunsplit((s.scheme.lower() or "https", (s.hostname or "").lower(), path, q, ""))


def urls_in(obj) -> list:
    """Every http(s) URL inside a JSON value."""
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += urls_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += urls_in(v)
    elif isinstance(obj, str):
        out += re.findall(r"https?://[^\s\"'<>)\]]+", obj)
    return out


def catalog() -> dict:
    """The three catalog files (models.json may not exist yet)."""
    out = {}
    for name, key in (("datasets", "datasets"), ("models", "models"), ("hardware", "hardware")):
        p = ROOT / "data" / f"{name}.json"
        out[key] = json.loads(p.read_text())[key] if p.exists() else []
    return out


def known_keys(cat: dict) -> dict:
    """URL key -> 'dataset:<id>' / 'model:<id>' / 'hardware:<id>' for everything the catalog already cites."""
    keys = {}
    for kind, items in (("dataset", cat["datasets"]), ("model", cat["models"]), ("hardware", cat["hardware"])):
        for x in items:
            for u in urls_in({k: v for k, v in x.items() if k not in ("image", "thumb", "image_page")}):
                k = url_key(u)
                if k and (k.startswith(("arxiv:", "hf:", "gh:", "doi:")) or kind != "hardware"):
                    keys.setdefault(k, f"{kind}:{x['id']}")
    return keys


# ---------- page fingerprint: outbound data links, release phrases, text hash ----------
DATA_HOSTS = ("huggingface.co", "hf.co", "github.com", "gitlab.com", "drive.google.com", "docs.google.com", "forms.gle",
              "modelscope.cn", "opendatalab.com", "openxlab.org.cn", "zenodo.org", "figshare.com", "dataverse.", "kaggle.com",
              "pan.baidu.com", "scidb.cn", "sciencedb", "onedrive.live.com", "1drv.ms", "sharepoint.com", "dropbox.com", "box.com",
              "osf.io", "mega.nz", "alipan.com", "aliyundrive.com", "quark.cn", "data.mendeley.com", "ieee-dataport.org",
              "storage.googleapis.com", "amazonaws.com", "cloudfront.net", "wisemodel.cn", "gitee.com")
DATA_EXT = re.compile(r"\.(zip|tar|tgz|gz|7z|rar|h5|hdf5|parquet|pkl|npz|npy|bag|mcap|db3|csv|mat)(\?|$)", re.I)
PHRASE = re.compile(r"[^.!?\n]{0,120}\b(coming soon|to be released|will be (?:made )?(?:publicly )?(?:released|available|open[- ]sourced)|"
                    r"release[ds]? soon|available soon|upon (?:acceptance|publication)|stay tuned|under review|"
                    r"code and (?:data|dataset|models?) will|is being prepared|TBA|TBD)\b[^.!?\n]{0,120}", re.I)


def data_link(u: str) -> bool:
    """A link that can lead to data, code or weights: a repository on Hugging Face or GitHub, a record on a data host, or a
    file with a data extension. Navigation on those hosts (about, help, login, issues) is not one."""
    s = urllib.parse.urlsplit(u)
    host, path = (s.hostname or "").lower(), s.path
    if DATA_EXT.search(u):
        return True
    if host.startswith(("about.", "help.", "docs.", "blog.", "status.", "support.", "developers.")):
        return False
    if "huggingface.co" in host or host == "hf.co":
        return hf_repo(u) is not None and not re.search(r"/(discussions|commits|blame)(/|$)", path)
    if host == "github.com":
        return gh_repo(u) is not None and not re.search(r"^/[^/]+/?$|/(issues|pulls|stargazers|forks?|network|graphs|actions|wiki)(/|$)", path)
    if "zenodo.org" in host:
        return bool(re.match(r"/(records?|doi)/", path))
    return any(d in host for d in DATA_HOSTS)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.text, self._skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        for k, v in attrs:
            if k in ("href", "src", "data-href") and v:
                self.links.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def page_print(url: str, body: bytes) -> dict:
    p = _Page()
    try:
        p.feed(body.decode("utf-8", "replace"))
    except Exception:
        pass
    text = re.sub(r"\s+", " ", " ".join(p.text)).strip()
    links = set()
    for href in p.links:
        h = urllib.parse.urljoin(url, href.strip())
        if not h.startswith("http"):
            continue
        if data_link(h):
            n = norm_url(h)
            if n.rstrip("/") != norm_url(url).rstrip("/"):
                links.add(n)
    phrases = sorted({m.group(0).strip()[:200] for m in PHRASE.finditer(text)})
    return {"text_sha": hashlib.sha1(text.lower().encode()).hexdigest()[:16], "text_len": len(text),
            "links": sorted(links)[:200], "phrases": phrases[:20]}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
