# DaVinci Resolve AI Bridge

<img width="768" alt="Resolve AI Bridge demo" src="https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/assets/demo.gif" />

[![npm version](https://img.shields.io/npm/v/davinci-resolve-ai-bridge-mcp.svg)](https://www.npmjs.com/package/davinci-resolve-ai-bridge-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)

Connect AI assistants to the project open in **DaVinci Resolve Free** through a local MCP bridge. Inspect timelines, place media, animate clips, review edits on duplicate timelines, and analyze source audio. Studio users can use the same bridge.

The Free workflow starts a small worker from **Workspace → Scripts → Resolve AI Bridge → Start AI Bridge**, using the connection supplied by Resolve. It does not need a Studio license, paid AI feature, remote server, or manually entered API token. Availability of individual Resolve operations still depends on your version and media. The bridge cannot unlock Studio-only effects.

## Install

Requires Python 3.10 or later. Node/npm is only needed for the npm installer and optional website/motion-graphics development.

```bash
npx davinci-resolve-ai-bridge-mcp
```

For Free-compatible source frame capture and efficient audio decoding, also install the optional private FFmpeg binary:

```bash
npx davinci-resolve-ai-bridge-mcp --with-ffmpeg
```

This optional download stays in the bridge's private Python environment. It is not a Studio dependency. An existing `ffmpeg` on PATH also works; macOS `afconvert` supports audio extraction without FFmpeg.

Other installation routes:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/install.sh | bash
```

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/install.ps1 | iex
```

From a downloaded/cloned repository, run `python3 install.py --with-ffmpeg` (Windows: `py install.py --with-ffmpeg`), or use `install-macos.command` / `install-windows.bat` for the base install.

The installer copies the bridge into `~/.resolve-ai-bridge`, creates a private Python environment, installs menu launchers and editing skills, and configures detected supported AI clients. Existing valid JSON configurations are backed up and merged. Invalid configurations are left unchanged with a diagnostic. Antigravity and other clients can use the generated `mcp-config.json` manually.

## Start the worker in Resolve Free

1. Open Resolve with a project.
2. Choose **Workspace → Scripts → Resolve AI Bridge → Start AI Bridge**. Depending on the menu layout, it may appear under **Utility**.
3. The launcher starts the worker directly. **No Py3 selection, copy/paste, or Enter is needed.** Confirm with your AI client's `resolve_status`, or open **Workspace → Console** to see **RESOLVE AI BRIDGE READY**. Create or open a timeline before using timeline tools.

If automatic startup reports an error on your build, open **Workspace → Console**, select **Py3**, paste this fallback command and press Enter:

```python
import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())
```

Run **Start AI Bridge** once each Resolve session. Use **Stop AI Bridge** in the same menu to stop it; an active operation finishes first. Repeated starts do not create a second worker. If the menu is missing after installation, restart Resolve once.

**Live startup validation:** macOS, DaVinci Resolve **Free 21.0.3.7**, Python **3.14.6**: menu start, real status requests, repeated start, Stop, quit/reopen/start, and Console fallback passed. Windows/Linux and other Resolve builds still require live verification; the portable fallback remains available.

Resolve may keep the menu script marked busy while its separate `fuscript` process serves requests. Resolve's editing UI remains usable. Closing Resolve ends that process. The Console fallback uses a daemon worker with a startup handshake capped at one second. No new dependency, listening port, public MCP tool, or AI call is added.

When external scripting is available, the bridge can attach directly. Studio users can enable **Preferences → System → General → External scripting using → Local**. Direct attach is probed in a disposable process; when unavailable, the Console transport is used. Free users can stay with the Console workflow.

## Connect Codex / ChatGPT desktop

The installer registers the bridge when it finds the Codex CLI. Check with:

```bash
codex mcp get resolve-ai-bridge
```

If needed, register the installed runtime on macOS/Linux:

```bash
codex mcp add resolve-ai-bridge -- "$HOME/.resolve-ai-bridge/.venv/bin/python" "$HOME/.resolve-ai-bridge/bridge/server.py"
```

On Windows PowerShell:

```powershell
codex mcp add resolve-ai-bridge -- "$HOME/.resolve-ai-bridge/.venv/Scripts/python.exe" "$HOME/.resolve-ai-bridge/bridge/server.py"
```

Restart/refresh the MCP server in the desktop app after setup or a tool-schema update. Start a new task and ask: **“Call resolve_status, then bridge_capabilities and timeline_overview.”** With no timeline open, `resolve_status` can still confirm the project connection.

The ChatGPT desktop app and local Codex clients on the same host share the Codex MCP configuration. **ChatGPT web does not read this local configuration**; remote plugin/tunnel setup is a separate integration and is not installed by this project. See [official MCP setup documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

For lengthy source analysis, the optional Codex server setting `tool_timeout_sec = 180` allows more time than its default timeout. Keep it inside the existing `[mcp_servers.resolve-ai-bridge]` table.

## Other MCP clients

Use the absolute-path server entry generated at `~/.resolve-ai-bridge/mcp-config.json`. The installer also writes `claude-command.txt` and `codex-command.txt` there.

For clients that support npm commands, **install first**, then start the server with the explicit `--serve` mode:

```json
{
  "mcpServers": {
    "resolve-ai-bridge": {
      "command": "npx",
      "args": ["-y", "davinci-resolve-ai-bridge-mcp", "--serve"]
    }
  }
}
```

`npx davinci-resolve-ai-bridge-mcp` without `--serve` is the **installer**, not an MCP stdio process. Prefer the generated absolute Python command for predictable offline startup. The installer-created `resolve-ai-bridge` launcher starts the server directly; npm's executable with the same name requires `--serve`.

No token is needed in the client configuration. The server and Console worker share a local token file automatically.

## Inspect, preview, edit, verify

1. Call `resolve_status` and `timeline_overview`.
2. Use each clip's **`id`**, which uses its Resolve unique ID when available. `label` values such as `V1.2` remain accepted but can change after insertions/deletions. Rebuilt and duplicated clips have new IDs.
3. Call `preview_timeline` before a batch of changes. It creates and opens a copy while keeping the original.
4. Get fresh IDs from `timeline_overview`, make edits, and inspect after each change.
5. Use `compare_timelines(original, preview)` to review structural changes. Audition/view the result in Resolve too: the comparison does not render pixels or compare all Fusion, color, or Fairlight data.

All public `frame` inputs and clip start/end positions use **absolute timeline frames**. Marker offsets are relative to timeline start. Timecodes support non-drop-frame and 29.97/59.94 drop-frame (`HH:MM:SS;FF`). Cut end positions are exclusive.

## Tools

| Tool | What it does |
| --- | --- |
| `resolve_status`, `bridge_capabilities` | Connection, version, current project and decoder/API availability. |
| `timeline_overview`, `project_info`, `list_timelines` | Inspect timeline structure, unique clip IDs, labels and settings. |
| `timeline_frame` | Return a native MCP image plus metadata. Composite capture is attempted first; FFmpeg source fallback is labeled explicitly. |
| `timeline_audio` | Source PCM peak/RMS per channel, silence intervals, energy envelope, onsets, activity clusters or a trimmed WAV. |
| `preview_timeline`, `compare_timelines` | Duplicate/open a review timeline and compare structure/properties/markers without switching during comparison. |
| `project_health` | Check active-timeline missing sources, gaps, disabled/locked tracks/clips and supplied delivery expectations. |
| `review_silence`, `apply_silence_cuts` | Place candidate markers, then apply explicitly accepted intervals on a duplicate of an isolated dialogue clip or aligned AV pair. |
| `open_timeline`, `create_timeline`, `set_playhead`, `open_page` | Navigate Resolve. |
| `list_media`, `import_media`, `append_media`, `add_image` | Inspect/import/place media and duration-controlled stills. |
| `set_clip_transform`, `get_clip_transform`, `animate_zoom` | Static transforms and native Fusion animation. |
| `split_clip` | Rebuild a normal-speed clip into two pieces, with a verified timeline checkpoint first. See restrictions below. |
| `insert_title` | Best-effort title insertion; check `text_set`. |
| `create_compound_clip`, `change_clip_speed` | Compound creation and constant video speed through a bridge-owned TimeSpeed node. |
| `get_clip_grade`, `set_clip_grade`, `keyframe_clip_saturation`, `animate_color_fx` | Inspect/change available grade controls and Fusion color animation. |
| `apply_blur_effect`, `apply_spotlight_mask`, `inspect_fusion` | Existing Fusion blur/mask workflows and inspection. |
| `add_marker`, `delete_marker`, `set_clip_property`, `set_clip_color`, `set_clip_enabled` | Markers and clip metadata/state. |
| `add_track`, `set_track_name`, `delete_clips`, `save_project` | Track management, explicitly requested deletion, and saving. |
| `list_render_presets`, `render_current_timeline` | Inspect available presets and queue/start an approved render. |

## Compatibility and limitations

- **Free edition:** New review workflows use ordinary timeline, marker and clip APIs through the Console worker. No Studio AI transcription, Magic Mask, Smart Reframe, or neural feature was added. Calls check their results and report unsupported behavior.
- **Frame images:** Source fallback shows decoded source media, **not** the graded/composited viewer. It omits Fusion, transforms and overlays. `mode="composite"` fails explicitly if a composited still is unavailable. Without a resize utility, actual dimensions are reported rather than invented.
- **Audio:** Analysis reads source PCM, not the Fairlight mix. It excludes timeline gain, fades, mute, effects and retiming. Known source retiming is rejected. Silence uses 50 ms windows, not speech transcription. Results include the source offset, absolute timeline origin, exclusive ends and a truncation flag; default analysis limit is 300 seconds.
- **Splits:** Fusion clips, locked tracks, mixed rates and known retiming are rejected before deletion. A checkpoint is retained. Rebuilt clips restore static transforms, enabled state, clip color and the current color-grade layer. Audio links, fades, keyframes, other grade layers and all metadata are not guaranteed. On failure, the tool opens the checkpoint and reports any partial attempted timeline honestly.
- **Dialogue cuts:** Automatic application is restricted to one isolated clip or one aligned video/audio pair. It rejects stale review markers and complex multi-clip timelines. The original is kept intact. Review audio gain, fades and non-review markers on the result.
- **Speed:** Fusion mode changes video timing inside the clip, not timeline duration or linked audio. Resetting to 1× neutralizes only the updated bridge's own node; user-created and older untagged TimeSpeed nodes are left alone. Reverse mapping is not verified and is rejected. Clip-attributes mode changes **all uses of that media**, multiplying its current source FPS; it is not a per-clip reset or speed ramp.
- **Validation:** Automated tests cover mocked Resolve operations, source decoding and MCP responses. They do not certify every operation on every Free-version build or platform. See [testing guidance](docs/TESTING.md) for the manual integration checklist.

## Motion graphics

You can render external motion graphics with Remotion and import the result using `append_media`. Remotion is an optional separate toolchain, not part of this bridge's Python runtime. See [Remotion workflows](docs/REMOTION.md).

## Development and verification

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
node tools/check-package.mjs
python3 tools/doctor.py
```

Website development dependencies are separate from the published CLI's runtime dependencies:

```bash
npm ci
npm run build
```

The package check creates and inspects a temporary npm tarball; it does not publish. CI tests Python on macOS, Windows and Linux and checks website/package builds. Maintainers: see [release instructions](docs/RELEASING.md).

[Editing recipes](docs/RECIPES.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Release notes](RELEASE_NOTES.md)

MIT license. See [LICENSE](LICENSE).

## Request and update reliability

Console requests carry a unique ID, deadline, worker session and the project/timeline IDs last observed by that MCP client. Inspect `resolve_status` or `timeline_overview` in each client before its first queued edit. Mutations validate that context immediately before execution; stale or unavailable IDs are rejected. Restart the Console worker after updating: older workers are refused by the new client. Only one Console worker should use a runtime directory.

The heartbeat reports `busy`, `state` (`running`, `completed`, `failed`, or initial `idle`) and `request_id`. Its reporting thread makes no Resolve API calls; project/timeline details are cached during jobs. A fresh heartbeat proves the Python reporter is alive, not that a native operation is making progress. A native call holding Python's GIL may still prevent heartbeat updates.

A client timeout stops waiting; it **does not confirm cancellation**. Queued requests expire before execution, but active native work can finish later. Inspect `~/.resolve-ai-bridge/requests/<request-id>.json` and the timeline before attempting another edit. Completed/failed records retain results; a surviving `running` record after a crash means an unknown outcome and prevents replay of that ID. This is duplicate suppression, not an exactly-once guarantee. Records persist until manually removed with workers/clients stopped; removing them removes duplicate protection. A newly submitted request has a new ID.

Direct attach falls back to Console only before dispatch. Unexpected exceptions after dispatch report an unknown outcome without replay. UI switches during native execution cannot be locked out: keep the intended project/timeline open while edits run. Context validation catches mismatches immediately before execution, not switches away and back between observations.

Before updating, stop the Console worker and MCP clients. The installer builds and validates a staged runtime and dependencies before activation, retains the old directory at `~/.resolve-ai-bridge.previous`, and restores it on a caught activation failure. A hard interruption can leave a sibling `.install-lock` and `.stage-*` directory; see troubleshooting for recovery. Configuration/menu registration follows activation and is not one transaction with it. Run `python3 tools/doctor.py --offline` for file diagnostics without contacting Resolve.
