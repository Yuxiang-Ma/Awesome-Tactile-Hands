// Helpers shared by the dataset catalog (site.js) and the hardware page (hardware.js).
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
