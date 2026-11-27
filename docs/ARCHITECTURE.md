# MIMIC dashboard — architecture decisions

Each decision lists the options considered and why one won. The guiding
constraints:

1. **MIMIC is attacked by design.** Anything we add must not widen the
   attack surface of the machine it runs on.
2. **`pip install -r requirements.txt` and run.** No Node toolchain, no
   database server, no build step for people who just want to use it.
3. **Few dependencies.** Every dependency is code we ship to a hostile
   environment and must keep patched.

---

## 1. One process, one event loop

The dashboard runs **inside the honeypot process**, on the same asyncio
loop as the services (`python main.py --dashboard`).

| Option | Verdict |
|---|---|
| Separate dashboard process that starts/kills `main.py` (what the pygame GUI does with `taskkill` / `pkill`) | Rejected: fragile, kills by window title, no way to ask the honeypot for its state |
| **Same process, same loop** | **Chosen**: the dashboard calls the controller directly to start/stop services and block IPs; no IPC |

Headless mode (`python main.py`) is unchanged and does not load any
dashboard code.

## 2. Web framework: aiohttp

| Option | Verdict |
|---|---|
| FastAPI + uvicorn | Rejected: pulls in pydantic, starlette, uvicorn and friends; uvicorn wants to own the event loop |
| Flask / Django | Rejected: synchronous, would need threads next to the asyncio honeypot |
| **aiohttp** | **Chosen**: one dependency giving HTTP server, static files and streaming responses; runs on an *existing* loop via `AppRunner` |

## 3. Live updates: Server-Sent Events, "push invalidation, pull data"

| Option | Verdict |
|---|---|
| Polling | Rejected: laggy or wasteful |
| WebSockets | Rejected: two-way channel we don't need |
| **SSE** | **Chosen**: one-way, plain HTTP, the browser's `EventSource` reconnects by itself |

The stream only says *"something changed"*. The page then re-fetches the
small JSON views it shows. That keeps one source of truth (the API) instead
of merging partial updates in the browser, and the update rate is
throttled server-side so a brute-force flood can't flood the browser.

## 4. Storage: JSON Lines stay the truth, SQLite is a rebuildable index

The honeypot already writes `logs/*_honeypot.jsonl` (see LOG_FORMAT.md).
The dashboard needs aggregates: top passwords, files grouped by hash,
visitors grouped by IP.

| Option | Verdict |
|---|---|
| Re-scan the JSONL files on every request | Rejected: gets slower every day the honeypot runs |
| In-memory aggregates rebuilt at start | Rejected: start-up time grows with log size; lost on restart anyway |
| PostgreSQL / Elasticsearch | Rejected: a server to install, secure and patch, for one user |
| **SQLite (Python stdlib)** | **Chosen**: zero dependencies, real `GROUP BY` queries, survives restarts |

How it fits together:

- Services keep writing JSONL exactly as before; analysts can still use `jq`.
- `dashboard/store.py` **tails** those files and inserts new lines into
  `logs/mimic.db`, remembering the byte offset per file. Start-up only reads
  what is new.
- Delete `mimic.db` and it is rebuilt from the JSONL. The index can never
  become the only copy of the data.
- All SQLite work runs on **one dedicated worker thread**, so a slow query
  never blocks the honeypot's event loop.

## 5. Front end: plain HTML, CSS and JavaScript modules

| Option | Verdict |
|---|---|
| React / Vue / Svelte + Vite | Rejected: needs Node and a build step for every contributor; heavy for three screens |
| htmx + server templates | Rejected: adds Jinja2; the screens are mostly client-side interaction (seats, tags, live preview) |
| **Vanilla ES modules, no build** | **Chosen**: the browser runs the files we ship; nothing to install |

Fonts (IBM Plex, Instrument Serif, SIL OFL) are **vendored** in
`dashboard/static/fonts`: the dashboard makes **no third-party requests**,
works offline and doesn't tell Google who runs a honeypot.

## 6. Security of the dashboard itself

The dashboard can stop the honeypot, rewrite its config and reveal every
captured password. It must never be reachable by the audience.

- **Binds to `127.0.0.1` by default.** Use an SSH tunnel to reach it
  remotely. Binding elsewhere prints a loud warning.
- **Access token.** A random token is generated at start and printed as a
  link. Opening it sets an `HttpOnly`, `SameSite=Strict` cookie; every API
  call needs that cookie.
- **Host header check** blocks DNS-rebinding attacks from web pages the
  operator visits.
- **Origin check** on every state-changing request blocks cross-site
  requests.
- **No file downloads of captured malware** through the browser. The
  dashboard shows the SHA-256 and the path on disk; analysis happens on an
  isolated machine. Serving malware over HTTP adds risk and no value.
- Static files are served from a fixed directory; API responses are JSON
  and rendered with `textContent`, never `innerHTML`, because every string
  in them (usernames, commands, filenames) was typed by an attacker.

## 7. What the seats mean (the house)

Position is data, not decoration. Each visitor (IP, last 24 h) gets a seat:

| Zone | Rows | Rule |
|---|---|---|
| Front row | A | Logged in **and acted**: a command reached the fake shell, or a file was actually captured. Refused actions (e.g. an FTP upload when uploads are off) do not count |
| Stalls | B–C | Logged in, but did nothing more |
| Back | D | Tried to log in, always refused |
| Back | E | Only connected (or only sent HTTP/MySQL requests) |

Colour repeats how the door treated them: mint = got in, pink = refused,
grey = only knocked.

## 8. Operator blocklist

"Show them out" adds the IP to `config/blocklist.txt` (git-ignored). Every
service checks it before talking to a client, independently of the
automatic rate-limit blocks in `SecurityLayer`. It survives restarts.
