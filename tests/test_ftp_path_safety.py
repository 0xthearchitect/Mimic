"""Regression tests: an FTP client must never reach files outside ftp_storage.

The honeypot is attacked by design, so every path an attacker sends
(including the username, which becomes a home directory) has to stay
inside the virtual root.
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.service_emulator.ftp_emulator import FTPService  # noqa: E402

logging.disable(logging.CRITICAL)


@pytest.fixture
def ftp(tmp_path, monkeypatch):
    # FTPService uses a relative "ftp_storage" root, so run inside tmp_path.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SECRET.txt").write_text("host secret")
    return FTPService(2121, {"type": "ftp", "any_auth": True})


def session(cwd="/"):
    return {"current_dir": Path(cwd), "username": "anonymous"}


TRAVERSALS = [
    "../SECRET.txt",
    "../../SECRET.txt",
    "../../../../../../SECRET.txt",
    "/../../SECRET.txt",
    "..\\..\\SECRET.txt",
    "C:/Windows/win.ini",
    "C:\\Windows\\win.ini",
    "/C:/Windows/win.ini",
    "pub/file.txt:hidden_stream",
    "pub/\x00evil",
]


@pytest.mark.parametrize("arg", TRAVERSALS)
@pytest.mark.parametrize("cwd", ["/", "/pub", "/pub/incoming", "/home/admin"])
def test_paths_never_leave_storage(ftp, arg, cwd):
    real = ftp._to_real(ftp._to_virtual(session(cwd), arg))
    assert real is None or ftp._is_inside(real)


@pytest.mark.parametrize("arg", ["../../SECRET.txt", "C:/Windows/win.ini"])
def test_retr_size_mdtm_cannot_see_host_files(ftp, arg):
    s = session("/pub")
    assert ftp.handle_size(["SIZE", arg], s).startswith("550")
    assert ftp.handle_mdtm(["MDTM", arg], s).startswith("550")


@pytest.mark.parametrize(
    "username",
    ["../../../escape", "..\\..\\escape", "C:/Users/Public/escape", "a/../../escape", "..", ""],
)
def test_malicious_username_stays_in_home(ftp, tmp_path, username):
    user_dir = ftp.ensure_user_directory(username)
    assert ftp._is_inside(user_dir)
    assert user_dir.resolve().parent == (tmp_path / "ftp_storage" / "home").resolve()
    assert not (tmp_path / "escape").exists()


def test_destructive_ops_limited_to_incoming(ftp, tmp_path):
    s = session("/pub/incoming")
    assert ftp.handle_dele(["DELE", "../../../SECRET.txt"], s, "1.2.3.4").startswith("550")
    assert (tmp_path / "SECRET.txt").exists()

    ftp.handle_rnfr(["RNFR", "../../../SECRET.txt"], s)
    assert ftp.handle_rnto(["RNTO", "stolen.txt"], s, "1.2.3.4").startswith("550")
    assert (tmp_path / "SECRET.txt").exists()

    assert ftp.handle_mkd(["MKD", "/pub/incoming/../../../ESCAPED"], s, "1.2.3.4").startswith("553")
    assert not (tmp_path / "ESCAPED").exists()


def test_legit_incoming_operations_still_work(ftp):
    s = session("/pub/incoming")
    incoming = Path("ftp_storage/pub/incoming")
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "a.txt").write_text("hi")

    assert ftp.handle_size(["SIZE", "a.txt"], s) == "213 2"
    ftp.handle_rnfr(["RNFR", "a.txt"], s)
    assert ftp.handle_rnto(["RNTO", "b.txt"], s, "1.2.3.4").startswith("250")
    assert ftp.handle_dele(["DELE", "b.txt"], s, "1.2.3.4").startswith("250")
    assert ftp.handle_mkd(["MKD", "sub"], s, "1.2.3.4").startswith("257")
    assert ftp.handle_rmd(["RMD", "sub"], s, "1.2.3.4").startswith("250")


def test_cwd_and_cdup_stay_at_virtual_root(ftp):
    s = session("/pub")
    ftp.handle_cdup(s)
    ftp.handle_cdup(s)
    assert ftp._to_virtual(s) == "/"
    assert ftp.handle_cwd(["CWD", "C:/Windows"], s).startswith("550")
    assert ftp.handle_cwd(["CWD", "/home/../../evil"], s).startswith("550")
    assert ftp._to_virtual(s) == "/"
