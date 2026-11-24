// Taxel Atlas, hardware tab: facets, sorts, list rows, Compare table, Datasets map and the focus pane over data/hardware.json.
const HWTAB = (() => {
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
].map(F => ({...F, labels: HL[F.key]}));
const SORTS = {
  kind: (a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || b.datasets.length - a.datasets.length || a.name.localeCompare(b.name),
  used: (a, b) => b.datasets.length - a.datasets.length || a.name.localeCompare(b.name),
  year: (a, b) => (b.year ?? 0) - (a.year ?? 0) || a.name.localeCompare(b.name),
  taxels: (a, b) => (b.taxels ?? -1) - (a.taxels ?? -1),
  name: (a, b) => a.name.localeCompare(b.name),
};
const dsOf = h => h.datasets.filter(x => DB.ds[x.id]);
const textOf = h => [h.name, zhText(h), h.maker, h.kind, HL.region[h.region], h.principle, ...(h.specs || []), ...dsOf(h).map(x => DB.ds[x.id].name)].join(' ').toLowerCase();

const covText = c => !c || !c.length ? '' : c.length === 3 ? 'Fingers and palm' : c.map(r => HL.coverage[r]).join(' + ');
// rows show the count with a short qualifier ("per hand"); the pane shows the full note
const density = (h, full) => h.taxels == null ? (h.kind === 'tracker' ? 'No touch sensing' : 'Taxel count not stated')
  : `${h.taxels.toLocaleString('en-US')} taxels${h.taxels_note && (full || h.taxels_note.length <= 24) ? ` ${full ? '· ' : ''}${h.taxels_note}` : ''}`;
const specLine = h => [covText(h.coverage), h.principle && h.principle !== 'unspecified' ? HL.principle[h.principle].toLowerCase() : '', h.rate_hz ? `${h.rate_hz} Hz` : '', h.dof ? `${h.dof} DoF` : ''].filter(Boolean).join(' · ');
const avBadge = (h, cls) => `<span class="${cls} av-${h.availability}" title="${esc(AV_TEXT[h.availability])}">${HL.availability[h.availability]}</span>`;
const linkRow = h => {
  const L = h.links || {}, out = [];
  for (const [k, t] of [['product', 'Product'], ['project', 'Project'], ['paper', 'Paper'], ['code', 'Code']]) if (L[k]) out.push(`<a href="${esc(L[k])}" target="_blank" rel="noopener">${t}</a>`);
  return out.join('');
};
const metaLine = h => [h.maker, HL.region[h.region], h.price].filter(Boolean).map(esc).join(' · ');
const glyphOf = h => glyph(h.coverage || [], covText(h.coverage) || 'coverage not stated');
// models in data/models.json that use any dataset recorded with this device
const modelsOf = h => {const ids = new Set(dsOf(h).map(x => x.id)); return DB.M.filter(m => m.uses.some(u => ids.has(u.id)))};

/* ---------- list rows ---------- */
function groups(list, sort) {
  if (sort !== 'kind') return null;
  return KINDS.map(k => ({head: `<span>${HL.kindPlural[k]}</span>`, title: KIND_TEXT[k], items: list.filter(h => h.kind === k)}));
}
function row(h, sort) {
  const n = dsOf(h).length;
  return {img: h.thumb ? `<img src="${esc(h.thumb)}" alt="" loading="lazy">` : glyphOf(h), name: h.name, zh: h.zh?.name, year: h.year ?? '', tag: newTag('hardware', h.id),
    meta: [sort === 'kind' ? '' : esc(HL.kind[h.kind]), avBadge(h, ''), esc(h.taxels != null ? `${fmt(h.taxels)} taxels` : h.kind === 'tracker' ? 'no touch' : 'taxels not stated'),
      n ? `${n} ${n === 1 ? 'dataset' : 'datasets'}` : ''].filter(Boolean).join(' · '),
    glyph: glyphOf(h)};
}

/* ---------- Compare table ---------- */
function table(list) {
  const dsLink = x => {const d = DB.ds[x.id]; return d ? `<a href="${focusHref('d', x.id)}" title="${esc(`${d.name} (${x.role})`)}">${esc(d.name)}</a>` : ''};
  const row = h => `<tr data-id="${h.id}" tabindex="0">
    <td><b>${esc(h.name)}</b>${h.zh?.name ? `<span class="sub" lang="zh-CN">${esc(h.zh.name)}</span>` : ''}<span class="sub">${esc(h.maker)}</span></td>
    <td>${HL.kind[h.kind]}<span class="sub">${avBadge(h, 'av')}</span></td>
    <td>${esc(HL.region[h.region] || '–')}<span class="sub">${h.year ?? ''}</span></td>
    <td>${esc(HL.principle[h.principle || 'unspecified'])}</td>
    <td class="num">${h.taxels != null ? h.taxels.toLocaleString('en-US') : '–'}<span class="sub">${esc(h.taxels_note || '')}</span></td>
    <td><span class="cov">${glyphOf(h)}${esc(covText(h.coverage) || '–')}</span></td>
    <td class="num">${h.rate_hz ?? '–'}</td>
    <td>${esc(h.price || '–')}</td>
    <td>${h.datasets.length ? `<div class="used">${h.datasets.map(dsLink).join('')}</div>` : '–'}</td></tr>`;
  return `<div class="tablewrap"><table><thead><tr><th data-s="name">Device</th><th data-s="kind">Kind · availability</th><th data-s="year">Region · year</th><th>Principle</th>
    <th data-s="taxels">Taxels</th><th>Coverage</th><th>Rate (Hz)</th><th>Price</th><th data-s="used">Datasets</th></tr></thead><tbody>${list.map(row).join('')}</tbody></table></div>`;
}

/* ---------- datasets map: hardware on the left, datasets on the right, one curve per use ---------- */
function map(list) {
  let hw = list.filter(h => dsOf(h).length).sort(SORTS.kind);
  // order datasets by first-seen hardware, then each kind's devices by the mean rank of their datasets (fewer crossings)
  const first = [];
  for (const h of hw) for (const x of dsOf(h)) if (!first.includes(x.id)) first.push(x.id);
  const mean = h => dsOf(h).reduce((a, x) => a + first.indexOf(x.id), 0) / dsOf(h).length;
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
  for (const h of hw) for (const x of dsOf(h)) (ds[x.id] ||= []).push(hy.get(h.id));
  const ids = Object.keys(ds).sort((a, b) => ds[a].reduce((s, v) => s + v, 0) / ds[a].length - ds[b].reduce((s, v) => s + v, 0) / ds[b].length);
  const H2 = Math.max(y, T + 20 + ids.length * RH) + 10, step = (H2 - T - 30) / Math.max(1, ids.length);
  const dy = new Map(ids.map((id, i) => [id, T + 20 + i * step]));
  const o = [`<text class="k" x="${xl}" y="${T - 24}" text-anchor="end">HARDWARE</text><text class="k" x="${xr}" y="${T - 24}">DATASET</text>`];
  for (const [k, yy] of heads) o.push(`<text class="k" x="${xl}" y="${yy}" text-anchor="end">${HL.kindPlural[k].toUpperCase()}</text>`);
  for (const h of hw) for (const x of dsOf(h)) {
    const y1 = hy.get(h.id), y2 = dy.get(x.id), m = (xl + xr) / 2;
    o.push(`<path class="${ROLE_CLS[x.role] || 'rl-track'}" data-h="${h.id}" data-d="${x.id}" d="M${xl + 8} ${y1 - 4}C${m} ${y1 - 4} ${m} ${y2 - 4} ${xr - 8} ${y2 - 4}"><title>${esc(`${h.name} → ${DB.ds[x.id].name}: ${x.role}`)}</title></path>`);
  }
  for (const h of hw) o.push(`<g data-n="h:${h.id}"><circle class="${ROLE_CLS[dsOf(h)[0].role] || 'rl-track'}" cx="${xl + 6}" cy="${hy.get(h.id) - 4}" r="4.5"/>
    <a href="${focusHref('h', h.id)}"><text class="n" x="${xl - 4}" y="${hy.get(h.id)}" text-anchor="end">${esc(short(h.name))}</text></a></g>`);
  for (const id of ids) o.push(`<g data-n="d:${id}"><circle class="rl-track" cx="${xr - 6}" cy="${dy.get(id) - 4}" r="4.5"/>
    <a href="${focusHref('d', id)}"><text class="n" x="${xr + 4}" y="${dy.get(id)}">${esc(DB.ds[id].name)}</text></a></g>`);
  const legend = Object.entries(ROLE_CLS).map(([r, c]) => `<span><i style="background:var(${ROLE_VAR[c]})"></i>${r}</span>`).join('');
  return `<div class="chartwrap map"><div class="chead"><b>Which hardware recorded which dataset</b><span class="legend">${legend}</span></div>
    <svg class="chart" id="mapsvg" viewBox="0 0 ${W} ${H2}" role="img" aria-label="Links from hardware to the datasets recorded with it">${o.join('')}</svg>
    <p class="missing">Hover a device or dataset to highlight its links; click one to open it. Devices not used by any catalog dataset are in the list.</p></div>`;
}
function wireMap(root) {
  const svg = root.querySelector('#mapsvg'); if (!svg) return;
  const hi = (kind, id) => {
    svg.classList.toggle('dim', !!id);
    svg.querySelectorAll('path').forEach(p => p.classList.toggle('on', !!id && p.dataset[kind] === id));
  };
  svg.querySelectorAll('g[data-n]').forEach(g => {
    const [k, id] = g.dataset.n.split(':');
    g.onmouseenter = () => hi(k, id); g.onmouseleave = () => hi(k, null);
  });
}

/* ---------- focus pane ---------- */
const kvs = rows => `<dl class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
function pane(h) {
  const ds = dsOf(h), models = modelsOf(h);
  const facts = [['Touch', esc(density(h)), esc(specLine(h))], ['Availability', avBadge(h, ''), esc(AV_TEXT[h.availability])],
    ['Price', esc(h.price || ''), ''], ['First shown', h.year ?? '', '']];
  return `<header class="ph">${glyphOf(h)}
    <div><h2 id="paneTitle">${esc(h.name)}${h.year ? ` <span class="yr">${h.year}</span>` : ''}</h2>${zhHead(h, 'Name')}<p class="pt">${esc(HL.kind[h.kind])}</p><p class="pm">${metaLine(h)}</p></div></header>
    ${linkRow(h) ? `<div class="pact">${linkRow(h)}</div>` : ''}
    ${newTag('hardware', h.id) ? `<div class="tags">${newTag('hardware', h.id)}</div>` : ''}
    <div class="lead">${h.thumb ? `<img class="hero" src="${esc(h.thumb)}" alt="${esc(h.name)}">` : ''}
      <dl class="pfacts">${facts.map(([k, v, sub]) => `<div><dt>${k}</dt><dd>${v || '<i>not stated</i>'}${sub ? `<span class="sub">${sub}</span>` : ''}</dd></div>`).join('')}</dl></div>
    <section><h3>Datasets recorded with it <span>${ds.length}</span></h3>${ds.length ? `<div class="lks">${ds.map(x => dsTile(DB.ds[x.id], x.role)).join('')}</div>`
      : '<p class="src">None in the catalog yet.</p>'}</section>
    ${ds.length ? `<section><h3>Models trained on these datasets <span>${models.length}</span></h3>${models.length ? `<div class="lks">${models.map(m => modelTile(m,
      `on ${m.uses.filter(u => ds.some(x => x.id === u.id)).map(u => DB.ds[u.id]?.name).filter(Boolean).join(', ')}`)).join('')}</div>`
      : '<p class="src">No model in the catalog uses these datasets yet.</p>'}</section>` : ''}
    <section><h3>Touch sensing</h3>${kvs([['Principle', esc(HL.principle[h.principle || 'unspecified'])],
      ['Density', esc(density(h, true))], ['Coverage', esc(covText(h.coverage))], ['Rate', h.rate_hz ? `${h.rate_hz} Hz` : ''], ['Joints', h.dof ? `${h.dof} DoF` : '']])}</section>
    ${(h.specs || []).length ? `<section><h3>Specs</h3><ul class="specs">${h.specs.map(x => `<li>${esc(x)}</li>`).join('')}</ul></section>` : ''}
    ${(h.sources || []).length ? `<details class="srcs"><summary>Sources${(h.unconfirmed || []).length ? ' and open points' : ''}</summary>
      ${(h.unconfirmed || []).length ? `<p>Derived or not confirmed:</p><ul>${h.unconfirmed.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p>Read:</p>` : ''}
      <ul>${h.sources.map(x => `<li><a href="${esc(x)}" target="_blank" rel="noopener">${esc(x)}</a></li>`).join('')}</ul></details>` : ''}
    ${h.image_page ? `<p class="src credit">Photo: <a href="${esc(h.image_page)}" target="_blank" rel="noopener">${esc(new URL(h.image_page).hostname)}</a></p>` : ''}`;
}
// a device as a linked tile in a dataset's pane
const tile = (h, sub) => ({img: h.thumb ? `<img src="${esc(h.thumb)}" alt="">` : glyphOf(h), name: h.name, sub: esc(sub)});

return {key: 'hardware', fk: 'h', target: 'hardware', noun: ['device', 'devices'], items: () => DB.HW, byId: id => DB.hw[id],
  FACETS, SORTS, defaultSort: 'kind', years: false,
  sortOptions: [['kind', 'Kind'], ['used', 'Datasets using it'], ['year', 'Newest'], ['taxels', 'Taxels'], ['name', 'Name']],
  views: [['list', 'List'], ['table', 'Compare'], ['map', 'Datasets map']], extra: {map}, wire: wireMap,
  search: 'Search name, maker, spec…', textOf, groups, row, table, pane, tile, title: h => h.name,
  summary: () => `${DB.HW.length} devices · ${DB.HW.filter(h => dsOf(h).length).length} used in catalog datasets · updated ${DB.metaH.last_updated}`, scope: () => DB.metaH.scope,
  contrib: ['Suggest hardware', `${REPO}/issues/new?title=${encodeURIComponent('Hardware: ')}`],
  footer: 'Specs are as the makers or authors state them; prices and availability change quickly, so confirm with the vendor. Photos belong to their makers and link to their source.',
  empty: 'No device matches these filters.'};
})();
