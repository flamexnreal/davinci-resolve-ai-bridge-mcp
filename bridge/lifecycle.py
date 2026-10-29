"""Small, standard-library-only worker lifetime helpers. No Resolve imports."""
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import time
import uuid


# Retention for files the queue leaves behind (seconds).
OUTBOX_MAX_AGE = 3600           # unread replies: no client waits longer than a few minutes
REQUEST_RECORD_MAX_AGE = 7 * 86400
UNKNOWN_RECORD_MAX_AGE = 30 * 86400  # "running" records explain an unknown outcome; keep longer
LOG_MAX_BYTES = 1024 * 1024


def private_directory(path):
    """Keep local requests and their authentication material owner-only."""
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def atomic_json(path, data, indent=None):
    """Write private JSON atomically, including the temporary file's first byte."""
    path = Path(path)
    temp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=True, indent=indent)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(str(temp), str(path))
    finally:
        temp.unlink(missing_ok=True)


def load_token(path):
    """Return the shared queue token, creating it owner-only (0600) if it is missing.

    O_EXCL makes exactly one process create the token, so the MCP server and the
    Resolve worker can never start with different tokens.
    """
    path = Path(path)
    private_directory(path.parent)
    for _ in range(40):
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                if os.name != "nt":
                    path.chmod(0o600)
                return value
        except FileNotFoundError:
            token = "rab_" + secrets.token_urlsafe(32)
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue  # Another process won the race; read its token.
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token + "\n")
            return token
        time.sleep(0.025)  # Empty: another process may still be writing it.
    return replace_token(path)  # Still empty after a second.


def replace_token(path):
    """Write a new token atomically; the file is owner-only from its first byte."""
    path = Path(path)
    token = "rab_" + secrets.token_urlsafe(32)
    temp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
        os.replace(str(temp), str(path))
    finally:
        temp.unlink(missing_ok=True)
    return token


def prune_runtime(home, now=None):
    """Delete stale queue leftovers and rotate the worker log. Returns the count removed."""
    home = Path(home)
    now = time.time() if now is None else now
    removed = 0

    def old(path, age):
        try:
            return now - path.stat().st_mtime > age
        except OSError:
            return False

    for path in (home / "outbox").glob("*.json"):
        if old(path, OUTBOX_MAX_AGE):
            path.unlink(missing_ok=True)
            removed += 1
    for path in (home / "requests").glob("*.json"):
        if not old(path, REQUEST_RECORD_MAX_AGE):
            continue
        try:
            running = json.loads(path.read_text(encoding="utf-8")).get("state") == "running"
        except (OSError, ValueError, AttributeError):
            running = False
        if running and not old(path, UNKNOWN_RECORD_MAX_AGE):
            continue
        path.unlink(missing_ok=True)
        removed += 1
    log = home / "logs" / "agent.log"
    try:
        if log.stat().st_size > LOG_MAX_BYTES:
            os.replace(str(log), str(log.with_name("agent.log.1")))
    except OSError:
        pass
    return removed


class WorkerLock:
    """OS lock, released on process exit; never delete the shared lock file."""

    def __init__(self, home):
        home = Path(home)
        # A sibling stays locked across runtime-directory replacement on Windows.
        self.path = home.with_name(home.name + ".worker-lock")
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def read_state(home):
    try:
        data = json.loads((Path(home) / "agent.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def fresh_state(home):
    data = read_state(home)
    try:
        return data if -10 <= time.time() - float(data.get("time", 0)) <= 25 else {}
    except (TypeError, ValueError):
        return {}


def request_stop(home):
    """A session-bound local signal; no API call or new public MCP tool."""
    home = Path(home)
    state = fresh_state(home)
    if not state.get("session"):
        return False
    if not state.get("menu_lifecycle"):
        raise RuntimeError("This older worker must be stopped in its Py3 Console or by closing Resolve.")
    token = (home / "token.txt").read_text(encoding="utf-8").strip()
    atomic_json(home / "stop.json", {"session": state["session"], "token": token})
    return True


def consume_stop(home, session, token):
    path = Path(home) / "stop.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False
    try:
        return (isinstance(data, dict) and data.get("session") == session
                and hmac.compare_digest(str(data.get("token", "")).encode("utf-8"), token.encode("utf-8")))
    finally:
        path.unlink(missing_ok=True)


class MenuHost:
    """Only fuscript is held open. Never block an embedded Console interpreter.

    POSIX reparents an orphan. Windows needs a process handle: getppid() there
    keeps returning the dead parent's ID. Neither check calls Resolve's API.
    """

    def __init__(self):
        self.is_child = Path(sys.executable).stem.lower() == "fuscript"
        self.parent = os.getppid()
        self.handle = None
        self.kernel = None
        if self.is_child and os.name == "nt":
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.kernel.OpenProcess.restype = wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.kernel.WaitForSingleObject.restype = wintypes.DWORD
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.handle = self.kernel.OpenProcess(0x00100000, False, self.parent)
            if not self.handle:
                raise RuntimeError("Cannot monitor Resolve's lifetime; use the Py3 Console fallback.")

    def alive(self):
        if self.kernel is not None:
            return self.kernel.WaitForSingleObject(self.handle, 0) == 0x00000102
        return self.parent > 1 and os.getppid() == self.parent

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
