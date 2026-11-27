// THE STAGE: the script (what happened) and the house (who is in the room).
import { $, h, api, num, clock, ago, toast } from './dom.js';
import { refresh } from './app.js';

const ZONE_TEXT = {
  front: { color: 'var(--text)', desc: 'got in and acted: ran shell commands or left a file' },
  stalls: { color: 'var(--muted)', desc: 'got in, but did nothing more' },
  refused: { color: 'var(--dim)', desc: 'row D: tried to log in, always refused' },
  knocked: { color: 'var(--dim)', desc: 'row E: only knocked, never tried a password' },
};
const STATUS_WORD = { in: 'got in', out: 'refused', knock: 'only knocked' };

let picked = null;   // ip of the selected seat

export async function render() {
  const data = await api('/api/stage');
  const { house, script, headline, blocked } = data;
  const banned = new Set(blocked);

  $('#n-visitors').textContent = num(headline.visitors);
  $('#n-tries').textContent = num(headline.tries);
  $('#n-files').textContent = num(headline.files);
  $('#headline').textContent = headline.visitors
    ? 'The audience is watching.'
    : 'An empty house, for now.';

  if (!picked || !house.visitors[picked]) {
    // Default spotlight: the visitor who got deepest, most recently.
    const order = ['front', 'stalls', 'refused', 'knocked'];
    const all = Object.values(house.visitors).sort((a, b) =>
      order.indexOf(a.zone) - order.indexOf(b.zone) || (b.last_seen > a.last_seen ? 1 : -1));
    picked = all.length ? all[0].ip : null;
  }

  renderScript(script, house);
  renderHouse(house, banned);
  renderTicket(house.visitors[picked], banned);
}

function renderScript(scenes, house) {
  const box = $('#scenes');
  if (!scenes.length) {
    box.replaceChildren(h('p', { class: 'empty' }, 'No scenes yet. The first visitor writes the first line.'));
    return;
  }
  const total = scenes.length;
  box.replaceChildren(...scenes.map((sc, i) => {
    const v = house.visitors[sc.ip];
    const seat = v && v.seat ? `seat ${v.seat}` : 'standing';
    const tone = sc.uploads ? 'out' : sc.tone;
    return h('article', { class: 'scene' + (sc.ip === picked ? ' spot' : '') },
      h('p', { class: 'slug' },
        `SCENE ${total - i} — INT. ${sc.service.toUpperCase()} :${sc.port ?? '?'} — ${clock(sc.end)}`,
        sc.ip === picked ? h('span', { class: 'spotlight' }, '● in the spotlight') : null),
      h('div', { class: 'body' },
        h('span', { class: 'who' },
          h('button', { type: 'button', onclick: () => { picked = sc.ip; refresh(); },
                        'aria-label': `Show ticket for ${sc.ip}` }, sc.ip ?? 'unknown'),
          ' ', h('span', { class: 'seatno' }, `· ${seat}`)),
        h('span', { class: `dir ${tone}` }, `(${sc.direction})`),
        sc.lines.map((ln) => h('span', {
          class: 'line' + (ln.kind === 'login' ? (ln.ok ? ' ok' : ' no') : '') + (ln.kind === 'upload' ? ' upload' : ''),
        }, ln.kind === 'command' ? `$ ${ln.text}` : ln.kind === 'upload' ? `⇪ ${ln.text}` : ln.text))));
  }));
}

function renderHouse(house, banned) {
  const zones = house.zones.map((z) => h('div', { class: 'zone' },
    h('div', { class: 'zone-head' },
      h('span', { class: 't', style: { color: ZONE_TEXT[z.key].color } }, z.title),
      h('span', { class: 'd' }, ZONE_TEXT[z.key].desc)),
    z.rows.map((r) => h('div', { class: 'row' },
      h('span', { class: 'n', 'aria-hidden': 'true' }, r.name),
      r.seats.map((s) => s.ip
        ? h('button', {
            type: 'button',
            class: `seat ${s.status}` + (banned.has(s.ip) ? ' banned' : ''),
            'aria-pressed': String(s.ip === picked),
            'aria-label': `Seat ${s.seat}: ${s.ip}, ${STATUS_WORD[s.status]}`,
            title: `${s.seat} · ${s.ip}`,
            style: { color: `var(--${s.status})` },
            onclick: () => { picked = s.ip; refresh(); },
          })
        : h('span', { class: 'seat', 'aria-hidden': 'true' })))),
    z.standing ? h('span', { class: 'standing' }, `+${z.standing} standing at the back of this zone`) : null));
  $('#hall').replaceChildren(h('div', { class: 'stage-lip', 'aria-hidden': 'true' }, 'STAGE · THE HONEYPOT'), ...zones);
}

const ZONE_NAME = { front: 'FRONT ROW', stalls: 'STALLS', refused: 'BACK', knocked: 'BACK' };

function renderTicket(v, banned) {
  const box = $('#seat-ticket');
  if (!v) { box.replaceChildren(); return; }
  const isBanned = banned.has(v.ip);
  const row = v.seat ? v.seat[0] : '–';
  const num_ = v.seat ? v.seat.slice(1) : '–';
  box.replaceChildren(h('div', { class: 'seat-ticket' },
    h('div', { class: 'main-part' },
      h('span', { class: 'head' }, h('span', {}, 'ADMIT ONE'),
        h('span', {}, `${ZONE_NAME[v.zone]} · ROW ${row} · SEAT ${num_}`)),
      h('span', { class: 'ip' }, v.ip),
      h('span', { class: 'story' }, v.story),
      h('span', { class: 'mono', style: { fontSize: '13px' } },
        `${v.tries} login tr${v.tries === 1 ? 'y' : 'ies'} · ${v.commands} command${v.commands === 1 ? '' : 's'} · ${v.uploads} file${v.uploads === 1 ? '' : 's'}`),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn', onclick: () => exportScene(v.ip) }, 'Export their scene'),
        isBanned
          ? h('button', { type: 'button', class: 'btn', onclick: () => setBlock(v.ip, false) }, 'Let them back in')
          : h('button', { type: 'button', class: 'btn danger', onclick: () => setBlock(v.ip, true) }, 'Show them out'))),
    h('div', { class: 'stub' },
      h('span', {}, v.services.map((s) => s.toUpperCase()).join(' · ')),
      h('span', {}, `first seen ${clock(v.first_seen)}`),
      h('span', {}, `last ${ago(v.last_seen)}`),
      isBanned ? h('span', { class: 'out' }, 'BLOCKED') : null)));
}

async function setBlock(ip, block) {
  if (block && !confirm(`Show ${ip} out? Every service will refuse it from now on, also after a restart.`)) return;
  try {
    await api(block ? '/api/block' : '/api/unblock', { method: 'POST', body: { ip } });
    toast(block ? `${ip} was shown out.` : `${ip} may come back in.`);
    refresh();
  } catch (e) { toast(e.message); }
}

async function exportScene(ip) {
  const data = await api(`/api/visitor/${encodeURIComponent(ip)}`);
  const lines = data.events.map((e) => JSON.stringify({ client_ip: ip, ...e })).join('\n') + '\n';
  const url = URL.createObjectURL(new Blob([lines], { type: 'application/x-ndjson' }));
  const a = h('a', { href: url, download: `mimic-${ip.replace(/[:.]/g, '_')}.jsonl` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
