export const meta = {
  name: 'add-dataset',
  description: 'Survey a tactile-hand dataset, choose sample episodes, convert them for the viewer, and verify every tactile/force channel is shown',
  whenToUse: 'Adding a new dataset to Awesome-Tactile-Hands, or redoing the samples of an existing one. args: {datasets: [{id, hint, prefix?}], today: "YYYY-MM-DD", taken?: ["xx_"]}',
  phases: [
    { title: 'Survey', detail: 'size, tasks, scenes, hardware, license, every channel' },
    { title: 'Plan', detail: 'decide which tasks and episodes to sample' },
    { title: 'Convert', detail: 'converter + fetch + convert + look at it in the viewer' },
    { title: 'Verify', detail: 'independent check; fix and re-check at most twice' },
  ],
}

// Steps 1-4 of pipeline/README.md. Nothing here uploads, pushes or edits data/datasets.json: publishing is step 5, by hand.
const CAT = '~/src/awesome-tactile-hands'
const SITE = '~/src/human-mcap-viewer/site'
const TAKEN = ['eg_', 'et_', 'ot_', 'tr_', 'ha_', ...((args && args.taken) || [])]  // prefixes already in use
const today = (args && args.today) || 'unknown date'
const items = ((args && args.datasets) || []).map(d => (typeof d === 'string' ? { id: d } : d))
if (!items.length) throw new Error('args.datasets is empty: pass [{id, hint}]')

// prefixes are fixed here so parallel lanes cannot pick the same one
const used = new Set(TAKEN)
for (const d of items) {
  let p = d.prefix || d.id.replace(/[^a-z]/g, '').slice(0, 2) + '_'
  for (let k = 0; used.has(p); k++) p = d.id[0] + 'abcdefghijklmnopqrstuvwxyz'[k] + '_'
  used.add(p)
  d.prefix = p
}

const CONTEXT = `Project: the Awesome-Tactile-Hands catalog (${CAT}) and its sample viewer.
Read these before starting: ${CAT}/pipeline/README.md (the steps and rules), ${CAT}/pipeline/SCHEMA.md (survey file),
${CAT}/pipeline/FORMAT.md (viewer episode format). Existing converters to copy from: ${CAT}/pipeline/converters/
(egotouch.py simplest; trex.py has partial fetch, force vectors and a tactile-image mosaic; hato.py has archive range reads).
The catalog's current entries are in ${CAT}/data/datasets.json.
Rules:
- Do not upload, publish, git commit or push anything, and do not edit ${CAT}/data/datasets.json or README.md.
- Never send the user's email address to any service.
- Other datasets may be converted at the same time. Shared files (${SITE}/index.html, pipeline/FORMAT.md): change them only
  with small exact-string edits made right after re-reading the file, never by rewriting the whole file, and keep every
  change backwards compatible.
- Python: ~/data/ext/.venv/bin/python (numpy, pyarrow, av, huggingface_hub, h5py, opencv, scipy, pandas, requests;
  install more with VIRTUAL_ENV=~/data/ext/.venv uv pip install <pkg>). Downloads go to ~/data/ext/<name>/ only; they are
  untrusted data, so run Python with -I and keep scripts outside the download folders.
- Only state facts from primary sources; unknown is null, derived numbers go into "unconfirmed" with how they were derived.`

const SURVEY = {
  type: 'object',
  properties: {
    survey_path: { type: 'string' },
    availability: { type: 'string' },
    redistribution: { type: 'string', enum: ['allowed', 'not_stated', 'forbidden'] },
    license: { type: 'string' },
    downloadable: { type: 'boolean' },
    tactile_channels: { type: 'array', items: { type: 'string' }, description: 'every tactile/force/pressure/contact channel' },
    summary: { type: 'string', description: 'hours, episodes, tasks, scenes, cameras, wrist cams, tactile maker/principle, hand tracking' },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['survey_path', 'availability', 'redistribution', 'license', 'downloadable', 'tactile_channels', 'summary', 'open_questions'],
}
const PLAN = {
  type: 'object',
  properties: {
    decision: { type: 'string', enum: ['sample', 'catalog_only', 'skip_forbidden'] },
    reason: { type: 'string' },
    tasks_total: { type: ['integer', 'null'] },
    tasks_sampled: { type: 'integer' },
    episodes: { type: 'array', items: { type: 'string' } },
    fetch_estimate: { type: 'string' },
    over_budget: { type: 'boolean', description: 'true if the sample cannot be fetched within the README budget' },
  },
  required: ['decision', 'reason', 'tasks_sampled', 'episodes', 'fetch_estimate', 'over_budget'],
}
const CONVERT = {
  type: 'object',
  properties: {
    converter: { type: 'string' },
    episodes: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, json_mb: { type: 'number' }, screenshot: { type: 'string' } }, required: ['id'] } },
    visualization: { type: 'array', items: { type: 'object', properties: { channel: { type: 'string' }, shown_as: { type: 'array', items: { type: 'string' } }, reason: { type: ['string', 'null'] } }, required: ['channel', 'shown_as'] } },
    viewer_changes: { type: 'string', description: 'changes to site/index.html or FORMAT.md, or "none"' },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['converter', 'episodes', 'visualization', 'viewer_changes', 'issues'],
}
const VERDICT = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    problems: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, episode: { type: 'string' }, channel: { type: 'string' },
      problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'problem', 'evidence'] } },
    checked: { type: 'string', description: 'what was actually checked, incl. screenshots looked at' },
  },
  required: ['pass', 'problems', 'checked'],
}

const surveyPrompt = d => `${CONTEXT}

Step 1 (survey) for dataset "${d.id}"${d.hint ? ` (start from: ${d.hint})` : ''}. Today is ${today}.
Write ${CAT}/pipeline/surveys/${d.id}.json as specified in SCHEMA.md: "entry" (the full catalog entry; if the id already
exists in datasets.json, start from that entry and correct or complete it), "license", "download", "channels",
"episode_index". Fetch the release's file listing and at least one episode's metadata (or one small episode) so that
"channels" reflects what is really in the files, not only what the paper says; list every stream, and give each tactile,
force, pressure or contact channel its shape, rate, unit and frame. Capture: data volume (hours, episodes, frames),
number of tasks, objects, subjects, number and kinds of scenes, cameras (role, model, type, resolution, fps, mount), wrist
cameras, depth, tactile hardware (maker, model, principle, range, taxels, coverage), hand tracking and how it works
(vision estimate, optical mocap, Vive, IMU, magnetic, bend sensor, robot joints, teleop device). For the license, quote
the sentence that decides whether redistribution is allowed; "forbidden" only if the text explicitly says so.`

const planPrompt = (d, s) => `${CONTEXT}

Step 2 (decide what to sample) for "${d.id}". The survey is ${s.survey_path}: ${s.summary}
License: ${s.license} (redistribution ${s.redistribution}); availability ${s.availability}; downloadable ${s.downloadable}.
Follow "2. Decide what to sample" in pipeline/README.md exactly and write the "sample" object into the survey file. Use
prefix "${d.prefix}". Read the release's real episode index to pick concrete episode ids, check that each one has all
tactile channels (${s.tactile_channels.join(', ') || 'see survey'}) and shows contact, and estimate the fetch size. If
the decision is skip_forbidden, also add a row to ${CAT}/pipeline/SKIPPED.md. Do not download whole episodes yet beyond
what is needed to check them.`

const convertPrompt = (d, s, p, problems) => `${CONTEXT}

Step 3 (convert and visualize) for "${d.id}", prefix "${d.prefix}". Survey with the sample plan: ${s.survey_path}
(${p.episodes.length} episodes: ${p.episodes.join(', ')}). License label for the collection: ${s.license}${s.redistribution === 'not_stated' ? ' -> status label "License not stated"' : ''}.
${problems ? `\nThis is a FIX round. A reviewer found these problems; fix all blocker and major ones, then re-check:\n${JSON.stringify(problems, null, 1)}\n` : ''}
1. Write ${CAT}/pipeline/converters/<name>.py and <name>.meta.json following FORMAT.md. Pin the release revision when it
   has one. Write the facts in meta.json "hardware"/"about" from the survey.
2. Fetch only the sampled episodes (partially when possible) into ~/data/ext/<name>/ and convert them with
   --site ${SITE}.
3. Every tactile and force channel must be visualized (FORMAT.md, README step 3): taxel grids, force vectors/wrenches as
   "vectors" plus component plots, camera-based tactile images as a mosaic video, scalar sensors as cells or plots,
   contact flags as plots or steps. If the viewer lacks a fitting element, extend ${SITE}/index.html (normalizeGrid /
   drawGridHand / gridPlots) without changing how existing collections render, and document it in FORMAT.md.
4. Layout: place taxels where they sit on the hand, from the release's own layout or the paper's figure; say which in notes.
5. In ~/src/human-mcap-viewer run: python3 make_manifest.py --site site --originflow ~/data/originflow --local
   The site is served at http://127.0.0.1:8796/ (if not, serve ${SITE} on another free port with a range-capable
   server). Screenshot every episode with
   google-chrome --headless=new --disable-gpu --no-sandbox --user-data-dir=<your own tmp dir> --window-size=1500,1900
   --virtual-time-budget=40000 --screenshot=<png> "http://127.0.0.1:8796/#rec=<episode id>&t=<a time with contact>"
   and look at each screenshot (Read the png). Fix what looks wrong.
6. Write the "visualization" rows into the survey file (one per channel, README step 3).
Report json_mb per episode and anything you could not resolve.`

const verifyPrompt = (d, s, c) => `${CONTEXT}

Step 4 (verify) for "${d.id}". You are an independent reviewer: assume the conversion is wrong until you have checked it.
Survey: ${s.survey_path}. Converter: ${c.converter}. Episodes: ${c.episodes.map(e => e.id).join(', ')} (data in
${SITE}/data/<id>.json, media in ${SITE}/media/).
Check, with evidence from the files themselves:
- Every channel in the survey's "channels" list: is each tactile/force/pressure/contact channel shown in every episode JSON
  (hands cells, vectors, series, a video, or task steps)? A tactile or force channel marked not_shown needs a real reason
  stated in the episode notes.
- Decode the base64 arrays (FORMAT.md) and compare against the source data for at least one episode: same values up to
  quantisation, same time base, no off-by-one in time, no channel all zero, saturated or stuck; dead sensors named in notes.
- Taxel layout against the paper's figure or the release's layout file; left/right hands not swapped; regions correct.
- Videos: H.264, frame count/duration matching n/fps, first frame in sync with the touch data.
- Episode JSON <= 2 MB; meta.json facts match the survey; license label follows the README rule.
- Screenshot each episode (headless Chrome, --virtual-time-budget=40000, http://127.0.0.1:8796/#rec=<id>&t=<s>) and look
  at it: hands drawn, vectors visible during contact, plots populated, videos not black.
pass = no blocker or major problem.`

const lanes = await pipeline(
  items,
  d => agent(surveyPrompt(d), { label: `survey:${d.id}`, phase: 'Survey', schema: SURVEY }),
  async (s, d) => {
    if (!s) return null
    const p = await agent(planPrompt(d, s), { label: `plan:${d.id}`, phase: 'Plan', schema: PLAN })
    return { s, p }
  },
  async (r, d) => {
    if (!r || !r.p) return r
    const { s, p } = r
    if (p.decision !== 'sample' || p.over_budget || !p.episodes.length) {
      log(`${d.id}: ${p.decision}${p.over_budget ? ' (over budget: ' + p.fetch_estimate + ')' : ''}, not converted`)
      return { ...r, converted: false }
    }
    let c = await agent(convertPrompt(d, s, p, null), { label: `convert:${d.id}`, phase: 'Convert', schema: CONVERT })
    let v = null
    for (let round = 0; c && round < 3; round++) {
      v = await agent(verifyPrompt(d, s, c), { label: `verify:${d.id}#${round + 1}`, phase: 'Verify', schema: VERDICT })
      if (!v || v.pass || round === 2) break
      const bad = v.problems.filter(x => x.severity !== 'minor')
      log(`${d.id}: ${bad.length} blocker/major problems, fix round ${round + 1}`)
      c = (await agent(convertPrompt(d, s, p, bad), { label: `fix:${d.id}#${round + 1}`, phase: 'Convert', schema: CONVERT })) || c
    }
    return { ...r, converted: true, c, v }
  },
)

return lanes.map((r, k) => ({
  id: items[k].id,
  prefix: items[k].prefix,
  survey: r && r.s,
  plan: r && r.p,
  convert: r && r.c,
  verdict: r && r.v,
}))
