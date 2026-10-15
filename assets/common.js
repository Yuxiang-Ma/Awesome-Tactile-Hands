// Helpers shared by the dataset catalog (site.js) and the hardware page (hardware.js).
const REPO = 'https://github.com/Yuxiang-Ma/Awesome-Tactile-Hands';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
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
