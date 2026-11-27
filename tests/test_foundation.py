"""Phase 1 foundation: unified log schema, service registry, config validation."""
import asyncio
import ftplib
import hashlib
import io
import json
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import controller as controller_mod  # noqa: E402
from core.config_schema import ConfigError, validate_config  # noqa: E402
from core.controller import PLANNED_SERVICES, SERVICE_REGISTRY, MIMICController  # noqa: E402
from log_system import events  # noqa: E402

logging.disable(logging.CRITICAL)

REQUIRED_FIELDS = {"timestamp", "event", "service", "port", "client_ip"}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(events, "LOG_DIR", tmp_path / "logs")
    return tmp_path


class StubSecurity:
    """Stand-in for SecurityLayer, whose constructor needs a running event loop."""
    enabled = False

    def validate_port(self, port):
        return True


def build_controller(path):
    async def build():
        c = MIMICController(path)
        c.security.cleanup_task.cancel()
        return c
    return asyncio.run(build())


def read_events(workdir, service):
    path = workdir / "logs" / f"{service}_honeypot.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- Event log ---------------------------------------------------------------

def test_emit_writes_common_schema(workdir):
    events.emit("ssh", 22, events.LOGIN_ATTEMPT, "1.2.3.4",
                username="root", password="toor", success=False)
    (entry,) = read_events(workdir, "ssh")
    assert REQUIRED_FIELDS <= entry.keys()
    assert entry["event"] == "login_attempt"
    assert entry["client_ip"] == "1.2.3.4"
    assert entry["timestamp"].endswith("Z")
    assert entry["username"] == "root" and entry["password"] == "toor"


def test_emit_keeps_non_ascii_and_odd_values(workdir):
    events.emit("telnet", 23, events.COMMAND, "::1", command="ls 🎭 ção", extra=Path("x"))
    (entry,) = read_events(workdir, "telnet")
    assert entry["command"] == "ls 🎭 ção"
    assert entry["extra"] == "x"


# --- Service registry --------------------------------------------------------

@pytest.mark.parametrize("service_type", sorted(SERVICE_REGISTRY))
def test_every_registered_service_can_be_built(workdir, service_type):
    ctrl = MIMICController.__new__(MIMICController)
    ctrl.config = {"system": {"hostname": "stage"}, "options": {}, "security": {"enabled": True}}
    ctrl.security = StubSecurity()
    service = ctrl.create_service(40000, {"type": service_type, "enabled": True})
    assert service.port == 40000
    assert hasattr(service, "start") and hasattr(service, "stop")


# --- Config validation -------------------------------------------------------

def check(config):
    return validate_config(config, SERVICE_REGISTRY, PLANNED_SERVICES)


def test_example_config_is_valid():
    config = yaml.safe_load((ROOT / "config" / "honeypot.example.yaml").read_text(encoding="utf-8"))
    assert check(config) == []


@pytest.mark.parametrize("config, fragment", [
    (None, "empty"),
    ({"services": {}}, "no services"),
    ({"services": {"abc": {"type": "ssh"}}}, "port must be a number"),
    ({"services": {"70000": {"type": "ssh"}}}, "between 1 and 65535"),
    ({"services": {"22": {"type": "gopher"}}}, "unknown type 'gopher'"),
    ({"services": {"22": {"enabled": True}}}, "missing 'type'"),
    ({"services": {"22": {"type": "ssh", "enabled": "yes"}}}, "'enabled' must be bool"),
    ({"options": {"brute_force_attempts": 0}, "services": {"22": {"type": "ssh"}}}, "at least 1"),
    ({"options": {"any_auth": "true"}, "services": {"22": {"type": "ssh"}}}, "'any_auth' must be bool"),
])
def test_invalid_configs_are_reported(config, fragment):
    errors = check(config)
    assert any(fragment in e for e in errors), errors


def test_all_errors_reported_at_once():
    errors = check({"services": {"0": {"type": "nope"}, "22": {"type": "ssh", "enabled": 1}}})
    assert len(errors) == 3


def test_planned_service_is_accepted_but_skipped(workdir, capsys):
    assert check({"services": {"3389": {"type": "rdp"}}}) == []
    ctrl = MIMICController.__new__(MIMICController)
    ctrl.services = {}
    asyncio.run(ctrl.start_service(3389, {"type": "rdp"}))
    assert ctrl.services == {}
    assert "not implemented yet" in capsys.readouterr().out


def test_controller_creates_config_from_example(workdir, monkeypatch):
    (workdir / "config").mkdir()
    example = workdir / "config" / "honeypot.example.yaml"
    example.write_text((ROOT / "config" / "honeypot.example.yaml").read_text(encoding="utf-8"),
                       encoding="utf-8")
    monkeypatch.setattr(controller_mod, "EXAMPLE_CONFIG", example)
    ctrl = build_controller(str(workdir / "config" / "honeypot.yaml"))
    assert (workdir / "config" / "honeypot.yaml").exists()
    assert "services" in ctrl.config


def test_controller_rejects_invalid_config(workdir):
    bad = workdir / "bad.yaml"
    bad.write_text("services:\n  '22':\n    type: gopher\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="gopher"):
        build_controller(str(bad))


# --- End to end: real FTP and Telnet clients ---------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_service(service):
    def serve():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(service.start())
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(0.8)


@pytest.fixture
def ctrl(workdir):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    c = MIMICController.__new__(MIMICController)
    c.config = {"options": {"any_auth": True, "brute_force_attempts": 1}, "security": {}}
    c.security = StubSecurity()
    return c


def test_ftp_logs_structured_logins_and_uploads(workdir, ctrl):
    port = free_port()
    svc = ctrl.create_service(port, {"type": "ftp", "allow_upload": True})
    svc.response_delay = {"random": False, "fixed": 0}
    run_service(svc)

    f = ftplib.FTP()
    f.connect("127.0.0.1", port, timeout=5)
    f.login("admin", "pass with spaces")
    f.storbinary("STOR loot.bin", io.BytesIO(b"malware"))
    f.quit()

    log = read_events(workdir, "ftp")
    assert all(REQUIRED_FIELDS <= e.keys() for e in log)

    logins = [e for e in log if e["event"] == "login_attempt"]
    assert logins and logins[-1]["username"] == "admin"
    assert logins[-1]["password"] == "pass with spaces"
    assert logins[-1]["success"] is True
    # The password must not also leak into raw command entries.
    assert not any("pass with spaces" in e.get("command", "") for e in log)

    (upload,) = [e for e in log if e["event"] == "file_upload"]
    assert upload["filename"] == "loot.bin" and upload["size"] == 7
    assert upload["sha256"] == hashlib.sha256(b"malware").hexdigest()


def test_telnet_logs_structured_login(workdir, ctrl):
    port = free_port()
    run_service(ctrl.create_service(port, {"type": "telnet"}))

    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(b"root\r\n")
        time.sleep(0.2)
        s.sendall(b"hunter2\r\n")
        time.sleep(2)

    (login,) = [e for e in read_events(workdir, "telnet") if e["event"] == "login_attempt"]
    assert login["username"] == "root" and login["password"] == "hunter2"
    assert login["success"] is False
