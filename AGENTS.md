# Resolve AI Bridge Agent Instructions

Read `README.md` and `skills/resolve-ai-editing/SKILL.md` before changing the Python bridge or editing a Resolve project.

## Architecture rules

- `bridge/operations.py` is the single implementation of every Resolve operation. Add new capability there, not in a transport. It must stay standard library only, and must never import `mcp` or `fusionscript`.
- `agent/ResolveConsole.py` may depend only on the standard library, `bridge/operations.py`, and Resolve's injected objects.
- Never import Resolve from `bridge/server.py`, `bridge/client.py`, or `tools/`. Only `bridge/direct.py` loads Resolve's native module, and only in a process that can afford to die.
- `bridge/direct.py` must keep probing in a disposable subprocess before loading the native module in-process. A native module built for another Python can abort the process, and the MCP server has to survive that.
- Fall back to the Console queue only before direct dispatch starts. After an unexpected dispatch failure, report an unknown outcome and never replay automatically.
- Keep Resolve API calls on the single operation worker. Heartbeat reporting must use cached Python data. Preserve deadline, session, per-client observed context and durable request checks.
- Stage and validate runtime/dependencies before activation; retain the previous runtime. Test installers in temporary directories, with no live client configuration changes.
- Never write normal output to stdout from `bridge/`; stdio is reserved for MCP JSON-RPC.
- Preserve token validation on every queue request.
- Preserve the non-blocking Console start. Do not replace the daemon worker with a blocking loop.
- Use absolute installed paths in MCP configuration.

## Setup rules

- Nothing a user copies may contain a personal path. The Console line must stay a single portable line that expands `~` at runtime.
- Keep the three start routes working: direct attach, the Workspace > Scripts launcher, and the Console line.
- Menu launcher files live in `agent/menu/` and are copied by the installer. They must degrade with a readable message when the runtime is missing.

## Honesty rules

- Report what Resolve actually did. `add_image` returning a shorter clip than requested must say so; `insert_title` must report whether the text was really set.
- Be explicit about anything not tested against a real Resolve instance.
- Do not add tools for API calls that are Studio-only or that cannot be verified.

Run the doctor check after changes. Keep README.md and documentation in agreement.

## Review and regression rules

- Use unique clip IDs as primary identifiers; short labels are positional.
- Frame inputs are absolute timeline positions. Keep marker-relative offsets and source positions explicit, and retain drop-frame tests.
- New workflows must use Free-compatible ordinary APIs; verify returned results and document manual integration limits.
- Preserve the original/checkpoint before destructive reconstruction. Report partial failures honestly.
- Modify only bridge-owned speed nodes; never bypass a user's Fusion chain during reset.
- Treat source images/audio as source-only, not a composited viewer or Fairlight mix.
- Do not overwrite malformed client configs. Back up valid configs before atomic merges.
- Run `python3 -m unittest discover -s tests -v` and `node tools/check-package.mjs` for relevant changes, plus the doctor after installation.
- Follow docs/RELEASING.md when publishing is explicitly requested. Do not choose a release tag/version on behalf of a maintainer who is handling that separately.
