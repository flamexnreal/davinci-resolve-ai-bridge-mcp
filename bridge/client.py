"""Authenticated file-queue client used by the MCP server."""

import json
import os
import secrets
import time
import uuid
from pathlib import Path

from bridge.operations import QUEUE_READ_ONLY


HOME = Path(os.environ.get("RESOLVE_AI_BRIDGE_HOME", Path.home() / ".resolve-ai-bridge")).expanduser()
INBOX = HOME / "inbox"
OUTBOX = HOME / "outbox"
TOKEN_FILE = HOME / "token.txt"
HEARTBEAT_FILE = HOME / "agent.json"
# Per MCP process: bind edits to what this client last observed, not another
# client's latest heartbeat context. Assignment replaces the snapshot atomically.
_observed = None


class BridgeError(RuntimeError):
    pass


class BridgeOffline(BridgeError):
    pass


class BridgeTimeout(BridgeError):
    pass


class BridgeCallError(BridgeError):
    pass


def _ensure_dirs():
    for path in (HOME, INBOX, OUTBOX):
        path.mkdir(parents=True, exist_ok=True)


def _token():
    value = os.environ.get("RESOLVE_AI_BRIDGE_TOKEN", "").strip()
    if value:
        return value
    if TOKEN_FILE.exists():
        try:
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            pass
    # Self-heal / auto-generate shared local token with strict 0600 permissions
    _ensure_dirs()
    token = "rab_" + secrets.token_urlsafe(32)
    try:
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(str(TOKEN_FILE), 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return token


def _read_json(path):
    last_error = None
    for _ in range(4):
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError) as exc:
            last_error = exc
            time.sleep(0.025)
    raise last_error


def _atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(str(temp), str(path))


def heartbeat(max_age=25.0):
    try:
        data = _read_json(HEARTBEAT_FILE)
    except (OSError, ValueError, TypeError):
        return None
    age = time.time() - float(data.get("time", 0))
    if age > max_age or age < -10:
        return None
    data["heartbeat_age_seconds"] = round(max(0.0, age), 2)
    return data


def require_online():
    data = heartbeat()
    if data is None:
        raise BridgeOffline(
            "The Resolve Console worker is not running. In Resolve choose Workspace > Scripts > "
            "Resolve AI Bridge > Start AI Bridge, or paste the single line saved in "
            "~/.resolve-ai-bridge/console-command.txt into Workspace > Console with the Py3 tab "
            "selected."
        )
    return data


def call(operation, params=None, timeout=30.0):
    global _observed
    worker = require_online()
    if worker.get("queue_protocol") != 2:
        raise BridgeCallError("Restart the updated Console worker before sending requests.")
    observed = _observed
    if operation not in QUEUE_READ_ONLY and (
        not observed or observed.get("session") != worker.get("session")
    ):
        raise BridgeCallError("Inspect status or timeline_overview in this client before editing.")
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_path = INBOX / (request_id + ".json")
    response_path = OUTBOX / (request_id + ".json")
    request = {
        "id": request_id,
        "op": str(operation),
        "params": params or {},
        "token": _token(),
        "sent": time.time(),
        "deadline": time.time() + float(timeout),
        "context": (observed or {}).get("context"),
        "session": worker.get("session"),
    }
    _atomic_json(request_path, request)
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if response_path.exists():
            try:
                response = _read_json(response_path)
            finally:
                try:
                    response_path.unlink()
                except OSError:
                    pass
            if not response.get("ok"):
                raise BridgeCallError(response.get("error", "Resolve returned an unknown error."))
            _observed = {"context": response.get("context"), "session": response.get("session")}
            return response.get("result")
        time.sleep(0.06)
    try:
        request_path.unlink()
    except OSError:
        pass
    raise BridgeTimeout(
        "Client timed out waiting for %s (%s) after %.0f seconds. This is not confirmed "
        "cancellation: an active native operation may still finish. Do not replay an edit; "
        "inspect the request record in requests/ and Resolve state."
        % (operation, request_id, timeout)
    )
