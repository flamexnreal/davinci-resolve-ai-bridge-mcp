#!/usr/bin/env python
"""Stop the session's worker, including workers in another menu process."""
import os
import sys


def main():
    home = os.path.expanduser(os.environ.get("RESOLVE_AI_BRIDGE_HOME", "~/.resolve-ai-bridge"))
    if home not in sys.path:
        sys.path.insert(0, home)
    try:
        from bridge.lifecycle import request_stop
        if request_stop(home):
            print("Stop requested. The worker will stop after its current operation finishes.")
        else:
            print("Resolve AI Bridge is not running.")
    except Exception as exc:
        print("Could not stop Resolve AI Bridge: %s" % exc)


main()
