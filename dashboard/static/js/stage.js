// THE STAGE: the script (what happened) and the house (who is in the room).
import { $, h, api, num, clock, ago, toast } from './dom.js';
import { refresh } from './app.js';

// The two back zones say how they differ, so neither is just "BACK".
const ZONE_TEXT = {
  front: { title: 'FRONT ROW', color: 'var(--text)', desc: 'got in and acted: ran shell commands or left a file' },
  stalls: { title: 'STALLS', color: 'var(--muted)', desc: 'got in, but did nothing more' },
  refused: { title: 'BACK · REFUSED', color: 'var(--dim)', desc: 'tried to log in, always refused' },
  knocked: { title: 'BACK · KNOCKED', color: 'var(--dim)', desc: 'only knocked, never tried a password' },
};

// Protocol plumbing: commands every FTP client sends on its own. They are kept, but folded
// into one dim line, so what shows intent (logins, real commands, files) reads first.
const ROUTINE = new Set(['USER', 'PASS', 'TYPE', 'PASV', 'EPSV', 'PORT', 'EPRT', 'SYST', 'FEAT',
  'NOOP', 'PWD', 'XPWD', 'QUIT', 'OPTS', 'MODE', 'STRU', 'AUTH', 'CLNT']);
const isRoutine = (service, ln) => ln.kind === 'command' && service !== 'ssh'
  && ROUTINE.has(String(ln.text).split(' ')[0].toUpperCase());
// '$' marks a real shell command (SSH); '›' a protocol command (FTP, HTTP, MySQL).
const STATUS_WORD = { in: 'got in', out: 'refused', knock: 'only knocked' };

let picked = null;   // ip of the selected seat
let onlyPicked = false;   // script shows only the picked visitor's scenes

export async function render(state) {
  const data = await api('/api/stage');
  const { house, script, headline, blocked } = data;
  const banned = new Set(blocked);

  $('#n-visitors').textContent = num(headline.visitors);
  $('#n-tries').textContent = num(headline.tries);
  $('#n-files').textContent = num(headline.files);
  // The headline states the facts: is the show on, and is anyone there?
  $('#headline').textContent = !state.status.running
    ? 'Between shows.'
    : headline.visitors ? 'The audience is watching.' : 'An empty house, for now.';

  if (!picked || !house.visitors[picked]) {
    // Default spotlight: the visitor who got deepest, most recently.
    const order = ['front', 'stalls', 'refused', 'knocked'];
    const all = Object.values(house.visitors).sort((a, b) =>
      order.indexOf(a.zone) - order.indexOf(b.zone) || (b.last_seen > a.last_seen ? 1 : -1));
    picked = all.length ? all[0].ip : null;
  }

  renderScript(script, house);
  renderHouse(house, banned);
  renderTicket(house.visitors[picked], banned, script.filter((sc) => sc.ip === picked));
}

function renderScript(scenes, house) {
  const box = $('#scenes');
  const bar = $('#script-bar');
  if (!scenes.length) {
    bar.replaceChildren();
    box.replaceChildren(h('p', { class: 'empty' }, 'No scenes yet. The first visitor writes the first line.'));
    return;
  }
  const total = scenes.length;
  const v = picked && house.visitors[picked];
  const theirs = scenes.filter((sc) => sc.ip === picked).length;
  if (!theirs) onlyPicked = false;
  const seatName = v && v.seat ? `seat ${v.seat}` : 'standing';
  const toggle = (only, label) => h('button', {
    type: 'button', class: 'seg', 'aria-pressed': String(onlyPicked === only),
    onclick: () => { onlyPicked = only; refresh(); } }, label);
  bar.replaceChildren(
    h('div', { class: 'segs', role: 'group', 'aria-label': 'Which scenes to show' },
      toggle(false, `Everyone · ${total}`),
      theirs ? toggle(true, `Only ${seatName} · ${theirs}`) : null),
    h('div', { class: 'keys' },
      theirs ? h('span', { class: 'key' }, h('i', { 'aria-hidden': 'true' }),
        `= ${picked}, whose ticket is open`) : null,
      h('span', { class: 'key' }, h('b', { class: 'routine-sample' }, '› TYPE · PASV'),
        ' dim = routine protocol commands')));

  const shown = scenes.map((sc, i) => [sc, total - i]).filter(([sc]) => !onlyPicked || sc.ip === picked);
  box.replaceChildren(...shown.map(([sc, n]) => {
    const seen = house.visitors[sc.ip];
    const seat = seen && seen.seat ? `seat ${seen.seat}` : 'standing';
    const tone = sc.uploads ? 'out' : sc.tone;
    return h('article', { class: 'scene' + (sc.ip === picked ? ' spot' : '') },
      h('p', { class: 'slug' }, `SCENE ${n} — INT. ${sc.service.toUpperCase()} :${sc.port ?? '?'} — ${clock(sc.end)}`),
      h('div', { class: 'body' },
        h('p', { class: 'cue' },
          h('span', { class: 'who' },
            h('button', { type: 'button', onclick: () => { picked = sc.ip; refresh(); },
                          'aria-label': `Show ticket for ${sc.ip}` }, sc.ip ?? 'unknown'),
            ' ', h('span', { class: 'seatno' }, `· ${seat}`)),
          h('span', { class: `dir ${tone}` }, `(${sc.direction})`)),
        h('div', { class: 'lines' }, sceneLines(sc))));
  }));
}

function sceneLines(sc) {
  const out = [];
  let fold = [];
  const flush = () => {
    if (fold.length) out.push(h('span', { class: 'line routine', title: 'Routine protocol commands' },
      `› ${fold.join(' · ')}`));
    fold = [];
  };
  for (const ln of sc.lines) {
    if (ln.kind === 'blocked') continue;          // the direction already says "refused at the door"
    if (isRoutine(sc.service, ln)) { fold.push(ln.text); continue; }
    flush();
    out.push(h('span', {
      class: 'line' + (ln.kind === 'login' ? (ln.ok ? ' ok' : ' no') : '') + (ln.kind === 'upload' ? ' upload' : ''),
    }, ln.kind === 'command' ? `${sc.service === 'ssh' ? '$' : '›'} ${ln.text}`
      : ln.kind === 'upload' ? `⇪ ${ln.text}` : ln.text));
  }
  flush();
  return out;
}

function renderHouse(house, banned) {
  const zones = house.zones.map((z) => h('div', { class: 'zone' },
    h('div', { class: 'zone-head' },
      h('span', { class: 't', style: { color: ZONE_TEXT[z.key].color } }, ZONE_TEXT[z.key].title),
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

function renderTicket(v, banned, scenes) {
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
      scenes.length > 1 ? h('span', { class: 'visits' },
        `${scenes.length} scenes on ${v.services.length} door${v.services.length === 1 ? '' : 's'}: everything this IP did sits on this one seat.`) : null,
      h('span', { class: 'mono', style: { fontSize: '13px' } },
        `${v.tries} login tr${v.tries === 1 ? 'y' : 'ies'} · ${v.commands} command${v.commands === 1 ? '' : 's'} · ${v.uploads} file${v.uploads === 1 ? '' : 's'}`),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn', onclick: () => exportScene(v.ip) }, 'Export their scene'),
        isBanned
          ? h('button', { type: 'button', class: 'btn', onclick: () => setBlock(v.ip, false) }, 'Let them back in')
          : h('button', { type: 'button', class: 'btn danger', onclick: () => setBlock(v.ip, true) }, 'Show them out'))),
    h('div', { class: 'stub' },
      h('span', { class: 'doors' }, v.services.map((s) => h('span', {}, s.toUpperCase()))),
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
