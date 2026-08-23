#!/usr/bin/env python
"""Workspace > Scripts > Resolve AI Bridge > Start AI Bridge.

Directly starts or attaches the Resolve AI Bridge Console worker.
"""

import os
import sys

HOME = os.path.expanduser(
    os.environ.get("RESOLVE_AI_BRIDGE_HOME", "~/.resolve-ai-bridge")
)
AGENT = os.path.join(HOME, "ResolveConsole.py")


def main():
    if not os.path.isfile(AGENT):
        print("\nResolve AI Bridge is not installed at %s. Run install.py first.\n" % HOME)
        return

    if HOME not in sys.path:
        sys.path.insert(0, HOME)

    # Inform the worker to keep running in the background across menu execution
    globals()["RESOLVE_AI_BRIDGE_KEEPALIVE"] = True
    os.environ.pop("RESOLVE_AI_BRIDGE_NO_AUTOSTART", None)

    try:
        with open(AGENT, encoding="utf-8") as handle:
            source = handle.read()
        exec(compile(source, AGENT, "exec"), globals())
    except Exception as exc:
        print("\nCould not start Resolve AI Bridge automatically: %s" % exc)
        print("Fallback: Open Workspace > Console, click Py3, and paste:")
        print('import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())\n')


if __name__ == "__main__":
    main()


