import functools
import hashlib
import hmac
import importlib.util
import json
import operator
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bridge import client, lifecycle, lua_transport, transport

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "rab_" + "test-only-token-" * 4


def envelope(value):
    payload = lua_transport._canonical(value)
    return {"payload": payload, "signature": hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha256).hexdigest()}


@unittest.skipIf(LuaRuntime is None, "optional lupa Lua 5.1 test runtime unavailable")
class LuaProtocolTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        mask = 0xffffffff
        # The portable Lua 5.1 wheel has no LuaJIT bit module. Supply its integer
        # semantics for these tests; the real Resolve host supplies bit itself.
        self.lua.globals().bit = self.lua.table_from({
            "band": lambda *v: functools.reduce(operator.and_, (int(n) & mask for n in v)),
            "bxor": lambda *v: functools.reduce(operator.xor, (int(n) & mask for n in v)),
            "bnot": lambda v: (~int(v)) & mask,
            "rshift": lambda v, n: (int(v) & mask) >> int(n),
            "ror": lambda v, n: (((int(v) & mask) >> (int(n) % 32)) |
                                 ((int(v) & mask) << ((32 - int(n)) % 32))) & mask,
            "tohex": lambda v: "%08x" % (int(v) & mask),
        })
        self.modules = {}
        self.lua.globals().require = lambda name: self.modules[name]
        for name in ("json_raw", "sha256", "rpc"):
            self.modules[name] = self.lua.execute((ROOT / "agent/lua" / (name + ".lua")).read_text())
        self.rpc, self.json = self.modules["rpc"], self.modules["json_raw"]
        self.resolve = self.lua.execute('''
            local value={count=0}
            function value:GetVersionString() return "21.1.2.10" end
            function value:Increment(v) self.count=self.count+v; return self.count end
            function value:Items() return {1,2,3} end
            return setmetatable(value,{__resolve_object=true})
        ''')
        self.ops = self.rpc.new_ops(self.resolve, self.lua.table())
        self.nonces = self.rpc.new_nonces(60)
        self.config = self.lua.table_from({"token": TOKEN, "auth_clock_skew_seconds": 60})
        self.transaction = "transaction-for-tests-0001"

    def request(self, op, args=None, **changes):
        value = {"protocol": "1.0", "id": os.urandom(16).hex(), "timestamp": int(time.time()),
                 "nonce": os.urandom(16).hex(), "operation": op, "arguments": args or {},
                 "deadline": time.time() + 30, "expected_session": self.ops.session,
                 "transaction": self.transaction}
        value.update(changes)
        value["signature"] = hmac.new(TOKEN.encode(), lua_transport._canonical(value).encode(), hashlib.sha256).hexdigest()
        return value

    def process(self, request):
        result = self.rpc.process(lua_transport._canonical(request), self.ops, self.config, self.nonces)
        return json.loads(self.json.encode(result))

    def begin(self):
        result = self.process(self.request("begin_operation", {"deadline": time.time() + 30}))
        self.assertTrue(result["ok"], result)

    def test_sha_and_hmac_vectors(self):
        for message in ("", "abc", "hello 🦊 é" * 10):
            self.assertEqual(self.modules["sha256"].sha256(message), hashlib.sha256(message.encode()).hexdigest())
            self.assertEqual(self.modules["sha256"].hmac_sha256(TOKEN, message),
                             hmac.new(TOKEN.encode(), message.encode(), hashlib.sha256).hexdigest())

    def test_unsigned_or_wrong_key_cannot_mutate(self):
        self.begin()
        request = self.request("call", {"target": "resolve", "method": "Increment", "args": [1]})
        request["signature"] = "0" * 64
        self.assertEqual(self.process(request)["error"]["code"], "unauthorized")
        self.assertEqual(self.resolve.count, 0)

    def test_valid_call_is_not_replayed(self):
        self.begin()
        request = self.request("call", {"target": "resolve", "method": "Increment", "args": [1]})
        self.assertTrue(self.process(request)["ok"])
        self.assertEqual(self.process(request)["error"]["code"], "replayed_request")
        self.assertEqual(self.resolve.count, 1)

    def test_session_lease_and_deadline_are_checked_before_mutation(self):
        args = {"target": "resolve", "method": "Increment", "args": [1]}
        self.assertEqual(self.process(self.request("call", args))["error"]["code"], "lease_mismatch")
        self.begin()
        for change, code in (({"expected_session": "old"}, "session_changed"),
                             ({"transaction": "other"}, "lease_mismatch"),
                             ({"deadline": time.time() - 1}, "expired"),
                             ({"timestamp": int(time.time()) - 120}, "stale_request")):
            self.assertEqual(self.process(self.request("call", args, **change))["error"]["code"], code)
        self.assertEqual(self.resolve.count, 0)

    def test_finish_releases_lease_and_handles(self):
        self.begin()
        self.assertTrue(self.process(self.request("finish_operation"))["ok"])
        self.assertIsNone(self.ops.transaction)
        result = self.process(self.request("get_attribute", {"target": "resolve", "name": "Increment"}))
        self.assertEqual(result["error"]["code"], "lease_mismatch")

    def test_private_attributes_and_truncation_are_explicit(self):
        self.begin()
        result = self.process(self.request("get_attribute", {"target": "resolve", "name": "__secret"}))
        self.assertEqual(result["error"]["code"], "method_not_allowed")
        self.ops.max_items = 2
        result = self.process(self.request("call", {"target": "resolve", "method": "Items", "args": []}))
        self.assertTrue(result["result"]["truncated"])


class FileTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "token.txt").write_text(TOKEN)
        lifecycle.atomic_json(self.home / "lua-outbox.json", {})

    def test_heartbeat_requires_signature_and_fresh_live_session(self):
        value = {"time": time.time(), "session": "current", "active": True}
        lifecycle.atomic_json(self.home / "lua-agent.json", envelope(value))
        self.assertTrue(lua_transport.probe(self.home)["connected"])
        for field in ({"time": time.time() - 60}, {"active": False}, {"session": None}):
            lifecycle.atomic_json(self.home / "lua-agent.json", envelope(dict(value, **field)))
            self.assertFalse(lua_transport.probe(self.home)["connected"])
        bad = envelope(value); bad["signature"] = "0" * 64
        lifecycle.atomic_json(self.home / "lua-agent.json", bad)
        self.assertFalse(lua_transport.probe(self.home)["connected"])

    def test_partial_reply_is_waited_for_without_resending_request(self):
        requests = []
        def worker():
            for _ in range(200):
                try:
                    request = json.loads((self.home / "lua-inbox.json").read_text())
                    break
                except (OSError, ValueError):
                    time.sleep(0.002)
            else:
                return
            requests.append(request["id"])
            reply = json.dumps(envelope({"id": request["id"], "ok": True, "result": {"ready": True}})) + "\n"
            with (self.home / "lua-outbox.json").open("w") as out:
                out.write(reply[:20]); out.flush(); time.sleep(0.02)
                out.write(reply[20:]); out.flush()
        thread = threading.Thread(target=worker)
        thread.start()
        self.addCleanup(thread.join)
        connection = lua_transport.LuaClient(self.home, timeout=2)
        self.assertEqual(connection.request("health"), {"ready": True})
        self.assertEqual(len(requests), 1)

    def test_auto_lua_dispatch_failure_never_replays_to_python(self):
        with patch.object(lua_transport, "probe", return_value={"connected": True}), \
             patch.object(lua_transport, "call", side_effect=client.BridgeCallError("outcome unknown")), \
             patch.object(transport, "direct_operations") as direct, patch.object(client, "call") as queue, \
             patch.dict(os.environ, RESOLVE_AI_BRIDGE_MODE="auto"):
            with self.assertRaisesRegex(client.BridgeCallError, "unknown"):
                transport.call("set_clip_transform", {"zoom": 2})
            direct.assert_not_called(); queue.assert_not_called()

    def test_uncertain_reply_blocks_cleanup_mutations_too(self):
        connection = lua_transport.LuaClient(self.home)
        with patch.object(connection, "_request", side_effect=lua_transport._WireFailure("lost reply")) as send:
            with self.assertRaises(lua_transport._WireFailure):
                connection.request("call", {"method": "SetProperty"})
            with self.assertRaisesRegex(lua_transport._WireFailure, "halted"):
                connection.request("call", {"method": "SetCurrentTimeline"})
            self.assertEqual(send.call_count, 1)

    def test_partial_heartbeat_does_not_trigger_python_fallback(self):
        value = envelope({"time": time.time(), "session": "current", "active": True})
        path = self.home / "lua-agent.json"
        path.write_text('{"payload":')
        thread = threading.Thread(target=lambda: (time.sleep(0.01), path.write_text(json.dumps(value)+"\n")))
        thread.start(); self.addCleanup(thread.join)
        self.assertTrue(lua_transport.probe(self.home)["connected"])

    def test_staged_lua_paths_use_destination_and_private_slots(self):
        spec = importlib.util.spec_from_file_location("lua_installer", ROOT / "install.py")
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        stage = self.home / "stage"
        destination = self.home / "runtime with spaces"
        with patch.object(installer, "HOME", stage):
            installer.copy_runtime(runtime_home=destination)
        start = (stage / "ResolveLua.lua").read_text()
        literal = start.splitlines()[0].split(" = ", 1)[1]
        installed_home = json.loads(literal)
        self.assertEqual(installed_home, str(destination))
        self.assertNotIn(str(stage), installed_home)
        if LuaRuntime is not None:
            self.assertEqual(LuaRuntime().execute("return " + literal), str(destination))
        for name in ("lua-inbox.json", "lua-outbox.json", "lua-agent.json", "lua-stop.json"):
            if os.name != "nt":
                self.assertEqual((stage / name).stat().st_mode & 0o777, 0o600)
