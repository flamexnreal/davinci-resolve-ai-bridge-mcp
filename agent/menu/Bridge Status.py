#!/usr/bin/env python
"""Workspace > Scripts > Resolve AI Bridge > Bridge Status.

Prints what the bridge sees right now, without changing anything. Use this
first whenever an AI client says Resolve is offline.
"""

import json
import os
import time

HOME = os.path.expanduser(
    os.environ.get("RESOLVE_AI_BRIDGE_HOME", "~/.resolve-ai-bridge")
)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def main():
    print("\n" + "=" * 68)
    print("RESOLVE AI BRIDGE STATUS")
    print("Runtime folder: %s" % HOME)

    if not os.path.isdir(HOME):
        print("\nNot installed. Run install.py from the downloaded project folder.")
        print("=" * 68 + "\n")
        return

    heartbeat = read_json(os.path.join(HOME, "agent.json"))
    if heartbeat:
        age = time.time() - float(heartbeat.get("time", 0))
        state = "running" if age < 25 else "stale (%.0fs old)" % age
        print("\nBridge worker: %s" % state)
        print("  Project:  %s" % (heartbeat.get("project") or "none open"))
        print("  Timeline: %s" % (heartbeat.get("timeline") or "none open"))
        print("  Requests served: %s" % heartbeat.get("served", 0))
        print("  Version: %s" % heartbeat.get("agent_version", "unknown"))
    else:
        print("\nBridge worker: not running")
        print("  Choose Workspace > Scripts > Resolve AI Bridge > Start AI Bridge.")
        print("  Your AI client may still reach Resolve directly, which needs no worker.")

    config = os.path.join(HOME, "mcp-config.json")
    print("\nMCP configuration: %s" % ("present" if os.path.isfile(config) else "missing"))
    print("  %s" % config)
    print("\nProvider commands:")
    for label, name in (("Claude Code", "claude-command.txt"), ("Codex", "codex-command.txt")):
        path = os.path.join(HOME, name)
        print("  %-12s %s" % (label + ":", path if os.path.isfile(path) else "missing"))
    print("\nFull diagnosis, in a normal terminal: python3 tools/doctor.py")
    print("=" * 68 + "\n")


main()
