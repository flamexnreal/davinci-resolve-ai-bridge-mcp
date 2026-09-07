#!/usr/bin/env python3
"""Install Resolve AI Bridge into a stable per-user runtime folder."""

import argparse
import json
import os
import platform
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path


from bridge.operations import AGENT_VERSION as VERSION
from bridge.lifecycle import WorkerLock
ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("RESOLVE_AI_BRIDGE_HOME", Path.home() / ".resolve-ai-bridge")).expanduser()
TOKEN_FILE = HOME / "token.txt"

MENU_FOLDER = "Resolve AI Bridge"
# Stray scripts from earlier hand-made experiments that clutter Workspace >
# Scripts. The installer moves any it finds out of Resolve's Utility folder into
# a reversible backup rather than deleting them outright. Matching is by exact
# name or by these prefixes.
SUPERSEDED_SCRIPT_NAMES = {
    "Resolve AI Bridge.py",
    "Start Resolve AI Bridge.py",
    "add_explosion_overlay.py",
}
SUPERSEDED_SCRIPT_PREFIXES = ("RFAIB_",)
CONSOLE_LINE = (
    'import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),'
    'encoding="utf-8").read())'
)


def fail(message):
    print("\nINSTALL FAILED")
    print(message)
    raise SystemExit(1)


def venv_python():
    return HOME / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# --------------------------------------------------------------- runtime copy


def copy_runtime():
    """Copy into a staging directory, never remove a working bridge."""
    HOME.mkdir(parents=True, exist_ok=True)
    for folder in ("inbox", "outbox", "logs"):
        (HOME / folder).mkdir(exist_ok=True)
    shutil.copy2(ROOT / "agent" / "ResolveConsole.py", HOME / "ResolveConsole.py")
    shutil.copytree(ROOT / "bridge", HOME / "bridge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    for source in [HOME / "ResolveConsole.py", * (HOME / "bridge").glob("*.py")]:
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
    for name in ("operations.py", "server.py", "client.py", "transport.py", "lifecycle.py"):
        if not (HOME / "bridge" / name).is_file():
            fail("Incomplete staged runtime: " + name)


def prepare_runtime(skip=False, with_ffmpeg=False):
    """Stage dependencies before activation; retain previous runtime for recovery.

    A rename gap is recoverable on the next run, including after a hard kill.
    Stop MCP clients and the Console worker before updating.
    """
    global HOME
    destination = HOME
    heartbeat = destination / "agent.json"
    if heartbeat.exists():
        try:
            active = time.time() - float(json.loads(heartbeat.read_text())["time"]) < 25
        except (ValueError, KeyError, OSError, TypeError):
            active = True
        if active:
            fail("Stop the Console worker and MCP clients before updating this runtime.")
    previous = destination.with_name(destination.name + ".previous")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(destination.name + ".install-lock")
    try:
        lock.mkdir()
    except FileExistsError:
        fail("Another install may be running. If it stopped, remove %s and retry." % lock)
    stage = None
    worker_lock = None
    try:
        if not destination.exists() and previous.exists():
            os.replace(previous, destination)
        if destination.exists():
            worker_lock = WorkerLock(destination)
            if not worker_lock.acquire():
                fail("Stop the running bridge worker before updating this runtime.")
        stage = Path(tempfile.mkdtemp(prefix=destination.name + ".stage-", dir=destination.parent))
        HOME = stage
        copy_runtime()
        if (destination / ".venv").is_dir():
            shutil.copytree(destination / ".venv", stage / ".venv", symlinks=True)
        install_dependencies(skip=skip)
        if with_ffmpeg:
            install_source_decoder()
        if not skip:
            subprocess.run([str(venv_python()), "-c", "import mcp; import bridge.server"],
                           cwd=stage, check=True)
        # Preserve local state only after staging has succeeded. Updates require
        # stopped clients: copying a live queue cannot be made transactional.
        if destination.exists():
            for item in destination.iterdir():
                if item.name not in {"bridge", "ResolveConsole.py", ".venv", "agent.json", "worker.lock", "stop.json"}:
                    target = stage / item.name
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)
        if previous.exists():
            os.replace(previous, previous.with_name(previous.name + "-%d" % time.time_ns()))
        if destination.exists():
            os.replace(destination, previous)
        try:
            os.replace(stage, destination)
        except BaseException:
            if previous.exists() and not destination.exists():
                os.replace(previous, destination)
            raise
    finally:
        HOME = destination
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        if worker_lock is not None:
            worker_lock.release()
        lock.rmdir()


def get_token(rotate=False):
    if TOKEN_FILE.exists() and not rotate:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = "rab_" + secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(str(TOKEN_FILE), 0o600)
    except OSError:
        pass
    return token


def install_dependencies(skip=False):
    target = HOME / ".venv"
    if not venv_python().exists():
        print("[1/5] Creating the private Python environment...")
        venv.EnvBuilder(with_pip=True, clear=False).create(str(target))
    else:
        print("[1/5] Reusing the private Python environment...")
    if skip:
        print("      Dependency install skipped by request.")
        return
    requirements = ROOT / "requirements.txt"
    if not requirements.exists():
        fail("requirements.txt is missing.")
    print("[2/5] Installing the MCP dependency...")
    command = [
        str(venv_python()),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-r",
        str(requirements),
    ]
    try:
        subprocess.run(command, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        fail(
            "pip could not install requirements.txt. Check your internet connection and rerun the "
            "installer.\n%s" % exc
        )


def write_configs(token=None):
    entry = {
        "command": str(venv_python().resolve()),
        "args": [str((HOME / "bridge" / "server.py").resolve())],
    }
    config = {"mcpServers": {"resolve-ai-bridge": entry}}
    (HOME / "mcp-server-entry.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    claude_entry = dict(entry)
    claude_entry["type"] = "stdio"
    (HOME / "claude-server-entry.json").write_text(
        json.dumps(claude_entry, indent=2) + "\n", encoding="utf-8"
    )
    (HOME / "mcp-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # One portable line. os.path.expanduser resolves the home folder inside
    # Resolve's own interpreter, so there is never a user name to substitute
    # and the same text works on macOS, Windows, and Linux.
    (HOME / "console-command.txt").write_text(CONSOLE_LINE + "\n", encoding="utf-8")

    if os.name == "nt":
        claude_line = (
            '$entry = Get-Content -Raw "%s"; '
            "claude mcp add-json resolve-ai-bridge $entry --scope user"
        ) % (HOME / "claude-server-entry.json")
        codex_line = 'codex mcp add resolve-ai-bridge -- "%s" "%s"' % (
            entry["command"],
            entry["args"][0],
        )
    else:
        claude_line = 'claude mcp add-json resolve-ai-bridge "$(cat %s)" --scope user' % shlex.quote(
            str(HOME / "claude-server-entry.json")
        )
        codex_line = "codex mcp add resolve-ai-bridge -- %s %s" % (
            shlex.quote(entry["command"]),
            shlex.quote(entry["args"][0]),
        )
    (HOME / "codex-command.txt").write_text(codex_line + "\n", encoding="utf-8")
    (HOME / "claude-command.txt").write_text(claude_line + "\n", encoding="utf-8")
    return entry, config, claude_line, codex_line


def install_source_decoder():
    """Optional private FFmpeg binary; the Resolve worker stays standard-library only."""
    subprocess.run([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check",
                    "imageio-ffmpeg>=0.6,<1"], check=True)
    result = subprocess.run([str(venv_python()), "-c",
                             "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                            check=True, capture_output=True, text=True)
    binary = Path(result.stdout.strip())
    if not binary.is_file():
        fail("The optional FFmpeg package did not provide an executable.")
    (HOME / "ffmpeg-path.txt").write_text(str(binary) + "\n", encoding="utf-8")
    print("      Configured the private FFmpeg source decoder.")


# ------------------------------------------------------- Resolve Scripts menu


def resolve_script_roots():
    """Per-user folders DaVinci Resolve scans for Workspace > Scripts entries.

    Taken from Blackmagic's own scripting README. Resolve reads these once at
    startup, so a new entry appears after the next Resolve launch.
    """
    home = Path.home()
    if sys.platform.startswith("darwin"):
        return [home / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"]
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        return [
            appdata / "Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts",
            appdata / "Blackmagic Design/DaVinci Resolve/Fusion/Scripts",
        ]
    return [
        home / ".local/share/DaVinciResolve/Fusion/Scripts",
        Path("/opt/resolve/Fusion/Scripts"),
    ]


def _is_superseded_script(name):
    if name in SUPERSEDED_SCRIPT_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in SUPERSEDED_SCRIPT_PREFIXES)


def tidy_superseded_scripts():
    """Move earlier stray Resolve scripts into a reversible backup folder.

    Keeps Workspace > Scripts > Utility clean without destroying work: anything
    matched is moved under HOME/removed-scripts-backup, never deleted, so the
    user can restore or bin it themselves.
    """
    backup = HOME / "removed-scripts-backup"
    moved = []
    for root in resolve_script_roots():
        utility = root / "Utility"
        if not utility.is_dir():
            continue
        for entry in utility.iterdir():
            if entry.is_file() and _is_superseded_script(entry.name):
                try:
                    backup.mkdir(parents=True, exist_ok=True)
                    target = backup / entry.name
                    if target.exists():
                        target = backup / ("%s.%d%s" % (entry.stem, int(entry.stat().st_mtime), entry.suffix))
                    shutil.move(str(entry), str(target))
                    moved.append((str(entry), str(target)))
                except OSError:
                    continue
    return moved


def install_menu_scripts():
    """Copy the one-click launchers into Workspace > Scripts > Utility."""
    source = ROOT / "agent" / "menu"
    if not source.is_dir():
        return []
    installed = []
    roots = resolve_script_roots()
    existing = [root for root in roots if root.is_dir()]
    targets = existing or roots[:1]
    for root in targets:
        folder = root / "Utility" / MENU_FOLDER
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for script in sorted(source.glob("*.py")):
                shutil.copy2(script, folder / script.name)
            installed.append(str(folder))
        except OSError:
            continue
    return installed


def remove_menu_scripts():
    removed = []
    for root in resolve_script_roots():
        folder = root / "Utility" / MENU_FOLDER
        if folder.is_dir():
            try:
                shutil.rmtree(folder)
                removed.append(str(folder))
            except OSError:
                pass
    return removed


def install_skills():
    source = ROOT / "skills" / "resolve-ai-editing" / "SKILL.md"
    if not source.exists():
        return []
    installed = []
    target_locations = [
        # Antigravity / Gemini
        Path.home() / ".gemini" / "config" / "skills" / "resolve-ai-editing" / "SKILL.md",
        Path.home() / ".gemini" / "antigravity" / "skills" / "resolve-ai-editing" / "SKILL.md",
        # Claude
        Path.home() / ".claude" / "skills" / "resolve-ai-editing" / "SKILL.md",
        # Codex
        Path.home() / ".codex" / "skills" / "resolve-ai-editing" / "SKILL.md",
        # Cursor
        Path.home() / ".cursor" / "skills" / "resolve-ai-editing" / "SKILL.md",
        Path.home() / ".cursor" / "skills-cursor" / "resolve-ai-editing" / "SKILL.md",
        # Windsurf
        Path.home() / ".codeium" / "windsurf" / "skills" / "resolve-ai-editing" / "SKILL.md",
    ]
    for target in target_locations:
        if target.parent.parent.is_dir() or target.parent.is_dir():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                installed.append(str(target))
            except OSError:
                pass
    runtime_skill = HOME / "skills" / "resolve-ai-editing" / "SKILL.md"
    runtime_skill.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, runtime_skill)
    installed.append(str(runtime_skill))
    return installed


def install_global_launcher():
    """Install a global wrapper script so users can use command: 'resolve-ai-bridge' with zero path config."""
    launcher_paths = []
    if os.name == "nt":
        target_dir = Path(os.environ.get("USERPROFILE", Path.home())) / ".local" / "bin"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            batch = target_dir / "resolve-ai-bridge.cmd"
            script_content = '@echo off\r\n"%s" "%s" %%*\r\n' % (
                venv_python().resolve(),
                (HOME / "bridge" / "server.py").resolve(),
            )
            batch.write_text(script_content, encoding="utf-8")
            launcher_paths.append(str(batch))
        except OSError:
            pass
    else:
        candidates = [
            Path.home() / ".local" / "bin",
            Path("/usr/local/bin"),
        ]
        for target_dir in candidates:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                launcher = target_dir / "resolve-ai-bridge"
                script_content = '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (
                    venv_python().resolve(),
                    (HOME / "bridge" / "server.py").resolve(),
                )
                launcher.write_text(script_content, encoding="utf-8")
                launcher.chmod(0o755)
                launcher_paths.append(str(launcher))
                break
            except (OSError, PermissionError):
                continue
    return launcher_paths


def auto_configure_clients(entry):
    """Automatically detect and configure installed AI clients without manual copy-pasting."""
    configured = []

    def _merge_mcp_config(config_path, label):
        try:
            config_path = Path(config_path)
            if not config_path.parent.is_dir():
                return False
            data = {}
            if config_path.is_file():
                try:
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                except (ValueError, OSError) as exc:
                    print("      Could not read %s configuration; left unchanged: %s" % (label, exc))
                    return False
            if not isinstance(data, dict) or ("mcpServers" in data and not isinstance(data["mcpServers"], dict)):
                print("      Invalid %s configuration structure; left unchanged." % label)
                return False
            data.setdefault("mcpServers", {})
            data["mcpServers"]["resolve-ai-bridge"] = entry
            if config_path.is_file():
                backup = config_path.with_name(config_path.name + ".backup-%d" % time.time_ns())
                shutil.copy2(config_path, backup)
            fd, temporary = tempfile.mkstemp(prefix="." + config_path.name, dir=str(config_path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                if config_path.exists():
                    os.chmod(temporary, config_path.stat().st_mode & 0o777)
                os.replace(temporary, config_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            if label not in configured:
                configured.append(label)
            return True
        except OSError:
            return False

    # 1. Claude Desktop
    if sys.platform.startswith("darwin"):
        _merge_mcp_config(Path.home() / "Library/Application Support/Claude/claude_desktop_config.json", "Claude Desktop")
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        _merge_mcp_config(appdata / "Claude/claude_desktop_config.json", "Claude Desktop")
    else:
        _merge_mcp_config(Path.home() / ".config/Claude/claude_desktop_config.json", "Claude Desktop")

    # 2. Cursor
    cursor_paths = [
        Path.home() / ".cursor" / "mcp.json",
    ]
    if sys.platform.startswith("darwin"):
        cursor_paths.append(Path.home() / "Library/Application Support/Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json")
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        cursor_paths.append(appdata / "Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json")
    for cp in cursor_paths:
        _merge_mcp_config(cp, "Cursor")

    # 3. Windsurf
    windsurf_path = Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
    _merge_mcp_config(windsurf_path, "Windsurf")

    # 4. VS Code (Cline / Roo Code)
    vscode_paths = []
    if sys.platform.startswith("darwin"):
        vscode_paths.extend([
            Path.home() / "Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json",
            Path.home() / "Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
        ])
    elif os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        vscode_paths.append(appdata / "Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json")
    for vp in vscode_paths:
        _merge_mcp_config(vp, "VS Code")

    # 5. Claude Code CLI
    if shutil.which("claude"):
        claude_entry_file = HOME / "claude-server-entry.json"
        if claude_entry_file.is_file():
            try:
                res = subprocess.run(
                    ["claude", "mcp", "add-json", "resolve-ai-bridge", claude_entry_file.read_text(encoding="utf-8"), "--scope", "user"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if res.returncode == 0 and "Claude Code CLI" not in configured:
                    configured.append("Claude Code CLI")
            except Exception:
                pass

    # 6. Codex CLI
    if shutil.which("codex"):
        try:
            res = subprocess.run(
                ["codex", "mcp", "add", "resolve-ai-bridge", "--", entry["command"], entry["args"][0]],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and "Codex CLI" not in configured:
                configured.append("Codex CLI")
        except Exception:
            pass

    return configured


def probe_direct_attach():
    """Ask the private venv Python whether it can attach to Resolve on its own."""
    python = venv_python()
    if not python.exists():
        return {"ok": False, "loadable": False, "reason": "The private Python is not installed yet."}
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
        return json.loads((finished.stdout or "").strip())
    except Exception as exc:
        return {"ok": False, "loadable": False, "reason": str(exc)}


def remove_runtime():
    if not HOME.exists():
        print("Nothing to remove at %s" % HOME)
        return
    answer = input("Delete %s and its token? Type DELETE to confirm: " % HOME).strip()
    if answer != "DELETE":
        print("Uninstall cancelled.")
        return
    shutil.rmtree(HOME)
    print("Removed %s" % HOME)
    for folder in remove_menu_scripts():
        print("Removed %s" % folder)
    print("Remove the resolve-ai-bridge entry from your AI client's MCP settings separately.")


def main():
    parser = argparse.ArgumentParser(description="Install Resolve AI Bridge %s" % VERSION)
    parser.add_argument("--rotate-token", action="store_true", help="Create a new token and rewrite MCP snippets")
    parser.add_argument("--skip-deps", action="store_true", help="Copy files without running pip")
    parser.add_argument("--no-menu", action="store_true", help="Skip the Workspace > Scripts menu entries")
    parser.add_argument("--with-ffmpeg", action="store_true", help="Install an optional private FFmpeg binary for Free-compatible frame/audio extraction")
    parser.add_argument("--uninstall", action="store_true", help="Remove the installed per-user runtime")
    args = parser.parse_args()

    if args.uninstall:
        remove_runtime()
        return
    if sys.version_info < (3, 10):
        fail("Python 3.10 or newer is required. Current: %s" % sys.version.split()[0])

    print("\nResolve AI Bridge installer %s" % VERSION)
    print("Runtime: %s" % HOME)
    print("System:  %s %s\n" % (platform.system(), platform.release()))

    prepare_runtime(skip=args.skip_deps, with_ffmpeg=args.with_ffmpeg)
    print("[0/5] Activated validated runtime; previous installation retained.")
    token = get_token(rotate=args.rotate_token)
    print("[3/5] Writing the authenticated MCP configuration...")
    _entry, _config, claude_line, codex_line = write_configs(token)
    menu_paths = [] if args.no_menu else install_menu_scripts()
    tidied = [] if args.no_menu else tidy_superseded_scripts()
    print("[4/5] %s" % (
        "Installed the Workspace > Scripts menu entries."
        if menu_paths
        else "Skipped the Workspace > Scripts menu entries."
    ))
    if tidied:
        print("      Moved %d superseded script(s) out of the Scripts menu into %s"
              % (len(tidied), HOME / "removed-scripts-backup"))
    skill_paths = install_skills()
    print("[5/5] Installed the Resolve editing skill in standard skill locations.")
    launcher_paths = install_global_launcher()
    if launcher_paths:
        print("      Installed global CLI launcher at %s" % launcher_paths[0])
    auto_configured = auto_configure_clients(_entry)
    if auto_configured:
        print("      Auto-configured clients: %s" % ", ".join(auto_configured))

    direct = probe_direct_attach()

    print("\n" + "=" * 72)
    print("INSTALL COMPLETE")

    print("\nSTEP 1  Connect your AI client (Zero manual configuration needed).")
    if auto_configured:
        print("        [AUTO-CONFIGURED] Successfully registered with:")
        for client_name in auto_configured:
            print("          ✓ %s" % client_name)
        print("        Your tools are connected in those apps right away!")

    if launcher_paths:
        print("\n        GLOBAL LAUNCHER INSTALLED: %s" % launcher_paths[0])
        print("        In any client, you can use zero-path command:")
        print('          {"mcpServers": {"resolve-ai-bridge": {"command": "resolve-ai-bridge"}}}')

    print("\n        PORTABLE ZERO-PATH SNIPPET (No username or home folder editing needed):")
    print("        macOS / Linux:")
    print('          {"mcpServers": {"resolve-ai-bridge": {"command": "sh", "args": ["-c", "exec \\"$HOME/.resolve-ai-bridge/.venv/bin/python\\" \\"$HOME/.resolve-ai-bridge/bridge/server.py\\""]}}}')

    print("\n        Provider one-liners:")
    print("        Claude Code: %s" % claude_line)
    print("        Codex:       %s" % codex_line)
    print("        Explicit Absolute Config (Saved at %s):" % (HOME / "mcp-config.json"))
    for line in json.dumps(_config, indent=2).splitlines():
        print("          " + line)

    print("\nSTEP 2  Start Resolve.")
    if direct.get("ok"):
        print("        Direct attach works on this computer, so there is nothing to start")
        print("        inside Resolve. Open a project and your AI is connected.")
        print("        Detected: %s %s" % (direct.get("product", ""), direct.get("version", "")))
    else:
        print("        Resolve was not running during this check, so a direct attach could not be")
        print("        confirmed. Your AI may connect with no further steps. If it reports the")
        print("        bridge as offline, use the one-click launcher below.")
        if direct.get("reason"):
            print("        Check detail: %s" % direct["reason"])

    if menu_paths:
        print("\nSTEP 3  Start the bridge in Resolve (Free or Studio):")
        print("        Restart DaVinci Resolve once, then choose")
        print("        Workspace > Scripts > Resolve AI Bridge > Start AI Bridge.")
        print("        It starts the worker directly; no Console paste is needed on supported builds.")
        for path in menu_paths:
            print("          %s" % path)

    print("\n        Fallback Console command (Workspace > Console, Py3 tab):")
    print("          %s" % CONSOLE_LINE)
    print("        The same line is saved at %s" % (HOME / "console-command.txt"))

    print("\nVERIFY  python3 tools/doctor.py")
    print("        Then ask your AI: \"Call resolve_status and tell me what is open.\"")

    print("\nLocal Token: %s (auto-managed at %s)" % (token, TOKEN_FILE))
    print("Authentication between bridge and Resolve is 100% automatic locally.")
    if not shutil.which("node"):
        print("\nHEAVILY RECOMMENDED: install the current Node.js LTS release for Remotion.")
        print("Then follow the Remotion section in docs/REMOTION.md.")
    if skill_paths:
        print("\nResolve editing skill copies:")
        for path in skill_paths:
            print("  %s" % path)
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
