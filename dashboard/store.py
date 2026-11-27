"""Read-side of the dashboard: a SQLite index over the JSONL logs.

The JSONL files stay the source of truth (docs/ARCHITECTURE.md §4). This
module tails them into logs/mimic.db and answers the queries the three
screens need. Every method here is blocking and must run on the single
worker thread owned by `Store` (use `await store.call(fn, ...)`).
"""
import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,
    service    TEXT NOT NULL,
    port       INTEGER,
    ip         TEXT,
    username   TEXT,
    password   TEXT,
    success    INTEGER,
    command    TEXT,
    filename   TEXT,
    size       INTEGER,
    sha256     TEXT,
    saved_path TEXT
);
CREATE INDEX IF NOT EXISTS events_ts  ON events(ts);
CREATE INDEX IF NOT EXISTS events_ip  ON events(ip, ts);
CREATE INDEX IF NOT EXISTS events_ev  ON events(event, ts);
CREATE TABLE IF NOT EXISTS sources (
    path   TEXT PRIMARY KEY,
    offset INTEGER NOT NULL
);
"""

# The house: zone rules (docs/ARCHITECTURE.md §7). Order matters: first match wins.
ZONES = [
    # key,     title,       rows (name, seats)
    ("front", "FRONT ROW", [("A", 8)]),
    ("stalls", "STALLS", [("B", 10), ("C", 12)]),
    ("refused", "BACK", [("D", 12)]),
    ("knocked", "BACK", [("E", 14)]),
]

# Services that offer a login. A visitor of HTTP/MySQL only can never be past row E.
LOGIN_SERVICES = ("ssh", "ftp", "telnet")


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self, log_dir: Path = Path("logs"), db_path: Optional[Path] = None):
        self.log_dir = Path(log_dir)
        self.db_path = Path(db_path) if db_path else self.log_dir / "mimic.db"
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mimic-store")
        self._db: Optional[sqlite3.Connection] = None

    # --- threading -----------------------------------------------------------

    async def call(self, fn, *args):
        """Run a blocking store method on the store's own thread."""
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn, *args)

    def close(self) -> None:
        def _close():
            if self._db:
                self._db.close()
                self._db = None
        self._pool.submit(_close).result()
        self._pool.shutdown(wait=True)

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # One worker thread uses it in production; tests may call it directly.
            self._db = sqlite3.connect(self.db_path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
        return self._db

    # --- ingest --------------------------------------------------------------

    def ingest(self) -> int:
        """Read new complete lines from every logs/*_honeypot.jsonl. Returns rows added."""
        added = 0
        db = self.db
        for path in sorted(self.log_dir.glob("*_honeypot.jsonl")):
            key = str(path.resolve())
            row = db.execute("SELECT offset FROM sources WHERE path=?", (key,)).fetchone()
            offset = row["offset"] if row else 0
            size = path.stat().st_size
            if size < offset:          # file was truncated or replaced: start over
                offset = 0
            if size == offset:
                continue
            with open(path, "rb") as f:
                f.seek(offset)
                chunk = f.read(size - offset)
            end = chunk.rfind(b"\n")
            if end < 0:                # no complete line yet
                continue
            rows = []
            for line in chunk[:end].split(b"\n"):
                rec = self._parse(line)
                if rec:
                    rows.append(rec)
            with db:
                db.executemany(
                    "INSERT INTO events (ts, event, service, port, ip, username, password, success,"
                    " command, filename, size, sha256, saved_path)"
                    " VALUES (:ts,:event,:service,:port,:ip,:username,:password,:success,"
                    " :command,:filename,:size,:sha256,:saved_path)", rows)
                db.execute("INSERT INTO sources (path, offset) VALUES (?, ?)"
                           " ON CONFLICT(path) DO UPDATE SET offset=excluded.offset",
                           (key, offset + end + 1))
            added += len(rows)
        return added

    @staticmethod
    def _parse(line: bytes) -> Optional[Dict[str, Any]]:
        try:
            e = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return None
        if not isinstance(e, dict) or "event" not in e or "timestamp" not in e:
            return None  # pre-v1.2 lines (event_type/source_ip) are ignored

        def text(k):
            v = e.get(k)
            return None if v is None else str(v)[:2000]

        success = e.get("success")
        return {
            "ts": text("timestamp"), "event": text("event"), "service": text("service") or "?",
            "port": e.get("port") if isinstance(e.get("port"), int) else None,
            "ip": text("client_ip"), "username": text("username"), "password": text("password"),
            "success": None if success is None else int(bool(success)),
            "command": text("command"), "filename": text("filename"),
            "size": e.get("size") if isinstance(e.get("size"), int) else None,
            "sha256": text("sha256"), "saved_path": text("saved_path"),
        }

    # --- the house -----------------------------------------------------------

    def _visitors(self, since: str) -> List[Dict[str, Any]]:
        rows = self.db.execute("""
            SELECT ip,
                   MIN(ts) AS first_seen, MAX(ts) AS last_seen,
                   GROUP_CONCAT(DISTINCT service) AS services,
                   SUM(event='login_attempt') AS tries,
                   MAX(event='login_attempt' AND success=1) AS got_in,
                   SUM(event='command' AND service='ssh') AS shell_cmds,
                   SUM(event='file_upload') AS uploads,
                   SUM(event='blocked_connection') AS blocked
            FROM events WHERE ip IS NOT NULL AND ts >= ?
            GROUP BY ip ORDER BY first_seen
        """, (since,)).fetchall()
        out = []
        for r in rows:
            v = dict(r)
            v["services"] = sorted((v["services"] or "").split(","))
            # "Acted" only counts what we can prove happened: a shell command
            # reached the fake shell, or a file was actually captured. A refused
            # FTP STOR is just words.
            if v["got_in"] and (v["shell_cmds"] or v["uploads"]):
                v["zone"] = "front"
            elif v["got_in"]:
                v["zone"] = "stalls"
            elif v["tries"]:
                v["zone"] = "refused"
            else:
                v["zone"] = "knocked"
            v["status"] = "in" if v["got_in"] else ("out" if v["tries"] or v["blocked"] else "knock")
            out.append(v)
        return out

    def _first_login(self, ip: str) -> Optional[sqlite3.Row]:
        return self.db.execute(
            "SELECT username, service FROM events WHERE ip=? AND event='login_attempt' AND success=1"
            " ORDER BY ts LIMIT 1", (ip,)).fetchone()

    def _story(self, v: Dict[str, Any]) -> str:
        """One plain sentence describing what this visitor did. Facts only."""
        svc = " and ".join(s.upper() for s in v["services"])
        if v["zone"] in ("front", "stalls"):
            login = self._first_login(v["ip"])
            who = f"Got in to {login['service'].upper()} as {login['username']!s}" if login else "Got in"
            parts = []
            if v["shell_cmds"]:
                parts.append(f"ran {v['shell_cmds']} command{'s' * (v['shell_cmds'] != 1)}")
            if v["uploads"]:
                parts.append(f"left {v['uploads']} file{'s' * (v['uploads'] != 1)} behind")
            return who + (" and " + " and ".join(parts) if parts else ", then did nothing") + "."
        if v["zone"] == "refused":
            n = v["tries"]
            return f"Tried {n} password{'s' * (n != 1)} on {svc}. All refused."
        if v["blocked"]:
            return f"Knocked on {svc} but was blocked at the door."
        return f"Knocked on {svc} and left without trying to log in."

    def house(self, hours: int = 24) -> Dict[str, Any]:
        since = _utc(datetime.now(timezone.utc) - timedelta(hours=hours))
        visitors = self._visitors(since)
        by_zone: Dict[str, List[Dict[str, Any]]] = {z[0]: [] for z in ZONES}
        for v in visitors:
            by_zone[v["zone"]].append(v)

        zones, seats = [], {}
        for key, title, rows in ZONES:
            queue = list(by_zone[key])  # oldest first: seats fill left to right by arrival
            out_rows = []
            for name, n in rows:
                row_seats = []
                for i in range(1, n + 1):
                    if queue:
                        v = queue.pop(0)
                        seat = f"{name}{i}"
                        seats[v["ip"]] = seat
                        row_seats.append({"seat": seat, "ip": v["ip"], "status": v["status"]})
                    else:
                        row_seats.append({"seat": f"{name}{i}", "ip": None, "status": None})
                out_rows.append({"name": name, "seats": row_seats})
            zones.append({"key": key, "title": title, "rows": out_rows, "standing": len(queue)})

        return {
            "hours": hours,
            "zones": zones,
            "visitors": {
                v["ip"]: {
                    "ip": v["ip"], "seat": seats.get(v["ip"]), "zone": v["zone"], "status": v["status"],
                    "services": v["services"], "first_seen": v["first_seen"], "last_seen": v["last_seen"],
                    "tries": v["tries"], "commands": v["shell_cmds"], "uploads": v["uploads"],
                    "story": self._story(v),
                } for v in visitors
            },
        }

    # --- the script ----------------------------------------------------------

    def script(self, limit_scenes: int = 30) -> List[Dict[str, Any]]:
        """Recent activity as scenes: consecutive events of one IP on one service."""
        rows = self.db.execute("""
            SELECT ts, event, service, port, ip, username, password, success, command, filename, size
            FROM events WHERE event IN ('login_attempt','command','file_upload','blocked_connection')
            ORDER BY ts DESC, id DESC LIMIT 600
        """).fetchall()
        scenes: List[Dict[str, Any]] = []
        for r in rows:  # newest first
            cur = scenes[-1] if scenes else None
            if not cur or cur["ip"] != r["ip"] or cur["service"] != r["service"]:
                if len(scenes) == limit_scenes:
                    break
                cur = {"ip": r["ip"], "service": r["service"], "port": r["port"], "start": r["ts"],
                       "end": r["ts"], "lines": [], "got_in": False, "refused": 0,
                       "uploads": 0, "commands": 0, "blocked": False}
                scenes.append(cur)
            cur["start"] = r["ts"]
            if r["event"] == "login_attempt":
                if r["success"]:
                    cur["got_in"] = True
                    cur["user"] = r["username"]
                else:
                    cur["refused"] += 1
                pw = "(anonymous)" if r["password"] is None else r["password"]
                cur["lines"].append({"kind": "login", "ok": bool(r["success"]),
                                     "text": f"{r['username']} / {pw}"})
            elif r["event"] == "command":
                cur["commands"] += 1
                cur["lines"].append({"kind": "command", "text": r["command"]})
            elif r["event"] == "file_upload":
                cur["uploads"] += 1
                cur["lines"].append({"kind": "upload", "text": f"{r['filename']} ({r['size']} bytes)"})
            else:
                cur["blocked"] = True
                cur["lines"].append({"kind": "blocked", "text": "refused at the door"})

        for s in scenes:
            s["lines"].reverse()            # read top to bottom in time order
            del s["lines"][12:]              # a scene shows its first 12 lines
            if s["uploads"]:
                s["direction"] = "left a file behind"
            elif s["got_in"]:
                s["direction"] = f"gets in as {s.get('user')}"
            elif s["blocked"]:
                s["direction"] = "is refused at the door"
            else:
                s["direction"] = ("is turned away" if s["refused"]
                                  else "carries on talking" if s["commands"] else "says something")
            s["tone"] = "in" if s["got_in"] else "out"
        return scenes

    # --- headline numbers ----------------------------------------------------

    def headline(self, hours: int = 24) -> Dict[str, int]:
        since = _utc(datetime.now(timezone.utc) - timedelta(hours=hours))
        r = self.db.execute("""
            SELECT COUNT(DISTINCT ip) AS visitors,
                   SUM(event='login_attempt') AS tries
            FROM events WHERE ts >= ?""", (since,)).fetchone()
        files = self.db.execute(
            "SELECT COUNT(DISTINCT sha256) FROM events WHERE event='file_upload'").fetchone()[0]
        return {"visitors": r["visitors"] or 0, "tries": r["tries"] or 0, "files": files or 0}

    # --- lost & found --------------------------------------------------------

    def captures(self) -> Dict[str, Any]:
        files = [dict(r) for r in self.db.execute("""
            SELECT sha256, MAX(filename) AS filename, MAX(size) AS size, COUNT(*) AS times,
                   MIN(ts) AS first_seen, MAX(ts) AS last_seen,
                   GROUP_CONCAT(DISTINCT ip) AS ips, MAX(saved_path) AS saved_path
            FROM events WHERE event='file_upload' AND sha256 IS NOT NULL
            GROUP BY sha256 ORDER BY last_seen DESC
        """)]
        for f in files:
            f["ips"] = sorted((f["ips"] or "").split(","))
        creds = [dict(r) for r in self.db.execute("""
            SELECT username, password, COUNT(*) AS times, COUNT(DISTINCT ip) AS ips
            FROM events WHERE event='login_attempt' AND password IS NOT NULL
            GROUP BY username, password ORDER BY times DESC, ips DESC LIMIT 6
        """)]
        return {"files": files, "credentials": creds}

    def visitor_events(self, ip: str, limit: int = 500) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT ts, event, service, port, username, password, success, command, filename, size, sha256"
            " FROM events WHERE ip=? ORDER BY ts, id LIMIT ?", (ip, limit))]
