// Router, live updates and the "is the show on?" state shared by every view.
import { $, api, duration, toast } from './dom.js';
import * as stage from './stage.js';
import * as playbill from './playbill.js';
import * as lostfound from './lostfound.js';

const views = { stage, playbill, lostfound };
export const state = { status: { running: false, services: [] }, view: null };

function current() {
  const v = location.hash.slice(1);
  return views[v] ? v : 'stage';
}

async function show() {
  const name = current();
  state.view = name;
  for (const key of Object.keys(views)) $(`#view-${key}`).hidden = key !== name;
  document.querySelectorAll('nav.main a').forEach((a) => {
    if (a.dataset.view === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  await refresh();
}

export async function refreshStatus() {
  state.status = await api('/api/status');
  const s = state.status;
  // The frame itself shows the state: curtains drawn in + still mask = stopped.
  document.body.classList.toggle('open', s.running);
  document.body.classList.toggle('closed', !s.running);
  const live = s.services.filter((x) => x.running).length;
  $('#state').textContent = s.running
    ? `CURTAINS OPEN · ${live} DOOR${live === 1 ? '' : 'S'} LIVE`
    : 'CURTAINS CLOSED · HONEYPOT STOPPED';
  $('#stop').hidden = !s.running;
  $('#open').hidden = s.running || state.view === 'playbill';
  $('#running').textContent = s.running
    ? `Curtain up · running ${duration(s.started_at)}`
    : 'Curtains closed · nobody can get in right now';
}

let busy = false, again = false;
async function refresh() {
  if (busy) { again = true; return; }
  busy = true;
  try {
    await refreshStatus();
    await views[state.view].render(state);
  } catch (e) {
    toast(e.message);
  } finally {
    busy = false;
    if (again) { again = false; refresh(); }
  }
}
export { refresh };

$('#stop').addEventListener('click', async () => {
  if (!confirm('Close the curtains? Every honeypot service stops until you start it again.')) return;
  await api('/api/stop', { method: 'POST' });
  toast('Curtains closed. The honeypot is stopped.');
  refresh();
});

window.addEventListener('hashchange', show);

// Server-Sent Events only say "something changed"; we then re-fetch what this
// view shows. EventSource reconnects on its own if MIMIC restarts.
const es = new EventSource('/api/events');
es.addEventListener('changed', () => refresh());

// Keep relative times ("running 12 min") honest without new events.
setInterval(() => { if (state.status.running) refreshStatus().catch(() => {}); }, 60000);

show();
