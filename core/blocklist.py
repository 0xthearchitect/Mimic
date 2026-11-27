"""Operator blocklist: IPs the operator chose to "show out" from the dashboard.

Independent of SecurityLayer's automatic rate-limit blocks (which only apply
when security is enabled). Persisted one IP per line in config/blocklist.txt
so it survives restarts. Every service checks it before talking to a client.
"""
import ipaddress
import threading
from pathlib import Path
from typing import List, Set

PATH = Path("config/blocklist.txt")

_lock = threading.Lock()
_blocked: Set[str] = set()
_loaded_from: Path = None


def _ensure_loaded() -> None:
    global _loaded_from
    if _loaded_from == PATH:
        return
    _blocked.clear()
    try:
        for line in PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                _blocked.add(line)
    except FileNotFoundError:
        pass
    _loaded_from = PATH


def _save() -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    body = "# IPs blocked from the MIMIC dashboard, one per line\n" + "".join(
        f"{ip}\n" for ip in sorted(_blocked))
    PATH.write_text(body, encoding="utf-8")


def normalize(ip: str) -> str:
    """Return the canonical form of an IP address, or raise ValueError."""
    return str(ipaddress.ip_address(str(ip).strip()))


def is_blocked(ip: str) -> bool:
    with _lock:
        _ensure_loaded()
        return ip in _blocked


def block(ip: str) -> str:
    ip = normalize(ip)
    with _lock:
        _ensure_loaded()
        _blocked.add(ip)
        _save()
    return ip


def unblock(ip: str) -> str:
    ip = normalize(ip)
    with _lock:
        _ensure_loaded()
        _blocked.discard(ip)
        _save()
    return ip


def all_blocked() -> List[str]:
    with _lock:
        _ensure_loaded()
        return sorted(_blocked)
