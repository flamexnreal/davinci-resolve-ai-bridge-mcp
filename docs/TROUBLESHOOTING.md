# Troubleshooting

Run `python3 tools/doctor.py` on macOS or `py tools/doctor.py` on Windows before changing files. With Resolve open it reports which transport is live and round-trips a real request.

## My AI Says The Bridge Is Offline

In this order:

1. Open DaVinci Resolve with a project.
2. Run doctor and read the **Direct attach to Resolve** line.
3. If it says the library loads but Resolve did not answer, check **Preferences > System > General > External scripting using**. For external scripting, **Local** is the normal setting. Resolve Free users can use the Console worker without enabling external access.
4. If direct attach is unavailable on your build, use **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**.
5. If that menu is missing, run the installer again and restart Resolve once. Resolve only scans for new menu scripts while it starts up.
6. As a last resort, paste the line in `~/.resolve-ai-bridge/console-command.txt` into **Workspace > Console** with the **Py3** tab selected.

## The Workspace > Scripts Menu Entry Is Missing

Resolve enumerates script folders at startup only.

1. Run `python3 install.py` again and read the path it prints.
2. Fully quit and reopen DaVinci Resolve.
3. Look under **Workspace > Scripts > Resolve AI Bridge**.

The launchers are installed here:

- macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/Resolve AI Bridge`
- Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Resolve AI Bridge`
- Linux: `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Resolve AI Bridge`

## Installed Console Worker Is Missing

Run the installer again from the complete downloaded repository. The required installed files are:

```text
~/.resolve-ai-bridge/ResolveConsole.py
~/.resolve-ai-bridge/bridge/operations.py
```

The downloaded repository folder may be renamed. Do not rename the installed files.

## Console Says Resolve's API Object Was Not Found

1. Confirm the command ran inside Resolve, not in a normal terminal.
2. Confirm the Console language tab is **Py3**.
3. Confirm a normal Resolve project is open.
4. Paste the exact line from `~/.resolve-ai-bridge/console-command.txt`.
5. Copy the full Console error into a private support request. Do not include the token.

## Resolve Becomes Unresponsive

The worker starts a daemon thread and returns control immediately. If the Console stays busy, restart Resolve and confirm the installed file is the current `ResolveConsole.py`. Do not paste an older agent that ends in a blocking polling loop.

## Console Worker Reports Stale

The MCP process treats the worker as offline when `agent.json` is missing or older than 25 seconds. That is expected after Resolve quits, and harmless when direct attach is in use.

1. Keep Resolve open.
2. Run **Bridge Status** from the Workspace > Scripts menu.
3. Run **Start AI Bridge** again. A running worker prints its summary without starting a second one.
4. Run doctor again.

## Token Mismatch or Authentication

The bridge uses a private local token file stored at `~/.resolve-ai-bridge/token.txt` (chmod `0600`).
Both the MCP server and Resolve Console worker read the same file automatically, so no token needs to be typed or configured in your AI client.

If you previously hardcoded an old `RESOLVE_AI_BRIDGE_TOKEN` in your AI client's MCP configuration (`env` block), simply remove the `env` block from your MCP settings. The server will automatically use the live local token file.

Rotate a leaked token with:

```bash
python3 install.py --rotate-token
```

## MCP Server Does Not Appear

- Use absolute paths from the generated `mcp-config.json`.
- Preserve valid JSON commas and braces when merging with existing servers.
- Confirm the private venv Python exists.
- Fully restart the AI client after changing its MCP config.
- Check the AI client's MCP log for the first Python exception.

Do not run `bridge/server.py` in a visible terminal and type into it. The AI client starts it and communicates over stdio.

## An Image Only Lasts One Frame

The image was appended as ordinary footage. Use `add_image` with `duration_seconds`, then read `actual_duration_frames` in the reply.

If Resolve shortens the still anyway, raise **Preferences > Editing > Standard still duration** and try again. `add_image` reports when this happened rather than reporting a false success.

## An Image Is Not Visible

It is probably underneath your footage. Put overlays on `track_index` 2 or higher, then confirm with `timeline_overview` that the item label is `V2.x` and that the clip is enabled.

## insert_title Reports text_set false

Setting a title's text through the scripting API is not supported on every Resolve build. Type the text in the Inspector, or build the title in Remotion and import the rendered clip.

## An Edit Tool Returns An Error

Resolve rejected the operation. Call `timeline_overview` again and check the open timeline, ids, frame rate, and permissions. Do not assume the edit happened.

Some Resolve APIs differ by version. Include the Resolve version, operating system, exact tool call, returned error, and a redacted `logs/agent.log` when reporting a bug.

## Forcing A Transport While Testing

```bash
RESOLVE_AI_BRIDGE_MODE=console python3 tools/doctor.py
RESOLVE_AI_BRIDGE_MODE=direct python3 tools/doctor.py
```

Set the same variable in your MCP entry's `env` block to pin one route permanently.

## Remotion Command Is Not Found

1. Install the current Node.js LTS release.
2. Close and reopen the terminal.
3. Confirm `node --version` and `npm --version` work.
4. Run Remotion commands from the Remotion project folder, not the Resolve Console.

## New tools are missing after an update

Reinstall from the updated checkout, then restart/refresh the MCP server in your AI client. The running Console worker reloads operations per request, but clients cache tool schemas. `resolve_status` can work without a timeline; timeline tools require one.

## Free frame capture needs a decoder

Install the optional private binary with `python3 install.py --with-ffmpeg`, or provide ffmpeg on PATH. A custom absolute binary path can be provided through RESOLVE_AI_BRIDGE_FFMPEG. Source fallback cannot show timeline effects; use the actual Resolve viewer to verify those when composite export is unavailable.

## Split or cleanup refuses a clip

Reconstruction is restricted where source timing or effect preservation is uncertain. Use Resolve's manual razor for Fusion clips, retimed/mixed-rate material, or complex linked edits. Checkpoint/preview names are returned for recovery. Never delete the original/checkpoint before reviewing the result.

## Speed reset does not remove an older TimeSpeed node

The updated bridge only resets nodes tagged as its own. User-made and older untagged TimeSpeed nodes are preserved because their ownership cannot be determined safely. Inspect/remove the old node manually if appropriate. Reverse mapping is not verified and is refused.

## Existing client configuration was not updated

Malformed JSON or an unexpected structure is preserved rather than overwritten. Fix the existing configuration, then rerun setup. Successful merges create a timestamped .backup file next to the original.
