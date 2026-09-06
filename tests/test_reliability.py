"""Queue and installation regressions; never attach to a native Resolve."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from bridge import client, transport

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, RESOLVE_AI_BRIDGE_NO_AUTOSTART="1"):
    spec = importlib.util.spec_from_file_location("console_test", ROOT / "agent/ResolveConsole.py")
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)
spec = importlib.util.spec_from_file_location("install_test", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "runtime"
        for module in (console, client):
            for key, relative in {"HOME": "", "INBOX": "inbox", "OUTBOX": "outbox",
                                  "TOKEN_FILE": "token.txt", "HEARTBEAT_FILE": "agent.json"}.items():
                p = patch.object(module, key, self.home / relative)
                p.start(); self.addCleanup(p.stop)
        p = patch.object(console, "LOGS", self.home / "logs")
        p.start(); self.addCleanup(p.stop)
        self.runtime = console.ResolveRuntime(Mock())
        self.ops = Mock()
        self.context = {"project_id": "p1", "timeline_id": "t1"}
        self.ops.queue_context.return_value = self.context
        self.ops.heartbeat_payload.return_value = {"online": True}
        self.ops.dispatch.return_value = {"edited": True}
        self.runtime.operations = self.ops
        self.runtime._refresh_snapshot()
        self.runtime._heartbeat()
        p = patch.object(client, "_observed", {"context": dict(self.context), "session": self.runtime.session})
        p.start(); self.addCleanup(p.stop)

    def request(self, name="a", **values):
        request = dict(id=name, op="add_marker", params={}, token=self.runtime.token,
                       deadline=time.time() + 30, session=self.runtime.session,
                       context=dict(self.context))
        request.update(values)
        path = console.INBOX / (name + ".json")
        console._atomic_json(path, request)
        return path, request

    def result(self, name="a"):
        return json.loads((console.OUTBOX / (name + ".json")).read_text())

    def test_post_edit_failure_is_not_replayed(self):
        edits = []
        def edit(*args):
            edits.append(1)
            raise ConnectionError("lost response after edit")
        ops = Mock(); ops.dispatch.side_effect = edit
        with patch.object(transport, "direct_operations", return_value=ops), patch.object(client, "call") as queue, patch.object(transport.direct, "reset"):
            with self.assertRaisesRegex(client.BridgeCallError, "Outcome unknown"):
                transport.call("add_marker")
            queue.assert_not_called()
        self.assertEqual(edits, [1])

    def test_pre_execution_unavailable_uses_queue(self):
        with patch.object(transport, "direct_operations", return_value=None), patch.object(client, "call", return_value={}) as queue:
            self.assertEqual(transport.call("status"), ({}, "console"))
            queue.assert_called_once()

    def test_expired_and_switched_context(self):
        for name, changes in [("expired", {"deadline": time.time() - 1}),
                              ("timeline", {"context": {"project_id": "p1", "timeline_id": "t2"}}),
                              ("project", {"context": {"project_id": "p2", "timeline_id": "t1"}})]:
            path, _ = self.request(name, **changes)
            self.runtime._process(path)
            self.assertFalse(self.result(name)["ok"])
        self.ops.dispatch.assert_not_called()

    def test_duplicate_and_restart_unknown_outcome(self):
        path, request = self.request()
        self.runtime._process(path)
        console._atomic_json(path, request)
        self.runtime._process(path)
        self.assertEqual(self.ops.dispatch.call_count, 1)
        record = self.home / "requests/a.json"
        saved = json.loads(record.read_text()); saved["state"] = "running"
        console._atomic_json(record, saved)
        console._atomic_json(path, request)
        self.runtime._process(path)
        self.assertIn("unknown", self.result()["error"])
        self.assertEqual(self.ops.dispatch.call_count, 1)
        self.assertEqual(json.loads(record.read_text())["state"], "running")

    def test_long_job_heartbeat_and_client_timeout(self):
        entered, release = threading.Event(), threading.Event()
        def job(*args):
            entered.set(); release.wait(5); return "done"
        self.ops.dispatch.side_effect = job
        self.runtime.thread = threading.Thread(target=self.runtime._loop)
        self.runtime.thread.start()
        try:
            with self.assertRaisesRegex(client.BridgeTimeout, "not confirmed cancellation"):
                client.call("add_marker", timeout=.2)
            self.assertTrue(entered.is_set())
            time.sleep(1.1)
            beat = client.heartbeat(max_age=1.1)
            self.assertTrue(beat["busy"])
            self.assertEqual(beat["state"], "running")
            # Advance wall clock beyond the old 25-second offline threshold.
            future = time.time() + 30
            with patch.object(console.time, "time", return_value=future):
                self.runtime._heartbeat()
                self.assertIsNotNone(client.heartbeat())
            # Reporter never invokes Resolve status or identity while blocked.
            calls = self.ops.queue_context.call_count
            time.sleep(1.1)
            self.assertEqual(self.ops.queue_context.call_count, calls)
        finally:
            release.set()
            self.runtime.stop_event.set()
            self.runtime.thread.join(5)
        records = list((self.home / "requests").glob("*.json"))
        self.assertEqual(json.loads(records[0].read_text())["state"], "completed")

    def test_concurrent_clients_delayed_switch(self):
        errors = []
        def caller():
            try:
                client.call("add_marker", timeout=2)
            except client.BridgeCallError as exc:
                errors.append(str(exc))
        threads = [threading.Thread(target=caller) for _ in range(2)]
        for thread in threads: thread.start()
        limit = time.monotonic() + 1
        while len(list(console.INBOX.glob("*.json"))) < 2 and time.monotonic() < limit:
            time.sleep(.01)
        self.ops.queue_context.return_value = {"project_id": "p1", "timeline_id": "other"}
        for path in console.INBOX.glob("*.json"): self.runtime._process(path)
        for thread in threads: thread.join(3)
        self.assertEqual(len(errors), 2)
        self.ops.dispatch.assert_not_called()

    def test_client_keeps_observed_context_after_other_client_switches(self):
        self.ops.queue_context.return_value = {"project_id": "p1", "timeline_id": "other"}
        self.runtime._refresh_snapshot()
        self.runtime._heartbeat()
        self.runtime.thread = threading.Thread(target=self.runtime._loop)
        self.runtime.thread.start()
        try:
            with self.assertRaisesRegex(client.BridgeCallError, "context changed"):
                client.call("add_marker", timeout=2)
            self.ops.dispatch.assert_not_called()
        finally:
            self.runtime.stop_event.set()
            self.runtime.thread.join(3)

    def test_install_failure_preserves_runtime(self):
        console.HEARTBEAT_FILE.unlink()
        (self.home / "bridge").mkdir()
        original = self.home / "bridge/original.py"
        original.write_text("old working runtime")
        with patch.object(installer, "HOME", self.home), patch.object(installer, "install_dependencies", side_effect=RuntimeError("pip failed")):
            with self.assertRaisesRegex(RuntimeError, "pip failed"):
                installer.prepare_runtime()
        self.assertEqual(original.read_text(), "old working runtime")

    def test_successful_update_retains_previous_and_token(self):
        console.HEARTBEAT_FILE.unlink()
        (self.home / "bridge").mkdir()
        (self.home / "bridge/original.py").write_text("old")
        with patch.object(installer, "HOME", self.home), patch.object(installer, "install_dependencies"):
            installer.prepare_runtime(skip=True)
        self.assertTrue((self.home / "bridge/server.py").exists())
        previous = self.home.with_name(self.home.name + ".previous")
        self.assertEqual((previous / "bridge/original.py").read_text(), "old")
        self.assertEqual((self.home / "token.txt").read_text().strip(), self.runtime.token)

    def test_hard_interruption_gap_recovered_before_dependency_failure(self):
        console.HEARTBEAT_FILE.unlink()
        previous = self.home.with_name(self.home.name + ".previous")
        os.replace(self.home, previous)
        with patch.object(installer, "HOME", self.home), patch.object(installer, "install_dependencies", side_effect=RuntimeError("pip failed")):
            with self.assertRaises(RuntimeError): installer.prepare_runtime()
        self.assertEqual((self.home / "token.txt").read_text().strip(), self.runtime.token)

    def test_interrupted_activation_restores_runtime(self):
        console.HEARTBEAT_FILE.unlink()
        (self.home / "bridge").mkdir()
        original = self.home / "bridge/original.py"
        original.write_text("old")
        replace = os.replace
        def interrupt(source, target):
            if ".stage-" in str(source) and Path(target) == self.home:
                raise KeyboardInterrupt()
            return replace(source, target)
        with patch.object(installer, "HOME", self.home), patch.object(installer, "install_dependencies"), patch.object(installer.os, "replace", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): installer.prepare_runtime(skip=True)
        self.assertEqual(original.read_text(), "old")
