"""Pick the best available route into DaVinci Resolve.

Two transports exist and they behave identically from the MCP server's point of
view:

``direct``
    The MCP process attaches to a running Resolve through Blackmagic's native
    scripting library. Nothing has to be pasted or clicked. This is the default
    when it is available.

``console``
    The authenticated file queue in ``~/.resolve-ai-bridge``. A small worker
    started from Resolve's own Console (or the Workspace > Scripts menu) does
    the work. This always works, including on builds or preference settings
    that refuse an external attach.

Set ``RESOLVE_AI_BRIDGE_MODE`` to ``direct``, ``console``, or ``auto``
(default) to override the choice.
"""

import os
import time

from bridge import client, direct
from bridge.operations import OperationError, ResolveOperations


RETRY_SECONDS = 30.0

_state = {"ops": None, "last_probe": 0.0}


def mode():
    value = os.environ.get("RESOLVE_AI_BRIDGE_MODE", "auto").strip().lower()
    return value if value in ("auto", "direct", "console", "queue") else "auto"


def _token_id():
    try:
        import hashlib

        return hashlib.sha256(client._token().encode("utf-8")).hexdigest()[:12]
    except Exception:
        return None


def direct_operations(force=False):
    """Return a ready ``ResolveOperations`` bound to a live Resolve, or None."""
    if mode() in ("console", "queue"):
        return None

    if _state["ops"] is not None:
        return _state["ops"] if direct.attach() is not None else None

    outcome = direct.probe()
    if not outcome.get("loadable"):
        elapsed = time.monotonic() - _state["last_probe"]
        if not force and _state["last_probe"] and elapsed < RETRY_SECONDS:
            return None
        _state["last_probe"] = time.monotonic()
        outcome = direct.probe(force=True)
        if not outcome.get("loadable"):
            return None

    if direct.attach() is None:
        return None
    _state["ops"] = ResolveOperations(direct.attach, _token_id(), "direct")
    return _state["ops"]


def describe():
    """Report both transports for resolve_status and the doctor check."""
    selected_mode = mode()
    probe = direct.probe() if selected_mode not in ("console", "queue") else {
        "ok": False,
        "loadable": False,
        "reason": "Direct attach disabled by RESOLVE_AI_BRIDGE_MODE=%s." % selected_mode,
    }
    console = client.heartbeat()
    return {
        "configured_mode": selected_mode,
        "direct": probe,
        "console_worker": {
            "online": console is not None,
            "project": (console or {}).get("project"),
            "state": (console or {}).get("state"),
            "busy": (console or {}).get("busy"),
            "request_id": (console or {}).get("request_id"),
            "heartbeat_age_seconds": (console or {}).get("heartbeat_age_seconds"),
        },
        "active": "direct" if probe.get("ok") else ("console" if console else "none"),
    }


def call(operation, params=None, timeout=30.0):
    """Run one operation over whichever transport is available."""
    try:
        operations = direct_operations()
    except Exception:  # No dispatch has started, so Console fallback is safe.
        direct.reset()
        _state["ops"] = None
        operations = None
    if operations is not None:
        try:
            return operations.dispatch(operation, params or {}), "direct"
        except OperationError:
            raise
        except Exception as exc:  # A broken attach should not end the session.
            direct.reset()
            _state["ops"] = None
            raise client.BridgeCallError(
                "Direct dispatch failed (%s). Outcome unknown; the operation may have "
                "already changed Resolve. Inspect before retrying; no Console replay was sent." % exc
            ) from exc

    return client.call(operation, params or {}, timeout=timeout), "console"


def offline_help():
    """A single actionable sentence for when neither transport is available."""
    probe = direct.probe()
    reason = probe.get("reason") or "Direct attach is unavailable."
    return (
        "Resolve is not reachable. %s Open DaVinci Resolve with a project. If tools still fail, "
        "start the worker from Workspace > Scripts > Resolve AI Bridge > Start AI Bridge, or paste "
        "the line in ~/.resolve-ai-bridge/console-command.txt into Workspace > Console (Py3)."
        % reason
    )
