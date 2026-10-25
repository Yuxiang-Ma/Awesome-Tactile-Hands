// Taxel Atlas models page: faceted list over data/models.json, linked to the datasets each model uses.
const PAGE_TARGET = 'model';
const ML = {
  kind: {world_model: 'World model', policy: 'Policy', representation: 'Tactile representation', estimation: 'Estimation', generation: 'Touch generation', other: 'Other'},
  kindPlural: {world_model: 'World models', policy: 'Policies', representation: 'Tactile representations', estimation: 'Estimation', generation: 'Touch generation', other: 'Other'},
  code: {released: 'Released', announced: 'Announced', not_released: 'Not released'},
  weights: {released: 'Released', announced: 'Announced', not_released: 'Not released'},
  touch: {input: 'Touch as input', output: 'Touch as output', both: 'Touch in and out'},
  embodiment: {human: 'Human hands', robot: 'Robot hands', both: 'Human and robot hands'},
  data: {catalog: 'Uses catalog datasets', own: 'Own data only'},
};
const KIND_TEXT = {world_model: 'Predict future touch, often with video, from actions or context.', policy: 'Output robot actions from touch and other inputs.',
  representation: 'Tactile encoders and pretrained features.', estimation: 'Infer touch or force from other signals, or hand and object state from touch.',
  generation: 'Synthesize touch signals.', other: ''};
const KINDS = Object.keys(ML.kind);
const FACETS = [
  {key: 'kind', title: 'Kind', get: m => [m.kind]},
  {key: 'code', title: 'Code', get: m => [m.release.code]},
  {key: 'weights', title: 'Weights', get: m => [m.release.weights]},
  {key: 'touch', title: 'Touch', hint: 'Whether the model reads touch, predicts it, or both', get: m => [m.touch]},
  {key: 'embodiment', title: 'Touch recorded on', get: m => [m.embodiment]},
  {key: 'data', title: 'Training data', get: m => [m.uses.length ? 'catalog' : 'own']},
];
const REL_ORDER = {released: 2, announced: 1, not_released: 0};
const when = m => {const a = /arxiv\.org\/abs\/(\d{2})(\d{2})\./.exec(m.links.paper || ''); return a ? (2000 + +a[1]) * 100 + +a[2] : m.year * 100};
const SORTS = {
  kind: (a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || when(b) - when(a) || a.name.localeCompare(b.name),
  year: (a, b) => when(b) - when(a) || a.name.localeCompare(b.name),
  released: (a, b) => REL_ORDER[b.release.code] + REL_ORDER[b.release.weights] - REL_ORDER[a.release.code] - REL_ORDER[a.release.weights] || when(b) - when(a),
  uses: (a, b) => b.uses.length - a.uses.length || when(b) - when(a),
  name: (a, b) => a.name.localeCompare(b.name),
};
// one icon per release state, drawn in the page's stroke style
const ST_ICON = {released: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', announced: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.8"/>', not_released: '<path d="M6 12h12"/>'};
const stIcon = s => `<svg class="st" viewBox="0 0 24 24" aria-hidden="true">${ST_ICON[s]}</svg>`;

let M = [], DS = {}, META = {}, S = {q: '', f: {}, view: 'list', sort: 'kind', m: null};

/* ---------- state <-> hash ---------- */
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  S.q = p.get('q') || ''; S.view = p.get('view') === 'table' ? 'table' : 'list';
  S.sort = SORTS[p.get('sort')] ? p.get('sort') : 'kind'; S.m = p.get('m'); S.f = {};
  for (const F of FACETS) {const v = p.get(F.key); if (v) S.f[F.key] = new Set(v.split(','))}
}
function writeHash() {
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  for (const [k, v] of Object.entries(S.f)) if (v.size) p.set(k, [...v].join(','));
  if (S.view !== 'list') p.set('view', S.view); if (S.sort !== 'kind') p.set('sort', S.sort);
  if (S.m) p.set('m', S.m);
  const s = p.toString().replace(/%2C/g, ',');
  history.replaceState(null, '', s ? `#${s}` : location.pathname + location.search);
}

/* ---------- filtering ---------- */
const textOf = m => [m.name, m.title, m.authors, m.venue, m.summary, ML.kind[m.kind], m.own_data, ...m.uses.map(u => DS[u.id]?.name)].join(' ').toLowerCase();
function passes(m, skip) {
  if (S.q && !S.q.toLowerCase().split(/\s+/).every(w => textOf(m).includes(w))) return false;
  for (const F of FACETS) {
    if (F.key === skip) continue;
    const sel = S.f[F.key]; if (!sel || !sel.size) continue;
    if (!F.get(m).some(v => sel.has(v))) return false;
  }
  return true;
}
function renderFacets() {
  $('facets').innerHTML = `<p class="intro">${esc(META.scope || '')}</p>` + FACETS.map(F => {
    const sel = S.f[F.key] || new Set(), pool = M.filter(m => passes(m, F.key));
    const vals = Object.keys(ML[F.key]).filter(v => M.some(m => F.get(m).includes(v)));
    return `<fieldset class="fs"><legend>${F.title}</legend>${F.hint ? `<p class="hint">${F.hint}</p>` : ''}${vals.map(v => {
      const n = pool.filter(m => F.get(m).includes(v)).length;
      return `<label class="opt" data-zero="${!n && !sel.has(v)}"><input type="checkbox" data-f="${F.key}" value="${v}"${sel.has(v) ? ' checked' : ''}>${ML[F.key][v]}<span class="n">${n}</span></label>`;
    }).join('')}</fieldset>`;
  }).join('') + `<button class="clear" id="clear">Clear filters</button>`;
  $('facets').querySelectorAll('input[data-f]').forEach(i => i.onchange = () => {
    const s = S.f[i.dataset.f] ||= new Set(); i.checked ? s.add(i.value) : s.delete(i.value); update();
  });
  $('clear').onclick = () => {S.f = {}; S.q = ''; $('q').value = ''; update()};
}
function renderChips() {
  const c = [];
  for (const [k, v] of Object.entries(S.f)) for (const x of v) c.push(`<button data-k="${k}" data-v="${x}">${k === 'code' || k === 'weights' ? `${k[0].toUpperCase() + k.slice(1)}: ` : ''}${ML[k][x]}</button>`);
  $('chips').innerHTML = c.join('');
  $('chips').querySelectorAll('button').forEach(b => b.onclick = () => {S.f[b.dataset.k].delete(b.dataset.v); update()});
}

/* ---------- pieces ---------- */
const dsLink = u => {const d = DS[u.id]; return d ? `<a href="./#d=${esc(u.id)}" title="${esc(`${d.name}: ${u.role}${u.note ? ` · ${u.note}` : ''}`)}">${esc(d.name)}</a>` : ''};
const relCell = (m, k) => {
  const s = m.release[k], url = m.links[k];
  return `<span class="st-${s}">${stIcon(s)}${s === 'released' && url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${ML[k][s]}</a>` : ML[k][s]}</span>`;
};
const relRow = (m, k) => `<dt>${k === 'code' ? 'Code' : 'Weights'}</dt><dd class="st-${m.release[k]}">${relCell(m, k).replace(/^<span[^>]*>|<\/span>$/g, '')}</dd>`;
// the license without its parenthetical or second clause; the table cell carries the full text as a tooltip
const licShort = m => /^not stated/i.test(m.license) ? 'not stated' : m.license.replace(/^Code: /, '').split(/ \(|; |, /)[0];
const linkRow = m => [['paper', 'Paper'], ['project', 'Project'], ['code', 'Code'], ['weights', 'Weights']]
  .filter(([k]) => m.links[k]).map(([k, t]) => `<a href="${esc(m.links[k])}" target="_blank" rel="noopener">${t}</a>`).join('');
const ownText = m => m.dataset && DS[m.dataset] ? '' : m.own_data ? `<span class="own">Own data: ${esc(m.own_data)}</span>` : '';

function row(m) {
  return `<article class="mrow" data-id="${m.id}" tabindex="0" aria-label="${esc(m.name)}">
    <div class="mcol">
      <div class="ttl"><h3>${esc(m.name)}</h3><span>${m.year}</span></div>
      <div class="src">${esc(m.venue)} · ${esc(m.authors)}</div>
      <div class="tags"><span class="tag kind">${ML.kind[m.kind]}</span><span class="tag dim">${ML.touch[m.touch]}</span><span class="tag dim">${ML.embodiment[m.embodiment]}</span>${newTag('model', m.id)}</div>
      <p class="desc">${esc(m.summary)}</p>
    </div>
    <div class="mcol muses"><span class="mlbl">Data</span>${m.uses.length ? `<div class="used">${m.uses.map(dsLink).join('')}</div>` : ''}${ownText(m)}</div>
    <div class="mcol"><span class="mlbl">Released</span><dl class="rel">${relRow(m, 'code')}${relRow(m, 'weights')}</dl><span class="chk">Checked ${esc(m.checked)}</span></div>
  </article>`;
}
function list(items) {
  if (S.sort !== 'kind') return `<div class="mlist">${items.map(row).join('')}</div>`;
  return KINDS.map(k => [k, items.filter(m => m.kind === k)]).map(([k, g]) => g.length ? `<section class="rgroup"><h2><span class="rh">${ML.kindPlural[k]}</span>
    <span>${esc(KIND_TEXT[k])}</span><small>${g.length}</small></h2><div class="mlist">${g.map(row).join('')}</div></section>` : '').join('');
}
function table(items) {
  const r = m => `<tr data-id="${m.id}">
    <td><b>${esc(m.name)}</b><span class="sub">${esc(m.venue)}</span></td>
    <td>${ML.kind[m.kind]}<span class="sub">${ML.touch[m.touch]}</span></td>
    <td>${ML.embodiment[m.embodiment]}</td>
    <td>${m.uses.length ? `<div class="used">${m.uses.map(dsLink).join('')}</div>` : esc(m.own_data || '–')}</td>
    <td><span class="st-${m.release.code}">${ML.code[m.release.code]}</span></td>
    <td><span class="st-${m.release.weights}">${ML.weights[m.release.weights]}</span></td>
    <td title="${esc(m.license)}">${esc(licShort(m))}</td>
    <td class="num">${m.year}</td></tr>`;
  return `<div class="tablewrap"><table><thead><tr><th data-s="name">Model</th><th data-s="kind">Kind · touch</th><th>Touch recorded on</th><th data-s="uses">Data</th>
    <th data-s="released">Code</th><th data-s="released">Weights</th><th>License</th><th data-s="year">Year</th></tr></thead><tbody>${items.map(r).join('')}</tbody></table></div>`;
}

function render() {
  const items = M.filter(m => passes(m)).sort(SORTS[S.sort]);
  $('count').textContent = `${items.length} of ${M.length} models`;
  $('out').innerHTML = !items.length ? `<p class="empty">No model matches these filters.</p>` : S.view === 'table' ? table(items) : list(items);
  $('out').querySelectorAll('[data-id]').forEach(el => {
    el.onclick = e => {if (!e.target.closest('a[href]')) {e.preventDefault(); openDetail(el.dataset.id)}};
    el.onkeydown = e => {if (e.key === 'Enter' && !e.target.closest('a[href]')) openDetail(el.dataset.id)};
  });
  $('out').querySelectorAll('th[data-s]').forEach(th => th.onclick = () => {S.sort = th.dataset.s; $('sort').value = S.sort; update()});
  document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
}

function openDetail(id) {
  const m = M.find(x => x.id === id); if (!m) return;
  S.m = id; writeHash();
  const kvs = rows => `<dl class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const dsl = m.uses.filter(u => DS[u.id]).map(u => {const d = DS[u.id];
    return `<a href="./#d=${esc(u.id)}">${d.thumb ? `<img src="${esc(d.thumb)}" alt="">` : ''}<div><b>${esc(d.name)}</b><span>${esc(u.role)}${u.id === m.dataset ? ' · released with this model' : ''}</span></div></a>`}).join('');
  const notes = m.uses.filter(u => u.note && DS[u.id]).map(u => `<li><b>${esc(DS[u.id].name)}</b> (${esc(u.role)}): ${esc(u.note)}</li>`).join('');
  $('dlg').innerHTML = `<div class="dl"><header><div><h2 id="dlgTitle">${esc(m.name)}</h2><p>${esc(m.title)}</p><p>${esc(m.authors)} · ${esc(m.venue)}</p></div>
    <button class="x" aria-label="Close"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
    <div class="scroll"><p>${esc(m.summary)}</p>
    <h4>Model</h4>${kvs([['Kind', `${ML.kind[m.kind]}${KIND_TEXT[m.kind] ? `<span class="sub">${esc(KIND_TEXT[m.kind])}</span>` : ''}`], ['Touch', ML.touch[m.touch]], ['Recorded on', ML.embodiment[m.embodiment]]])}
    <h4>Released</h4>${kvs([['Code', relCell(m, 'code')], ['Weights', relCell(m, 'weights')], ['License', esc(m.license)],
      ['Evidence', esc(m.release.note || '')], ['Checked', esc(m.checked)]])}
    <h4>Data</h4>${dsl ? `<div class="dsl">${dsl}</div>` : ''}${notes ? `<ul class="usedby">${notes}</ul>` : ''}${m.own_data ? `<p class="plain">Own data: ${esc(m.own_data)}</p>` : ''}${!dsl && !m.own_data ? '<p class="src">Training data not stated.</p>' : ''}
    <div class="links">${linkRow(m)}</div>
    ${(m.sources || []).length ? `<details class="srcs"><summary>Sources${(m.unconfirmed || []).length ? ' and open points' : ''}</summary>
      ${(m.unconfirmed || []).length ? `<p>Derived or not confirmed:</p><ul>${m.unconfirmed.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p>Read:</p>` : ''}
      <ul>${m.sources.map(x => `<li><a href="${esc(x)}" target="_blank" rel="noopener">${esc(x)}</a></li>`).join('')}</ul></details>` : ''}</div></div>`;
  $('dlg').querySelector('.x').onclick = () => $('dlg').close();
  if (!$('dlg').open) $('dlg').showModal();
}

function update() {writeHash(); renderFacets(); renderChips(); render()}

async function main() {
  const [mj, dj] = await Promise.all(['data/models.json', 'data/datasets.json'].map(async u => (await fetch(u)).json()));
  M = mj.models; META = mj.metadata; DS = Object.fromEntries(dj.datasets.map(d => [d.id, d]));
  const code = M.filter(m => m.release.code === 'released').length, wts = M.filter(m => m.release.weights === 'released').length;
  $('sum').textContent = `${M.length} models · ${code} with code, ${wts} with weights · updated ${META.last_updated}`;
  $('gh').href = REPO; $('contrib').href = `${REPO}/issues/new?title=${encodeURIComponent('Model: ')}`;
  await loadNightly();
  readHash(); $('q').value = S.q; $('sort').value = S.sort;
  $('q').oninput = e => {S.q = e.target.value; writeHash(); renderFacets(); renderChips(); render()};
  $('sort').onchange = e => {S.sort = e.target.value; update()};
  document.querySelectorAll('.seg button').forEach(b => b.onclick = () => {S.view = b.dataset.view; update()});
  $('filtbtn').onclick = () => document.body.dataset.filters = document.body.dataset.filters === 'open' ? '' : 'open';
  document.addEventListener('click', e => {if (document.body.dataset.filters === 'open' && !e.target.closest('#facets,#filtbtn')) document.body.dataset.filters = ''});
  $('dlg').addEventListener('close', () => {S.m = null; writeHash()});
  $('dlg').addEventListener('click', e => {if (e.target === $('dlg')) $('dlg').close()});
  update();
  if (S.m) openDetail(S.m);
}
main();
