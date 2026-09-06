"""Resolve AI Bridge Console worker.

Three ways to start this file, all equivalent:

1. Workspace > Scripts > Resolve AI Bridge > Start AI Bridge  (one click)
2. Paste the one line from ~/.resolve-ai-bridge/console-command.txt into
   Workspace > Console with the Py3 tab selected. It contains no personal
   paths, so there is nothing to edit:

       import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())

3. Nothing at all, when the MCP server can attach to Resolve directly. Run
   ``python3 tools/doctor.py`` to see which route your machine uses.

The worker captures Resolve's injected API object, starts a background thread,
and returns control to the Console immediately. The Workspace Scripts launcher
uses a non-daemon thread because Resolve may tear down a one-shot menu-script
context as soon as the launcher returns. It only depends on the standard
library and on ``bridge/operations.py``, which the installer places beside it.
"""

import builtins
import hashlib
import hmac
import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path


RUNTIME_KEY = "__resolve_ai_bridge_runtime__"
HOME = Path(os.environ.get("RESOLVE_AI_BRIDGE_HOME", Path.home() / ".resolve-ai-bridge")).expanduser()
INBOX = HOME / "inbox"
OUTBOX = HOME / "outbox"
LOGS = HOME / "logs"
TOKEN_FILE = HOME / "token.txt"
HEARTBEAT_FILE = HOME / "agent.json"


def _import_operations():
    """Load the shared operation implementations from the installed runtime."""
    candidates = [HOME]
    try:  # Running straight from a cloned repository also works.
        candidates.append(Path(__file__).resolve().parents[1])
    except NameError:
        pass
    for root in candidates:
        if (root / "bridge" / "operations.py").exists() and str(root) not in sys.path:
            sys.path.insert(0, str(root))
    try:
        from bridge import operations
    except ImportError as exc:
        raise RuntimeError(
            "bridge/operations.py was not found next to this file. Run install.py again from the "
            "complete downloaded folder, then restart this worker. (%s)" % exc
        )
    return operations


operations = _import_operations()
AGENT_VERSION = operations.AGENT_VERSION
PROTOCOL_VERSION = operations.PROTOCOL_VERSION


def _ensure_dirs():
    for path in (HOME, INBOX, OUTBOX, LOGS):
        path.mkdir(parents=True, exist_ok=True)


def _atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(str(temp), str(path))


def _read_json(path):
    last_error = None
    for _ in range(4):
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError) as exc:
            last_error = exc
            time.sleep(0.03)
    raise last_error


def _load_token():
    if TOKEN_FILE.exists():
        value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = "rab_" + secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(value + "\n", encoding="utf-8")
    try:
        os.chmod(str(TOKEN_FILE), 0o600)
    except OSError:
        pass
    return value


def _injected(name, namespace=None):
    if namespace and namespace.get(name) is not None:
        return namespace[name]
    value = globals().get(name)
    if value is not None:
        return value
    return getattr(builtins, name, None)


def _scriptapp_from_disk():
    """Obtain Resolve's API object without relying on injected globals.

    A Console paste always inherits ``resolve`` from the Console's namespace, but
    a Workspace > Scripts invocation does not always inject it into the script's
    own globals. Resolve's own interpreter can still import its scripting module,
    so this reproduces what Blackmagic's ``DaVinciResolveScript`` does: import the
    native module and ask it for the app. This is the difference between the menu
    launcher working and the user having to paste into the Console.
    """
    attempts = []

    # Resolve's interpreter usually has both of these importable already.
    for module_name in ("fusionscript", "DaVinciResolveScript"):
        try:
            module = __import__(module_name)
        except Exception as exc:
            attempts.append("import %s (%s)" % (module_name, exc))
            continue
        for getter in ("scriptapp", "GetResolve"):
            call = getattr(module, getter, None)
            if call is None:
                continue
            try:
                candidate = call("Resolve") if getter == "scriptapp" else call()
            except Exception as exc:
                attempts.append("%s.%s (%s)" % (module_name, getter, exc))
                continue
            if candidate is not None and hasattr(candidate, "GetProjectManager"):
                return candidate, attempts

    # Fall back to loading the native library straight off disk.
    import importlib.machinery
    import importlib.util

    for path in _library_candidates():
        if not os.path.isfile(path):
            attempts.append("%s (not found)" % path)
            continue
        try:
            loader = importlib.machinery.ExtensionFileLoader("fusionscript", path)
            spec = importlib.util.spec_from_loader("fusionscript", loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            candidate = module.scriptapp("Resolve")
        except Exception as exc:
            attempts.append("%s (%s)" % (path, exc))
            continue
        if candidate is not None and hasattr(candidate, "GetProjectManager"):
            return candidate, attempts
        attempts.append("%s (loaded, but Resolve did not answer)" % path)
    return None, attempts


def _library_candidates():
    """Absolute paths to Resolve's scripting library, most specific first."""
    candidates = []
    override = os.environ.get("RESOLVE_SCRIPT_LIB", "").strip()
    if override:
        candidates.append(override)
    if sys.platform.startswith("darwin"):
        candidates.append(
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/"
            "Libraries/Fusion/fusionscript.so"
        )
    elif os.name == "nt":
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        candidates.append(
            os.path.join(program_files, "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
        )
    else:
        candidates.append("/opt/resolve/libs/Fusion/fusionscript.so")
        candidates.append("/home/resolve/libs/Fusion/fusionscript.so")
    unique = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def _get_resolve(namespace=None):
    candidate = _injected("resolve", namespace)
    if candidate is not None and hasattr(candidate, "GetProjectManager"):
        return candidate

    for name in ("app", "fusion", "fu"):
        host = _injected(name, namespace)
        if host is None:
            continue
        try:
            candidate = host.GetResolve()
            if candidate is not None and hasattr(candidate, "GetProjectManager"):
                return candidate
        except Exception:
            pass

    bmd = _injected("bmd", namespace)
    if bmd is not None:
        try:
            candidate = bmd.scriptapp("Resolve")
            if candidate is not None and hasattr(candidate, "GetProjectManager"):
                return candidate
        except Exception:
            pass

    candidate, attempts = _scriptapp_from_disk()
    if candidate is not None:
        return candidate

    raise RuntimeError(
        "Resolve's API object was not found. Open a project first, and check "
        "Preferences > System > General > External scripting using is not set to None. "
        "Then retry Workspace > Scripts > Resolve AI Bridge > Start AI Bridge, or paste the one "
        "line from ~/.resolve-ai-bridge/console-command.txt into Workspace > Console (Py3 tab). "
        "Attach attempts: %s" % ("; ".join(attempts) or "none")
    )


class ResolveRuntime:
    """The daemon worker plus its authenticated queue."""

    def __init__(self, resolve):
        _ensure_dirs()
        self.resolve = resolve
        self.token = _load_token()
        self.token_id = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:12]
        self.operations = operations.ResolveOperations(
            lambda: self.resolve, token_id=self.token_id, transport="console"
        )
        self.stop_event = threading.Event()
        self.thread = None
        self.started_at = time.time()
        self.last_heartbeat = 0.0
        self.served = 0
        self.log_path = LOGS / "agent.log"
        self.session = uuid.uuid4().hex
        self.snapshot = {}
        self.state = {"state": "idle", "busy": False}
        (HOME / "requests").mkdir(exist_ok=True)

    def log(self, message):
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write("[%s] %s\n" % (stamp, message))
        except Exception:
            pass

    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.alive():
            print("Resolve AI Bridge is already running in this Resolve session.")
            self.summary()
            return
        self.stop_event.clear()
        # Resolve runs Workspace scripts in a short-lived interpreter context.
        # A daemon thread is killed when that context returns, often before the
        # first heartbeat is written. The menu launcher opts into a non-daemon
        # worker; a pasted Console command keeps the historical daemon behavior.
        keepalive = bool(globals().get("RESOLVE_AI_BRIDGE_KEEPALIVE"))
        self.thread = threading.Thread(
            target=self._loop,
            name="ResolveAIBridge",
            daemon=not keepalive,
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.log("Stop requested from inside Resolve")
        print("Resolve AI Bridge is stopping. The heartbeat expires within a few seconds.")

    def summary(self):
        """Short, friendly confirmation. The installer already wrote every config file."""
        status = dict(self.snapshot)
        print("\n" + "=" * 68)
        print("RESOLVE AI BRIDGE READY")
        print("Version %s  |  worker requests served: %d" % (AGENT_VERSION, self.served))
        print("Project:  %s" % (status.get("project") or "none open"))
        print("Timeline: %s" % (status.get("timeline") or "none open"))
        print("Resolve:  %s %s" % (status.get("product") or "", status.get("version") or ""))
        print("")
        print("Your AI client needs no token typed by hand. The filled configuration is at:")
        print("  %s" % (HOME / "mcp-config.json"))
        print("Provider one-liners:")
        print("  Claude Code: %s" % (HOME / "claude-command.txt"))
        print("  Codex:       %s" % (HOME / "codex-command.txt"))
        print("")
        print("Stop this worker with: %s.stop()" % RUNTIME_KEY)
        print("=" * 68 + "\n")

    def print_details(self):
        """Everything a provider could need, on request rather than on every start."""
        venv_python = HOME / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        server = HOME / "bridge" / "server.py"
        entry = {
            "command": str(venv_python),
            "args": [str(server)],
        }
        print("\nGENERIC MCP SERVER ENTRY (zero-token standard):")
        print(json.dumps(entry, indent=2))
        print("\nFULL MCP CONFIG (Antigravity, Cursor, Claude Desktop, and JSON clients):")
        print(json.dumps({"mcpServers": {"resolve-ai-bridge": entry}}, indent=2))
        claude_entry_file = HOME / "claude-server-entry.json"
        if os.name == "nt":
            claude_line = (
                '$entry = Get-Content -Raw "%s"; '
                "claude mcp add-json resolve-ai-bridge $entry --scope user"
            ) % claude_entry_file
            launch = subprocess.list2cmdline([str(venv_python), str(server)])
        else:
            claude_line = 'claude mcp add-json resolve-ai-bridge "$(cat %s)" --scope user' % shlex.quote(
                str(claude_entry_file)
            )
            launch = "%s %s" % (shlex.quote(str(venv_python)), shlex.quote(str(server)))
        print("\nCLAUDE CODE COMMAND:")
        print(claude_line)
        print("\nCODEX CLI COMMAND:")
        print(
            "codex mcp add resolve-ai-bridge -- %s"
            % launch
        )
        print("\nLocal Token: %s (auto-managed at %s)" % (self.token, TOKEN_FILE))
        print("")

    # Kept as an alias so older instructions and screenshots still work.
    banner = summary

    def _refresh_snapshot(self):
        payload = self.operations.heartbeat_payload()
        try:
            payload["context"] = self.operations.queue_context()
        except Exception:
            payload["context"] = None
        self.snapshot = payload

    def _heartbeat(self):
        # This reporter only reads Python data, never Resolve objects.
        payload = dict(self.snapshot)
        payload.update(self.state)
        payload.update(time=time.time(), session=self.session, queue_protocol=2,
                       thread_alive=self.alive(), served=self.served,
                       started_at=self.started_at, agent_version=AGENT_VERSION)
        _atomic_json(HEARTBEAT_FILE, payload)
        self.last_heartbeat = time.time()

    def _report(self):
        while not self.stop_event.wait(1):
            if self.thread is None or not self.thread.is_alive():
                return
            try:
                self._heartbeat()
            except Exception as exc:
                self.log("Heartbeat failed: %s" % exc)

    def _process(self, path):
        request_id = path.stem
        started = time.time()
        response = {"id": request_id, "ok": False}
        try:
            request = _read_json(path)
            if str(request.get("id", "")) != request_id:
                raise RuntimeError("Request id does not match its queue filename.")
            if not hmac.compare_digest(str(request.get("token", "")), self.token):
                raise RuntimeError(
                    "Bridge token mismatch. Re-run install.py and update your AI client's MCP entry."
                )
            record = HOME / "requests" / (request_id + ".json")
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
            if record.exists():
                previous = _read_json(record)
                if previous.get("fingerprint") != fingerprint:
                    raise RuntimeError("Request identity reused with different content; refused.")
                if previous.get("state") == "running":
                    raise RuntimeError("Previous execution outcome unknown; request will not be replayed.")
                _atomic_json(OUTBOX / path.name, previous)
                path.unlink(missing_ok=True)
                return
            response["fingerprint"] = fingerprint
            if float(request.get("deadline", 0)) <= time.time():
                raise RuntimeError("Request expired before execution; no operation started.")
            if request.get("session") != self.session:
                raise RuntimeError("Worker session changed; inspect context and submit a new request.")
            # All operations except inspection require a stable submission context.
            if request.get("op") not in operations.QUEUE_READ_ONLY:
                if not request.get("context") or request["context"] != self.operations.queue_context():
                    raise RuntimeError("Project/timeline context changed or unavailable; no edit started.")
            if float(request.get("deadline", 0)) <= time.time():
                raise RuntimeError("Request expired during validation; no operation started.")
            response.update(fingerprint=fingerprint, state="running")
            _atomic_json(record, response)
            self.state = {"state": "running", "busy": True, "request_id": request_id}
            response["result"] = self.operations.dispatch(
                str(request.get("op", "")), request.get("params") or {}
            )
            try:
                response["context"] = self.operations.queue_context()
            except Exception:
                response["context"] = None
            response["session"] = self.session
            response["ok"] = True
            self.served += 1
        except Exception as exc:
            response["error"] = str(exc)
            response["traceback"] = traceback.format_exc(limit=8)
            self.log("Request %s failed: %s" % (request_id, exc))
        response["state"] = "completed" if response["ok"] else "failed"
        # Preserve a running journal on uncertain failures writing the final result.
        if response.get("fingerprint"):
            _atomic_json(HOME / "requests" / (request_id + ".json"), response)
        self.state = {"state": response["state"], "busy": False, "request_id": request_id}
        response["took_ms"] = int((time.time() - started) * 1000)
        _atomic_json(OUTBOX / (request_id + ".json"), response)
        try:
            path.unlink()
        except OSError:
            pass

    def _loop(self):
        self.log("Worker %s started with token id %s" % (AGENT_VERSION, self.token_id))
        try:
            self._refresh_snapshot()
            self._heartbeat()
            self.summary()
            threading.Thread(target=self._report, daemon=True).start()
            refreshed = 0.0
            while not self.stop_event.wait(0.08):
                now = time.time()
                if now - refreshed >= 2.0:
                    refreshed = now
                    try:
                        self._refresh_snapshot()
                    except Exception as exc:
                        self.log("Heartbeat failed: %s" % exc)
                for path in sorted(INBOX.glob("*.json"))[:8]:
                    if self.stop_event.is_set():
                        break
                    try:
                        self._process(path)
                        self._refresh_snapshot()
                    except Exception as exc:
                        self.log("Could not process %s: %s" % (path.name, exc))
        finally:
            try:
                HEARTBEAT_FILE.unlink()
            except OSError:
                pass
            self.log("Worker stopped")


def start_bridge(namespace=None):
    """Start or reuse the worker. ``namespace`` carries Resolve's injected globals."""
    _ensure_dirs()
    existing = getattr(builtins, RUNTIME_KEY, None)
    if existing is not None and getattr(existing, "alive", lambda: False)():
        print("Resolve AI Bridge is already running in this Resolve session.")
        existing.summary()
        return existing
    runtime = ResolveRuntime(_get_resolve(namespace))
    setattr(builtins, RUNTIME_KEY, runtime)
    globals()[RUNTIME_KEY] = runtime
    runtime.start()
    return runtime


def stop_bridge():
    existing = getattr(builtins, RUNTIME_KEY, None)
    if existing is None:
        print("Resolve AI Bridge is not running in this Resolve session.")
        return False
    existing.stop()
    return True


# Backwards-compatible private name used by earlier releases.
_start_bridge = start_bridge


if os.environ.get("RESOLVE_AI_BRIDGE_NO_AUTOSTART", "").strip() != "1":
    try:
        start_bridge(globals())
    except Exception as error:
        print("\nRESOLVE AI BRIDGE DID NOT START")
        print(str(error))
        print("Log: %s\n" % (LOGS / "agent.log"))
