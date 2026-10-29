"""Authenticated native-file Lua transport. Operations remain in operations.py.

Python runs outside Resolve. Lua uses Fusion's native OpenFile API, available
on Free 21.1.2 without io, FFI, sockets or Python inside Resolve.
"""
import hashlib
import hmac
import json
from pathlib import Path
import time
import uuid

from bridge import client, lifecycle
from bridge.operations import QUEUE_READ_ONLY, ResolveOperations

MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_observed = None


class _WireFailure(BaseException):
    # Optional API helpers in operations.py catch Exception and try fallbacks.
    # An uncertain RPC must escape those helpers to prevent a second mutation.
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class LuaClient:
    def __init__(self, home=None, timeout=30):
        self.home = Path(home or client.HOME)
        self.token = lifecycle.load_token(self.home / "token.txt")
        self.deadline = time.time() + timeout
        self.session = None
        self.transaction = None
        self.failed = False
        self.methods = set()

    def request(self, operation, arguments=None):
        if self.failed and operation != "finish_operation":
            raise _WireFailure("Lua dispatch halted after an uncertain reply; inspect before retrying.")
        try:
            return self._request(operation, arguments)
        except _WireFailure:
            self.failed = True
            raise

    def _request(self, operation, arguments=None):
        remaining = self.deadline - time.time()
        if remaining <= 0:
            raise _WireFailure("Lua operation deadline expired; an earlier native call may have completed.")
        request = {"protocol": "1.0", "id": uuid.uuid4().hex, "timestamp": int(time.time()),
                   "nonce": uuid.uuid4().hex, "operation": operation, "arguments": arguments or {},
                   "deadline": self.deadline}
        if self.session is not None:
            request["expected_session"] = self.session
        if self.transaction is not None:
            request["transaction"] = self.transaction
        request["signature"] = hmac.new(self.token.encode(), _canonical(request).encode(), hashlib.sha256).hexdigest()
        wire = (_canonical(request) + "\n").encode()
        if len(wire) > 1048576:
            raise _WireFailure("Lua RPC exceeds the request size limit; dispatch stopped.")
        try:
            lifecycle.atomic_json(self.home / "lua-inbox.json", request)
            raw = b""
            while time.time() < self.deadline:
                try:
                    with (self.home / "lua-outbox.json").open("rb") as output:
                        candidate = output.readline(MAX_MESSAGE_BYTES + 1)
                    if len(candidate) > MAX_MESSAGE_BYTES:
                        raise _WireFailure("Lua reply exceeds the size limit; inspect before retrying.")
                    envelope = json.loads(candidate)
                    payload = envelope["payload"]
                    expected = hmac.new(self.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(expected, envelope["signature"]):
                        # A native write may momentarily combine new payload
                        # bytes with the old signature. Retry reading only.
                        raise ValueError("Lua reply signature mismatch")
                    reply = json.loads(payload)
                    if reply.get("id") == request["id"]:
                        raw = candidate
                        break
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                time.sleep(0.005)
            if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
                raise ValueError("incomplete or oversized Lua reply")
            envelope = json.loads(raw)
            payload = envelope["payload"]
            expected = hmac.new(self.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, envelope["signature"]):
                raise ValueError("Lua reply signature mismatch")
            reply = json.loads(payload)
            if reply.get("id") != request["id"]:
                raise ValueError("Lua reply request ID mismatch")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise _WireFailure("Lua RPC failed (%s). Outcome unknown; inspect Resolve before retrying." % exc) from exc
        if not reply.get("ok"):
            error = reply.get("error") or {}
            if error.get("code") == "capability_unavailable":
                raise AttributeError(error.get("message", "Resolve method unavailable"))
            raise _WireFailure("Lua RPC refused: %s. Inspect before retrying." % error)
        result = reply.get("result")
        if isinstance(result, dict) and result.get("truncated"):
            raise _WireFailure("Lua reply was truncated; stopped rather than using incomplete timeline data.")
        return result

    def decode(self, value):
        if isinstance(value, dict):
            if "__handle__" in value:
                return _Proxy(self, value["__handle__"])
            return {key: self.decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.decode(item) for item in value]
        return value

    def encode(self, value):
        if isinstance(value, _Proxy):
            if value._connection is not self:
                raise _WireFailure("Cannot reuse Resolve handles from a different operation.")
            return {"__handle__": value._target}
        if isinstance(value, dict):
            return {str(key): self.encode(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.encode(item) for item in value]
        return value

    def health(self):
        result = self.request("health")
        if not isinstance(result, dict) or not result.get("connected") or not result.get("session"):
            raise _WireFailure("Lua worker returned no usable session.")
        self.session = result["session"]
        return result


class _Proxy:
    def __init__(self, connection, target):
        self._connection, self._target = connection, target

    def __eq__(self, other):
        return isinstance(other, _Proxy) and self._connection is other._connection and self._target == other._target

    def __setattr__(self, name, value):
        if not name.startswith("_"):
            raise AttributeError("Lua proxy attribute assignment is unavailable; use an explicit Resolve setter")
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        key = (self._target, name)
        reply = ({"kind": "callable"} if key in self._connection.methods else
                 self._connection.request("get_attribute", {"target": self._target, "name": name}))
        if reply.get("kind") == "absent":
            raise AttributeError(name)
        if reply.get("kind") == "callable":
            self._connection.methods.add(key)
            def method(*args):
                result = self._connection.request("call", {"target": self._target, "method": name,
                                                          "args": self._connection.encode(args)})
                if not isinstance(result, dict):
                    raise _WireFailure("Invalid Lua method reply; stopped without attempting a fallback.")
                return self._connection.decode(result.get("value"))
            return method
        return self._connection.decode(reply.get("value"))


def _probe_once(home=None):
    """Authenticated cached heartbeat; does not compete with an active operation."""
    try:
        home = Path(home or client.HOME)
        token = (home / "token.txt").read_text(encoding="utf-8").strip()
        with (home / "lua-agent.json").open("rb") as stream:
            raw = stream.readline(65537)
        if len(raw) > 65536:
            raise ValueError("oversized heartbeat")
        envelope = json.loads(raw)
        payload = envelope["payload"]
        expected = hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, envelope["signature"]):
            raise ValueError("invalid Lua heartbeat signature")
        result = json.loads(payload)
        age = time.time() - float(result["time"])
        if not result.get("active") or not result.get("session") or not -10 <= age <= 25:
            raise ValueError("Lua worker is not running or its heartbeat is stale")
        result.update(connected=True, heartbeat_age_seconds=round(max(0, age), 2))
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"connected": False, "reason": str(exc)}


def probe(home=None):
    # Fusion writes into pre-created private files. A reader can briefly see an
    # incomplete line between WriteLine/Flush. Retry inspection, never an edit.
    for attempt in range(8):
        result = _probe_once(home)
        if result.get("connected") or "not running" in result.get("reason", ""):
            return result
        if attempt < 7:
            time.sleep(0.005)
    return result


def request_stop(home=None):
    """Authenticated session-bound control; native worker waits for lease end."""
    home = Path(home or client.HOME)
    heartbeat = probe(home)
    if not heartbeat.get("connected"):
        return False
    token = (home / "token.txt").read_text(encoding="utf-8").strip()
    payload = _canonical({"session": heartbeat["session"], "deadline": int(time.time()) + 600,
                          "nonce": uuid.uuid4().hex, "action": "stop"})
    lifecycle.atomic_json(home / "lua-stop.json", {
        "payload": payload,
        "signature": hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest(),
    })
    return True


def call(operation, params=None, timeout=30):
    """Serialize complete operations and bind edits to this client's observations."""
    global _observed
    connection = LuaClient(timeout=timeout)
    lock = lifecycle.WorkerLock(connection.home.with_name(connection.home.name + ".lua-operation"))
    while not lock.acquire():
        if time.time() >= connection.deadline:
            raise client.BridgeTimeout("Timed out before Lua dispatch; no new operation started.")
        time.sleep(0.05)
    record = None
    begun = False
    try:
        connection.health()
        connection.transaction = uuid.uuid4().hex
        connection.request("begin_operation", {"deadline": connection.deadline})
        begun = True
        ops = ResolveOperations(lambda: _Proxy(connection, "resolve"), transport="lua")
        context = ops.queue_context()
        if operation not in QUEUE_READ_ONLY and _observed != {"session": connection.session, "context": context}:
            raise client.BridgeCallError("Inspect resolve_status or timeline_overview in this client before editing; Lua session/context changed.")
        request_id = uuid.uuid4().hex
        lifecycle.private_directory(connection.home / "requests")
        record = connection.home / "requests" / (request_id + ".json")
        data = {"id": request_id, "op": operation, "session": connection.session,
                "context": context, "state": "running", "transport": "lua", "time": time.time()}
        lifecycle.atomic_json(record, data)
        result = ops.dispatch(operation, params or {})
        context = ops.queue_context()
        _observed = {"session": connection.session, "context": context}
        data.update(state="completed", result=result, context=context)
        lifecycle.atomic_json(record, data)
        return result
    except _WireFailure as exc:
        _observed = None
        if record is not None:
            data.update(state="unknown", error=str(exc))
            lifecycle.atomic_json(record, data)
        raise client.BridgeCallError("%s Request record: %s. No automatic replay or Python fallback was sent."
                                     % (exc, record or "dispatch not started")) from exc
    except Exception as exc:
        if record is not None:
            data.update(state="failed", error=str(exc))
            lifecycle.atomic_json(record, data)
        raise
    finally:
        # Handles are scoped to one complete operation, with the OS lock held.
        if begun:
            try:
                # Finishing releases handles/lease only; it never retries an edit.
                connection.deadline = time.time() + 2
                connection.request("finish_operation")
            except (Exception, _WireFailure):
                pass
        lock.release()
