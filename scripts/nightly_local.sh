#!/usr/bin/env bash
# One nightly flow of the Taxel Atlas on this machine (pipeline/NIGHTLY.md): scan, review in a restricted Claude Code
# session, cache new figures, guard, commit and push to claude/nightly. The 09:00 publish job merges that branch.
#
#   scripts/nightly_local.sh discovery|status [--no-push]
#
# Runs in its own clone ($TAXEL_NIGHTLY_HOME, default ~/taxel-nightly), never in a working checkout. The review session
# cannot run git, cannot edit scripts, pages or settings, and cannot read outside that clone; git is done here.
set -uo pipefail
FLOW=${1:-}; [[ $FLOW == discovery || $FLOW == status ]] || { echo "usage: $0 discovery|status [--no-push]" >&2; exit 2; }
PUSH=1; [[ ${2:-} == --no-push ]] && PUSH=0
HOME_DIR=${TAXEL_NIGHTLY_HOME:-$HOME/taxel-nightly}
REPO=$HOME_DIR/Awesome-Tactile-Hands
LOGS=$HOME_DIR/logs
GH_REPO=Yuxiang-Ma/Awesome-Tactile-Hands
BRANCH=claude/nightly
CLAUDE=${CLAUDE_BIN:-$HOME/.nvm/versions/node/v20.20.2/bin/claude}
PY=/usr/bin/python3
export PATH="$(dirname "$CLAUDE"):/snap/bin:/usr/local/bin:/usr/bin:/bin"
DATE=$(TZ=America/New_York date +%F)
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOG=$LOGS/$DATE-$FLOW
mkdir -p "$LOGS"
exec > >(tee -a "$LOG.log") 2>&1
echo "== $STARTED nightly $FLOW for $DATE"

exec 9>"$HOME_DIR/.lock"
flock -w 7200 9 || { echo "another nightly run holds the lock"; exit 1; }

git_auth() { git -c credential.helper= -c "credential.helper=!f() { echo username=x-access-token; echo password=\$(gh auth token); }; f" "$@"; }

fail() {  # one open issue per flow collects the failures, so a bad week sends one thread of mail
  local why=$1
  echo "FAILED: $why"
  local title="Nightly $FLOW run failed"
  local body="$DATE: $why"$'\n\n'"Log on the workstation: \`$LOG.log\`"
  local n; n=$(gh issue list -R "$GH_REPO" --state open --search "\"$title\" in:title" --json number -q '.[0].number' 2>/dev/null)
  if [[ -n $n ]]; then gh issue comment "$n" -R "$GH_REPO" --body "$body" >/dev/null; else gh issue create -R "$GH_REPO" --title "$title" --body "$body" >/dev/null; fi
  exit 1
}

# 1. the staging branch, with main merged in
[[ -d $REPO/.git ]] || git_auth clone -q "https://github.com/$GH_REPO.git" "$REPO" || fail "clone failed"
cd "$REPO" || fail "no clone"
git_auth fetch -q origin || fail "git fetch failed"
git reset -q --hard && git clean -qfd
if git rev-parse -q --verify "origin/$BRANCH" >/dev/null; then git checkout -q -B "$BRANCH" "origin/$BRANCH"; else git checkout -q -B "$BRANCH" origin/main; fi
git merge -q --no-edit origin/main || { git merge --abort; fail "claude/nightly does not merge cleanly with main; resolve by hand"; }
# the scripts that run below must be main's
git diff --quiet origin/main -- scripts pipeline/merge_entry.py pipeline/publish.py .github assets '*.html' ':!assets/thumbs' ':!assets/hw' \
  || fail "scripts or pages on claude/nightly differ from main"

# 2. scan (the GitHub token is given to the scan scripts only, never to the review session)
TOKEN=$(gh auth token 2>/dev/null)
if [[ $FLOW == discovery ]]; then GITHUB_TOKEN=$TOKEN $PY scripts/discover.py || fail "discover.py failed"
else GITHUB_TOKEN=$TOKEN $PY scripts/watch.py || fail "watch.py failed"; fi
unset TOKEN

# 3. review
if [[ $FLOW == discovery ]]; then MODEL=opus; FALLBACK=sonnet; LIMIT=150m; INPUT=watch/candidates.json
else MODEL=sonnet; FALLBACK=opus; LIMIT=100m; INPUT=watch/signals.json; fi
DOY=$((10#$(TZ=America/New_York date +%j)))
QUERIES="$(( DOY % 12 )), $(( (DOY + 1) % 12 )), $(( (DOY + 2) % 12 )), $(( (DOY + 3) % 12 ))"
EXTRA=""; [[ $FLOW == discovery ]] && EXTRA=" Tonight's search sweep uses queries $QUERIES of the list in NIGHTLY.md."
PROMPT="Tonight's Taxel Atlas nightly run. Flow: $FLOW. Date: $DATE (America/New_York).$EXTRA You are in a checkout of the catalog \
repository on branch $BRANCH. The scan for tonight has run and written $INPUT. Read pipeline/NIGHTLY.md, then follow its \
'Rules for every run', 'Scope' and 'Flow: $FLOW' sections, and write data/changes/$DATE-$FLOW.json (only if something changed) \
and watch/runs/$DATE-$FLOW.json as its 'Formats' section describes. Before you finish, run python3 scripts/build_readme.py \
--validate and python3 scripts/nightly_guard.py and fix what they report. Do not run any other git command than git status \
and git diff; this wrapper commits after you finish. End with a short plain summary of what you changed."
# exact commands only: a prefix rule on git would also allow options that write files (git diff --output=...)
ALLOW=(Read Edit Write Glob Grep WebFetch WebSearch "Bash(python3 scripts/nightly_tool.py:*)" "Bash(python3 scripts/build_readme.py --validate)"
       "Bash(python3 scripts/nightly_guard.py)" "Bash(python3 pipeline/merge_entry.py pipeline/surveys/:*)" "Bash(git status)"
       "Bash(git status --short)" "Bash(git diff)" "Bash(git diff --stat)")
DENY=("Edit(scripts/**)" "Write(scripts/**)" "Edit(pipeline/*.py)" "Write(pipeline/*.py)" "Edit(pipeline/converters/**)" "Write(pipeline/converters/**)"
      "Edit(.github/**)" "Write(.github/**)" "Edit(.claude/**)" "Write(.claude/**)" "Edit(assets/**)" "Write(assets/**)" "Edit(viewer/**)" "Write(viewer/**)"
      "Edit(*.html)" "Write(*.html)" "Edit(README.md)" "Write(README.md)" "Edit(.git/**)" "Write(.git/**)")
env -u GITHUB_TOKEN -u GH_TOKEN -u HF_TOKEN timeout "$LIMIT" "$CLAUDE" -p "$PROMPT" --restricted --model "$MODEL" --fallback-model "$FALLBACK" --effort high \
  --permission-mode dontAsk --permission-prompts none --tools "Read,Edit,Write,Glob,Grep,WebFetch,WebSearch,Bash" \
  --allowedTools "${ALLOW[@]}" --disallowedTools "${DENY[@]}" --output-format json > "$LOG.result.json"
RC=$?
echo "review exit $RC"
$PY - "$LOG.result.json" <<'EOF' || true
import json, sys
try:
    r = json.load(open(sys.argv[1]))
    print(f"turns {r.get('num_turns')}, {round((r.get('duration_ms') or 0) / 60000)} min, session {r.get('session_id')}")
    print((r.get("result") or "")[:3000])
except Exception as e:
    print(f"no result ({e})")
EOF

# 4. figures of new entries, then the guard
NEW=$($PY - <<'EOF'
import json, subprocess
ids = []
for f, k in (("data/datasets.json", "datasets"), ("data/hardware.json", "hardware")):
    old = {x["id"] for x in json.loads(subprocess.run(["git", "show", f"origin/main:{f}"], capture_output=True, text=True).stdout)[k]}
    ids += [x["id"] for x in json.load(open(f))[k] if x["id"] not in old and x.get("image")]
print(",".join(ids))
EOF
)
[[ -n $NEW ]] && { $PY scripts/fetch_thumbs.py --only="$NEW" || true; }
GUARD=$($PY scripts/nightly_guard.py --base=origin/main 2>&1); GUARD_RC=$?
echo "$GUARD"
OK=true; [[ $RC -ne 0 || $GUARD_RC -ne 0 ]] && OK=false
if [[ $GUARD_RC -ne 0 ]]; then  # keep the rejected work for a person, then drop it
  { git diff; git status --short; } > "$LOG.rejected.diff"
  git reset -q --hard && git clean -qfd
fi

# 5. run report, commit, push
$PY - "$FLOW" "$DATE" "$STARTED" "$OK" "$RC" "$GUARD" "$MODEL" <<'EOF'
import json, sys, time
from pathlib import Path
flow, date, started, ok, rc, guard, model = sys.argv[1:]
p = Path(f"watch/runs/{date}-{flow}.json")
try:
    r = json.loads(p.read_text())
except Exception:
    r = {"flow": flow, "date": date}
r.update(flow=flow, date=date, started=started, finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ok=ok == "true",
         review_exit=int(rc), guard=guard.strip().splitlines()[-1] if guard.strip() else "", model=r.get("model") or model)
if ok != "true":
    r["guard_output"] = guard.strip().splitlines()[:30]
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n")
EOF
git add -A data pipeline/surveys watch assets/thumbs assets/hw
SUMMARY=$($PY - "$DATE" "$FLOW" <<'EOF'
import json, sys
from pathlib import Path
date, flow = sys.argv[1:]
p = Path(f"data/changes/{date}-{flow}.json")
ch = json.loads(p.read_text())["changes"] if p.exists() else []
n = {k: sum(c["kind"] == k for c in ch) for k in ("added", "released", "updated", "withdrawn")}
print(", ".join(f"{v} {k}" for k, v in n.items() if v) or "no catalog changes")
EOF
)
git -c user.name="$(git config user.name || echo Yuxiang-Ma)" commit -q -m "Nightly $FLOW $DATE: $SUMMARY" \
  -m "Scan, review and guard by scripts/nightly_local.sh (pipeline/NIGHTLY.md). Review exit $RC; guard: $(echo "$GUARD" | tail -1)" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>" || echo "nothing to commit"
if [[ $PUSH == 1 ]]; then
  git_auth push -q origin "$BRANCH" || { git_auth fetch -q origin && git rebase -q "origin/$BRANCH" && git_auth push -q origin "$BRANCH"; } || fail "push failed"
fi
[[ $OK == true ]] || fail "review exit $RC; guard: $(echo "$GUARD" | tail -3 | tr '\n' ' ')"
echo "== done $(date -u +%H:%M:%SZ): $SUMMARY"
