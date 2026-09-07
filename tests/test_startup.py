"""Worker lifetime regressions. Real OS locks, fake Resolve, no live edits."""
import builtins
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from bridge import lifecycle

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, RESOLVE_AI_BRIDGE_NO_AUTOSTART="1"):
    spec = importlib.util.spec_from_file_location("startup_console", ROOT / "agent/ResolveConsole.py")
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.addCleanup(self.home.with_name(self.home.name + ".worker-lock").unlink, missing_ok=True)
        for key, relative in {"HOME": "", "INBOX": "inbox", "OUTBOX": "outbox",
                              "LOGS": "logs", "TOKEN_FILE": "token.txt",
                              "HEARTBEAT_FILE": "agent.json"}.items():
            p = patch.object(console, key, self.home / relative)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(builtins, console.RUNTIME_KEY, None, create=True)
        p.start(); self.addCleanup(p.stop)
        self.resolve = Mock()
        self.ops = Mock()
        self.ops.heartbeat_payload.return_value = {"product": "DaVinci Resolve"}
        self.ops.queue_context.return_value = {"project_id": "p", "timeline_id": None}
        p = patch.object(console.operations, "ResolveOperations", return_value=self.ops)
        p.start(); self.addCleanup(p.stop)

    def start(self, menu=True):
        runtime = console.start_bridge({"resolve": self.resolve}, menu=menu)
        if runtime:
            self.addCleanup(self.stop, runtime)
        return runtime

    @staticmethod
    def stop(runtime):
        runtime.stop_event.set()
        runtime.thread.join(3)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail("Worker condition was not reached")

    def test_lock_excludes_another_process_and_recovers_after_exit(self):
        code = ('from bridge.lifecycle import WorkerLock;import sys;'
                'x=WorkerLock(sys.argv[1]);print(x.acquire(),flush=True);sys.stdin.read()')
        child = subprocess.Popen([sys.executable, '-c', code, str(self.home)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 text=True, cwd=ROOT)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'True')
            lock = lifecycle.WorkerLock(self.home)
            self.assertFalse(lock.acquire())
            child.terminate(); child.wait(timeout=5)
            self.assertTrue(lock.acquire())
            lock.release()
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
            child.stdin.close(); child.stdout.close()

    def test_console_start_returns_and_uses_daemon(self):
        with contextlib.redirect_stdout(io.StringIO()):
            runtime = self.start(menu=False)
            self.assertTrue(runtime.thread.daemon)
            self.wait_for(lambda: runtime.last_heartbeat)
            self.assertTrue(runtime.alive())
            self.stop(runtime)
        self.assertFalse((self.home/'agent.json').exists())

    def test_console_output_stays_on_calling_thread(self):
        class MainOnly(io.StringIO):
            def write(self, value):
                if threading.current_thread() is not threading.main_thread():
                    raise RuntimeError("Unsafe Console output")
                return super().write(value)
        output = MainOnly()
        with contextlib.redirect_stdout(output):
            runtime = self.start(menu=False)
            self.assertTrue(runtime.alive())
            self.assertIsNone(runtime.failure)
            self.stop(runtime)
        self.assertIn("RESOLVE AI BRIDGE READY", output.getvalue())

    def test_output_failure_does_not_unlock_running_worker(self):
        with patch.object(console.ResolveRuntime, "summary", side_effect=RuntimeError("output failed")):
            with self.assertRaisesRegex(RuntimeError, "output failed"):
                console.start_bridge({"resolve": self.resolve})
        runtime = getattr(builtins, console.RUNTIME_KEY)
        self.addCleanup(self.stop, runtime)
        self.assertTrue(runtime.alive())
        lock = lifecycle.WorkerLock(self.home)
        self.assertFalse(lock.acquire())
        self.stop(runtime)
        self.assertTrue(lock.acquire()); lock.release()

    def test_same_interpreter_reuses_worker(self):
        runtime = self.start()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIs(self.start(), runtime)
        self.wait_for(lambda: runtime.last_heartbeat)
        self.ops.heartbeat_payload.assert_called()

    def test_separate_interpreter_start_does_not_duplicate(self):
        runtime = self.start()
        with patch.object(builtins, console.RUNTIME_KEY, None):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(self.start())
        self.assertTrue(runtime.alive())

    def test_dead_new_worker_heartbeat_does_not_block_restart(self):
        (self.home/'agent.json').write_text(json.dumps({"time": time.time(), "menu_lifecycle": 1}))
        self.assertIsNotNone(self.start())

    def test_old_live_worker_is_not_duplicated(self):
        (self.home/'agent.json').write_text(json.dumps({"time": time.time()}))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(self.start())
        lock = lifecycle.WorkerLock(self.home)
        self.assertTrue(lock.acquire()); lock.release()

    def test_worker_refuses_start_during_installation(self):
        marker = self.home.with_name(self.home.name + ".install-lock")
        marker.mkdir()
        self.addCleanup(marker.rmdir)
        with self.assertRaisesRegex(RuntimeError, "installation is in progress"):
            self.start()
        self.ops.heartbeat_payload.assert_not_called()

    def test_installer_refuses_locked_worker_without_heartbeat(self):
        spec = importlib.util.spec_from_file_location("startup_installer", ROOT / "install.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        lock = lifecycle.WorkerLock(self.home)
        self.assertTrue(lock.acquire())
        try:
            with patch.object(installer, "HOME", self.home), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    installer.prepare_runtime(skip=True)
            self.assertFalse(self.home.with_name(self.home.name + ".install-lock").exists())
        finally:
            lock.release()

    def test_start_failure_releases_lock_without_native_import(self):
        with self.assertRaisesRegex(RuntimeError, "injected API"):
            console.start_bridge({})
        lock = lifecycle.WorkerLock(self.home)
        self.assertTrue(lock.acquire()); lock.release()

    def test_stop_signal_is_authenticated_and_session_bound(self):
        for data in ({"session": "other", "token": "secret"},
                     {"session": "current", "token": "wrong"},
                     {"session": "current", "token": "\u2603"}, []):
            (self.home/'stop.json').write_text(json.dumps(data))
            self.assertFalse(lifecycle.consume_stop(self.home, "current", "secret"))
        (self.home/'stop.json').write_text(json.dumps({"session": "current", "token": "secret"}))
        self.assertTrue(lifecycle.consume_stop(self.home, "current", "secret"))
        self.assertFalse(lifecycle.consume_stop(self.home, "current", "secret"))

    def test_menu_stop_ends_worker_and_releases_lock(self):
        runtime = self.start()
        self.wait_for(lambda: runtime.last_heartbeat)
        self.assertTrue(lifecycle.request_stop(self.home))
        runtime.thread.join(3)
        self.assertFalse(runtime.alive())
        self.assertFalse((self.home/'agent.json').exists())
        lock = lifecycle.WorkerLock(self.home)
        self.assertTrue(lock.acquire()); lock.release()

    def test_stop_waits_until_active_operation_finishes(self):
        runtime = self.start()
        self.wait_for(lambda: runtime.last_heartbeat)
        entered, release = threading.Event(), threading.Event()
        def process(path):
            entered.set(); release.wait(3); path.unlink(missing_ok=True)
        with patch.object(runtime, '_process', side_effect=process):
            (self.home/'inbox/job.json').write_text('{}')
            self.assertTrue(entered.wait(3))
            lifecycle.request_stop(self.home)
            self.assertTrue(runtime.alive())
            release.set(); runtime.thread.join(3)
        self.assertFalse(runtime.alive())

    def test_menu_output_stays_on_main_thread(self):
        host = Mock(is_child=True)
        host.alive.return_value = True
        writes = []
        class MainOnly(io.StringIO):
            def write(self, value):
                if threading.current_thread() is not threading.main_thread():
                    raise RuntimeError('Resolve cannot print from this worker thread')
                writes.append(value)
                return super().write(value)
        # A separate stopper represents the Stop menu process.
        def stop_later():
            deadline = time.monotonic()+3
            while time.monotonic()<deadline:
                if lifecycle.fresh_state(self.home):
                    time.sleep(.6); lifecycle.request_stop(self.home); return
                time.sleep(.01)
        stopper = threading.Thread(target=stop_later, daemon=True)
        stopper.start()
        with patch.object(lifecycle, 'MenuHost', return_value=host), contextlib.redirect_stdout(MainOnly()):
            runtime = console.start_menu_bridge({"resolve": self.resolve})
        stopper.join(3)
        self.assertFalse(runtime.alive())
        self.assertIn('RESOLVE AI BRIDGE READY', ''.join(writes))
        host.close.assert_called_once()

    def test_embedded_menu_does_not_wait_or_exit(self):
        host = Mock(is_child=False)
        with patch.object(lifecycle, 'MenuHost', return_value=host), contextlib.redirect_stdout(io.StringIO()):
            runtime = console.start_menu_bridge({"resolve": self.resolve})
            self.addCleanup(self.stop, runtime)
            self.assertTrue(runtime.alive())
            host.alive.assert_not_called()
            self.stop(runtime)

    def test_host_detection_never_blocks_resolve_executable(self):
        with patch.object(sys, 'executable', '/Applications/Resolve'):
            host = lifecycle.MenuHost()
            self.assertFalse(host.is_child)
            host.close()

    @unittest.skipIf(os.name == 'nt', 'POSIX reparenting test')
    def test_host_detects_parent_exit_without_resolve_api(self):
        with patch.object(sys, 'executable', '/opt/resolve/bin/fuscript'), patch('os.getppid', return_value=42):
            host = lifecycle.MenuHost()
            self.assertTrue(host.is_child)
            self.assertTrue(host.alive())
            with patch('os.getppid', return_value=1):
                self.assertFalse(host.alive())
            host.close()


if __name__ == '__main__':
    unittest.main()
