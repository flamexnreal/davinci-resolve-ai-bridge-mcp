"""Token creation, request order and cleanup of what the queue leaves behind."""

import importlib.util
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge import lifecycle

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, RESOLVE_AI_BRIDGE_NO_AUTOSTART="1"):
    spec = importlib.util.spec_from_file_location("console_hygiene", ROOT / "agent/ResolveConsole.py")
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)


class QueueHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_concurrent_token_creation_agrees(self):
        path = self.home / "token.txt"
        tokens, barrier = [], threading.Barrier(8)

        def create():
            barrier.wait()
            tokens.append(lifecycle.load_token(path))

        threads = [threading.Thread(target=create) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(tokens)), 1)
        self.assertEqual(path.read_text().strip(), tokens[0])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_token_kept_and_empty_token_replaced(self):
        path = self.home / "token.txt"
        path.write_text("rab_existing\n")
        self.assertEqual(lifecycle.load_token(path), "rab_existing")
        path.write_text("")
        with patch.object(lifecycle.time, "sleep"):
            replaced = lifecycle.load_token(path)
        self.assertTrue(replaced.startswith("rab_"))
        self.assertEqual(path.read_text().strip(), replaced)
        rotated = lifecycle.replace_token(path)
        self.assertNotEqual(rotated, replaced)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ["token.txt"])

    def test_prune_removes_only_stale_files(self):
        now = time.time()
        for folder in ("outbox", "requests", "logs"):
            (self.home / folder).mkdir()

        def write(relative, data, age):
            path = self.home / relative
            path.write_text(json.dumps(data))
            os.utime(path, (now - age, now - age))
            return path

        fresh_reply = write("outbox/fresh.json", {}, 60)
        old_reply = write("outbox/old.json", {}, 2 * 3600)
        fresh_record = write("requests/fresh.json", {"state": "completed"}, 3600)
        old_record = write("requests/old.json", {"state": "completed"}, 8 * 86400)
        unknown = write("requests/unknown.json", {"state": "running"}, 8 * 86400)
        ancient_unknown = write("requests/ancient.json", {"state": "running"}, 31 * 86400)
        log = self.home / "logs" / "agent.log"
        log.write_bytes(b"x" * (lifecycle.LOG_MAX_BYTES + 1))
        self.assertEqual(lifecycle.prune_runtime(self.home, now), 3)
        self.assertTrue(fresh_reply.exists() and fresh_record.exists() and unknown.exists())
        self.assertFalse(old_reply.exists() or old_record.exists() or ancient_unknown.exists())
        self.assertFalse(log.exists())
        self.assertTrue((self.home / "logs" / "agent.log.1").exists())

    def test_requests_are_taken_oldest_first(self):
        inbox = self.home / "inbox"
        inbox.mkdir()
        now = time.time()
        for age, name in ((5, "ffff"), (30, "zzzz"), (1, "0000")):
            path = inbox / (name + ".json")
            path.write_text("{}")
            os.utime(path, (now - age, now - age))
        self.assertEqual([p.stem for p in console._queued(inbox)], ["zzzz", "ffff", "0000"])


if __name__ == "__main__":
    unittest.main()
