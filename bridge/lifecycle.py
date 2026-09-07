"""Small, standard-library-only worker lifetime helpers. No Resolve imports."""
import hmac
import json
import os
from pathlib import Path
import sys
import time
import uuid


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
    target = home / "stop.json"
    temp = home / (".stop.%s.tmp" % uuid.uuid4().hex)
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump({"session": state["session"], "token": token}, handle)
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
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
