// LOST & FOUND: files visitors left behind, and the credentials they tried.
import { $, h, api, num, ago, toast } from './dom.js';

let picked = null;   // sha256 of the selected tag

// Tilt encodes how many times the same file was left: 1 time = straight,
// more = more crooked (log scale, capped at 14°). Alternate left/right.
const tilt = (times, i) => Math.min(14, Math.log2(times) * 5) * (i % 2 ? 1 : -1);

export async function render() {
  const { files, credentials } = await api('/api/captures');
  if (!files.find((f) => f.sha256 === picked)) picked = files.length ? files[0].sha256 : null;

  $('#tags').replaceChildren(...(files.length ? files.map((f, i) => h('button', {
    type: 'button', class: 'tag', 'aria-pressed': String(f.sha256 === picked),
    'aria-label': `${f.filename}, left ${f.times} time${f.times === 1 ? '' : 's'}`,
    style: { transform: `rotate(${tilt(f.times, i)}deg)` },
    onclick: () => { picked = f.sha256; render(); },
  },
    h('span', { class: 'no' }, `Nº ${String(files.length - i).padStart(3, '0')}`),
    h('span', { class: 'fn' }, f.filename),
    h('span', { class: 'meta' }, `${num(f.size)} bytes`, h('br'), `left ${f.times}× · ${ago(f.last_seen)}`)))
    : [h('p', { class: 'empty', style: { width: '100%' } }, 'Nothing left behind yet. Turn on FTP to give them somewhere to drop files.')]));

  renderClaim(files.find((f) => f.sha256 === picked));
  renderCreds(credentials);
}

function renderClaim(f) {
  const box = $('#claim');
  if (!f) { box.replaceChildren(); return; }
  box.replaceChildren(
    h('h2', { class: 'serif', style: { margin: 0, fontWeight: 400, fontSize: '32px' } }, 'Claim ticket'),
    h('div', { class: 'claim-card' },
      h('dl', {},
        h('dt', {}, 'FILE'), h('dd', {}, f.filename),
        h('dt', {}, 'SHA-256'), h('dd', {}, f.sha256),
        h('dt', {}, 'SIZE'), h('dd', {}, `${num(f.size)} bytes`),
        h('dt', {}, 'LEFT BY'), h('dd', {}, f.ips.join(', ')),
        h('dt', {}, 'TIMES'), h('dd', {}, `${f.times} (first ${ago(f.first_seen)}, last ${ago(f.last_seen)})`),
        h('dt', {}, 'ON DISK'), h('dd', {}, f.saved_path || '—')),
      h('p', { class: 'warn' }, 'Treat this as malware. MIMIC does not serve it to the browser on purpose: copy it from the path above onto an isolated machine to analyse it.'),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn', onclick: () => copy(f.sha256, 'Fingerprint copied.') }, 'Copy SHA-256'),
        h('button', { type: 'button', class: 'btn', onclick: () => copy(f.saved_path || '', 'Path copied.') }, 'Copy path'),
        h('a', { class: 'btn', style: { display: 'inline-grid', placeItems: 'center', textDecoration: 'none' },
                 href: `https://www.virustotal.com/gui/file/${f.sha256}`, target: '_blank', rel: 'noopener noreferrer' },
          'Look up on VirusTotal ↗')),
      h('p', { class: 'muted', style: { margin: 0, fontSize: '13px' } }, 'The VirusTotal link only sends the hash, and only if you click it.')));
}

function renderCreds(creds) {
  $('#bulbs').replaceChildren(...Array.from({ length: 18 }, () => h('i')));
  const max = creds.length ? creds[0].times : 1;
  $('#creds').replaceChildren(...(creds.length ? creds.map((c, i) => h('li', {},
    h('span', { class: 'rank' }, String(i + 1).padStart(2, '0')),
    h('span', { class: 'cred' }, `${c.username} / ${c.password}`),
    h('span', { class: 'cnt' }, `${num(c.times)}× · ${c.ips} IP${c.ips === 1 ? '' : 's'}`),
    h('span', { class: 'bar', style: { width: `${(c.times / max) * 100}%` } })))
    : [h('li', { class: 'empty', style: { display: 'block' } }, 'No lines rehearsed yet.')]));
}

async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); }
  catch { toast('Could not copy: your browser blocked the clipboard.'); }
}
