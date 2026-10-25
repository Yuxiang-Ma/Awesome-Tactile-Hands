"""Publish the night's work: merge claude/nightly into main, rebuild the derived files, push. Run by
.github/workflows/publish.yml at 09:00 New York time (pipeline/NIGHTLY.md); GitHub Pages serves main.

    python3 scripts/publish_nightly.py [--dry-run]

Refuses to publish, and opens or updates an issue, when the branch does not merge cleanly or scripts/nightly_guard.py
rejects the change set. After a publish, claude/nightly is reset to the new main.
"""
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "claude/nightly"
BOT = {"GIT_AUTHOR_NAME": "github-actions[bot]", "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
       "GIT_COMMITTER_NAME": "github-actions[bot]", "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}
IGNORED = {"rank", "contents", "used_by", "checked"}  # derived fields, and the date a model was last looked at
GENERATED = {"README.md", "data/changes.json", "data/status.json"}


def sh(*a, check=True) -> str:
    r = subprocess.run(a, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"{' '.join(a)} failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def issue(why: str) -> None:
    title = "Nightly publish failed"
    body = f"{time.strftime('%Y-%m-%d')}: {why}\n\nThe branch `{BRANCH}` was left as it is; main was not changed."
    n = sh("gh", "issue", "list", "--state", "open", "--search", f'"{title}" in:title', "--json", "number", "-q", ".[0].number", check=False)
    if n:
        sh("gh", "issue", "comment", n, "--body", body, check=False)
    else:
        sh("gh", "issue", "create", "--title", title, "--body", body, check=False)


def content(path: str, ref: str = None):
    """A catalog file without its metadata and derived fields, to tell whether the catalog itself changed."""
    try:
        j = json.loads(sh("git", "show", f"{ref}:{path}") if ref else (ROOT / path).read_text())
    except (SystemExit, FileNotFoundError, ValueError):
        return None
    key = next(k for k in j if k != "metadata")
    return [{k: v for k, v in x.items() if k not in IGNORED} for x in j[key]]


def main() -> None:
    dry = "--dry-run" in sys.argv
    os.environ.update(BOT)  # the runner has no git identity, and even a --no-commit merge needs one
    today = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    sh("git", "fetch", "-q", "origin", "main")
    if subprocess.run(["git", "fetch", "-q", "origin", BRANCH], cwd=ROOT).returncode:
        print(f"no {BRANCH} branch; nothing to publish")
        return
    ahead = int(sh("git", "rev-list", "--count", f"origin/main..origin/{BRANCH}"))
    if not ahead:
        print("nothing new on the nightly branch")
        return
    sh("git", "checkout", "-q", "-B", "main", "origin/main")
    merge = subprocess.run(["git", "merge", "--no-ff", "--no-commit", f"origin/{BRANCH}"], cwd=ROOT, capture_output=True, text=True)
    if merge.returncode:
        conflicted = set(sh("git", "diff", "--name-only", "--diff-filter=U").split())
        if conflicted and conflicted <= GENERATED:  # generated files are rebuilt below anyway
            for f in conflicted:
                sh("git", "checkout", "--theirs", "--", f)
                sh("git", "add", f)
        else:
            sh("git", "merge", "--abort", check=False)
            issue(f"`{BRANCH}` does not merge cleanly into main (conflicts: {', '.join(sorted(conflicted)) or merge.stderr.strip()}).")
            raise SystemExit("merge conflict")
    guard = subprocess.run([sys.executable, "scripts/nightly_guard.py", "--base=origin/main"], cwd=ROOT, capture_output=True, text=True)
    print(guard.stdout + guard.stderr)
    if guard.returncode:
        sh("git", "merge", "--abort", check=False)
        issue("the nightly guard rejected the change set:\n\n```\n" + (guard.stdout + guard.stderr).strip()[-3000:] + "\n```")
        raise SystemExit("guard failed")
    for name in ("datasets", "models", "hardware"):
        path = f"data/{name}.json"
        if (ROOT / path).exists() and content(path) != content(path, "origin/main"):
            j = json.loads((ROOT / path).read_text())
            j["metadata"]["last_updated"] = today
            (ROOT / path).write_text(json.dumps(j, indent=1, ensure_ascii=False) + "\n")
    sh(sys.executable, "scripts/build_readme.py")
    sh(sys.executable, "scripts/build_readme.py", "--check")
    sh("git", "add", "-A")
    fresh = []
    for f in sh("git", "diff", "--cached", "--name-only", "--diff-filter=A", "origin/main", "--", "data/changes/").split():
        fresh += json.loads((ROOT / f).read_text()).get("changes", [])
    counts = {k: sum(c["kind"] == k for c in fresh) for k in ("added", "released", "updated", "withdrawn")}
    head = ", ".join(f"{v} {k}" for k, v in counts.items() if v) or "checks only, no catalog changes"
    body = "\n".join(f"- {c['text']}" for c in fresh[:25]) + (f"\n- and {len(fresh) - 25} more" if len(fresh) > 25 else "")
    sh("git", "commit", "-q", "-m", f"Publish nightly checks {today}: {head}", *(["-m", body] if body else []))
    print(sh("git", "log", "--stat", "-1"))
    if dry:
        print("dry run: not pushed")
        return
    sh("git", "push", "-q", "origin", "main")
    sh("git", "push", "-q", "--force", "origin", f"main:{BRANCH}")
    # a push made with the workflow token may not start a Pages build on its own; ask for one (best effort)
    sh("gh", "api", "-X", "POST", "repos/{owner}/{repo}/pages/builds", check=False)
    print(f"published: {head}")


if __name__ == "__main__":
    main()
