#!/usr/bin/env bash
# One nightly flow of the Taxel Atlas on this machine (pipeline/NIGHTLY.md): scan, review in a restricted Claude Code
# session, cache new figures, guard, commit and push to claude/nightly. The 09:00 publish job merges that branch.
#
#   scripts/nightly_local.sh discovery|status [--no-push|--check]
#
# --check runs only the preflight (claude CLI, GitHub push access, commits left unpushed by an earlier run) and exits.
#
# Runs in its own clone ($TAXEL_NIGHTLY_HOME, default ~/taxel-nightly), never in a working checkout. The review session
# cannot run git, cannot edit scripts, pages or settings, and cannot read outside that clone; git is done here.
set -uo pipefail
FLOW=${1:-}; [[ $FLOW == discovery || $FLOW == status ]] || { echo "usage: $0 discovery|status [--no-push|--check]" >&2; exit 2; }
PUSH=1; [[ ${2:-} == --no-push ]] && PUSH=0
CHECK=0; [[ ${2:-} == --check ]] && CHECK=1
HOME_DIR=${TAXEL_NIGHTLY_HOME:-$HOME/taxel-nightly}
REPO=$HOME_DIR/Awesome-Tactile-Hands
LOGS=$HOME_DIR/logs
GH_REPO=Yuxiang-Ma/Awesome-Tactile-Hands
BRANCH=claude/nightly
# the claude CLI: CLAUDE_BIN, else PATH, else the native installer's ~/.local/bin, else the newest nvm install
CLAUDE=${CLAUDE_BIN:-}
if [[ -z $CLAUDE ]]; then
  for c in "$(command -v claude 2>/dev/null)" "$HOME/.local/bin/claude" "$(ls -d "$HOME"/.nvm/versions/node/*/bin/claude 2>/dev/null | sort -V | tail -1)"; do
    [[ -n $c && -x $c ]] && { CLAUDE=$c; break; }
  done
fi
PY=/usr/bin/python3
export PATH="$(dirname "$CLAUDE"):/snap/bin:/usr/local/bin:/usr/bin:/bin"
DATE=$(TZ=America/New_York date +%F)
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOG=$LOGS/$DATE-$FLOW
mkdir -p "$LOGS"
if [[ $CHECK == 0 ]]; then  # --check writes no log and takes no lock, so it can run beside a nightly run
  exec > >(tee -a "$LOG.log") 2>&1
  echo "== $STARTED nightly $FLOW for $DATE"
fi

if [[ -z ${NIGHTLY_LOCKED:-} && $CHECK == 0 ]]; then  # launch.sh already holds the lock on fd 9
  exec 9>"$HOME_DIR/.lock"
  flock -w 7200 9 || { echo "another nightly run holds the lock"; exit 1; }
fi

# GitHub: ~/taxel-nightly/github.token (a token for this repository only), else GH_TOKEN, else the gh login of the
# repository owner. Never gh's active account alone: on a machine with several gh logins it can change under the cron
# job, and from 2026-11-04 to 2026-11-23 it did, so every push got 403 and the site went 19 days without an update.
GH_OWNER=${NIGHTLY_GH_USER:-${GH_REPO%%/*}}
if [[ -s $HOME_DIR/github.token ]]; then GH_TOKEN=$(tr -d '[:space:]' < "$HOME_DIR/github.token")
elif [[ -z ${GH_TOKEN:-} ]]; then GH_TOKEN=$(gh auth token --user "$GH_OWNER" 2>/dev/null || gh auth token 2>/dev/null); fi
export GH_TOKEN
UNPUSHED=$HOME_DIR/unpushed  # the commit of a run whose push failed, pushed by the next run

git_auth() { git -c credential.helper= -c "credential.helper=!f() { echo username=x-access-token; echo password=\$(gh auth token); }; f" "$@"; }

fail() {  # one open issue per flow collects the failures, so a bad week sends one thread of mail
  local why=$1
  echo "FAILED: $why"
  [[ $CHECK == 1 ]] && exit 1  # --check only reports
  local title="Nightly $FLOW run failed"
  local body="$DATE: $why"$'\n\n'"Log on the workstation: \`$LOG.log\`"
  local n; n=$(gh issue list -R "$GH_REPO" --state open --search "\"$title\" in:title" --json number -q '.[0].number' 2>/dev/null)
  if [[ -n $n ]]; then gh issue comment "$n" -R "$GH_REPO" --body "$body" >/dev/null; else gh issue create -R "$GH_REPO" --title "$title" --body "$body" >/dev/null; fi
  exit 1
}

# 0. preflight: stop before the scan, and before the clone is reset, when tonight's run could not finish
[[ -n $CLAUDE && -x $CLAUDE ]] && "$CLAUDE" --version >/dev/null 2>&1 \
  || fail "claude CLI not found or not runnable (tried CLAUDE_BIN, PATH, ~/.local/bin/claude, ~/.nvm); set CLAUDE_BIN in ~/taxel-nightly/launch.sh"
for try in 1 2 3; do  # three tries, so one GitHub API hiccup does not cost the night
  WHO=$(gh api user -q .login 2>/dev/null); CAN_PUSH=$(gh api "repos/$GH_REPO" -q .permissions.push 2>/dev/null)
  [[ -n $CAN_PUSH ]] && break; [[ $try == 3 ]] || sleep 30
done
[[ $PUSH == 0 || $CAN_PUSH == true ]] \
  || fail "the GitHub token (account ${WHO:-unknown}) cannot push to $GH_REPO; put a token for this repository in ~/taxel-nightly/github.token or log gh in as $GH_OWNER"
echo "preflight: $("$CLAUDE" --version 2>/dev/null | head -1) at $CLAUDE; GitHub as ${WHO:-unknown}, push ${CAN_PUSH:-unknown}"
if [[ $CHECK == 1 ]]; then
  [[ -s $UNPUSHED ]] && echo "commit $(head -c 12 "$UNPUSHED") from an earlier run is waiting to be pushed"
  exit 0
fi

# 1. the staging branch, with main merged in
[[ -d $REPO/.git ]] || git_auth clone -q "https://github.com/$GH_REPO.git" "$REPO" || fail "clone failed"
cd "$REPO" || fail "no clone"
git_auth fetch -q origin || fail "git fetch failed"
git reset -q --hard && git clean -qfd
# a run whose push failed left its commit on the local branch; push it now, rebased onto the branch's current tip
# (the publish job resets claude/nightly to main), so a failed push never costs a night. If it will not rebase or push,
# it stays in a bundle under logs/ for a person.
if [[ $PUSH == 1 && -s $UNPUSHED ]]; then
  WAITING=$(tr -d '[:space:]' < "$UNPUSHED")
  if git cat-file -e "$WAITING^{commit}" 2>/dev/null && ! git merge-base --is-ancestor "$WAITING" "origin/$BRANCH" 2>/dev/null; then
    git checkout -q -B "$BRANCH" "$WAITING"
    if git rebase -q "origin/$BRANCH" && git_auth push -q origin "$BRANCH"; then
      echo "pushed the commit left unpushed by an earlier run ($(git log -1 --format=%s))"
      git_auth fetch -q origin
    else
      git rebase --abort 2>/dev/null
      echo "could not push the commit left by an earlier run; it is in $(ls "$LOGS"/*.unpushed.bundle 2>/dev/null | tail -1)"
    fi
  fi
  rm -f "$UNPUSHED"
fi
if git rev-parse -q --verify "origin/$BRANCH" >/dev/null; then git checkout -q -B "$BRANCH" "origin/$BRANCH"; else git checkout -q -B "$BRANCH" origin/main; fi
git merge -q --no-edit origin/main || { git merge --abort; fail "claude/nightly does not merge cleanly with main; resolve by hand"; }
BASE=$(git rev-parse origin/main)  # every comparison below uses this commit, whatever happens to the refs meanwhile
# the scripts that run below must be main's
git diff --quiet "$BASE" -- scripts pipeline/merge_entry.py pipeline/publish.py .github assets '*.html' ':!assets/thumbs' ':!assets/hw' \
  || fail "scripts or pages on claude/nightly differ from main"

# 2. scan (the GitHub token is given to the scan scripts only, never to the review session)
TOKEN=$(gh auth token 2>/dev/null)
OAKEY=$(cat "$HOME_DIR/openalex.key" 2>/dev/null)  # optional: a free OpenAlex key raises its daily budget from $0.10 to $1
if [[ $FLOW == discovery ]]; then SCAN=watch/candidates.json; GITHUB_TOKEN=$TOKEN OPENALEX_API_KEY=$OAKEY $PY scripts/discover.py || fail "discover.py failed"
else SCAN=watch/signals.json; GITHUB_TOKEN=$TOKEN $PY scripts/watch.py || fail "watch.py failed"; fi
unset TOKEN OAKEY
# the sources the scan could not reach go into the run report; kept outside the clone, so a rejected run reports them too
rm -f "$LOG.scan.json"; $PY - "$SCAN" "$LOG.scan.json" <<'EOF' || true
import json, sys
j = json.load(open(sys.argv[1]))
json.dump({"sources_failed": j.get("sources_failed") or [], "scan_problems": j.get("problems") or []}, open(sys.argv[2], "w"))
EOF

# 3. review
if [[ $FLOW == discovery ]]; then MODEL=opus; FALLBACK=sonnet; LIMIT=150m
else MODEL=sonnet; FALLBACK=opus; LIMIT=100m; fi
DOY=$((10#$(TZ=America/New_York date +%j)))
QUERIES="$(( DOY % 12 )), $(( (DOY + 1) % 12 )), $(( (DOY + 2) % 12 )), $(( (DOY + 3) % 12 ))"
EXTRA=""; [[ $FLOW == discovery ]] && EXTRA=" Tonight's search sweep uses queries $QUERIES of the list in NIGHTLY.md."
# a shorter run for tests: NIGHTLY_LIMIT=15 caps the candidates decided (and the entries added at a third of that)
[[ ${NIGHTLY_LIMIT:-} =~ ^[0-9]+$ ]] && EXTRA="$EXTRA This is a short test run: decide at most $NIGHTLY_LIMIT candidates or deep checks, \
add at most $(( (NIGHTLY_LIMIT + 2) / 3 )) datasets and $(( (NIGHTLY_LIMIT + 2) / 3 )) models, and skip the search sweep."
PROMPT="Tonight's Taxel Atlas nightly run. Flow: $FLOW. Date: $DATE (America/New_York).$EXTRA You are in a checkout of the catalog \
repository on branch $BRANCH. The scan for tonight has run and written $SCAN. Read pipeline/NIGHTLY.md, then follow its \
'Rules for every run', 'Scope' and 'Flow: $FLOW' sections, and write data/changes/$DATE-$FLOW.json (only if something changed) \
and watch/runs/$DATE-$FLOW.json as its 'Formats' section describes. Before you finish, run python3 scripts/build_readme.py \
--validate and python3 scripts/nightly_guard.py and fix what they report. The shell accepts only the commands listed under \
'Shell access' in NIGHTLY.md, each run on its own exactly as written (no cd, no && or ; chains, no python3 -c); if one is \
refused, the listed ones still work. This wrapper commits after you finish. End with a short plain summary of what you changed."
# exact commands only: a prefix rule on git would also allow options that write files (git diff --output=...)
ALLOW=(Read Edit Write Glob Grep WebFetch WebSearch "Bash(python3 scripts/nightly_tool.py:*)" "Bash(python3 scripts/build_readme.py --validate)"
       "Bash(python3 scripts/nightly_guard.py)" "Bash(python3 pipeline/merge_entry.py pipeline/surveys/:*)" "Bash(git status)"
       "Bash(git status --short)" "Bash(git diff)" "Bash(git diff --stat)")
DENY=("Edit(scripts/**)" "Write(scripts/**)" "Edit(pipeline/*.py)" "Write(pipeline/*.py)" "Edit(pipeline/converters/**)" "Write(pipeline/converters/**)"
      "Edit(.github/**)" "Write(.github/**)" "Edit(.claude/**)" "Write(.claude/**)" "Edit(assets/**)" "Write(assets/**)" "Edit(viewer/**)" "Write(viewer/**)"
      "Edit(*.html)" "Write(*.html)" "Edit(README.md)" "Write(README.md)" "Edit(.git/**)" "Write(.git/**)")
env -u GITHUB_TOKEN -u GH_TOKEN -u HF_TOKEN DISABLE_AUTOUPDATER=1 timeout "$LIMIT" "$CLAUDE" -p "$PROMPT" --restricted --model "$MODEL" --fallback-model "$FALLBACK" --effort high \
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
NEW=$($PY - "$BASE" <<'EOF'
import json, subprocess, sys
ids = []
for f, k in (("data/datasets.json", "datasets"), ("data/hardware.json", "hardware")):
    old = {x["id"] for x in json.loads(subprocess.run(["git", "show", f"{sys.argv[1]}:{f}"], capture_output=True, text=True).stdout)[k]}
    ids += [x["id"] for x in json.load(open(f))[k] if x["id"] not in old and x.get("image")]
print(",".join(ids))
EOF
)
[[ -n $NEW ]] && { $PY scripts/fetch_thumbs.py --only="$NEW" || true; }
GUARD=$($PY scripts/nightly_guard.py --base="$BASE" 2>&1); GUARD_RC=$?
echo "$GUARD"
OK=true; [[ $RC -ne 0 || $GUARD_RC -ne 0 ]] && OK=false
if [[ $GUARD_RC -ne 0 ]]; then  # keep the rejected work for a person, then drop it
  { git diff; git status --short; } > "$LOG.rejected.diff"
  git reset -q --hard && git clean -qfd
fi

# 5. run report, commit, push
$PY - "$FLOW" "$DATE" "$STARTED" "$OK" "$RC" "$GUARD" "$MODEL" "$LOG.scan.json" <<'EOF'
import json, sys, time
from pathlib import Path
flow, date, started, ok, rc, guard, model, scan = sys.argv[1:]
p = Path(f"watch/runs/{date}-{flow}.json")
try:
    r = json.loads(p.read_text())
except Exception:
    r = {"flow": flow, "date": date}
r.update(flow=flow, date=date, started=started, finished=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ok=ok == "true",
         review_exit=int(rc), guard=guard.strip().splitlines()[-1] if guard.strip() else "", model=r.get("model") or model)
try:
    scan = json.loads(Path(scan).read_text())
except Exception:
    scan = {}
for k in ("sources_failed", "scan_problems"):
    if scan.get(k):
        r[k] = scan[k]
    else:
        r.pop(k, None)
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
  if ! { git_auth push -q origin "$BRANCH" || { git_auth fetch -q origin && git rebase -q "origin/$BRANCH" && git_auth push -q origin "$BRANCH"; }; }; then
    git rebase --abort 2>/dev/null
    git rev-parse HEAD > "$UNPUSHED"
    git bundle create "$LOG.unpushed.bundle" "$BASE..HEAD" >/dev/null 2>&1
    fail "push failed; the commit is kept on the local branch and in $LOG.unpushed.bundle, and the next run pushes it first"
  fi
fi
[[ $OK == true ]] || fail "review exit $RC; guard: $(echo "$GUARD" | tail -3 | tr '\n' ' ')"
# one night without arXiv is routine; a source missing from the last three runs of this flow needs a person
STREAK=$($PY - "$FLOW" <<'EOF'
import json, sys
from pathlib import Path
sets = []
for p in sorted(Path("watch/runs").glob(f"*-{sys.argv[1]}.json"))[-3:]:
    try:
        sets.append(set(json.loads(p.read_text()).get("sources_failed") or []))
    except ValueError:
        sets.append(set())
print(", ".join(sorted(set.intersection(*sets))) if len(sets) == 3 else "")
EOF
)
[[ -z $STREAK ]] || fail "not reached on the last three $FLOW runs: $STREAK (scan_problems in watch/runs/ says what failed)"
# a run that finished and pushed closes its flow's failure issue, so an open issue always means the flow is broken now
if [[ $PUSH == 1 ]]; then
  n=$(gh issue list -R "$GH_REPO" --state open --search "\"Nightly $FLOW run failed\" in:title" --json number -q '.[0].number' 2>/dev/null)
  [[ -n $n ]] && gh issue close "$n" -R "$GH_REPO" --comment "$DATE: the $FLOW run finished and pushed ($SUMMARY)." >/dev/null 2>&1
fi
echo "== done $(date -u +%H:%M:%SZ): $SUMMARY"
