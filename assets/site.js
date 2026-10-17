// Taxel Atlas: faceted catalog over data/datasets.json. No build step; the page state lives in the URL hash.
// shared helpers (REPO, $, esc, fmt, glyph) are in common.js

const LABEL = {
  embodiment: {human: 'Human glove', robot: 'Robot hand', both: 'Human + robot'},
  coverage: {tip: 'Fingertips', phalanx: 'Finger segments', palm: 'Palm'},
  type: {piezoresistive: 'Piezoresistive', capacitive: 'Capacitive', vision: 'Vision-based', magnetic: 'Magnetic', unspecified: 'Not specified', estimated: 'Estimated (no sensor)'},
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
  rank: {1: 'R1 · Open + checked', 2: 'R2 · Open', 3: 'R3 · Restricted', 4: 'R4 · Paper only'},
};
// rank and quality are derived by scripts/build_readme.py (evidence ranking after the MIT CDFG survey)
const RANK_TEXT = {1: 'Public download, license stated, sample episodes converted and checked in the viewer.',
  2: 'Public download, but the license is not stated or the files have not been checked yet.',
  3: 'Gated, on request, or only a partial sample released.', 4: 'Announced or described in a paper; no data released.'};
const QUAL = {calibrated: 'Touch in physical units (N, kPa)', video: 'Synchronized camera video', hand_pose: 'Finger pose or joint tracking',
  scale: '10 h or 1,000 episodes or more', diversity: '10 tasks or 5 environments or more'};
const rankOf = d => d.rank ? d.rank.n : 4;
const qbar = d => {const q = d.quality; if (!q) return ''; return `<span class="qbar" title="Quality ${q.score} of ${q.of}: ${Object.entries(q.flags).map(([k, v]) => `${QUAL[k]}: ${v ? 'yes' : 'no'}`).join('; ')}">${
  Object.values(q.flags).map(v => `<i class="${v ? 'on' : ''}"></i>`).join('')}<b>Q${q.score}</b></span>`};
const rankBadge = (d, cls = 'badge') => `<span class="${cls} rk rk${rankOf(d)}" title="${esc(RANK_TEXT[rankOf(d)])}">${LABEL.rank[rankOf(d)]}</span>`;
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
// cards: one item per method, system name without its parenthetical, at most two; the dialog lists everything
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
  {key: 'rank', title: 'Rank', hint: 'How open and verified the data is', get: d => [String(rankOf(d))]},
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
];
// arXiv ids carry the month (YYMM.xxxxx); entries without one sort by year
const when = d => {const m = /arxiv\.org\/abs\/(\d{2})(\d{2})\./.exec(d.links.paper || ''); return m ? (2000 + +m[1]) * 100 + +m[2] : d.year * 100};
const SORTS = {
  rank: (a, b) => rankOf(a) - rankOf(b) || (b.quality?.score ?? 0) - (a.quality?.score ?? 0) || when(b) - when(a),
  year: (a, b) => when(b) - when(a) || a.name.localeCompare(b.name),
  taxels: (a, b) => (b.sensor.taxels_per_hand ?? -1) - (a.sensor.taxels_per_hand ?? -1),
  hours: (a, b) => (b.scale.hours ?? -1) - (a.scale.hours ?? -1),
  tasks: (a, b) => (b.scale.tasks ?? -1) - (a.scale.tasks ?? -1),
  name: (a, b) => a.name.localeCompare(b.name),
};

let D = [], HW = [], META = {}, S = {q: '', f: {}, y0: null, y1: null, view: 'cards', sort: 'rank', d: null};

const makerModel = s => s.model && s.maker && s.model.toLowerCase().startsWith(s.maker.split(/[ (]/)[0].toLowerCase()) ? s.model : [s.maker, s.model].filter(Boolean).join(' ');
const makerText = d => {const s = d.sensor, m = shortSys(makerModel(s) || '');
  return [m, principle(d) !== 'unspecified' ? LABEL.principle[principle(d)].toLowerCase() : ''].filter(Boolean).join(', ') || `${LABEL.embodiment[d.embodiment]}${d.bimanual ? ', bimanual' : ''}`};
const covText = c => c.length === 3 ? 'Fingers and palm' : c.map(r => LABEL.coverage[r]).join(' + ') || 'Coverage not stated';
const sensorLine = d => {
  const s = d.sensor, n = s.taxels_per_hand;
  return n != null ? `${n.toLocaleString('en-US')} taxels per hand` : s.sensors_per_hand ? `${s.sensors_per_hand} sensors per hand` : 'Taxel count not stated';
};

/* ---------- state <-> hash ---------- */
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  S.q = p.get('q') || ''; S.view = ['table', 'chart'].includes(p.get('view')) ? p.get('view') : 'cards'; S.sort = SORTS[p.get('sort')] ? p.get('sort') : 'rank';
  S.d = p.get('d'); S.y0 = +p.get('from') || null; S.y1 = +p.get('to') || null; S.f = {};
  for (const F of FACETS) {const v = p.get(F.key); if (v) S.f[F.key] = new Set(v.split(','))}
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  for (const [k, v] of Object.entries(S.f)) if (v.size) p.set(k, [...v].join(','));
  if (S.y0) p.set('from', S.y0); if (S.y1) p.set('to', S.y1);
  if (S.view !== 'cards') p.set('view', S.view); if (S.sort !== 'rank') p.set('sort', S.sort);
  if (S.d) p.set('d', S.d);
  const h = p.toString().replace(/%2C/g, ',');
  history.replaceState(null, '', h ? `#${h}` : location.pathname + location.search);
}

/* ---------- filtering ---------- */
const textOf = d => [d.name, zhText(d), d.title, d.authors, d.summary, d.hand, d.venue, d.sensor.maker, d.sensor.model, (d.scale.scene_types || []).join(' '),
  ...(setup(d).cameras || []).map(c => c.model), ...(setup(d).tracking || []).map(t => t.system), ...hwOf(d).map(([h]) => h.name)].join(' ').toLowerCase();
// devices in data/hardware.json that list this dataset, with their role
const hwOf = d => HW.flatMap(h => h.datasets.filter(x => x.id === d.id).map(x => [h, x.role]));
function passes(d, skip) {
  if (S.q && !S.q.toLowerCase().split(/\s+/).every(w => textOf(d).includes(w))) return false;
  if (S.y0 && d.year < S.y0 || S.y1 && d.year > S.y1) return false;
  for (const F of FACETS) {
    if (F.key === skip) continue;
    const sel = S.f[F.key]; if (!sel || !sel.size) continue;
    const vals = F.get(d);
    if (F.all ? ![...sel].every(v => vals.includes(v)) : !vals.some(v => sel.has(v))) return false;
  }
  return true;
}

function renderFacets() {
  const ys = D.map(d => d.year);
  $('facets').innerHTML = `<p class="intro">${esc(META.scope)}</p>` + FACETS.map(F => {
    const sel = S.f[F.key] || new Set(), pool = D.filter(d => passes(d, F.all ? null : F.key));
    const vals = Object.keys(LABEL[F.key]).filter(v => D.some(d => F.get(d).includes(v)));
    return `<fieldset class="fs"><legend>${F.title}</legend>${F.hint ? `<p class="hint">${F.hint}</p>` : ''}${vals.map(v => {
      const n = pool.filter(d => F.get(d).includes(v)).length;
      return `<label class="opt" data-zero="${!n && !sel.has(v)}"><input type="checkbox" data-f="${F.key}" value="${v}"${sel.has(v) ? ' checked' : ''}>${LABEL[F.key][v]}<span class="n">${n}</span></label>`;
    }).join('')}</fieldset>`;
  }).join('') + `<fieldset class="fs"><legend>Year</legend><div class="years"><input id="y0" type="number" aria-label="From year" placeholder="${Math.min(...ys)}" value="${S.y0 || ''}">–<input id="y1" type="number" aria-label="To year" placeholder="${Math.max(...ys)}" value="${S.y1 || ''}"></div></fieldset>
    <button class="clear" id="clear">Clear filters</button>`;
  $('facets').querySelectorAll('input[data-f]').forEach(i => i.onchange = () => {
    const s = S.f[i.dataset.f] ||= new Set(); i.checked ? s.add(i.value) : s.delete(i.value); update();
  });
  ['y0', 'y1'].forEach(k => $(k).onchange = e => {S[k] = +e.target.value || null; update()});
  $('clear').onclick = () => {S.f = {}; S.q = ''; S.y0 = S.y1 = null; $('q').value = ''; update()};
}

function renderChips() {
  const c = [];
  for (const [k, v] of Object.entries(S.f)) for (const x of v) c.push(`<button data-k="${k}" data-v="${x}">${LABEL[k][x]}</button>`);
  if (S.y0 || S.y1) c.push(`<button data-k="year">${S.y0 || '…'}–${S.y1 || '…'}</button>`);
  $('chips').innerHTML = c.join('');
  $('chips').querySelectorAll('button').forEach(b => b.onclick = () => {
    if (b.dataset.k === 'year') S.y0 = S.y1 = null; else S.f[b.dataset.k].delete(b.dataset.v);
    update();
  });
}

const linkRow = d => {
  const L = d.links, out = [];
  for (const [k, t] of [['paper', 'Paper'], ['project', 'Project'], ['data', 'Data'], ['code', 'Code']]) if (L[k]) out.push(`<a href="${esc(L[k])}" target="_blank" rel="noopener">${t}</a>`);
  if (d.viewer) out.push(`<a class="play" href="viewer/#rec=${esc(d.viewer)}"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" aria-hidden="true" style="vertical-align:-2px"><path d="M8 5v14l11-7z"/></svg> Play samples</a>`);
  return out.join('');
};
const thumb = d => d.thumb ? `<img src="${esc(d.thumb)}" alt="" loading="lazy">` : glyph(d.sensor.coverage, covText(d.sensor.coverage));

// the four numbers people compare first; missing values say so instead of disappearing
function facts(d) {
  const c = d.scale, j = (...a) => a.filter(Boolean).join(' · ');
  return [['Scale', esc(j(c.hours ? `${hrs(c.hours)} h` : '', c.episodes ? plural(c.episodes, 'episode') : ''))],
    ['Tasks', esc(j(c.tasks ? plural(c.tasks, 'task') : '', sceneText(d), c.subjects ? plural(c.subjects, 'person').replace('persons', 'people') : ''))],
    ['Cameras', esc(d.setup ? camSummary(d) || 'none' : '')],
    ['Hand tracking', esc(d.setup ? trackSummary(d, true) || 'none' : '')]];
}
function cards(list) {
  if (S.sort === 'rank') return [1, 2, 3, 4].map(n => list.filter(d => rankOf(d) === n)).map((g, k) => g.length ? `<section class="rgroup"><h2>${rankBadge(g[0], 'rh')}
    <span>${esc(RANK_TEXT[k + 1])}</span><small>${g.length}</small></h2>${cardGrid(g)}</section>` : '').join('');
  return cardGrid(list);
}
function cardGrid(list) {
  return `<div class="grid">${list.map(d => `<article class="card" data-id="${d.id}" tabindex="0" aria-label="${esc(d.name)}">
    <div class="thumb">${thumb(d)}${rankBadge(d)}</div>
    <div class="body">
      <div class="ttl"><h3>${esc(d.name)}</h3>${qbar(d)}<span>${d.year}</span></div>
      ${zhLine(d)}<div class="src">${esc(d.venue)} · ${esc(d.authors)}</div>
      <p class="desc">${esc(d.summary)}</p>
      <div class="spec">${glyph(d.sensor.coverage, covText(d.sensor.coverage))}<div><b>${sensorLine(d)}</b><span>${covText(d.sensor.coverage)} · ${esc(makerText(d))}</span></div></div>
      <dl class="facts">${facts(d).map(([k, v]) => `<div><dt>${k}</dt><dd>${v || '<i>not stated</i>'}</dd></div>`).join('')}</dl>
    </div>
    <div class="links">${linkRow(d)}</div></article>`).join('')}</div>`;
}

function table(list) {
  const num = (v, u = '') => v != null ? `${u === ' h' ? hrs(v) : fmt(v)}${u}` : '–', c = d => d.scale;
  const row = d => `<tr data-id="${d.id}">
    <td><b>${esc(d.name)}</b>${d.zh?.name ? `<span class="sub" lang="zh-CN">${esc(d.zh.name)}</span>` : ''}<span class="sub">${esc(d.venue)}</span></td>
    <td>${rankBadge(d, 'rk-t')}<span class="sub">${qbar(d)}</span></td>
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
    <td><span class="av-${d.availability}">${LABEL.availability[d.availability]}</span><span class="sub">${esc(d.license)}</span></td></tr>`;
  return `<div class="tablewrap"><table><thead><tr><th data-s="name">Dataset</th><th data-s="rank">Rank · quality</th><th>Hand</th><th>Coverage</th><th data-s="taxels">Taxels / hand</th><th>Tactile sensor</th>
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
    ${miss.length ? `<p class="missing">Not plotted, taxel count or hours not stated: ${miss.map(d => `<a href="#" data-id="${d.id}">${esc(d.name)}</a>`).join(', ')}</p>` : ''}</div>`;
}

function render() {
  const list = D.filter(d => passes(d)).sort(SORTS[S.sort]);
  $('count').textContent = `${list.length} of ${D.length} datasets`;
  $('out').innerHTML = !list.length ? `<p class="empty">No dataset matches these filters.</p>` : S.view === 'table' ? table(list) : S.view === 'chart' ? chart(list) : cards(list);
  $('out').querySelectorAll('[data-id]').forEach(el => {
    el.onclick = e => {if (!e.target.closest('a[href]:not([href="#"])')) {e.preventDefault(); openDetail(el.dataset.id)}};
    el.onkeydown = e => {if (e.key === 'Enter') openDetail(el.dataset.id)};
  });
  $('out').querySelectorAll('th[data-s]').forEach(th => th.onclick = () => {S.sort = th.dataset.s; $('sort').value = S.sort; update()});
  document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
}

function openDetail(id) {
  const d = D.find(x => x.id === id); if (!d) return;
  S.d = id; writeHash();
  const s = d.sensor, c = d.scale, u = setup(d), kvs = rows => `<dl class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const scale = kvs([['Recorded', esc([c.hours ? `${hrs(c.hours)} h` : '', c.episodes ? `${fmt(c.episodes)} episodes` : '', c.frames ? `${fmt(c.frames)} frames` : ''].filter(Boolean).join(' · '))],
    ['Tasks', c.tasks ? fmt(c.tasks) : ''], ['Objects', c.objects ? fmt(c.objects) : ''], ['Participants', c.subjects ? fmt(c.subjects) : ''],
    ['Environments', esc([sceneText(d), (c.scene_types || []).join(', ')].filter(Boolean).join(': '))], ['Summary', esc(c.text)]]);
  const tactile = kvs([['Hand', `${LABEL.embodiment[d.embodiment]} · ${esc(d.hand)} · ${d.bimanual ? 'bimanual' : 'single hand'}`],
    ['Sensor', esc(makerModel(s) || 'not stated')], ['Principle', LABEL.principle[principle(d)]],
    ['Coverage', covText(s.coverage)], ['Density', sensorLine(d)], ['Rate', s.rate_hz ? `${esc(s.rate_hz)} Hz` : ''], ['Range', esc(s.range || '')], ['Notes', esc(s.note || '')]]);
  const cams = (u.cameras || []).length ? `<table class="mini"><thead><tr><th>Camera</th><th>Model</th><th>Type</th><th>Resolution</th><th>FPS</th></tr></thead><tbody>${u.cameras.map(k =>
    `<tr><td>${(k.count || 1) > 1 ? `${k.count} × ` : ''}${ROLE[k.role] || esc(k.role)}${k.mount ? `<span class="sub">${esc(k.mount)}</span>` : ''}</td><td>${esc(k.model || '–')}</td><td>${esc(k.type || '–')}</td><td>${esc(k.resolution || '–')}</td><td>${k.fps ?? '–'}</td></tr>`).join('')}</tbody></table>`
    : `<p class="src">${d.setup ? 'No camera streams released.' : 'Not yet compiled.'}</p>`;
  const track = (u.tracking || []).length ? kvs(u.tracking.map(t => [esc(t.target[0].toUpperCase() + t.target.slice(1)), `<b>${LABEL.tracking[t.method] || esc(t.method)}</b>${t.system ? ` · ${esc(t.system)}` : ''}${t.note ? `<span class="sub">${esc(t.note)}</span>` : ''}`]))
    : `<p class="src">${d.setup ? 'No hand tracking.' : 'Not yet compiled.'}</p>`;
  const other = [...d.modalities.map(m => LABEL.modality[m]), ...(u.other || [])];
  $('dlg').innerHTML = `<div class="dl"><header>${glyph(s.coverage, covText(s.coverage)).replace('class="glyph"', 'class="glyph" style="width:44px;flex:none"')}
    <div><h2 id="dlgTitle">${esc(d.name)}</h2><p>${esc(d.title)}</p>${zhHead(d, 'Name and title')}<p>${esc(d.authors)} · ${esc(d.venue)}</p></div><button class="x" aria-label="Close"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
    <div class="scroll">${d.thumb ? `<img class="hero" src="${esc(d.thumb)}" alt="${esc(d.name)} overview figure">` : ''}
    <p>${esc(d.summary)}</p>
    ${d.caveats.length ? `<div class="warn"><ul>${d.caveats.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : ''}
    <h4>Rank and quality</h4>${kvs([['Rank', `${rankBadge(d, 'rk-t')} ${esc(RANK_TEXT[rankOf(d)])}${d.rank ? `<span class="sub">${esc(d.rank.why.join(' · '))}</span>` : ''}`],
      ['Quality', d.quality ? `<b>${d.quality.score} of ${d.quality.of}</b><ul class="ql">${Object.entries(d.quality.flags).map(([k, v]) => `<li class="${v ? 'on' : ''}">${v ? '<svg class="qi" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>' : '<svg class="qi" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17"/></svg>'}${QUAL[k]}<span class="vh">${v ? ' (yes)' : ' (no)'}</span></li>`).join('')}</ul>` : '']])}
    <h4>Data</h4>${scale}<h4>Tactile sensing</h4>${tactile}${hwOf(d).length ? `<h4>Hardware</h4><div class="dsl">${hwOf(d).map(([h, r]) =>
      `<a href="hardware.html#h=${esc(h.id)}">${h.thumb ? `<img src="${esc(h.thumb)}" alt="" style="object-fit:contain">` : ''}<div><b>${esc(h.name)}</b><span>${esc(r)} · ${esc(h.maker)}</span></div></a>`).join('')}</div>` : ''}<h4>Cameras</h4>${cams}<h4>Hand tracking</h4>${track}
    <h4>Also recorded</h4><p class="plain">${esc([...new Set(other)].join(', ') || 'Tactile only')}</p>
    <h4>Access</h4>${kvs([['Availability', `${LABEL.availability[d.availability]} · ${esc(d.access)}`], ['License', esc(d.license)]])}
    ${(d.used_by || []).length ? `<h4>Used by</h4><ul class="usedby">${d.used_by.map(u => `<li><a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.name)}</a>${u.note ? `: ${esc(u.note)}` : ''}</li>`).join('')}</ul>` : ''}
    <div class="links">${d.viewer ? `<a class="btn" href="viewer/#rec=${esc(d.viewer)}"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>Play samples in the viewer</a>` : ''}${linkRow(d).replace(/<a class="play"[^]*?<\/a>/, '')}</div>
    ${(d.sources || []).length ? `<details class="srcs"><summary>Sources${(d.unconfirmed || []).length ? ' and open points' : ''}</summary>
      ${(d.unconfirmed || []).length ? `<p>Derived or not confirmed:</p><ul>${d.unconfirmed.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p>Read:</p>` : ''}
      <ul>${d.sources.map(x => `<li><a href="${esc(x)}" target="_blank" rel="noopener">${esc(x)}</a></li>`).join('')}</ul></details>` : ''}
    ${d.image_credit ? `<p class="src" style="margin-top:12px">Figure: ${esc(d.image_credit)}</p>` : ''}</div></div>`;
  $('dlg').querySelector('.x').onclick = () => $('dlg').close();
  if (!$('dlg').open) $('dlg').showModal();
}

function update() {writeHash(); renderFacets(); renderChips(); render()}

async function main() {
  const j = await (await fetch('data/datasets.json')).json();
  D = j.datasets; META = j.metadata;
  try {HW = (await (await fetch('data/hardware.json')).json()).hardware} catch {HW = []}
  $('sum').textContent = `${D.length} datasets · updated ${META.last_updated}`;
  $('gh').href = REPO; $('contrib').href = `${REPO}/issues/new?template=add_dataset.yml`;
  readHash(); $('q').value = S.q; $('sort').value = S.sort;
  $('q').oninput = e => {S.q = e.target.value; writeHash(); renderFacets(); renderChips(); render()};
  $('sort').onchange = e => {S.sort = e.target.value; update()};
  document.querySelectorAll('.seg button').forEach(b => b.onclick = () => {S.view = b.dataset.view; update()});
  $('filtbtn').onclick = () => document.body.dataset.filters = document.body.dataset.filters === 'open' ? '' : 'open';
  document.addEventListener('click', e => {if (document.body.dataset.filters === 'open' && !e.target.closest('#facets,#filtbtn')) document.body.dataset.filters = ''});
  $('dlg').addEventListener('close', () => {S.d = null; writeHash()});
  $('dlg').addEventListener('click', e => {if (e.target === $('dlg')) $('dlg').close()});
  update();
  if (S.d) openDetail(S.d);
}
main();
