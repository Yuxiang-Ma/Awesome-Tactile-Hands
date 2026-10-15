# Adding a dataset: survey, sample, visualize

Every dataset in the catalog goes through the same steps. Their output is a survey file
(`pipeline/surveys/<id>.json`, spec in [SCHEMA.md](SCHEMA.md)), a converter (`pipeline/converters/<name>.py` +
`<name>.meta.json`, format in [FORMAT.md](FORMAT.md)), and converted sample episodes for the viewer.

Steps 1-4 run as a Claude Code workflow (one dataset per pipeline lane):

```
Workflow({scriptPath: "~/src/awesome-tactile-hands/.claude/workflows/add-dataset.js",
          args: {datasets: [{id: "humanoid_everyday", hint: "https://huggingface.co/datasets/USC-PSI-Lab/humanoid-everyday"}],
                 today: "2026-10-15"}})
```

Step 5 (catalog merge and publishing) is run by hand after reviewing the workflow's report.

## 1. Survey

Read the paper, supplementary, project page, dataset card and code. List the release's files, and open one episode to
confirm what is actually in it. Fill `entry` (the catalog fields), `license`, `download`, `channels` and
`episode_index`.

- `channels` lists every stream in one released episode, with shape, rate, unit and frame.
- Numbers that come from counting files or deriving (frames / fps) go into `entry.unconfirmed` with how they were derived.

## 2. Decide what to sample

Write `sample` into the survey:

```
"sample": {
  "decision": "sample" | "catalog_only" | "skip_forbidden",
  "reason": "...",
  "prefix": "he_",                       // two letters + "_", unused by other collections
  "tasks_total": 246, "tasks_sampled": 8,
  "episodes": [ {"id": "<release episode id>", "task": "...", "scene": "...", "subject": "...", "duration_s": 18,
                 "window": [t0, t1] | null, "why": "..."} ],
  "fetch_estimate": "~300 MB",
  "rules_applied": "..."
}
```

**Decision**
- `skip_forbidden`: the license or terms explicitly forbid redistribution. Add the dataset to [SKIPPED.md](SKIPPED.md)
  with the exact wording and URL, so permission can be requested.
- `catalog_only`: no data can be downloaded (announced, not released, or gated and access not granted).
- `sample`: everything else. If the license says nothing about redistribution, re-host and label the collection
  "License not stated". If it is licensed, show the license as the label.

**How many**
- Tasks: if the release has 6 tasks or fewer, take all of them. Otherwise take 6-8, chosen to span:
  - different environments or scenes,
  - different action types (grasp, twist, wipe, pour, insert, ...),
  - different objects,
  - one- and two-handed tasks.
- Episodes:
  - one per sampled task;
  - with 3 tasks or fewer, 2-3 per task, from different subjects, scenes or objects;
  - at least 3 and at most 10 in total.
- Each episode must:
  - have every tactile and force channel present and not corrupted;
  - show contact (readings above rest for at least 1 s);
  - be 10-60 s long. Cut longer ones to a window that holds the contact, and record the window.
- Budget:
  - episode JSON at most 2 MB;
  - re-hosted media at most ~30 MB per episode;
  - at most ~20 GB downloaded for the whole sample. Fetch partially (range requests, row groups, single files) when the
    release allows it. If it does not, report the cost and stop.

## 3. Convert and visualize

Write the converter following [FORMAT.md](FORMAT.md). Fetch only the sampled episodes, into `~/data/ext/<name>/`; use the
venv `~/data/ext/.venv`. Then convert, list the episodes locally (`make_manifest.py --local`), and look at them in the
viewer (headless Chrome with `--virtual-time-budget=40000`; shorter budgets often leave the videos black).

**Every tactile and force channel is visualized.** Record in the survey how each channel is shown:

```
"visualization": [ {"channel": "observation.tactile_force", "shown_as": ["vectors", "series"],
                    "detail": "(Fx, Fy) arrow + Fz ring per fingertip; Fz, |Fxy|, |M| plots", "reason": null},
                   {"channel": "observation.state", "shown_as": ["not_shown"], "reason": "joint states, not touch"} ]
```

`shown_as` takes grid | vectors | series | video | task | not_shown. A tactile or force channel may only be
`not_shown` when it is corrupted or empty in the release, and that is stated in the episode's `notes`. If the viewer has
no fitting element for a channel, extend the grid format (`site/index.html` `normalizeGrid` / `drawGridHand` /
`gridPlots`) and document it in FORMAT.md rather than dropping the channel.

## 4. Verify

A separate pass checks:
- every channel row in the survey against the episode JSON;
- value ranges: no channel all zero, saturated or stuck, and dead sensors noted;
- the layout against the paper's figure;
- that the videos are H.264 and start in sync with the touch data;
- file sizes;
- a screenshot of every episode in the viewer.

## 5. Publish (by hand)

```
python3 pipeline/merge_entry.py pipeline/surveys/<id>.json      # catalog entry; review the printed diff
python3 scripts/build_readme.py
~/data/ext/.venv/bin/python pipeline/publish.py <prefix>         # media repo + Space + viewer/ copy
# set "viewer": "<prefix><episode>" on the entry, rebuild the README, commit, push
```
