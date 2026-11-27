"""Dashboard: seat rules, the SQLite index, and the web server's guards."""
import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core import blocklist
from dashboard.server import COOKIE, Dashboard
from dashboard.store import Store


def write_events(log_dir: Path, service: str, events):
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / f"{service}_honeypot.jsonl", "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps({"timestamp": "2099-01-01T10:00:00.000Z", "service": service,
                                "port": 22, **e}) + "\n")


def ev(ip, event, **kw):
    return {"client_ip": ip, "event": event, **kw}


@pytest.fixture
def store(tmp_path):
    s = Store(log_dir=tmp_path / "logs")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def isolated_blocklist(tmp_path, monkeypatch):
    monkeypatch.setattr(blocklist, "PATH", tmp_path / "blocklist.txt")


# --- the house: row = how deep they got -------------------------------------

def test_zones_follow_the_rules(store, tmp_path):
    logs = tmp_path / "logs"
    write_events(logs, "ssh", [
        ev("10.0.0.1", "connection"),                                               # knocked
        ev("10.0.0.2", "login_attempt", username="root", password="x", success=False),  # refused
        ev("10.0.0.3", "login_attempt", username="admin", password="admin", success=True),  # stalls
        ev("10.0.0.4", "login_attempt", username="root", password="1", success=True),
        ev("10.0.0.4", "command", username="root", command="cat /etc/passwd"),      # front
    ])
    write_events(logs, "ftp", [
        ev("10.0.0.5", "login_attempt", username="anonymous", password=None, success=True),
        ev("10.0.0.5", "file_upload", username="anonymous", filename="x.sh", size=3, sha256="ab"),  # front
        ev("10.0.0.6", "login_attempt", username="anonymous", password=None, success=True),
        ev("10.0.0.6", "command", username="anonymous", command="LIST"),           # looking is not acting
    ])
    assert store.ingest() == 9
    v = store.house()["visitors"]
    assert {ip: x["zone"] for ip, x in v.items()} == {
        "10.0.0.1": "knocked", "10.0.0.2": "refused", "10.0.0.3": "stalls",
        "10.0.0.4": "front", "10.0.0.5": "front", "10.0.0.6": "stalls"}
    assert v["10.0.0.4"]["seat"] == "A1" and v["10.0.0.5"]["seat"] == "A2"   # by arrival
    assert v["10.0.0.2"]["seat"].startswith("D") and v["10.0.0.1"]["seat"].startswith("E")
    assert v["10.0.0.4"]["story"] == "Got in to SSH as root and ran 1 command."


def test_overflow_is_counted_not_dropped(store, tmp_path):
    write_events(tmp_path / "logs", "ssh", [ev(f"10.1.0.{i}", "connection") for i in range(20)])
    store.ingest()
    knocked = [z for z in store.house()["zones"] if z["key"] == "knocked"][0]
    assert knocked["standing"] == 6   # row E has 14 seats


def test_ingest_is_incremental_and_waits_for_full_lines(store, tmp_path):
    logs = tmp_path / "logs"
    write_events(logs, "ssh", [ev("10.0.0.1", "connection")])
    assert store.ingest() == 1
    assert store.ingest() == 0
    with open(logs / "ssh_honeypot.jsonl", "a", encoding="utf-8") as f:
        f.write('{"timestamp": "2099-01-01T10:00:01Z", "event": "conn')   # half-written line
    assert store.ingest() == 0
    with open(logs / "ssh_honeypot.jsonl", "a", encoding="utf-8") as f:
        f.write('ection", "service": "ssh", "client_ip": "10.0.0.9"}\n')
    assert store.ingest() == 1


def test_db_is_rebuildable_from_jsonl(tmp_path):
    logs = tmp_path / "logs"
    write_events(logs, "ssh", [ev("10.0.0.1", "connection"), ev("10.0.0.2", "connection")])
    s = Store(log_dir=logs); s.ingest(); s.close()
    (logs / "mimic.db").unlink()
    s = Store(log_dir=logs)
    try:
        assert s.ingest() == 2
    finally:
        s.close()


def test_captures_group_by_hash_and_rank_credentials(store, tmp_path):
    write_events(tmp_path / "logs", "ftp", [
        ev("10.0.0.1", "file_upload", filename="a.sh", size=4, sha256="h1"),
        ev("10.0.0.2", "file_upload", filename="a.sh", size=4, sha256="h1"),
        ev("10.0.0.1", "login_attempt", username="root", password="toor", success=False),
        ev("10.0.0.2", "login_attempt", username="root", password="toor", success=False),
        ev("10.0.0.2", "login_attempt", username="admin", password="1", success=False),
    ])
    store.ingest()
    c = store.captures()
    assert len(c["files"]) == 1 and c["files"][0]["times"] == 2
    assert c["files"][0]["ips"] == ["10.0.0.1", "10.0.0.2"]
    assert c["credentials"][0] == {"username": "root", "password": "toor", "times": 2, "ips": 2}


# --- blocklist ----------------------------------------------------------------

def test_blocklist_persists_and_rejects_garbage(tmp_path):
    blocklist.block("203.0.113.7")
    assert blocklist.is_blocked("203.0.113.7")
    assert "203.0.113.7" in (tmp_path / "blocklist.txt").read_text()
    with pytest.raises(ValueError):
        blocklist.block("not-an-ip; rm -rf /")
    blocklist.unblock("203.0.113.7")
    assert not blocklist.is_blocked("203.0.113.7")


def test_blocked_ip_is_refused_by_services(tmp_path, monkeypatch):
    from core.service_emulator.telnet_emulator import TelnetService
    from log_system import events
    monkeypatch.setattr(events, "LOG_DIR", tmp_path / "logs")
    blocklist.block("127.0.0.1")

    async def scenario():
        svc = TelnetService(0, {"type": "telnet", "banner": "login: "})
        server = await asyncio.start_server(svc._guarded_connection, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        data = await asyncio.wait_for(reader.read(100), 2)
        writer.close()
        server.close()
        return data

    assert asyncio.run(scenario()) == b""   # closed without a single byte
    lines = (tmp_path / "logs" / "telnet_honeypot.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["event"] == "blocked_connection"


# --- the web server's guards ---------------------------------------------------

class FakeController:
    def __init__(self):
        self.running = False
        self.config = {"system": {}, "services": {"22": {"type": "ssh", "enabled": True}}}
        self.saved = None

    def status(self):
        return {"running": self.running, "started_at": None, "services": []}

    def save_config(self, config):
        self.saved = config

    async def start_all_services(self):
        self.running = True
        return [{"type": "ssh", "port": 22, "ok": True, "error": None}]

    async def stop(self):
        self.running = False


def with_client(tmp_path, fn):
    async def scenario():
        store = Store(log_dir=tmp_path / "logs")
        board = Dashboard(FakeController(), store=store, token="secret-token")
        server = TestServer(board.app, host="127.0.0.1")
        await server.start_server()
        board.port = server.port
        client = TestClient(server)
        try:
            return await fn(client, board)
        finally:
            await client.close()
            store.close()
    return asyncio.run(scenario())


def test_requires_the_token_cookie(tmp_path):
    async def fn(client, board):
        r = await client.get("/api/status")
        assert r.status == 401
        r = await client.get("/?token=wrong", allow_redirects=False)
        assert r.status == 403
        r = await client.get("/?token=secret-token", allow_redirects=False)
        assert r.status == 303 and r.headers["Location"] == "/"
        assert "HttpOnly" in r.headers["Set-Cookie"] and "SameSite=Strict" in r.headers["Set-Cookie"]
        r = await client.get("/api/status", cookies={COOKIE: "secret-token"})
        assert r.status == 200
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    with_client(tmp_path, fn)


def test_rejects_foreign_host_header(tmp_path):
    async def fn(client, board):
        r = await client.get("/api/status", cookies={COOKIE: "secret-token"},
                             headers={"Host": f"evil.example:{board.port}"})
        assert r.status == 421
    with_client(tmp_path, fn)


def test_state_changes_need_our_origin(tmp_path):
    async def fn(client, board):
        c = {COOKIE: "secret-token"}
        r = await client.post("/api/start", cookies=c)
        assert r.status == 403                                   # no Origin
        r = await client.post("/api/start", cookies=c, headers={"Origin": "https://evil.example"})
        assert r.status == 403
        r = await client.post("/api/start", cookies=c, headers={"Origin": f"http://127.0.0.1:{board.port}"})
        assert r.status == 200 and board.controller.running
    with_client(tmp_path, fn)


def test_block_endpoint_validates_ip(tmp_path):
    async def fn(client, board):
        kw = {"cookies": {COOKIE: "secret-token"}, "headers": {"Origin": f"http://127.0.0.1:{board.port}"}}
        r = await client.post("/api/block", json={"ip": "../../etc"}, **kw)
        assert r.status == 400
        r = await client.post("/api/block", json={"ip": "198.51.100.7"}, **kw)
        assert r.status == 200 and (await r.json())["blocked"] == ["198.51.100.7"]
    with_client(tmp_path, fn)


def test_static_cannot_escape(tmp_path):
    async def fn(client, board):
        r = await client.get("/static/../server.py", cookies={COOKIE: "secret-token"})
        assert r.status in (403, 404)
        r = await client.get("/static/%2e%2e/server.py", cookies={COOKIE: "secret-token"})
        assert r.status in (403, 404)
    with_client(tmp_path, fn)
