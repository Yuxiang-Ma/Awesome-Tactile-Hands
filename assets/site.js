// Taxel Atlas: faceted catalog over data/datasets.json. No build step; the page state lives in the URL hash.
const REPO = 'https://github.com/Yuxiang-Ma/Awesome-Tactile-Hands';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = n => n == null ? '' : n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}K` : n.toLocaleString('en-US');

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
};
const taxBucket = d => {const n = d.sensor.taxels_per_hand; return n == null ? 'u' : n < 100 ? 'a' : n < 300 ? 'b' : n < 1000 ? 'c' : 'd'};
// each facet: values of a dataset, and whether several ticks must all match (all) or any (default)
const FACETS = [
  {key: 'embodiment', title: 'Hand', get: d => [d.embodiment]},
  {key: 'coverage', title: 'Tactile coverage', all: true, hint: 'Ticked regions must all be sensed', get: d => d.sensor.coverage},
  {key: 'taxels', title: 'Taxels per hand', get: d => [taxBucket(d)]},
  {key: 'type', title: 'Sensor', get: d => [d.sensor.type]},
  {key: 'modality', title: 'Also recorded', all: true, hint: 'Ticked streams must all be present', get: d => d.modalities},
  {key: 'hands', title: 'Hands', get: d => [d.bimanual ? 'two' : 'one']},
  {key: 'availability', title: 'Access', get: d => [d.availability]},
];
// arXiv ids carry the month (YYMM.xxxxx); entries without one sort by year
const when = d => {const m = /arxiv\.org\/abs\/(\d{2})(\d{2})\./.exec(d.links.paper || ''); return m ? (2000 + +m[1]) * 100 + +m[2] : d.year * 100};
const SORTS = {
  year: (a, b) => when(b) - when(a) || a.name.localeCompare(b.name),
  taxels: (a, b) => (b.sensor.taxels_per_hand ?? -1) - (a.sensor.taxels_per_hand ?? -1),
  hours: (a, b) => (b.scale.hours ?? -1) - (a.scale.hours ?? -1),
  name: (a, b) => a.name.localeCompare(b.name),
};

let D = [], META = {}, S = {q: '', f: {}, y0: null, y1: null, view: 'cards', sort: 'year', d: null};

/* ---------- coverage glyph: palm side of a right hand; filled regions carry taxels ---------- */
function glyph(cov, label) {
  const on = r => cov.includes(r) ? ' on' : '';
  const F = [[13.6, 8.5, 12.5], [19.6, 6, 15], [25.6, 7.5, 13.5], [31.4, 11, 10]]; // x, top, length of each finger
  const o = [];
  F.forEach(([x, y, l]) => {
    const tip = l * .3;
    o.push(`<rect class="r${on('tip')}" x="${x}" y="${y}" width="4.6" height="${tip.toFixed(2)}" rx="2"/>`,
      `<rect class="r${on('phalanx')}" x="${x}" y="${(y + tip + .6).toFixed(2)}" width="4.6" height="${(l - tip - .6).toFixed(2)}" rx="1"/>`);
  });
  const TH = 'rotate(-28 13 33)';
  o.push(`<g transform="${TH}"><rect class="r${on('tip')}" x="7.6" y="22" width="4.8" height="4.4" rx="2"/><rect class="r${on('phalanx')}" x="7.6" y="27" width="4.8" height="7" rx="1"/></g>`,
    `<rect class="r${on('palm')}" x="13.6" y="22.6" width="22.4" height="17" rx="3"/>`);
  return `<svg class="glyph" viewBox="5 4 33 37" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title>${o.join('')}</svg>`;
}
const covText = c => c.length === 3 ? 'Fingers and palm' : c.map(r => LABEL.coverage[r]).join(' + ') || 'Coverage not stated';
const sensorLine = d => {
  const s = d.sensor, n = s.taxels_per_hand;
  return n != null ? `${n.toLocaleString('en-US')} taxels per hand` : s.sensors_per_hand ? `${s.sensors_per_hand} sensors per hand` : 'Taxel count not stated';
};

/* ---------- state <-> hash ---------- */
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  S.q = p.get('q') || ''; S.view = p.get('view') === 'table' ? 'table' : 'cards'; S.sort = SORTS[p.get('sort')] ? p.get('sort') : 'year';
  S.d = p.get('d'); S.y0 = +p.get('from') || null; S.y1 = +p.get('to') || null; S.f = {};
  for (const F of FACETS) {const v = p.get(F.key); if (v) S.f[F.key] = new Set(v.split(','))}
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  for (const [k, v] of Object.entries(S.f)) if (v.size) p.set(k, [...v].join(','));
  if (S.y0) p.set('from', S.y0); if (S.y1) p.set('to', S.y1);
  if (S.view !== 'cards') p.set('view', S.view); if (S.sort !== 'year') p.set('sort', S.sort);
  if (S.d) p.set('d', S.d);
  const h = p.toString().replace(/%2C/g, ',');
  history.replaceState(null, '', h ? `#${h}` : location.pathname + location.search);
}

/* ---------- filtering ---------- */
const textOf = d => [d.name, d.title, d.authors, d.summary, d.hand, d.venue].join(' ').toLowerCase();
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
  if (d.viewer) out.push(`<a class="play" href="viewer/#rec=${esc(d.viewer)}">▶ Play samples</a>`);
  return out.join('');
};
const thumb = d => d.thumb ? `<img src="${esc(d.thumb)}" alt="" loading="lazy">` : glyph(d.sensor.coverage, covText(d.sensor.coverage));

function cards(list) {
  return `<div class="grid">${list.map(d => `<article class="card" data-id="${d.id}" tabindex="0" aria-label="${esc(d.name)}">
    <div class="thumb">${thumb(d)}<span class="badge av-${d.availability}">${LABEL.availability[d.availability]}</span></div>
    <div class="body">
      <div class="ttl"><h3>${esc(d.name)}</h3><span>${d.year}</span></div>
      <div class="src">${esc(d.venue)} · ${esc(d.authors)}</div>
      <p class="desc">${esc(d.summary)}</p>
      <div class="spec">${glyph(d.sensor.coverage, covText(d.sensor.coverage))}<div><b>${sensorLine(d)}</b><span>${covText(d.sensor.coverage)} · ${LABEL.embodiment[d.embodiment]}${d.bimanual ? ', bimanual' : ''}</span></div></div>
      <div class="tags">${d.scale.hours ? `<span class="tag dim">${fmt(d.scale.hours)} h</span>` : ''}${d.scale.episodes ? `<span class="tag dim">${fmt(d.scale.episodes)} episodes</span>` : ''}${d.modalities.map(m => `<span class="tag">${LABEL.modality[m]}</span>`).join('')}</div>
    </div>
    <div class="links">${linkRow(d)}</div></article>`).join('')}</div>`;
}

function table(list) {
  const row = d => `<tr data-id="${d.id}">
    <td><b>${esc(d.name)}</b><span class="sub">${esc(d.venue)}</span></td>
    <td>${LABEL.embodiment[d.embodiment]}<span class="sub">${d.bimanual ? 'Bimanual' : 'Single hand'}</span></td>
    <td><span class="cov">${glyph(d.sensor.coverage, covText(d.sensor.coverage))}${covText(d.sensor.coverage)}</span></td>
    <td class="num">${d.sensor.taxels_per_hand != null ? d.sensor.taxels_per_hand.toLocaleString('en-US') : d.sensor.sensors_per_hand ? `${d.sensor.sensors_per_hand} sensors` : '–'}</td>
    <td>${LABEL.type[d.sensor.type]}</td>
    <td>${d.modalities.map(m => LABEL.modality[m]).join(', ') || '–'}</td>
    <td class="num">${d.scale.hours ? `${fmt(d.scale.hours)} h` : '–'}</td>
    <td class="num">${d.scale.episodes ? fmt(d.scale.episodes) : '–'}</td>
    <td><span class="av-${d.availability}">${LABEL.availability[d.availability]}</span><span class="sub">${esc(d.license)}</span></td></tr>`;
  return `<div class="tablewrap"><table><thead><tr><th data-s="name">Dataset</th><th>Hand</th><th>Coverage</th><th data-s="taxels">Taxels / hand</th><th>Sensor</th><th>Also recorded</th><th data-s="hours">Hours</th><th>Episodes</th><th>Access</th></tr></thead>
    <tbody>${list.map(row).join('')}</tbody></table></div>`;
}

function render() {
  const list = D.filter(d => passes(d)).sort(SORTS[S.sort]);
  $('count').textContent = `${list.length} of ${D.length} datasets`;
  $('out').innerHTML = !list.length ? `<p class="empty">No dataset matches these filters.</p>` : S.view === 'table' ? table(list) : cards(list);
  $('out').querySelectorAll('[data-id]').forEach(el => {
    el.onclick = e => {if (!e.target.closest('a')) openDetail(el.dataset.id)};
    el.onkeydown = e => {if (e.key === 'Enter') openDetail(el.dataset.id)};
  });
  $('out').querySelectorAll('th[data-s]').forEach(th => th.onclick = () => {S.sort = th.dataset.s; $('sort').value = S.sort; update()});
  document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
}

function openDetail(id) {
  const d = D.find(x => x.id === id); if (!d) return;
  S.d = id; writeHash();
  const s = d.sensor, kv = [
    ['Hand', `${LABEL.embodiment[d.embodiment]} · ${esc(d.hand)}`], ['Hands', d.bimanual ? 'Bimanual' : 'Single hand'],
    ['Tactile coverage', covText(s.coverage)], ['Sensor', `${LABEL.type[s.type]}${s.rate_hz ? ` · ${esc(s.rate_hz)} Hz` : ''}`],
    ['Density', sensorLine(d)], ['Sensor notes', esc(s.note || '')],
    ['Also recorded', d.modalities.map(m => LABEL.modality[m]).join(', ') || 'Tactile only'], ['Scale', esc(d.scale.text)],
    ['Access', `${LABEL.availability[d.availability]} · ${esc(d.access)}`], ['License', esc(d.license)],
  ].filter(([, v]) => v);
  $('dlg').innerHTML = `<div class="dl"><header>${glyph(s.coverage, covText(s.coverage)).replace('class="glyph"', 'class="glyph" style="width:44px;flex:none"')}
    <div><h2 id="dlgTitle">${esc(d.name)}</h2><p>${esc(d.title)}</p><p>${esc(d.authors)} · ${esc(d.venue)}</p></div><button class="x" aria-label="Close">×</button></header>
    <div class="scroll">${d.thumb ? `<img class="hero" src="${esc(d.thumb)}" alt="${esc(d.name)} overview figure">` : ''}
    <p>${esc(d.summary)}</p>
    ${d.caveats.length ? `<div class="warn"><ul>${d.caveats.map(c => `<li>${esc(c)}</li>`).join('')}</ul></div>` : ''}
    <h4>Specification</h4><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
    <div class="links">${d.viewer ? `<a class="btn" href="viewer/#rec=${esc(d.viewer)}">▶ Play samples in the viewer</a>` : ''}${linkRow(d).replace(/<a class="play"[^]*?<\/a>/, '')}</div>
    ${d.image_credit ? `<p class="src" style="margin-top:12px">Figure: ${esc(d.image_credit)}</p>` : ''}</div></div>`;
  $('dlg').querySelector('.x').onclick = () => $('dlg').close();
  if (!$('dlg').open) $('dlg').showModal();
}

function update() {writeHash(); renderFacets(); renderChips(); render()}

async function main() {
  const j = await (await fetch('data/datasets.json')).json();
  D = j.datasets; META = j.metadata;
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
