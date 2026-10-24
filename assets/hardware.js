// Taxel Atlas hardware page: faceted list over data/hardware.json, linked both ways to data/datasets.json.
const HL = {
  kind: {glove: 'Tactile glove', robot_hand: 'Tactile robot hand', sensor: 'Add-on tactile sensor', tracker: 'Hand-tracking glove'},
  kindPlural: {glove: 'Tactile gloves', robot_hand: 'Tactile robot hands', sensor: 'Add-on tactile sensors', tracker: 'Hand-tracking gloves (no touch)'},
  availability: {commercial: 'Commercial', open_hardware: 'Open hardware', announced: 'Announced', research: 'Research only', discontinued: 'Discontinued'},
  region: {CN: 'China', US: 'United States', EU: 'Europe', JP: 'Japan', KR: 'Korea', SG: 'Singapore', other: 'Other'},
  principle: {piezoresistive: 'Piezoresistive', capacitive: 'Capacitive', piezoelectric: 'Piezoelectric', magnetic: 'Magnetic (Hall)', optical: 'Optical (camera-based)',
    barometric: 'Barometric', resistive: 'Resistive (FSR)', unspecified: 'Not specified'},
  coverage: {tip: 'Fingertips', phalanx: 'Finger segments', palm: 'Palm'},
  used: {yes: 'Used in a catalog dataset', no: 'Not in a catalog dataset yet'},
};
const KIND_TEXT = {glove: 'Worn by a person to record touch while they manipulate objects.',
  robot_hand: 'Dexterous robot hands with touch sensing built in.',
  sensor: 'Sensors and skins fitted to a robot hand, gripper or glove.',
  tracker: 'Finger-pose gloves that catalog datasets paired with a tactile glove.'};
const AV_TEXT = {commercial: 'Sold or quoted by a vendor', open_hardware: 'Design files or build guide published',
  announced: 'Shown or pre-sold, not shipping yet', research: 'Lab-built; no public design, not sold', discontinued: 'No longer sold'};
const ROLE_CLS = {'tactile glove': 'rl-glove', 'robot hand': 'rl-hand', 'tactile sensor': 'rl-sensor', 'hand tracking': 'rl-track'};
const ROLE_VAR = {'rl-glove': '--accent', 'rl-hand': '--c-robot', 'rl-sensor': '--c-both', 'rl-track': '--muted'};
const KINDS = Object.keys(HL.kind);

const FACETS = [
  {key: 'kind', title: 'Kind', get: h => [h.kind]},
  {key: 'availability', title: 'Availability', hint: 'Can you get one today', get: h => [h.availability]},
  {key: 'used', title: 'Datasets', get: h => [h.datasets.length ? 'yes' : 'no']},
  {key: 'principle', title: 'Sensing principle', get: h => [h.principle || 'unspecified']},
  {key: 'coverage', title: 'Coverage', all: true, hint: 'Ticked regions must all be sensed', get: h => h.coverage || []},
  {key: 'region', title: 'Maker region', get: h => [h.region || 'other']},
];
const SORTS = {
  kind: (a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || b.datasets.length - a.datasets.length || a.name.localeCompare(b.name),
  used: (a, b) => b.datasets.length - a.datasets.length || a.name.localeCompare(b.name),
  year: (a, b) => (b.year ?? 0) - (a.year ?? 0) || a.name.localeCompare(b.name),
  taxels: (a, b) => (b.taxels ?? -1) - (a.taxels ?? -1),
  name: (a, b) => a.name.localeCompare(b.name),
};

let H = [], DS = {}, META = {}, S = {q: '', f: {}, view: 'cards', sort: 'kind', h: null};

/* ---------- state <-> hash ---------- */
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  S.q = p.get('q') || ''; S.view = ['table', 'map'].includes(p.get('view')) ? p.get('view') : 'cards';
  S.sort = SORTS[p.get('sort')] ? p.get('sort') : 'kind'; S.h = p.get('h'); S.f = {};
  for (const F of FACETS) {const v = p.get(F.key); if (v) S.f[F.key] = new Set(v.split(','))}
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  for (const [k, v] of Object.entries(S.f)) if (v.size) p.set(k, [...v].join(','));
  if (S.view !== 'cards') p.set('view', S.view); if (S.sort !== 'kind') p.set('sort', S.sort);
  if (S.h) p.set('h', S.h);
  const s = p.toString().replace(/%2C/g, ',');
  history.replaceState(null, '', s ? `#${s}` : location.pathname + location.search);
}

/* ---------- filtering ---------- */
const textOf = h => [h.name, zhText(h), h.maker, h.kind, HL.region[h.region], h.principle, ...(h.specs || []), ...h.datasets.map(x => DS[x.id]?.name)].join(' ').toLowerCase();
function passes(h, skip) {
  if (S.q && !S.q.toLowerCase().split(/\s+/).every(w => textOf(h).includes(w))) return false;
  for (const F of FACETS) {
    if (F.key === skip) continue;
    const sel = S.f[F.key]; if (!sel || !sel.size) continue;
    const vals = F.get(h);
    if (F.all ? ![...sel].every(v => vals.includes(v)) : !vals.some(v => sel.has(v))) return false;
  }
  return true;
}
function renderFacets() {
  $('facets').innerHTML = `<p class="intro">${esc(META.scope || '')}</p>` + FACETS.map(F => {
    const sel = S.f[F.key] || new Set(), pool = H.filter(h => passes(h, F.all ? null : F.key));
    const vals = Object.keys(HL[F.key]).filter(v => H.some(h => F.get(h).includes(v)));
    return `<fieldset class="fs"><legend>${F.title}</legend>${F.hint ? `<p class="hint">${F.hint}</p>` : ''}${vals.map(v => {
      const n = pool.filter(h => F.get(h).includes(v)).length;
      return `<label class="opt" data-zero="${!n && !sel.has(v)}"><input type="checkbox" data-f="${F.key}" value="${v}"${sel.has(v) ? ' checked' : ''}>${HL[F.key][v]}<span class="n">${n}</span></label>`;
    }).join('')}</fieldset>`;
  }).join('') + `<button class="clear" id="clear">Clear filters</button>`;
  $('facets').querySelectorAll('input[data-f]').forEach(i => i.onchange = () => {
    const s = S.f[i.dataset.f] ||= new Set(); i.checked ? s.add(i.value) : s.delete(i.value); update();
  });
  $('clear').onclick = () => {S.f = {}; S.q = ''; $('q').value = ''; update()};
}
function renderChips() {
  const c = [];
  for (const [k, v] of Object.entries(S.f)) for (const x of v) c.push(`<button data-k="${k}" data-v="${x}">${HL[k][x]}</button>`);
  $('chips').innerHTML = c.join('');
  $('chips').querySelectorAll('button').forEach(b => b.onclick = () => {S.f[b.dataset.k].delete(b.dataset.v); update()});
}

/* ---------- pieces ---------- */
const covText = c => !c || !c.length ? '' : c.length === 3 ? 'Fingers and palm' : c.map(r => HL.coverage[r]).join(' + ');
// cards show the count with a short qualifier ("per hand"); the dialog shows the full note
const density = (h, full) => h.taxels == null ? (h.kind === 'tracker' ? 'No touch sensing' : 'Taxel count not stated')
  : `${h.taxels.toLocaleString('en-US')} taxels${h.taxels_note && (full || h.taxels_note.length <= 24) ? ` ${full ? '· ' : ''}${h.taxels_note}` : ''}`;
const specLine = h => [covText(h.coverage), h.principle && h.principle !== 'unspecified' ? HL.principle[h.principle].toLowerCase() : '', h.rate_hz ? `${h.rate_hz} Hz` : '', h.dof ? `${h.dof} DoF` : ''].filter(Boolean).join(' · ');
const avBadge = (h, cls) => `<span class="${cls} av-${h.availability}" title="${esc(AV_TEXT[h.availability])}">${HL.availability[h.availability]}</span>`;
const dsLink = x => {const d = DS[x.id]; return d ? `<a href="./#d=${esc(x.id)}" title="${esc(`${d.name} (${x.role})`)}">${esc(d.name)}</a>` : ''};
const used = h => h.datasets.length ? `<div class="used">Used in ${h.datasets.map(dsLink).join('')}</div>` : '';
const linkRow = h => {
  const L = h.links || {}, out = [];
  for (const [k, t] of [['product', 'Product'], ['project', 'Project'], ['paper', 'Paper'], ['code', 'Code']]) if (L[k]) out.push(`<a href="${esc(L[k])}" target="_blank" rel="noopener">${t}</a>`);
  return out.join('');
};
const photo = h => h.thumb ? `<img src="${esc(h.thumb)}" alt="${esc(h.name)}" loading="lazy">` : glyph(h.coverage || [], covText(h.coverage) || h.name);
const metaLine = h => [h.maker, HL.region[h.region], h.price].filter(Boolean).map(esc).join(' · ');

function cardGrid(list) {
  return `<div class="grid">${list.map(h => `<article class="card hw" data-id="${h.id}" tabindex="0" aria-label="${esc(h.name)}">
    <div class="thumb">${photo(h)}</div>
    <div class="body">
      <div class="ttl"><h3>${esc(h.name)}</h3><span>${h.year ?? ''}</span></div>
      ${zhLine(h)}<div class="src">${metaLine(h)}</div>
      <div class="tags">${avBadge(h, 'tag av')}</div>
      <div class="spec">${glyph(h.coverage || [], covText(h.coverage) || 'coverage not stated')}<div><b>${esc(density(h))}</b><span>${esc(specLine(h) || HL.kind[h.kind])}</span></div></div>
      ${(h.specs || []).length ? `<ul class="specs">${h.specs.slice(0, 4).map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      ${used(h)}
    </div>
    <div class="links">${linkRow(h)}</div></article>`).join('')}</div>`;
}
function cards(list) {
  if (S.sort !== 'kind') return cardGrid(list);
  return KINDS.map(k => [k, list.filter(h => h.kind === k)]).map(([k, g]) => g.length ? `<section class="rgroup"><h2><span class="rh">${HL.kindPlural[k]}</span>
    <span>${esc(KIND_TEXT[k])}</span><small>${g.length}</small></h2>${cardGrid(g)}</section>` : '').join('');
}
function table(list) {
  const row = h => `<tr data-id="${h.id}">
    <td><b>${esc(h.name)}</b>${h.zh?.name ? `<span class="sub" lang="zh-CN">${esc(h.zh.name)}</span>` : ''}<span class="sub">${esc(h.maker)}</span></td>
    <td>${HL.kind[h.kind]}<span class="sub">${avBadge(h, 'av')}</span></td>
    <td>${esc(HL.region[h.region] || '–')}<span class="sub">${h.year ?? ''}</span></td>
    <td>${esc(HL.principle[h.principle || 'unspecified'])}</td>
    <td class="num">${h.taxels != null ? h.taxels.toLocaleString('en-US') : '–'}<span class="sub">${esc(h.taxels_note || '')}</span></td>
    <td><span class="cov">${glyph(h.coverage || [], covText(h.coverage) || 'not stated')}${esc(covText(h.coverage) || '–')}</span></td>
    <td class="num">${h.rate_hz ?? '–'}</td>
    <td>${esc(h.price || '–')}</td>
    <td>${h.datasets.length ? `<div class="used">${h.datasets.map(dsLink).join('')}</div>` : '–'}</td></tr>`;
  return `<div class="tablewrap"><table><thead><tr><th data-s="name">Device</th><th data-s="kind">Kind · availability</th><th data-s="year">Region · year</th><th>Principle</th>
    <th data-s="taxels">Taxels</th><th>Coverage</th><th>Rate (Hz)</th><th>Price</th><th data-s="used">Datasets</th></tr></thead><tbody>${list.map(row).join('')}</tbody></table></div>`;
}

/* ---------- datasets map: hardware on the left, datasets on the right, one curve per use ---------- */
function map(list) {
  let hw = list.filter(h => h.datasets.length).sort(SORTS.kind);
  // order datasets by first-seen hardware, then each kind's devices by the mean rank of their datasets (fewer crossings)
  const first = [];
  for (const h of hw) for (const x of h.datasets) if (DS[x.id] && !first.includes(x.id)) first.push(x.id);
  const mean = h => h.datasets.reduce((a, x) => a + first.indexOf(x.id), 0) / h.datasets.length;
  hw = KINDS.flatMap(k => hw.filter(h => h.kind === k).sort((a, b) => mean(a) - mean(b)));
  const short = t => t.length > 38 ? t.slice(0, 36) + '…' : t;
  if (!hw.length) return `<p class="empty">None of the matching devices is used by a catalog dataset.</p>`;
  const RH = 24, GAP = 26, T = 44, W = 940, xl = 330, xr = 660;
  const hy = new Map(); let y = T;
  const heads = [];
  for (const k of KINDS) {
    const g = hw.filter(h => h.kind === k); if (!g.length) continue;
    heads.push([k, y]); y += 20;
    for (const h of g) {hy.set(h.id, y); y += RH}
    y += GAP - RH / 2;
  }
  // datasets ordered by the mean height of their hardware, to keep curves short
  const ds = {};
  for (const h of hw) for (const x of h.datasets) if (DS[x.id]) (ds[x.id] ||= []).push(hy.get(h.id));
  const ids = Object.keys(ds).sort((a, b) => ds[a].reduce((s, v) => s + v, 0) / ds[a].length - ds[b].reduce((s, v) => s + v, 0) / ds[b].length);
  const H2 = Math.max(y, T + 20 + ids.length * RH) + 10, step = (H2 - T - 30) / Math.max(1, ids.length);
  const dy = new Map(ids.map((id, i) => [id, T + 20 + i * step]));
  const o = [`<text class="k" x="${xl}" y="${T - 24}" text-anchor="end">HARDWARE</text><text class="k" x="${xr}" y="${T - 24}">DATASET</text>`];
  for (const [k, yy] of heads) o.push(`<text class="k" x="${xl}" y="${yy}" text-anchor="end">${HL.kindPlural[k].toUpperCase()}</text>`);
  for (const h of hw) for (const x of h.datasets) {
    if (!dy.has(x.id)) continue;
    const y1 = hy.get(h.id), y2 = dy.get(x.id), m = (xl + xr) / 2;
    o.push(`<path class="${ROLE_CLS[x.role] || 'rl-track'}" data-h="${h.id}" data-d="${x.id}" d="M${xl + 8} ${y1 - 4}C${m} ${y1 - 4} ${m} ${y2 - 4} ${xr - 8} ${y2 - 4}"><title>${esc(`${h.name} → ${DS[x.id].name}: ${x.role}`)}</title></path>`);
  }
  for (const h of hw) o.push(`<g data-n="h:${h.id}"><circle class="${ROLE_CLS[h.datasets[0].role] || 'rl-track'}" cx="${xl + 6}" cy="${hy.get(h.id) - 4}" r="4.5"/>
    <text class="n" data-id="${h.id}" x="${xl - 4}" y="${hy.get(h.id)}" text-anchor="end">${esc(short(h.name))}</text></g>`);
  for (const id of ids) o.push(`<g data-n="d:${id}"><circle class="rl-track" cx="${xr - 6}" cy="${dy.get(id) - 4}" r="4.5"/>
    <a href="./#d=${esc(id)}"><text class="n" x="${xr + 4}" y="${dy.get(id)}">${esc(DS[id].name)}</text></a></g>`);
  const legend = Object.entries(ROLE_CLS).map(([r, c]) => `<span><i style="background:var(${ROLE_VAR[c]})"></i>${r}</span>`).join('');
  return `<div class="chartwrap map"><div class="chead"><b>Which hardware recorded which dataset</b><span class="legend">${legend}</span></div>
    <svg class="chart" id="mapsvg" viewBox="0 0 ${W} ${H2}" role="img" aria-label="Links from hardware to the datasets recorded with it">${o.join('')}</svg>
    <p class="missing">Hover a device or dataset to highlight its links. Devices not used by any catalog dataset are listed under Cards.</p></div>`;
}
function wireMap() {
  const svg = $('mapsvg'); if (!svg) return;
  const hi = (kind, id) => {
    svg.classList.toggle('dim', !!id);
    svg.querySelectorAll('path').forEach(p => p.classList.toggle('on', !!id && p.dataset[kind] === id));
  };
  svg.querySelectorAll('g[data-n]').forEach(g => {
    const [k, id] = g.dataset.n.split(':');
    g.onmouseenter = () => hi(k, id); g.onmouseleave = () => hi(k, null);
  });
}

function render() {
  const list = H.filter(h => passes(h)).sort(SORTS[S.sort]);
  $('count').textContent = `${list.length} of ${H.length} devices`;
  $('out').innerHTML = !list.length ? `<p class="empty">No device matches these filters.</p>` : S.view === 'table' ? table(list) : S.view === 'map' ? map(list) : cards(list);
  $('out').querySelectorAll('[data-id]').forEach(el => {
    el.onclick = e => {if (!e.target.closest('a[href]')) {e.preventDefault(); openDetail(el.dataset.id)}};
    el.onkeydown = e => {if (e.key === 'Enter' && !e.target.closest('a[href]')) openDetail(el.dataset.id)};
  });
  $('out').querySelectorAll('th[data-s]').forEach(th => th.onclick = () => {S.sort = th.dataset.s; $('sort').value = S.sort; update()});
  document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
  wireMap();
}

function openDetail(id) {
  const h = H.find(x => x.id === id); if (!h) return;
  S.h = id; writeHash();
  const kvs = rows => `<dl class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const dsl = h.datasets.filter(x => DS[x.id]).map(x => {const d = DS[x.id];
    return `<a href="./#d=${esc(x.id)}">${d.thumb ? `<img src="${esc(d.thumb)}" alt="">` : ''}<div><b>${esc(d.name)}</b><span>${esc(x.role)} · ${d.year}${d.viewer ? ' · samples in viewer' : ''}</span></div></a>`}).join('');
  $('dlg').innerHTML = `<div class="dl"><header>${glyph(h.coverage || [], covText(h.coverage) || h.name).replace('class="glyph"', 'class="glyph" style="width:44px;flex:none"')}
    <div><h2 id="dlgTitle">${esc(h.name)}</h2><p>${esc(HL.kind[h.kind])} · ${metaLine(h)}</p>${zhHead(h, 'Name')}</div><button class="x" aria-label="Close"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
    <div class="scroll">${h.thumb ? `<img class="hero hw" src="${esc(h.thumb)}" alt="${esc(h.name)}">` : ''}
    <h4>Touch sensing</h4>${kvs([['Availability', `${avBadge(h, 'av')} · ${esc(AV_TEXT[h.availability])}`], ['Principle', esc(HL.principle[h.principle || 'unspecified'])],
      ['Density', esc(density(h, true))], ['Coverage', esc(covText(h.coverage))], ['Rate', h.rate_hz ? `${h.rate_hz} Hz` : ''], ['Joints', h.dof ? `${h.dof} DoF` : ''],
      ['Price', esc(h.price || '')], ['First shown', h.year ?? '']])}
    ${(h.specs || []).length ? `<h4>Specs</h4><ul class="specs">${h.specs.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    <h4>Datasets recorded with it</h4>${dsl ? `<div class="dsl">${dsl}</div>` : '<p class="src">None in the catalog yet.</p>'}
    <div class="links">${linkRow(h)}</div>
    ${(h.sources || []).length ? `<details class="srcs"><summary>Sources${(h.unconfirmed || []).length ? ' and open points' : ''}</summary>
      ${(h.unconfirmed || []).length ? `<p>Derived or not confirmed:</p><ul>${h.unconfirmed.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p>Read:</p>` : ''}
      <ul>${h.sources.map(x => `<li><a href="${esc(x)}" target="_blank" rel="noopener">${esc(x)}</a></li>`).join('')}</ul></details>` : ''}
    ${h.image_page ? `<p class="src" style="margin-top:12px">Photo: <a href="${esc(h.image_page)}" target="_blank" rel="noopener">${esc(new URL(h.image_page).hostname)}</a></p>` : ''}</div></div>`;
  $('dlg').querySelector('.x').onclick = () => $('dlg').close();
  if (!$('dlg').open) $('dlg').showModal();
}

function update() {writeHash(); renderFacets(); renderChips(); render()}

async function main() {
  const [hj, dj] = await Promise.all(['data/hardware.json', 'data/datasets.json'].map(async u => (await fetch(u)).json()));
  H = hj.hardware; META = hj.metadata; DS = Object.fromEntries(dj.datasets.map(d => [d.id, d]));
  $('sum').textContent = `${H.length} devices · ${H.filter(h => h.datasets.length).length} used in catalog datasets · updated ${META.last_updated}`;
  $('gh').href = REPO; $('contrib').href = `${REPO}/issues/new?title=${encodeURIComponent('Hardware: ')}`;
  readHash(); $('q').value = S.q; $('sort').value = S.sort;
  $('q').oninput = e => {S.q = e.target.value; writeHash(); renderFacets(); renderChips(); render()};
  $('sort').onchange = e => {S.sort = e.target.value; update()};
  document.querySelectorAll('.seg button').forEach(b => b.onclick = () => {S.view = b.dataset.view; update()});
  $('filtbtn').onclick = () => document.body.dataset.filters = document.body.dataset.filters === 'open' ? '' : 'open';
  document.addEventListener('click', e => {if (document.body.dataset.filters === 'open' && !e.target.closest('#facets,#filtbtn')) document.body.dataset.filters = ''});
  $('dlg').addEventListener('close', () => {S.h = null; writeHash()});
  $('dlg').addEventListener('click', e => {if (e.target === $('dlg')) $('dlg').close()});
  update();
  if (S.h) openDetail(S.h);
}
main();
