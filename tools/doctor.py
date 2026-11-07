#!/usr/bin/env python3
"""Diagnose the installed bridge without importing Resolve from this process."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("RESOLVE_AI_BRIDGE_HOME", Path.home() / ".resolve-ai-bridge")).expanduser()
MENU_FOLDER = "Resolve AI Bridge"
failures = 0
warnings = 0


def result(ok, label, detail="", warning=False):
    global failures, warnings
    if ok:
        prefix = "[OK]"
    elif warning:
        prefix = "[WARN]"
        warnings += 1
    else:
        prefix = "[FAIL]"
        failures += 1
    print("%-6s %s%s" % (prefix, label, (": " + detail) if detail else ""))


def check_python_sources():
    files = [ROOT / "install.py"]
    for folder in ("agent", "bridge", "tools"):
        files.extend(sorted((ROOT / folder).glob("*.py")))
    files.extend(sorted((ROOT / "agent" / "menu").glob("*.py")))
    errors = []
    for path in files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except Exception as exc:
            errors.append("%s: %s" % (path.relative_to(ROOT), exc))
    result(
        not errors,
        "Python source syntax",
        "; ".join(errors) if errors else "%d files compiled in memory" % len(files),
    )


def venv_python():
    return HOME / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def menu_script_folders():
    home = Path.home()
    if sys.platform.startswith("darwin"):
        roots = [home / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"]
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        roots = [
            appdata / "Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts",
            appdata / "Blackmagic Design/DaVinci Resolve/Fusion/Scripts",
        ]
    else:
        roots = [
            home / ".local/share/DaVinciResolve/Fusion/Scripts",
            Path("/opt/resolve/Fusion/Scripts"),
        ]
    return [root / "Utility" / MENU_FOLDER for root in roots]


def check_menu_scripts():
    folders = menu_script_folders()
    for label, name in (("Python", "Start AI Bridge.py"), ("Lua", "Start AI Bridge (Lua).lua")):
        found = next((folder / name for folder in folders if (folder / name).is_file()), None)
        result(
            found is not None,
            "Workspace > Scripts %s launcher" % label,
            str(found) if found else "not installed; rerun install.py, then restart Resolve",
            warning=True,
        )


def check_lua_runtime():
    scripts = ("ResolveLua.lua", "StopLua.lua", "StatusLua.lua", "lua/rpc.lua", "lua/json_raw.lua", "lua/sha256.lua")
    slots = ("lua-inbox.json", "lua-outbox.json", "lua-agent.json", "lua-stop.json")
    missing = [name for name in scripts + slots if not (HOME / name).is_file()]
    result(not missing, "Installed Lua worker",
           "missing " + ", ".join(missing) if missing else "native Fusion file transport")


def check_console_command(name, label, markers):
    try:
        line = (HOME / name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        line = ""
    ready = bool(line) and len(line.splitlines()) == 1 and all(marker in line for marker in markers)
    result(ready, label, "ready" if ready else "missing or outdated; rerun install.py")


def check_direct_attach():
    """Probe the direct attach in the private Python, in its own process."""
    python = venv_python()
    if not python.exists():
        result(False, "Direct attach to Resolve", "private Python missing", warning=True)
        return None
    source = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from bridge import direct;"
        "sys.stdout.write(json.dumps(direct.probe_in_process()))" % str(HOME)
    )
    try:
        finished = subprocess.run(
            [str(python), "-c", source],
            capture_output=True,
            text=True,
            timeout=25,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        payload = json.loads((finished.stdout or "").strip())
    except Exception as exc:
        payload = {"ok": False, "loadable": False, "reason": str(exc)}

    if payload.get("ok"):
        result(
            True,
            "Direct attach to Resolve",
            "%s %s, no Console worker needed"
            % (payload.get("product", "Resolve"), payload.get("version", "")),
        )
    elif payload.get("loadable"):
        result(
            False,
            "Direct attach to Resolve",
            "library loads but Resolve did not answer (is Resolve open?)",
            warning=True,
        )
    else:
        result(
            False,
            "Direct attach to Resolve",
            "unavailable on this setup, the Console worker will be used",
            warning=True,
        )
    return payload


def main():
    global failures, warnings
    failures = warnings = 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Check files only; never attach or queue Resolve calls")
    args = parser.parse_args()
    print("\nResolve AI Bridge doctor")
    print("Runtime: %s\n" % HOME)

    result(sys.version_info >= (3, 10), "Python version", sys.version.split()[0])
    check_python_sources()
    result((HOME / "ResolveConsole.py").exists(), "Installed Console worker", str(HOME / "ResolveConsole.py"))
    result((HOME / "bridge" / "server.py").exists(), "Installed MCP server", str(HOME / "bridge" / "server.py"))
    result(
        (HOME / "bridge" / "operations.py").exists(),
        "Installed operations module",
        str(HOME / "bridge" / "operations.py"),
    )
    result((HOME / "bridge" / "lifecycle.py").exists(), "Installed worker lifecycle",
           str(HOME / "bridge" / "lifecycle.py"))
    check_lua_runtime()
    result(venv_python().exists(), "Private Python", str(venv_python()))
    check_menu_scripts()

    check_console_command("console-command.txt", "Portable Python Console line", ("expanduser", "ResolveConsole.py"))
    check_console_command("lua-console-command.txt", "Portable Lua Console line", ("RunScript", "ResolveLua.lua"))

    token_path = HOME / "token.txt"
    token = ""
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        pass
    result(
        token.startswith("rab_") and len(token) > 30,
        "Local token",
        "present and hidden" if token else "missing",
    )

    config_path = HOME / "mcp-config.json"
    config_ok = False
    config_detail = str(config_path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        entry = config["mcpServers"]["resolve-ai-bridge"]
        env_token = entry.get("env", {}).get("RESOLVE_AI_BRIDGE_TOKEN")
        token_valid = (env_token == token) if env_token else token_path.exists()
        config_ok = (
            Path(entry["command"]).exists()
            and Path(entry["args"][0]).exists()
            and token_valid
        )
        if not config_ok:
            config_detail = "paths or token do not match; rerun install.py"
    except Exception as exc:
        config_detail = str(exc)
    result(config_ok, "MCP configuration", config_detail)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from bridge import lifecycle, lua_transport
    lua = lua_transport.probe(HOME)
    lua_online = bool(lua.get("connected"))
    result(lua_online, "Lua worker", ("Resolve " + lua.get("resolve_version", "")) if lua_online else "not running", warning=True)
    direct = {} if args.offline or lua_online else (check_direct_attach() or {})

    heartbeat = lifecycle.fresh_state(HOME)
    console_online = bool(heartbeat)
    if console_online:
        detail = "project %s, timeline %s" % (
            heartbeat.get("project") or "none",
            heartbeat.get("timeline") or "none",
        )
    else:
        detail = "not running or heartbeat invalid/stale"
    # This is a live state, never an installation problem, so it stays a warning.
    result(console_online, "Console worker", detail, warning=True)

    if args.offline:
        result(True, "Round trip to Resolve", "skipped by --offline; no native or queue calls")
    elif direct.get("ok") or console_online or lua_online:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        try:
            from bridge import transport

            status, used = transport.call("status", timeout=10)
            result(
                bool(status and status.get("online")),
                "Round trip to Resolve",
                "answered over the %s transport" % used,
            )
        except Exception as exc:
            result(False, "Round trip to Resolve", str(exc))
    else:
        result(
            False,
            "Round trip to Resolve",
            "skipped until Resolve is open and reachable",
            warning=True,
        )

    print("\nSummary: %d failure(s), %d warning(s)" % (failures, warnings))
    if failures:
        print("See docs/TROUBLESHOOTING.md for repair steps.")
    elif args.offline:
        print("Local files are healthy. A live connection was not tested.")
    elif not (direct.get("ok") or console_online or lua_online):
        print("Local files are healthy. Open DaVinci Resolve with a project, then run this again.")
    else:
        print("The bridge is installed and Resolve is reachable.")
    print()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
