// Helpers shared by the dataset catalog (site.js), the models page (models.js) and the hardware page (hardware.js).
const REPO = 'https://github.com/Yuxiang-Ma/Awesome-Tactile-Hands';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
/* Chinese originals: x.zh = {name, title, maker, en: 'official' | 'translated', note}. English is shown first; the Chinese
   original follows it, and a Translated tag marks English the catalog wrote because the publisher has none. */
const zhTag = x => x.zh?.en === 'translated' ? '<span class="trn" title="No official English name; the English is the catalog\u2019s translation">Translated</span>' : '';
const zhLine = x => x.zh?.name ? `<div class="zhn"><span lang="zh-CN">${esc(x.zh.name)}</span>${zhTag(x)}</div>` : '';
const zhText = x => x.zh ? [x.zh.name, x.zh.title, x.zh.maker].filter(Boolean).join(' ') : '';
const zhHead = (x, what) => x.zh ? `<p class="zhl"><span lang="zh-CN">${esc([x.zh.name, x.zh.title, x.zh.maker].filter(Boolean).join(' · '))}</span>${x.zh.en === 'translated' ? ` · ${what} translated from Chinese by the catalog` : ''}</p>` : '';
const fmt = n => n == null ? '' : n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}K` : n.toLocaleString('en-US');

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

/* ---------- figure fit: card and dialog images are shown whole (object-fit: contain); the empty bands beside a figure take
   the colour of the image edge they touch, so a figure with a white or dark border runs on into the frame ---------- */
const FILL = new Map();
function edgeFill(img) {
  if (!img.naturalWidth || !img.clientHeight) return;
  const wide = img.naturalWidth / img.naturalHeight > img.clientWidth / img.clientHeight, key = `${img.currentSrc} ${wide}`;
  if (!FILL.has(key)) {
    const w = 48, h = Math.max(2, Math.round(w * img.naturalHeight / img.naturalWidth)), c = document.createElement('canvas');
    c.width = w; c.height = h;
    const x = c.getContext('2d', {willReadFrequently: true});
    x.drawImage(img, 0, 0, w, h);
    let px; try {px = x.getImageData(0, 0, w, h).data} catch {return}
    // median per channel along one edge, so a stray line or label at the border does not tint the band
    const med = ix => `rgb(${[0, 1, 2].map(k => ix.map(i => px[i * 4 + k]).sort((a, b) => a - b)[ix.length >> 1]).join(' ')})`;
    const row = y => Array.from({length: w}, (_, i) => y * w + i), col = v => Array.from({length: h}, (_, j) => j * w + v);
    const [a, b] = wide ? [med(row(0)), med(row(h - 1))] : [med(col(0)), med(col(w - 1))];
    FILL.set(key, a === b ? a : `linear-gradient(${wide ? 'to bottom' : 'to right'}, ${a} 50%, ${b} 50%)`);
  }
  img.style.background = FILL.get(key);
}
document.addEventListener('load', e => {if (e.target.matches?.('.thumb img, img.hero')) edgeFill(e.target)}, true);

/* ---------- nightly checks (pipeline/NIGHTLY.md): footer status, the change log in the dialog, and New tags for entries
   added in the last 14 days. Each page sets PAGE_TARGET ('dataset' | 'model' | 'hardware') and defines openDetail(id). ---------- */
const NIGHTLY = {changes: [], runs: {}, added: new Set()};
const TARGET_URL = {dataset: id => `./#d=${encodeURIComponent(id)}`, model: id => `models.html#m=${encodeURIComponent(id)}`,
  hardware: id => `hardware.html#h=${encodeURIComponent(id)}`};
const CHANGE_WORD = {added: 'Added', released: 'Released', updated: 'Updated', withdrawn: 'Withdrawn'};
const newTag = (target, id) => NIGHTLY.added.has(`${target}:${id}`) ? '<span class="tag new" title="Added by the nightly check in the last 14 days">New</span>' : '';
async function loadNightly() {
  const want = /(^|&)changes(&|$)/.test(location.hash.slice(1));  // #changes opens the change log once the page has rendered
  try {
    const [c, s] = await Promise.all(['data/changes.json', 'data/status.json'].map(async u => {const r = await fetch(u); return r.ok ? r.json() : {}}));
    NIGHTLY.changes = c.changes || []; NIGHTLY.runs = s.runs || {};
  } catch {return}
  if (want) setTimeout(() => openChanges(), 0);
  const cut = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10);
  for (const x of NIGHTLY.changes) if (x.kind === 'added' && x.date >= cut) NIGHTLY.added.add(`${x.target}:${x.id}`);
  const upd = $('upd'), runs = Object.values(NIGHTLY.runs);
  if (!upd || !runs.length) return;
  const last = runs.map(r => r.date).sort().pop(), bad = runs.filter(r => r.date === last && r.ok === false).map(r => r.flow);
  upd.innerHTML = `Checked every night; last check ${esc(last)}${bad.length ? ` (the ${esc(bad.join(' and '))} run did not finish)` : ''}.` +
    (NIGHTLY.changes.length ? ` <a href="#" id="chglink">Recent changes</a>` : '');
  $('chglink')?.addEventListener('click', e => {e.preventDefault(); openChanges()});
}
function openChanges() {
  const by = new Map();
  for (const x of NIGHTLY.changes.slice(0, 80)) (by.get(x.date) || by.set(x.date, []).get(x.date)).push(x);
  const runs = Object.values(NIGHTLY.runs).sort((a, b) => (a.flow > b.flow) - (a.flow < b.flow));
  $('dlg').innerHTML = `<div class="dl"><header><div><h2 id="dlgTitle">Recent changes</h2><p>Found by the nightly checks, newest first.
    New papers and repositories are reviewed at 01:30 and catalogued links rechecked at 04:30 (New York time); the site updates at 09:00.</p></div>
    <button class="x" aria-label="Close"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
    <div class="scroll">${runs.length ? `<dl class="kv">${runs.map(r => `<dt>${r.flow === 'discovery' ? 'Discovery' : 'Status check'}</dt><dd>${esc(r.date)}${r.ok === false ? ' · did not finish' : ''}${
      r.reviewed != null ? ` · ${r.reviewed} reviewed` : ''}${r.added ? ` · ${Object.entries(r.added).filter(([, v]) => v).map(([k, v]) => `${v} ${k} added`).join(', ') || 'nothing added'}` : ''}</dd>`).join('')}</dl>` : ''}
    ${[...by].map(([date, xs]) => `<h4>${esc(date)}</h4><ul class="chg">${xs.map(x => `<li><b class="ck ck-${esc(x.kind)}">${CHANGE_WORD[x.kind] || esc(x.kind)}</b><span><a href="${TARGET_URL[x.target]?.(x.id) || '#'}" data-t="${esc(x.target)}" data-i="${esc(x.id)}">${esc(x.text)}</a>${
      x.source ? ` <a class="srcl" href="${esc(x.source)}" target="_blank" rel="noopener">source</a>` : ''}</span></li>`).join('')}</ul>`).join('') || '<p class="src">No changes logged yet.</p>'}</div></div>`;
  $('dlg').querySelector('.x').onclick = () => $('dlg').close();
  $('dlg').querySelectorAll('a[data-t]').forEach(a => a.onclick = e => {
    if (typeof PAGE_TARGET !== 'undefined' && a.dataset.t === PAGE_TARGET && typeof openDetail === 'function') {e.preventDefault(); openDetail(a.dataset.i)}
  });
  if (!$('dlg').open) $('dlg').showModal();
}
