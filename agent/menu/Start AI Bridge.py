#!/usr/bin/env python
"""Workspace > Scripts > Resolve AI Bridge > Start AI Bridge.

Copies the activation command to clipboard and explains the Py3 step.
"""

import os
import subprocess
import sys

HOME = os.path.expanduser(
    os.environ.get("RESOLVE_AI_BRIDGE_HOME", "~/.resolve-ai-bridge")
)
PORTABLE_CMD = (
    'import os;exec(open(os.path.expanduser('
    '"~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())'
)


def _copy_to_clipboard(text):
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen("pbcopy", stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return True
        elif sys.platform.startswith("win"):
            p = subprocess.Popen("clip", stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return True
    except Exception:
        pass
    return False


def main():
    copied = _copy_to_clipboard(PORTABLE_CMD)
    paste_key = "Cmd+V" if sys.platform == "darwin" else "Ctrl+V"
    print("\n" + "=" * 72)
    print("RESOLVE AI BRIDGE ACTIVATION")
    print("=" * 72)
    if copied:
        print("[AUTO-COPIED] The activation command is already in your clipboard!\n")
    else:
        print("Copy the activation command below:\n")
    print("Command:")
    print("   " + PORTABLE_CMD + "\n")
    print("Next steps:")
    print("1. Click the 'Py3' tab at the top of this Console window.")
    print("2. Press %s (Paste) and hit Enter." % paste_key)
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()



