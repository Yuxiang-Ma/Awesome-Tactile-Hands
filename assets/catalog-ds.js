// Taxel Atlas, datasets tab: facets, sorts, list rows, Compare table, Chart and the focus pane over data/datasets.json.
// Loaded before catalog-hw.js and site.js (the shell); shared helpers are in common.js.

// the three catalogs, filled by site.js before anything renders
const DB = {D: [], HW: [], M: [], ds: {}, hw: {}, md: {}};

const DSTAB = (() => {
const LABEL = {
  embodiment: {human: 'Human glove', robot: 'Robot hand', both: 'Human + robot'},
  coverage: {tip: 'Fingertips', phalanx: 'Finger segments', palm: 'Palm'},
  modality: {hand_pose: 'Hand pose', egocentric: 'Egocentric video', wrist_rgb: 'Wrist cameras', multiview_rgb: 'Multi-view RGB', rgb: 'RGB video', depth: 'Depth',
    object_pose: 'Object pose', mocap: 'Motion capture', robot_action: 'Robot actions', language: 'Language', emg: 'EMG', imu: 'IMU', eye_tracking: 'Eye tracking',
    audio: 'Audio', segmentation: 'Segmentation'},
  availability: {public: 'Public', gated: 'Gated', partial: 'Partial', announced: 'Release announced', unclear: 'Unclear', not_released: 'Not released'},
  hands: {two: 'Bimanual', one: 'Single hand'},
  taxels: {a: 'Under 100', b: '100 to 299', c: '300 to 999', d: '1,000 or more', u: 'Not stated'},
  principle: {piezoresistive: 'Piezoresistive', capacitive: 'Capacitive', piezoelectric: 'Piezoelectric', magnetic: 'Magnetic (Hall)', optical: 'Optical (camera-based)',
    barometric: 'Barometric', resistive: 'Resistive (FSR)', unspecified: 'Not specified'},
  tracking: {vision_estimate: 'Vision (cameras)', optical_mocap: 'Optical mocap (markers)', optical_tracker: 'Optical tracker (Vive)', imu: 'IMU glove / suit',
    magnetic: 'Magnetic (EMF)', bend_sensor: 'Bend sensors', exoskeleton: 'Exoskeleton', robot_proprioception: 'Robot joint encoders', teleop_glove: 'Teleop glove',
    other: 'Other', none: 'None'},
  wrist: {yes: 'Wrist camera(s)', no: 'No wrist camera', u: 'Not stated'},
  scenes: {multi: 'Several environments', single: 'One setting', u: 'Not stated'},
  rank: {1: 'R1 · Open, checked', 2: 'R2 · Open, not checked', 3: 'R3 · Open, defects found', 4: 'R4 · Apply for access', 5: 'R5 · Sample only', 6: 'R6 · Paper only'},
  license: {open: 'Allows commercial use', nc: 'Non-commercial only', ns: 'Not stated'},
  checked: {passed: 'All checks passed', failed: 'A check failed', none: 'Not checked yet'},
};
// rank and contents are derived by scripts/build_readme.py: the rank from openness and the integrity checks, never the license
const RANK_TEXT = {1: 'Public download; sample episodes opened in the viewer and every integrity check passed.',
  2: 'Public download; the files have not been opened yet.', 3: 'Public download; sample episodes opened and at least one integrity check failed.',
  4: 'The data downloads after a form, a Hugging Face gate or the authors\' approval.', 5: 'Only a sample or part of the data is released.',
  6: 'Announced or described in a paper; no data released.'};
const CHECKS = {files: ['Files open', 'Every sampled file opens in its documented format.'],
  streams: ['Streams present', 'Tactile and every listed stream are in the files, none empty.'],
  time: ['Time base', 'Timestamps or a stated rate align the streams.'],
  tactile: ['Tactile intact', 'Tactile channels and frames are not lost or corrupted.']};
const CHECK_RULE = 'A check fails when a fault affects more than 5% of a stream\'s recordings, channels or frames, or when the release has neither timestamps nor a stated rate; smaller faults are listed as minor.';
const CONT = {calibrated: 'Touch in physical units (N, kPa)', video: 'Synchronized camera video', hand_pose: 'Finger pose or joint tracking',
  scale: '10 h or 1,000 episodes or more', diversity: '10 tasks or 5 environments or more'};
const GATE = {hf_gate: 'Hugging Face gate', form: 'Access form', request: 'Request to the authors', purchase: 'Purchase'};
const gateText = g => GATE[g.kind] + (g.approval !== 'not stated' ? `, ${g.approval} approval` : '');
const rankOf = d => d.rank ? d.rank.n : 6;
const checkedOf = d => ({passed: 'passed', failed: 'failed'})[d.rank?.integrity] || 'none';
const licOf = d => {const l = d.license.toLowerCase(); return /^(not stated|unconfirmed|unclear)/.test(l) ? 'ns' : /\bnc\b|non-commercial/.test(l) ? 'nc' : 'open'};
// the licence name without its parenthetical or second clause: "CC BY-NC-SA 4.0 (data); MIT (code)" -> "CC BY-NC-SA 4.0"
const licShort = d => licOf(d) === 'ns' ? (d.license.startsWith('unconfirmed') ? 'License unconfirmed' : 'License not stated') : d.license.split(/ \(|; /)[0];
const cbar = d => {const q = d.contents; if (!q) return ''; return `<span class="qbar" title="Contents ${q.score} of ${q.of}: ${Object.entries(q.flags).map(([k, v]) => `${CONT[k]}: ${v ? 'yes' : 'no'}`).join('; ')}">${
  Object.values(q.flags).map(v => `<i class="${v ? 'on' : ''}"></i>`).join('')}<b>${q.score}/${q.of}</b></span>`};
const rankBadge = (d, cls) => `<span class="${cls} rk rk${rankOf(d)}" title="${esc(RANK_TEXT[rankOf(d)])}">${LABEL.rank[rankOf(d)]}</span>`;
// license, application and failed checks as tags; the rank itself never depends on the first
const statusTags = d => [`<span class="tag lic${licOf(d) === 'ns' ? ' un' : ''}" title="License: ${esc(d.license)}">${esc(licShort(d))}</span>`,
  d.gate ? `<span class="tag gate" title="${esc(d.gate.note || '')}">Apply: ${esc(gateText(d.gate))}</span>` : '',
  ...(d.rank?.failed || []).map(c => `<span class="tag bad" title="${esc(d.integrity.faults.filter(f => f.check === c && f.severity === 'defect').map(f => f.text).join(' '))}">Failed: ${CHECKS[c][0]}</span>`)].join('');
// short names for compact cells
const TRACK_SHORT = {vision_estimate: 'Vision', optical_mocap: 'Optical mocap', optical_tracker: 'Vive tracker', imu: 'IMU', magnetic: 'Magnetic',
  bend_sensor: 'Bend sensors', exoskeleton: 'Exoskeleton', robot_proprioception: 'Joint encoders', teleop_glove: 'Teleop glove', other: 'Other'};
const ROLE = {egocentric: 'egocentric', wrist: 'wrist', third_person: 'third-person', robot_head: 'robot head', other: 'other'};
const setup = d => d.setup || {cameras: [], tracking: [], other: []};
const principle = d => {const p = (d.sensor.principle || '').split(/[\s(]/)[0].toLowerCase(); return LABEL.principle[p] ? p : d.sensor.type === 'vision' ? 'optical' : LABEL.principle[d.sensor.type] ? d.sensor.type : 'unspecified'};
const wristOf = d => {const w = setup(d).wrist_cameras; return w == null ? (d.setup ? 'u' : d.modalities.includes('wrist_rgb') ? 'yes' : 'u') : w > 0 ? 'yes' : 'no'};
const scenesOf = d => {const n = d.scale.scenes ?? (d.scale.scene_types || []).length; return !n ? 'u' : n > 1 ? 'multi' : 'single'};
const trackOf = d => {const t = setup(d).tracking || []; return d.setup ? (t.length ? [...new Set(t.map(x => x.method))] : ['none']) : []};
// "egocentric RGB-D + 2 wrist + 21 third-person"
function camSummary(d) {
  const by = {};
  for (const c of setup(d).cameras || []) {const r = ROLE[c.role] ? c.role : 'other'; (by[r] ||= []).push(c)}
  return Object.keys(ROLE).filter(r => by[r]).map(r => {
    const n = by[r].reduce((a, c) => a + (c.count || 1), 0), types = [...new Set(by[r].map(c => c.type).filter(t => t && t !== 'RGB'))];
    return `${n > 1 || r !== 'egocentric' ? n + ' ' : ''}${ROLE[r]}${types.length ? ' ' + types.join('/') : ''}`;
  }).join(' + ');
}
const shortSys = x => String(x).split(/ \(|;|, /)[0].trim();
// short form: one item per method, system name without its parenthetical, at most two; the long form lists everything
function trackSummary(d, short) {
  const t = (setup(d).tracking || []).filter(x => x.target !== 'object');
  if (!short) return t.map(x => `${LABEL.tracking[x.method] || x.method}${x.system ? ` (${x.system})` : ''}`).join(' + ');
  const by = new Map();
  for (const x of t) if (!by.has(x.method)) by.set(x.method, x.system ? shortSys(x.system) : '');
  const out = [...by].map(([m, sys]) => `${TRACK_SHORT[m] || m}${sys && sys.length < 28 ? ` (${sys})` : ''}`);
  return out.slice(0, 2).join(' + ') + (out.length > 2 ? ` +${out.length - 2}` : '');
}
const hrs = h => h >= 10 ? fmt(Math.round(h)) : String(+h.toFixed(1));
const plural = (n, w) => `${fmt(n)} ${w}${n === 1 ? '' : 's'}`;
const sceneText = d => {const c = d.scale, n = c.scenes ?? (c.scene_types || []).length; return n ? `${n} ${n === 1 ? 'setting' : 'environments'}` : ''};
const taxBucket = d => {const n = d.sensor.taxels_per_hand; return n == null ? 'u' : n < 100 ? 'a' : n < 300 ? 'b' : n < 1000 ? 'c' : 'd'};
// each facet: values of a dataset, and whether several ticks must all match (all) or any (default)
const FACETS = [
  {key: 'rank', title: 'Rank', hint: 'How open the data is and whether its files passed the integrity checks', get: d => [String(rankOf(d))]},
  {key: 'checked', title: 'Integrity checks', hint: 'Run on sample episodes opened in the viewer', get: d => [checkedOf(d)]},
  {key: 'license', title: 'License', get: d => [licOf(d)]},
  {key: 'embodiment', title: 'Hand', get: d => [d.embodiment]},
  {key: 'coverage', title: 'Tactile coverage', all: true, hint: 'Ticked regions must all be sensed', get: d => d.sensor.coverage},
  {key: 'taxels', title: 'Taxels per hand', get: d => [taxBucket(d)]},
  {key: 'principle', title: 'Tactile sensing', get: d => [principle(d)]},
  {key: 'tracking', title: 'Hand tracking', hint: 'How hand or finger pose is captured', get: trackOf},
  {key: 'wrist', title: 'Wrist cameras', get: d => [wristOf(d)]},
  {key: 'scenes', title: 'Environments', get: d => [scenesOf(d)]},
  {key: 'modality', title: 'Also recorded', all: true, hint: 'Ticked streams must all be present', get: d => d.modalities},
  {key: 'hands', title: 'Hands', get: d => [d.bimanual ? 'two' : 'one']},
  {key: 'availability', title: 'Access', get: d => [d.availability]},
].map(F => ({...F, labels: LABEL[F.key]}));
const CHK_ORDER = {passed: 0, none: 1, failed: 2};
// arXiv ids carry the month (YYMM.xxxxx); entries without one sort by year
const when = d => {const m = /arxiv\.org\/abs\/(\d{2})(\d{2})\./.exec(d.links.paper || ''); return m ? (2000 + +m[1]) * 100 + +m[2] : d.year * 100};
const SORTS = {
  rank: (a, b) => rankOf(a) - rankOf(b) || CHK_ORDER[checkedOf(a)] - CHK_ORDER[checkedOf(b)] || when(b) - when(a),
  contents: (a, b) => (b.contents?.score ?? 0) - (a.contents?.score ?? 0) || rankOf(a) - rankOf(b) || when(b) - when(a),
  year: (a, b) => when(b) - when(a) || a.name.localeCompare(b.name),
  taxels: (a, b) => (b.sensor.taxels_per_hand ?? -1) - (a.sensor.taxels_per_hand ?? -1),
  hours: (a, b) => (b.scale.hours ?? -1) - (a.scale.hours ?? -1),
  tasks: (a, b) => (b.scale.tasks ?? -1) - (a.scale.tasks ?? -1),
  name: (a, b) => a.name.localeCompare(b.name),
};

const makerModel = s => s.model && s.maker && s.model.toLowerCase().startsWith(s.maker.split(/[ (]/)[0].toLowerCase()) ? s.model : [s.maker, s.model].filter(Boolean).join(' ');
const makerText = d => {const s = d.sensor, m = shortSys(makerModel(s) || '');
  return [m, principle(d) !== 'unspecified' ? LABEL.principle[principle(d)].toLowerCase() : ''].filter(Boolean).join(', ') || `${LABEL.embodiment[d.embodiment]}${d.bimanual ? ', bimanual' : ''}`};
const covText = c => c.length === 3 ? 'Fingers and palm' : c.map(r => LABEL.coverage[r]).join(' + ') || 'Coverage not stated';
const sensorLine = d => {
  const s = d.sensor, n = s.taxels_per_hand;
  return n != null ? `${n.toLocaleString('en-US')} taxels per hand` : s.sensors_per_hand ? `${s.sensors_per_hand} sensors per hand` : 'Taxel count not stated';
};
// devices in data/hardware.json that list this dataset, with their role
const hwOf = d => DB.HW.flatMap(h => h.datasets.filter(x => x.id === d.id).map(x => [h, x.role]));
// models in data/models.json trained or evaluated on this dataset
const modelsOf = d => DB.M.filter(m => m.uses.some(u => u.id === d.id));
const textOf = d => [d.name, zhText(d), d.title, d.authors, d.summary, d.hand, d.venue, d.sensor.maker, d.sensor.model, (d.scale.scene_types || []).join(' '),
  ...(setup(d).cameras || []).map(c => c.model), ...(setup(d).tracking || []).map(t => t.system), ...hwOf(d).map(([h]) => h.name)].join(' ').toLowerCase();

const linkRow = d => {
  const L = d.links, out = [];
  for (const [k, t] of [['paper', 'Paper'], ['project', 'Project'], ['data', 'Data'], ['code', 'Code']]) if (L[k]) out.push(`<a href="${esc(L[k])}" target="_blank" rel="noopener">${t}</a>`);
  return out.join('');
};
const ICON_PLAY = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';

/* ---------- list rows ---------- */
function groups(list, sort) {
  if (sort !== 'rank') return null;
  return [1, 2, 3, 4, 5, 6].map(n => ({head: `<span class="rk rk${n}">${LABEL.rank[n]}</span>`, title: RANK_TEXT[n], items: list.filter(d => rankOf(d) === n)}));
}
function row(d, sort) {
  const s = d.sensor, c = d.scale, failed = (d.rank?.failed || []).length;
  const tax = s.taxels_per_hand != null ? `${fmt(s.taxels_per_hand)} taxels` : s.sensors_per_hand ? `${s.sensors_per_hand} sensors` : 'taxels not stated';
  const size = c.hours ? `${hrs(c.hours)} h` : c.episodes ? plural(c.episodes, 'episode') : 'size not stated';
  return {img: d.thumb ? `<img src="${esc(d.thumb)}" alt="" loading="lazy">` : glyph(s.coverage, covText(s.coverage)),
    name: d.name, zh: d.zh?.name, year: d.year, tag: newTag('dataset', d.id),
    meta: [sort === 'rank' ? '' : `<span class="rk rk${rankOf(d)}">R${rankOf(d)}</span>`, esc(tax), esc(size),
      `<span class="${licOf(d) === 'ns' ? 'warn-t' : ''}">${esc(licShort(d))}</span>`,
      failed ? `<span class="bad-t">${failed === 1 ? '1 check failed' : `${failed} checks failed`}</span>` : ''].filter(Boolean).join(' · '),
    glyph: glyph(s.coverage, covText(s.coverage))};
}

/* ---------- Compare table ---------- */
function table(list) {
  const num = (v, u = '') => v != null ? `${u === ' h' ? hrs(v) : fmt(v)}${u}` : '–', c = d => d.scale;
  const row = d => `<tr data-id="${d.id}" tabindex="0">
    <td><b>${esc(d.name)}</b>${d.zh?.name ? `<span class="sub" lang="zh-CN">${esc(d.zh.name)}</span>` : ''}<span class="sub">${esc(d.venue)}</span></td>
    <td>${rankBadge(d, 'rk-t')}<span class="sub">${(d.rank?.failed || []).map(c => `Failed: ${CHECKS[c][0]}`).join(', ') || (d.contents ? `Contents ${cbar(d)}` : '')}</span></td>
    <td>${LABEL.embodiment[d.embodiment]}<span class="sub">${d.bimanual ? 'Bimanual' : 'Single hand'}</span></td>
    <td><span class="cov">${glyph(d.sensor.coverage, covText(d.sensor.coverage))}${covText(d.sensor.coverage)}</span></td>
    <td class="num">${d.sensor.taxels_per_hand != null ? d.sensor.taxels_per_hand.toLocaleString('en-US') : d.sensor.sensors_per_hand ? `${d.sensor.sensors_per_hand} sensors` : '–'}</td>
    <td>${esc(shortSys(makerModel(d.sensor) || '–'))}<span class="sub">${LABEL.principle[principle(d)]}</span></td>
    <td>${esc(d.setup ? camSummary(d) || 'none' : '–')}<span class="sub">${wristOf(d) === 'no' && (setup(d).cameras || []).length ? 'no wrist camera' : ''}</span></td>
    <td>${esc(d.setup ? trackSummary(d, true) || 'none' : '–')}</td>
    <td class="num">${num(c(d).hours, ' h')}</td>
    <td class="num">${num(c(d).episodes)}</td>
    <td class="num">${num(c(d).tasks)}</td>
    <td>${esc(sceneText(d) || '–')}<span class="sub">${esc((c(d).scene_types || []).slice(0, 4).join(', '))}</span></td>
    <td class="num">${num(c(d).subjects)}</td>
    <td><span class="av-${d.availability}">${LABEL.availability[d.availability]}</span><span class="sub">${esc(licShort(d))}</span>${d.gate ? `<span class="sub">Apply: ${esc(gateText(d.gate))}</span>` : ''}</td></tr>`;
  return `<div class="tablewrap"><table><thead><tr><th data-s="name">Dataset</th><th data-s="rank">Rank</th><th>Hand</th><th>Coverage</th><th data-s="taxels">Taxels / hand</th><th>Tactile sensor</th>
    <th>Cameras</th><th>Hand tracking</th><th data-s="hours">Hours</th><th>Episodes</th><th data-s="tasks">Tasks</th><th>Environments</th><th>People</th><th>Access</th></tr></thead>
    <tbody>${list.map(row).join('')}</tbody></table></div>`;
}

/* ---------- chart: taxels per hand against hours, point area ~ task count ---------- */
function chart(list) {
  const W = 920, H = 520, L = 64, R = 24, T = 20, B = 92, pw = W - L - R, ph = H - T - B;
  const has = d => d.sensor.taxels_per_hand && d.scale.hours, pts = list.filter(has), miss = list.filter(d => !has(d));
  const lx = v => Math.log10(v), X0 = 0.5, X1 = 3.2, Y0 = -1, Y1 = 3;   // 3 .. 1,600 taxels, 0.1 .. 1,000 h
  const x = v => L + (lx(v) - X0) / (X1 - X0) * pw, y = v => T + ph - (Math.max(Y0, Math.min(Y1, lx(v))) - Y0) / (Y1 - Y0) * ph;
  const col = {human: 'var(--accent)', robot: 'var(--c-robot)', both: 'var(--c-both)'};
  const o = [];
  for (const v of [10, 30, 100, 300, 1000]) o.push(`<line class="gl" x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${T + ph}"/><text class="ax" x="${x(v)}" y="${T + ph + 16}" text-anchor="middle">${fmt(v)}</text>`);
  for (const v of [0.1, 1, 10, 100, 1000]) o.push(`<line class="gl" x1="${L}" x2="${L + pw}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v} h</text>`);
  o.push(`<text class="axt" x="${L + pw / 2}" y="${T + ph + 36}" text-anchor="middle">Taxels per hand (log)</text><text class="axt" transform="translate(16 ${T + ph / 2}) rotate(-90)" text-anchor="middle">Recorded hours (log)</text>`);
  const sorted = [...pts].sort((a, b) => (b.scale.tasks || 0) - (a.scale.tasks || 0)), boxes = [];
  for (const d of sorted) {
    const r = Math.min(34, 5 + Math.sqrt(d.scale.tasks || 1) * 1.3), cx = x(d.sensor.taxels_per_hand), cy = y(d.scale.hours);
    // label right of the circle, or left near the right edge; step down until it clears earlier labels
    const w = d.name.length * 7.4 + 4, left = cx + r + 4 + w > W - 4, lx0 = left ? cx - r - 4 - w : cx + r + 4;
    let ly = cy + 4;
    for (let k = 0; k < 8 && boxes.some(b => lx0 < b[0] + b[2] && b[0] < lx0 + w && Math.abs(b[1] - ly) < 14); k++) ly += 14;
    boxes.push([lx0, ly, w]);
    o.push(`<g class="pt" data-id="${d.id}" tabindex="0"><title>${esc(`${d.name}: ${d.sensor.taxels_per_hand} taxels/hand, ${d.scale.hours} h${d.scale.tasks ? `, ${d.scale.tasks} tasks` : ''}`)}</title>
      <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${r.toFixed(1)}" style="fill:${col[d.embodiment]}"/>
      <text x="${(left ? lx0 + w : lx0).toFixed(1)}" y="${ly.toFixed(1)}"${left ? ' text-anchor="end"' : ''}>${esc(d.name)}</text></g>`);
  }
  const legend = Object.entries(col).map(([k, c]) => `<span><i style="background:${c}"></i>${LABEL.embodiment[k]}</span>`).join('');
  return `<div class="chartwrap"><div class="chead"><b>Density against size</b><span class="legend">${legend}<span>Circle area ~ number of tasks</span></span></div>
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Scatter plot of taxels per hand against recorded hours">${o.join('')}</svg>
    ${miss.length ? `<p class="missing">Not plotted, taxel count or hours not stated: ${miss.map(d => `<a href="${focusHref('d', d.id)}">${esc(d.name)}</a>`).join(', ')}</p>` : ''}</div>`;
}

/* ---------- focus pane ---------- */
const ICON_YES = '<svg class="qi" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const ICON_NO = '<svg class="qi" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17"/></svg>';
// the four checks with pass or fail, then every fault found (defects first); unchecked datasets say so
function integrityBlock(d) {
  if (!d.integrity) return `<b>Not checked</b><span class="sub">No sample episodes have been opened in the viewer yet.</span>`;
  const faults = [...d.integrity.faults].sort((a, b) => (a.severity === 'defect' ? 0 : 1) - (b.severity === 'defect' ? 0 : 1));
  const bad = new Set(faults.filter(f => f.severity === 'defect').map(f => f.check));
  return `<ul class="ql chk">${Object.entries(CHECKS).map(([k, [lbl, what]]) => `<li class="${bad.has(k) ? 'no' : 'on'}" title="${esc(what)}">${bad.has(k) ? ICON_NO : ICON_YES}${lbl}<span class="vh">${bad.has(k) ? ' (failed)' : ' (passed)'}</span></li>`).join('')}</ul>
    ${faults.length ? `<ul class="faults">${faults.map(f => `<li><b class="${f.severity === 'defect' ? 'fd' : 'fm'}">${f.severity === 'defect' ? 'Defect' : 'Minor'}</b> ${CHECKS[f.check][0]}: ${esc(f.text)}</li>`).join('')}</ul>` : '<span class="sub">No faults found.</span>'}
    <span class="sub">${esc(CHECK_RULE)}</span>`;
}
// users that are not in data/models.json link out
const otherUse = u => `<li><a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.name)}</a>${u.note ? `: ${esc(u.note)}` : ''}</li>`;
const kvs = rows => `<dl class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;

function pane(d) {
  const s = d.sensor, c = d.scale, u = setup(d), j = (...a) => a.filter(Boolean).join(' · ');
  const hw = hwOf(d), models = modelsOf(d), others = (d.used_by || []).filter(x => !(x.model && DB.md[x.model]));
  const facts = [['Touch', esc(sensorLine(d)), esc(`${covText(s.coverage)} · ${makerText(d)}`)],
    ['Scale', esc(j(c.hours ? `${hrs(c.hours)} h` : '', c.episodes ? plural(c.episodes, 'episode') : '')), ''],
    ['Tasks', esc(j(c.tasks ? plural(c.tasks, 'task') : '', sceneText(d), c.subjects ? plural(c.subjects, 'person').replace('persons', 'people') : '')), ''],
    ['Cameras', esc(d.setup ? camSummary(d) || 'none' : ''), ''],
    ['Hand tracking', esc(d.setup ? trackSummary(d, true) || 'none' : ''), '']];
  const scale = kvs([['Recorded', esc([c.hours ? `${hrs(c.hours)} h` : '', c.episodes ? `${fmt(c.episodes)} episodes` : '', c.frames ? `${fmt(c.frames)} frames` : ''].filter(Boolean).join(' · '))],
    ['Tasks', c.tasks ? fmt(c.tasks) : ''], ['Objects', c.objects ? fmt(c.objects) : ''], ['Participants', c.subjects ? fmt(c.subjects) : ''],
    ['Environments', esc([sceneText(d), (c.scene_types || []).join(', ')].filter(Boolean).join(': '))], ['Summary', esc(c.text)]]);
  const tactile = kvs([['Hand', `${LABEL.embodiment[d.embodiment]} · ${esc(d.hand)} · ${d.bimanual ? 'bimanual' : 'single hand'}`],
    ['Sensor', esc(makerModel(s) || 'not stated')], ['Principle', LABEL.principle[principle(d)]],
    ['Coverage', covText(s.coverage)], ['Density', sensorLine(d)], ['Rate', s.rate_hz ? `${esc(s.rate_hz)} Hz` : ''], ['Range', esc(s.range || '')], ['Notes', esc(s.note || '')]]);
  const cams = (u.cameras || []).length ? `<div class="tscroll"><table class="mini"><thead><tr><th>Camera</th><th>Model</th><th>Type</th><th>Resolution</th><th>FPS</th></tr></thead><tbody>${u.cameras.map(k =>
    `<tr><td>${(k.count || 1) > 1 ? `${k.count} × ` : ''}${ROLE[k.role] || esc(k.role)}${k.mount ? `<span class="sub">${esc(k.mount)}</span>` : ''}</td><td>${esc(k.model || '–')}</td><td>${esc(k.type || '–')}</td><td>${esc(k.resolution || '–')}</td><td>${k.fps ?? '–'}</td></tr>`).join('')}</tbody></table></div>`
    : `<p class="src">${d.setup ? 'No camera streams released.' : 'Not yet compiled.'}</p>`;
  const track = (u.tracking || []).length ? kvs(u.tracking.map(t => [esc(t.target[0].toUpperCase() + t.target.slice(1)), `<b>${LABEL.tracking[t.method] || esc(t.method)}</b>${t.system ? ` · ${esc(t.system)}` : ''}${t.note ? `<span class="sub">${esc(t.note)}</span>` : ''}`]))
    : `<p class="src">${d.setup ? 'No hand tracking.' : 'Not yet compiled.'}</p>`;
  const other = [...d.modalities.map(m => LABEL.modality[m]), ...(u.other || [])];
  return `<header class="ph">${glyph(s.coverage, covText(s.coverage))}
    <div><h2 id="paneTitle">${esc(d.name)} <span class="yr">${d.year}</span></h2>${zhHead(d, 'Name and title')}<p class="pt">${esc(d.title)}</p><p class="pm">${esc(d.authors)} · ${esc(d.venue)}</p></div></header>
    <div class="pact">${d.viewer ? `<a class="btn" href="viewer/#rec=${esc(d.viewer)}">${ICON_PLAY}Play samples</a>` : ''}${linkRow(d)}</div>
    <div class="tags">${rankBadge(d, 'tag rk-tag')}${statusTags(d)}${newTag('dataset', d.id)}</div>
    <div class="lead">${d.thumb ? `<img class="hero" src="${esc(d.thumb)}" alt="${esc(d.name)} overview figure">` : ''}
      <dl class="pfacts">${facts.map(([k, v, sub]) => `<div><dt>${k}</dt><dd>${v || '<i>not stated</i>'}${sub ? `<span class="sub">${sub}</span>` : ''}</dd></div>`).join('')}</dl></div>
    <p class="psum">${esc(d.summary)}</p>
    ${d.caveats.length ? `<div class="warn"><ul>${d.caveats.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
    <section><h3>Recorded with <span>${hw.length}</span></h3>${hw.length ? `<div class="lks">${hw.map(([h, r]) => hwTile(h, `${r} · ${h.maker}`)).join('')}</div>`
      : `<p class="src">${esc(makerModel(s) || 'The sensor')} is not in the hardware list yet.</p>`}</section>
    <section><h3>Models trained on it <span>${models.length}</span></h3>${models.length ? `<div class="lks">${models.map(m => modelTile(m, m.dataset === d.id ?'released with this dataset' : '')).join('')}</div>`
      : '<p class="src">No model in the catalog uses this dataset yet.</p>'}
      ${others.length ? `<ul class="usedby">${others.map(otherUse).join('')}</ul>` : ''}</section>
    <section><h3>Rank and integrity</h3>${kvs([['Rank', `${rankBadge(d, 'rk-t')} ${esc(RANK_TEXT[rankOf(d)])}${d.rank ? `<span class="sub">${esc(d.rank.why.join(' · '))}</span>` : ''}`],
      ['Integrity', integrityBlock(d)],
      ['Contents', d.contents ? `<b>${d.contents.score} of ${d.contents.of}</b><span class="sub">What the data holds; not part of the rank.</span><ul class="ql">${Object.entries(d.contents.flags).map(([k, v]) => `<li class="${v ? 'on' : ''}">${v ? ICON_YES : ICON_NO}${CONT[k]}<span class="vh">${v ? ' (yes)' : ' (no)'}</span></li>`).join('')}</ul>` : '']])}</section>
    <section><h3>Data</h3>${scale}</section><section><h3>Tactile sensing</h3>${tactile}</section>
    <section><h3>Cameras</h3>${cams}</section><section><h3>Hand tracking</h3>${track}</section>
    <section><h3>Also recorded</h3><p class="plain">${esc([...new Set(other)].join(', ') || 'Tactile only')}</p></section>
    <section><h3>Access</h3>${kvs([['Availability', `${LABEL.availability[d.availability]} · ${esc(d.access)}`],
      ['Apply', d.gate ? `<a href="${esc(d.gate.url)}" target="_blank" rel="noopener">${esc(gateText(d.gate))}</a>${d.gate.note ? `<span class="sub">${esc(d.gate.note)}</span>` : ''}${d.gate.checked ? `<span class="sub">Checked ${esc(d.gate.checked)}.</span>` : ''}` : ''],
      ['License', `${esc(d.license)}<span class="sub">Shown for reuse; it does not change the rank.</span>`]])}</section>
    ${(d.sources || []).length ? `<details class="srcs"><summary>Sources${(d.unconfirmed || []).length ? ' and open points' : ''}</summary>
      ${(d.unconfirmed || []).length ? `<p>Derived or not confirmed:</p><ul>${d.unconfirmed.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p>Read:</p>` : ''}
      <ul>${d.sources.map(x => `<li><a href="${esc(x)}" target="_blank" rel="noopener">${esc(x)}</a></li>`).join('')}</ul></details>` : ''}
    ${d.image_credit ? `<p class="src credit">Figure: ${esc(d.image_credit)}</p>` : ''}`;
}

// a dataset as a linked tile in another item's pane
const tile = (d, sub) => ({img: d.thumb ? `<img src="${esc(d.thumb)}" alt="">` : glyph(d.sensor.coverage, covText(d.sensor.coverage)),
  name: d.name, sub: [sub && esc(sub), `<span class="rk rk${rankOf(d)}">R${rankOf(d)}</span>`, d.year].filter(Boolean).join(' · ')});

return {key: 'datasets', fk: 'd', target: 'dataset', noun: ['dataset', 'datasets'], items: () => DB.D, byId: id => DB.ds[id],
  FACETS, SORTS, defaultSort: 'rank', years: true,
  sortOptions: [['rank', 'Rank'], ['contents', 'Contents'], ['year', 'Newest'], ['taxels', 'Taxels per hand'], ['hours', 'Hours'], ['tasks', 'Tasks'], ['name', 'Name']],
  views: [['list', 'List'], ['table', 'Compare'], ['chart', 'Chart']], extra: {chart},
  search: 'Search name, author, hand, task…', textOf, groups, row, table, pane, tile, title: d => d.name,
  summary: () => `${DB.D.length} datasets · updated ${DB.metaD.last_updated}`, scope: () => DB.metaD.scope,
  contrib: ['Suggest a dataset', `${REPO}/issues/new?template=add_dataset.yml`],
  footer: 'Compiled from public papers, project pages and dataset cards. Numbers are as the authors report them; fields we could not confirm are marked.',
  empty: 'No dataset matches these filters.'};
})();
