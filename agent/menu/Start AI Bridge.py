#!/usr/bin/env python
"""Start the worker using the API object Resolve supplies to its menu scripts."""
import os
import sys

HOME = os.path.expanduser(os.environ.get("RESOLVE_AI_BRIDGE_HOME", "~/.resolve-ai-bridge"))
AGENT = os.path.join(HOME, "ResolveConsole.py")
PORTABLE_CMD = 'import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())'


def main():
    try:
        if not os.path.isfile(AGENT):
            raise RuntimeError("Resolve AI Bridge is not installed. Run install.py first.")
        if HOME not in sys.path:
            sys.path.insert(0, HOME)
        # An isolated namespace avoids overwriting this launcher's globals.
        namespace = dict(globals(), __file__=AGENT, RESOLVE_AI_BRIDGE_MANUAL_START=True)
        with open(AGENT, encoding="utf-8") as handle:
            exec(compile(handle.read(), AGENT, "exec"), namespace)
        namespace["start_menu_bridge"](namespace)
    except Exception as exc:
        print("\nRESOLVE AI BRIDGE DID NOT START: %s" % exc)
        print("Fallback: Workspace > Console, select Py3, paste and press Enter:")
        print(PORTABLE_CMD)


main()
