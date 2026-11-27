// PLAYBILL: the honeypot's configuration, written as a theatre programme.
import { $, h, api, toast } from './dom.js';
import { refresh, refreshStatus } from './app.js';

// Each service as a cast member: the italic line says what the door is for.
const ROLES = {
  ssh: ['SSH', 'the remote shell'],
  ftp: ['FTP', 'where files are dropped'],
  telnet: ['Telnet', 'the old, unlocked door'],
  http: ['HTTP', 'the web front'],
  mysql: ['MySQL', 'the database'],
  rdp: ['RDP', 'understudy, not on stage yet'],
};
const PLANNED = new Set(['rdp']);

// Exactly what core/service_emulator/ssh_emulator.py prints after login.
const WELCOME = {
  Ubuntu: 'Welcome to Ubuntu 18.04.6 LTS (GNU/Linux 4.15.0-20-generic x86_64)\n\n * Documentation:  https://help.ubuntu.com\n * Management:     https://landscape.canonical.com\n * Support:        https://ubuntu.com/advantage',
  Debian: 'Debian GNU/Linux 11 (bullseye)\n\n * Documentation:  https://www.debian.org/doc/\n * Support:        https://www.debian.org/support',
  CentOS: 'CentOS Linux release 7.9.2009 (Core)\n\n * Documentation:  https://docs.centos.org/\n * Support:        https://www.centos.org/',
  Windows: 'Microsoft Windows Server 2019 Standard\n(c) 2019 Microsoft Corporation. All rights reserved.',
};

let draft = null;      // working copy of the config
let services = [];     // [{port, ...serviceConfig}] so ports can be edited
let wired = false;

export async function render(state) {
  wire();
  const running = state.status.running;
  // Only reload from the server when not mid-edit, or when the show is running.
  // Live updates must not rebuild the form under the operator's cursor.
  if (draft && !running && $('#playbill').contains(document.activeElement)) return;
  if (!draft || running) {
    const { config } = await api('/api/config');
    draft = structuredClone(config);
    services = Object.entries(config.services || {}).map(([port, s]) => ({ port: String(port), ...s }));
  }
  fill(running);
}

function wire() {
  if (wired) return;
  wired = true;
  const form = $('#playbill');
  const os = form.elements.os_template;
  os.replaceChildren(...Object.keys(WELCOME).map((k) => h('option', { value: k }, k)));

  for (const name of ['hostname', 'os_template', 'username', 'password']) {
    form.elements[name].addEventListener('input', (e) => {
      draft.system = draft.system || {};
      draft.system[name] = e.target.value;
      rehearse();
    });
  }
  form.elements.brute_force_attempts.addEventListener('input', (e) => {
    draft.options = draft.options || {};
    draft.options.brute_force_attempts = Number(e.target.value) || 1;
    rehearse();
  });
  form.querySelectorAll('.mode').forEach((b) => b.addEventListener('click', () => {
    draft.options = draft.options || {};
    draft.options.any_auth = b.dataset.any === 'true';
    fill(false);
  }));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if ($('#launch').classList.contains('stop')) {
      await api('/api/stop', { method: 'POST' });
      toast('Curtains closed. You can edit the playbill now.');
      draft = null;
      return refresh();
    }
    await launch();
  });
}

function fill(running) {
  const form = $('#playbill');
  const sys = draft.system || {}, opt = draft.options || {};
  $('#pb-fields').disabled = running;
  form.elements.hostname.value = sys.hostname || '';
  form.elements.os_template.value = WELCOME[sys.os_template] ? sys.os_template : 'Ubuntu';
  form.elements.username.value = sys.username || '';
  form.elements.password.value = sys.password || '';
  form.elements.brute_force_attempts.value = opt.brute_force_attempts ?? 1;
  const any = opt.any_auth !== false;
  form.querySelectorAll('.mode').forEach((b) => b.setAttribute('aria-checked', String((b.dataset.any === 'true') === any)));
  $('#hard-to-get').hidden = !any;

  $('#cast').replaceChildren(...services.map((s, i) => {
    const [name, role] = ROLES[s.type] || [s.type, ''];
    const planned = PLANNED.has(s.type);
    const on = s.enabled !== false && !planned;
    return h('li', { class: on ? '' : 'off' },
      h('span', { class: 'name' }, name, h('small', {}, role)),
      h('span', { class: 'dots', 'aria-hidden': 'true' }),
      h('span', { class: 'port' }, `port ${s.port}`),
      planned
        ? h('span', { class: 'muted', style: { width: '52px', fontSize: '12px', textAlign: 'center' } }, 'soon')
        : h('button', { type: 'button', class: 'switch', role: 'switch', 'aria-checked': String(on),
                        'aria-label': `${name} on port ${s.port}`,
                        onclick: () => { services[i].enabled = !on; fill(false); } }));
  }));

  const sec = draft.security || {};
  const rl = sec.rate_limits || {};
  $('#backstage').replaceChildren(
    ...services.filter((s) => !PLANNED.has(s.type)).flatMap((s) => [
      field(`${(ROLES[s.type] || [s.type])[0]} port`, s.port, (v) => { s.port = v; }, { inputmode: 'numeric' }),
      field(`${(ROLES[s.type] || [s.type])[0]} banner (first words it says)`, s.banner || '', (v) => { s.banner = v; }),
    ]),
    field('Door security on (rate limits, auto-blocking)', '', null, { type: 'checkbox', checked: sec.enabled !== false,
      onchange: (e) => { draft.security = { ...(draft.security || {}), enabled: e.target.checked }; } }),
    field('Failed logins before an IP is blocked', rl.max_failed_logins ?? 10,
      (v) => setLimit('max_failed_logins', v), { type: 'number', min: 1 }),
    field('Block lasts (minutes)', rl.block_duration_minutes ?? 60,
      (v) => setLimit('block_duration_minutes', v), { type: 'number', min: 1 }),
  );

  const doors = services.filter((s) => s.enabled !== false && !PLANNED.has(s.type)).length;
  const launchBtn = $('#launch');
  launchBtn.classList.toggle('stop', running);
  $('#launch-k').textContent = running ? 'THE SHOW IS ON' : `OPENING NIGHT · ${doors} DOOR${doors === 1 ? '' : 'S'}`;
  $('#launch-t').textContent = running ? 'Close the curtains to edit' : 'Let the show begin';
  launchBtn.disabled = !running && doors === 0;
  rehearse();
}

function setLimit(key, value) {
  const sec = draft.security || {};
  draft.security = { ...sec, rate_limits: { ...(sec.rate_limits || {}), [key]: Number(value) } };
}

function field(label, value, onInput, extra = {}) {
  const { onchange, checked, ...attrs } = extra;
  const input = h('input', { value, ...attrs, onchange, checked: checked || null,
    oninput: onInput ? (e) => { onInput(e.target.value); rehearse(); } : null });
  const wide = attrs.type === 'checkbox' || /banner/.test(label);
  return h('label', { class: wide ? 'wide' : '' }, label, input);
}

function rehearse() {
  const sys = draft.system || {}, opt = draft.options || {};
  const user = sys.username || 'admin', host = sys.hostname || 'server';
  const ssh = services.find((s) => s.type === 'ssh' && s.enabled !== false);
  let text;
  if (!ssh) {
    text = '# SSH is off in this playbill:\n# nobody can open a shell.';
  } else {
    const any = opt.any_auth !== false;
    const n = Number(opt.brute_force_attempts) || 1;
    const port = ssh.port === '22' ? '' : ` -p ${ssh.port}`;
    const tries = any && n > 1
      ? Array.from({ length: n - 1 }, () => `${user}@${host}'s password:\nPermission denied, please try again.`).join('\n') + '\n'
      : '';
    const rule = any
      ? `# house rule: open house. Try ${n} lets them in, whatever the password.`
      : `# house rule: invitation only. Only "${sys.password || ''}" works.`;
    text = `$ ssh ${user}@${host}${port}\n${tries}${user}@${host}'s password:\n` +
      `${WELCOME[sys.os_template] || WELCOME.Ubuntu}\n\n` +
      `Last login: ${new Date().toDateString()} from 203.0.113.41\n${user}@${host}:~$ \n\n${rule}`;
  }
  $('#rehearsal').textContent = text;
}

async function launch() {
  const errors = $('#pb-errors');
  const results = $('#pb-results');
  errors.replaceChildren();
  results.replaceChildren();
  const config = structuredClone(draft);
  config.services = {};
  for (const { port, ...svc } of services) {
    if (config.services[port]) {
      errors.replaceChildren(h('li', {}, `Two doors use port ${port}. Each needs its own.`));
      return;
    }
    config.services[port] = svc;
  }
  try {
    await api('/api/config', { method: 'PUT', body: { config } });
    const res = await api('/api/start', { method: 'POST' });
    results.replaceChildren(...res.results.map((r) => h('li', { class: r.ok ? 'in' : 'out' },
      `${r.ok ? '✓' : '✗'} ${(ROLES[r.type] || [r.type])[0]} on port ${r.port}${r.ok ? ' is on stage' : `: ${r.error}`}`)));
    toast(res.running ? 'Curtain up. The honeypot is live.' : 'No door could open. See the list below.');
    draft = null;
    await refreshStatus();
    if (res.running && res.results.every((r) => r.ok || r.type === 'rdp')) location.hash = '#stage';
    else refresh();
  } catch (e) {
    errors.replaceChildren(...e.errors.map((m) => h('li', {}, m)));
  }
}
