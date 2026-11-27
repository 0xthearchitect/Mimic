"""Unified JSON Lines event log shared by every service.

Every service writes through ``emit`` so all logs share one schema
(documented in docs/LOG_FORMAT.md):

    {"timestamp": "...Z", "event": "...", "service": "...", "port": 22,
     "client_ip": "...", ...event-specific fields}

One file per service: logs/<service>_honeypot.jsonl
"""
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOG_DIR = Path("logs")

# Event names. Keep in sync with docs/LOG_FORMAT.md.
CONNECTION = "connection"
BLOCKED_CONNECTION = "blocked_connection"
LOGIN_ATTEMPT = "login_attempt"
COMMAND = "command"
FILE_UPLOAD = "file_upload"

_lock = threading.Lock()
_log = logging.getLogger("mimic.events")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def emit(service: str, port: int, event: str, client_ip: Optional[str] = None,
         **fields: Any) -> Dict[str, Any]:
    """Append one event to logs/<service>_honeypot.jsonl and return it."""
    entry: Dict[str, Any] = {
        "timestamp": _timestamp(),
        "event": event,
        "service": service,
        "port": port,
        "client_ip": client_ip,
        **fields,
    }
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _lock, open(LOG_DIR / f"{service}_honeypot.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        _log.exception("Failed to write %s event for %s", event, service)
    return entry
