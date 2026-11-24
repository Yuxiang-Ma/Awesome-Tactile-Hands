// Taxel Atlas catalog shell: a Datasets | Hardware list on the left and the focused item on the right, with its linked hardware,
// datasets and models. No build step. The state lives in the URL hash:
//   tab=hardware (omitted for datasets), q, one key per facet, from/to (years), view, sort, and d=<dataset id> or h=<device id>.
// Moving focus through a linked tile is a real hash link, so the browser's Back returns to the previous item.
// Tabs are defined in catalog-ds.js (DSTAB) and catalog-hw.js (HWTAB); shared helpers are in common.js.
const PAGE_TARGET = 'dataset';
const TABS = {datasets: DSTAB, hardware: HWTAB};
const KIND = {d: DSTAB, h: HWTAB};
const NARROW = matchMedia('(max-width: 860px)');
const fresh = T => ({q: '', f: {}, y0: null, y1: null, view: 'list', sort: T.defaultSort});
let TAB = 'datasets', S = fresh(DSTAB), FOCUS = null, LIST = [];
const cur = () => TABS[TAB];

/* ---------- state <-> hash ---------- */
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  TAB = p.get('tab') === 'hardware' ? 'hardware' : 'datasets';
  const T = cur(); S = fresh(T);
  S.q = p.get('q') || ''; S.view = T.views.some(([v]) => v === p.get('view')) ? p.get('view') : 'list';
  S.sort = T.SORTS[p.get('sort')] ? p.get('sort') : T.defaultSort;
  if (T.years) {S.y0 = +p.get('from') || null; S.y1 = +p.get('to') || null}
  for (const F of T.FACETS) {const v = p.get(F.key); if (v) S.f[F.key] = new Set(v.split(','))}
  const k = p.has('d') ? 'd' : p.has('h') ? 'h' : null;
  FOCUS = k && KIND[k].byId(p.get(k)) ? {k, id: p.get(k)} : null;
}
function hashOf(s, focus) {
  const p = new URLSearchParams(), T = cur();
  if (TAB !== 'datasets') p.set('tab', TAB);
  if (s.q) p.set('q', s.q);
  for (const [k, v] of Object.entries(s.f)) if (v.size) p.set(k, [...v].join(','));
  if (s.y0) p.set('from', s.y0); if (s.y1) p.set('to', s.y1);
  if (s.view !== 'list') p.set('view', s.view); if (s.sort !== T.defaultSort) p.set('sort', s.sort);
  if (focus) p.set(focus.k, focus.id);
  return '#' + p.toString().replace(/%2C/g, ',');
}
function writeHash(push) {
  const h = hashOf(S, FOCUS), url = h === '#' ? location.pathname + location.search : h;
  push ? history.pushState({list: true}, '', url) : history.replaceState(history.state, '', url);
}
// the address of an item in the List view, keeping the current search and filters
const focusHref = (k, id) => hashOf({...S, view: 'list'}, {k, id});

/* ---------- linked tiles in the pane ---------- */
const tileHtml = (href, t, ext) => `<a class="lk" href="${href}"${ext ? ' target="_blank" rel="noopener"' : ''}><span class="lki">${t.img}</span><span class="lkt"><b>${esc(t.name)}</b><span>${t.sub}</span></span></a>`;
const dsTile = (d, sub) => tileHtml(focusHref('d', d.id), DSTAB.tile(d, sub));
const hwTile = (h, sub) => tileHtml(focusHref('h', h.id), HWTAB.tile(h, sub));
const MKIND = {world_model: 'World model', policy: 'Policy', representation: 'Tactile representation', estimation: 'Estimation', generation: 'Touch generation', other: 'Model'};
const REL = {released: 'released', announced: 'announced', not_released: 'not released'};
const relText = r => r.code === r.weights ? `code and weights ${REL[r.code]}` : `code ${REL[r.code]}, weights ${REL[r.weights]}`;
const ICON_MODEL = '<svg class="mi" viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6.5" r="2.2"/><circle cx="5" cy="17.5" r="2.2"/><circle cx="19" cy="12" r="2.2"/><path d="M7.1 7.3 16.9 11.2M7.1 16.7l9.8-3.9M5 8.7v6.6"/></svg>';
const modelTile = (m, sub) => tileHtml(`models.html#m=${encodeURIComponent(m.id)}`,
  {img: ICON_MODEL, name: m.name, sub: esc([MKIND[m.kind] || 'Model', m.year, relText(m.release), sub].filter(Boolean).join(' · '))});

/* ---------- filtering ---------- */
function passes(x, skip) {
  const T = cur();
  if (S.q && !S.q.toLowerCase().split(/\s+/).every(w => T.textOf(x).includes(w))) return false;
  if (S.y0 && x.year < S.y0 || S.y1 && x.year > S.y1) return false;
  for (const F of T.FACETS) {
    if (F.key === skip) continue;
    const sel = S.f[F.key]; if (!sel || !sel.size) continue;
    const vals = F.get(x);
    if (F.all ? ![...sel].every(v => vals.includes(v)) : !vals.some(v => sel.has(v))) return false;
  }
  return true;
}

function renderFacets() {
  const T = cur(), all = T.items(), ys = all.map(x => x.year).filter(Boolean);
  $('facets').innerHTML = `<p class="intro">${esc(T.scope() || '')}</p>` + T.FACETS.map(F => {
    const sel = S.f[F.key] || new Set(), pool = all.filter(x => passes(x, F.all ? null : F.key));
    const vals = Object.keys(F.labels).filter(v => all.some(x => F.get(x).includes(v)));
    return `<fieldset class="fs"><legend>${F.title}</legend>${F.hint ? `<p class="hint">${F.hint}</p>` : ''}${vals.map(v => {
      const n = pool.filter(x => F.get(x).includes(v)).length;
      return `<label class="opt" data-zero="${!n && !sel.has(v)}"><input type="checkbox" data-f="${F.key}" value="${v}"${sel.has(v) ? ' checked' : ''}>${F.labels[v]}<span class="n">${n}</span></label>`;
    }).join('')}</fieldset>`;
  }).join('') + (T.years ? `<fieldset class="fs"><legend>Year</legend><div class="years"><input id="y0" type="number" aria-label="From year" placeholder="${Math.min(...ys)}" value="${S.y0 || ''}">–<input id="y1" type="number" aria-label="To year" placeholder="${Math.max(...ys)}" value="${S.y1 || ''}"></div></fieldset>` : '')
    + `<button class="clear" id="clear">Clear filters</button>`;
  $('facets').querySelectorAll('input[data-f]').forEach(i => i.onchange = () => {
    const s = S.f[i.dataset.f] ||= new Set(); i.checked ? s.add(i.value) : s.delete(i.value); update();
  });
  if (T.years) ['y0', 'y1'].forEach(k => $(k).onchange = e => {S[k] = +e.target.value || null; update()});
  $('clear').onclick = clearAll;
}
function clearAll() {S.f = {}; S.q = ''; S.y0 = S.y1 = null; $('q').value = ''; update()}

const ICON_X = '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M1 1l8 8M9 1 1 9"/></svg>';
function renderChips() {
  const T = cur(), c = [], lab = Object.fromEntries(T.FACETS.map(F => [F.key, F.labels]));
  for (const [k, v] of Object.entries(S.f)) for (const x of v) c.push(`<button data-k="${k}" data-v="${x}" aria-label="Remove filter ${esc(lab[k][x])}">${lab[k][x]}${ICON_X}</button>`);
  if (S.y0 || S.y1) c.push(`<button data-k="year" aria-label="Remove year filter">${S.y0 || '…'}–${S.y1 || '…'}${ICON_X}</button>`);
  $('chips').innerHTML = c.join('');
  $('chips').hidden = !c.length;
  $('chips').querySelectorAll('button').forEach(b => b.onclick = () => {
    if (b.dataset.k === 'year') S.y0 = S.y1 = null; else S.f[b.dataset.k].delete(b.dataset.v);
    update();
  });
}

/* ---------- list ---------- */
// on a wide screen an empty focus shows the first row; on a phone it shows the list alone
const shown = () => FOCUS || (!NARROW.matches && LIST[0] ? {k: cur().fk, id: LIST[0].id} : null);
function rowHtml(x) {
  const T = cur(), r = T.row(x, S.sort), f = shown(), on = f && f.k === T.fk && f.id === x.id;
  return `<li><a class="row" href="${focusHref(T.fk, x.id)}" data-id="${esc(x.id)}"${on ? ' aria-current="true"' : ''}>
    <span class="rt">${r.img}</span>
    <span class="rb"><span class="r1"><b>${esc(r.name)}</b>${r.zh ? `<span class="rz" lang="zh-CN">${esc(r.zh)}</span>` : ''}${r.tag}<span class="ry">${r.year}</span></span>
    <span class="r2">${r.meta}</span></span>${r.glyph}</a></li>`;
}
function renderList() {
  const T = cur(), g = T.groups(LIST, S.sort);
  $('rows').innerHTML = !LIST.length ? `<li class="empty">${esc(T.empty)} <button class="clear" data-clear>Clear filters</button></li>`
    : g ? g.filter(x => x.items.length).map(x => `<li class="gh" title="${esc(x.title)}">${x.head}<span class="n">${x.items.length}</span></li>${x.items.map(rowHtml).join('')}`).join('')
    : LIST.map(rowHtml).join('');
  $('rows').querySelector('[data-clear]')?.addEventListener('click', clearAll);
  $('listcol').setAttribute('aria-label', T.noun[1]);
}
function renderPane(scroll) {
  const f = shown(), T = f && KIND[f.k], x = T && T.byId(f.id);
  document.body.dataset.detail = NARROW.matches && FOCUS ? 'open' : '';
  $('pane').innerHTML = x ? `<button class="back" id="back">${ICON_BACK}${esc(`All ${cur().noun[1]}`)}</button>${T.pane(x)}`
    : `<p class="empty">${LIST.length ? '' : esc(cur().empty)}</p>`;
  $('back')?.addEventListener('click', () => {
    if (history.state?.list) history.back(); else {FOCUS = null; writeHash(); renderList(); renderPane(true)}
  });
  if (scroll) {$('pane').scrollTop = 0; if (NARROW.matches) window.scrollTo(0, 0)}
  document.title = x && FOCUS ? `${T.title(x)} · Taxel Atlas` : TAB === 'hardware' ? 'Tactile Hand Hardware · Taxel Atlas' : 'Taxel Atlas';
}
const ICON_BACK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';

function render(scroll) {
  const T = cur();
  LIST = T.items().filter(x => passes(x)).sort(T.SORTS[S.sort]);
  // with grouping on, the order on screen is the group order
  const g = T.groups(LIST, S.sort); if (g) LIST = g.flatMap(x => x.items);
  $('count').textContent = `${LIST.length} of ${T.items().length} ${T.noun[1]}`;
  document.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
  const wide = S.view !== 'list';
  $('work').hidden = wide; $('wide').hidden = !wide;
  if (wide) {
    $('wide').innerHTML = !LIST.length ? `<p class="empty">${esc(T.empty)}</p>` : S.view === 'table' ? T.table(LIST) : T.extra[S.view](LIST);
    $('wide').querySelectorAll('th[data-s]').forEach(th => th.onclick = () => {S.sort = th.dataset.s; $('sort').value = S.sort; update()});
    T.wire?.($('wide'));
  } else {renderList(); renderPane(scroll)}
}

// a row, table row or chart point opens the item in the List view; on a phone that is a new history entry, so Back returns to the list
function openItem(k, id, push) {
  FOCUS = {k, id}; S.view = 'list'; writeHash(push);
  render(true);
  $('rows').querySelector(`a[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({block: 'nearest'});
}
// the change log in the footer (common.js) calls this for datasets and hardware
function focusItem(target, id) {
  const k = target === 'hardware' ? 'h' : 'd';
  if (!KIND[k].byId(id)) return;
  $('dlg').close(); openItem(k, id, true);
}
const openDetail = id => focusItem('dataset', id);

function syncControls() {
  const T = cur();
  $('q').value = S.q; $('q').placeholder = T.search;
  $('sort').innerHTML = T.sortOptions.map(([v, t]) => `<option value="${v}">${t}</option>`).join(''); $('sort').value = S.sort;
  $('views').innerHTML = T.views.map(([v, t]) => `<button data-view="${v}" aria-pressed="${v === S.view}">${t}</button>`).join('');
  $('views').querySelectorAll('button').forEach(b => b.onclick = () => {S.view = b.dataset.view; update()});
  $('sum').textContent = T.summary();
  $('contrib').href = T.contrib[1]; $('contrib').querySelector('span').textContent = T.contrib[0];
  $('foot').textContent = T.footer;
  for (const [id, t] of [['navds', 'datasets'], ['navhw', 'hardware']]) t === TAB ? $(id).setAttribute('aria-current', 'page') : $(id).removeAttribute('aria-current');
}

function update() {writeHash(); renderFacets(); renderChips(); render()}

async function main() {
  const get = async u => {try {const r = await fetch(u); return r.ok ? r.json() : {}} catch {return {}}};
  const [dj, hj, mj] = await Promise.all(['data/datasets.json', 'data/hardware.json', 'data/models.json'].map(get));
  DB.D = dj.datasets || []; DB.metaD = dj.metadata || {}; DB.HW = hj.hardware || []; DB.metaH = hj.metadata || {}; DB.M = mj.models || [];
  DB.ds = Object.fromEntries(DB.D.map(d => [d.id, d])); DB.hw = Object.fromEntries(DB.HW.map(h => [h.id, h])); DB.md = Object.fromEntries(DB.M.map(m => [m.id, m]));
  $('gh').href = REPO;
  await loadNightly();
  readHash(); syncControls();
  $('q').oninput = e => {S.q = e.target.value; writeHash(); renderFacets(); renderChips(); render()};
  $('sort').onchange = e => {S.sort = e.target.value; update()};
  $('filtbtn').onclick = () => document.body.dataset.filters = document.body.dataset.filters === 'open' ? '' : 'open';
  document.addEventListener('click', e => {if (document.body.dataset.filters === 'open' && !e.target.closest('#facets,#filtbtn')) document.body.dataset.filters = ''});
  // list rows: on a wide screen a click moves the focus in place; on a phone it opens the item as a new history entry
  $('rows').addEventListener('click', e => {
    const a = e.target.closest('a.row'); if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    e.preventDefault(); openItem(cur().fk, a.dataset.id, NARROW.matches);
  });
  // Up and Down move through the list
  $('rows').addEventListener('keydown', e => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const rows = [...$('rows').querySelectorAll('a.row')], i = rows.indexOf(document.activeElement), n = rows[i + (e.key === 'ArrowDown' ? 1 : -1)];
    if (!n) return;
    e.preventDefault(); n.focus();
    // openItem redraws the list, so focus the new copy of the row
    if (!NARROW.matches) {openItem(cur().fk, n.dataset.id, false); $('rows').querySelector(`a[data-id="${CSS.escape(n.dataset.id)}"]`)?.focus()}
  });
  // Compare rows and chart points open the item in the List view
  $('wide').addEventListener('click', e => {
    if (e.target.closest('a[href], th')) return;
    const el = e.target.closest('[data-id]'); if (el) openItem(cur().fk, el.dataset.id, true);
  });
  $('wide').addEventListener('keydown', e => {const el = e.target.closest?.('[data-id]'); if (e.key === 'Enter' && el) openItem(cur().fk, el.dataset.id, true)});
  // hash links (linked tiles, map labels, the nav tabs, Back) re-read the whole state
  addEventListener('hashchange', () => {const t = TAB; readHash(); syncControls(); renderFacets(); renderChips(); render(true); if (t !== TAB) $('facets').scrollTop = 0});
  NARROW.addEventListener('change', () => render());
  $('dlg').addEventListener('click', e => {if (e.target === $('dlg')) $('dlg').close()});
  update();
}
main();
