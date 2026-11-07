"""Pick the best available route into DaVinci Resolve.

Three transports exist and they behave identically from the MCP server's point of
view:

``direct``
    The MCP process attaches to a running Resolve through Blackmagic's native
    scripting library. Nothing has to be pasted or clicked. This is the default
    when it is available.

``console``
    The authenticated file queue in ``~/.resolve-ai-bridge``. A small worker
    started from Resolve's own Console (or the Workspace > Scripts menu) does
    the work on Python-enabled builds.

``lua``
    Python runs the shared operations outside Resolve. An authenticated Lua
    worker uses native Fusion file APIs to call Resolve, including Free 21.1.2.

Set ``RESOLVE_AI_BRIDGE_MODE`` to ``direct``, ``console``, ``lua`` or ``auto``
(default) to override the choice.
"""

import os
import time

from bridge import client, direct, lua_transport
from bridge.operations import OperationError, ResolveOperations


RETRY_SECONDS = 30.0

_state = {"ops": None, "last_probe": 0.0}


def mode():
    value = os.environ.get("RESOLVE_AI_BRIDGE_MODE", "auto").strip().lower()
    return value if value in ("auto", "direct", "console", "queue", "lua") else "auto"


def _token_id():
    try:
        import hashlib

        return hashlib.sha256(client._token().encode("utf-8")).hexdigest()[:12]
    except Exception:
        return None


def direct_operations(force=False):
    """Return a ready ``ResolveOperations`` bound to a live Resolve, or None."""
    if mode() in ("console", "queue", "lua"):
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
    """Report available transports for resolve_status and the doctor check."""
    selected_mode = mode()
    lua = lua_transport.probe()
    use_lua = selected_mode == "lua" or (selected_mode == "auto" and lua.get("connected"))
    probe = direct.probe() if selected_mode not in ("console", "queue", "lua") and not use_lua else {
        "ok": False,
        "loadable": False,
        "reason": ("Auto mode selected the running Lua worker." if selected_mode == "auto" else
                   "Direct attach disabled by RESOLVE_AI_BRIDGE_MODE=%s." % selected_mode),
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
        "lua_worker": lua,
        "active": "lua" if use_lua and lua.get("connected") else
                  ("direct" if probe.get("ok") else
                   ("console" if console and selected_mode in ("auto", "console", "queue") else "none")),
    }


def call(operation, params=None, timeout=30.0):
    """Run one operation over whichever transport is available."""
    selected_mode = mode()
    lua = lua_transport.probe() if selected_mode in ("auto", "lua") else {}
    if lua.get("connected"):
        # Never fall through after Lua dispatch: an uncertain edit is not replayed.
        return lua_transport.call(operation, params or {}, timeout=timeout), "lua"
    if selected_mode == "lua":
        raise client.BridgeOffline("The Lua worker is not reachable with RESOLVE_AI_BRIDGE_MODE=lua. "
                                   "No request was dispatched. Use Start AI Bridge (Lua), then inspect status.")
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

    if selected_mode == "direct":
        raise client.BridgeOffline(
            "Direct attach is unavailable with RESOLVE_AI_BRIDGE_MODE=direct. "
            "No worker fallback was sent. Use auto mode to allow a Lua or Console worker."
        )
    return client.call(operation, params or {}, timeout=timeout), "console"


def offline_help():
    """Startup guidance for the selected transport."""
    selected_mode = mode()
    if selected_mode == "direct":
        return (
            "Open Resolve and check direct scripting availability (Studio: Preferences > System > "
            "General > External scripting using > Local). RESOLVE_AI_BRIDGE_MODE=direct disables "
            "worker fallback; set it to auto to use a Lua or Console worker."
        )
    lua_help = ("Choose Workspace > Scripts > Resolve AI Bridge > Start AI Bridge (Lua), "
                "or use lua-console-command.txt in the Lua Console.")
    python_help = ("On Python-enabled builds, choose Workspace > Scripts > Resolve AI Bridge > Start AI Bridge, "
                   "or use console-command.txt in the Py3 Console.")
    if selected_mode == "lua":
        return "Open Resolve with a project. " + lua_help
    if selected_mode in ("console", "queue"):
        return ("Open Resolve with a project. " + python_help +
                " On Free 21.1+, set RESOLVE_AI_BRIDGE_MODE to auto or lua, then start the Lua worker.")
    return "Open Resolve with a project. On Free 21.1+, " + lua_help + " " + python_help
