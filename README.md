# DaVinci Resolve AI Bridge MCP

<img width="768" alt="Resolve AI Bridge demo" src="https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/assets/demo.gif" />

[![npm version](https://img.shields.io/npm/v/davinci-resolve-ai-bridge-mcp.svg)](https://www.npmjs.com/package/davinci-resolve-ai-bridge-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![DaVinci Resolve Free & Studio](https://img.shields.io/badge/DaVinci%20Resolve-Free%20%26%20Studio-brightgreen.svg)](https://www.blackmagicdesign.com/products/davinciresolve)

Let your AI assistant help with the edit. Resolve AI Bridge connects Claude, Codex, Cursor, Antigravity, and other MCP-compatible assistants to the project open in **DaVinci Resolve Free or Studio**.

Inspect a timeline, place media, animate a zoom, adjust color, or try an edit on a duplicate timeline before touching the original.

**Current Resolve Free works through the Lua connector.** Native-file Lua
startup and editing are live-tested on **macOS Free 21.1.2.10**. Python runs in
the external MCP server; Resolve itself needs no Python, FFI or socket library.
Choose **Start AI Bridge (Lua)** on Free 21.1+. The existing Python worker remains
available on older Python-enabled Free builds and Studio. See
[compatibility evidence and limits](docs/COMPATIBILITY.md).

### Built to stay light

- **Works with current Resolve Free.** Lua editing is verified on macOS Free 21.1.2.10; the older Python worker is verified on Free 21.0.3.7. Studio-only effects stay Studio-only.
- **One click to start.** Choose **Start AI Bridge (Lua)** on current Free, or **Start AI Bridge** on Python-enabled builds. Your AI gets the existing editing tools.
- **A small, local runtime.** No remote bridge server or manually entered token. Website dependencies stay out of the CLI package; FFmpeg and Remotion are optional.
- **Keep your tokens for the edit.** The launcher starts locally, without an AI request or extra startup tools.

> ⭐ Finding it useful? Give the bridge a star—it helps other editors find it.

---

## Quick setup

You'll need **Python 3.10+** ([download](https://www.python.org/downloads/)).

### Option A: Run directly with npx (Recommended for Node / npm users)

```bash
npx davinci-resolve-ai-bridge-mcp
```

### Option B: One-line shell install

**macOS / Linux** (run in Terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/install.sh | bash
```

**Windows** (run in PowerShell):

```powershell
irm https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/install.ps1 | iex
```

From a downloaded/cloned repository, run `python3 install.py --with-ffmpeg` (Windows: `py install.py --with-ffmpeg`), or use `install-macos.command` / `install-windows.bat` for the base install.

Node/npm is only needed for the npm installer and optional website/motion-graphics development.

The installer sets up `~/.resolve-ai-bridge`, a private Python environment, the Resolve menu entries, editing skills, and detected supported AI clients. Valid client configs are backed up and merged; invalid configs are left unchanged with a diagnostic. Antigravity and other clients can use the generated `mcp-config.json` manually.

Wait for **INSTALL COMPLETE**, then reopen Resolve. If setup stops after downloading, see [installer troubleshooting](docs/TROUBLESHOOTING.md#the-one-line-installer-downloads-but-stops).

<br>

<details>
<summary><b>Optional: add FFmpeg for source frames and audio</b></summary>

For Free-compatible source frame capture and efficient audio decoding, also install the optional private FFmpeg binary:

```bash
npx davinci-resolve-ai-bridge-mcp --with-ffmpeg
```

This optional download stays in the bridge's private Python environment. It is not a Studio dependency. An existing `ffmpeg` on PATH also works; macOS `afconvert` supports audio extraction without FFmpeg.

</details>

---

## Connect to Resolve

1. Open **DaVinci Resolve** with a project.
2. Choose **Workspace → Scripts → Resolve AI Bridge → Start AI Bridge (Lua)** on Free 21.1+. On Python-enabled builds, use **Start AI Bridge**. The folder may appear under **Utility**.
3. Ask your AI: **“Call resolve_status, then bridge_capabilities and timeline_overview.”** Open or create a timeline before using timeline tools; status works without one.

**Start from the menu and get editing.** Start once per Resolve session. You can see **RESOLVE AI BRIDGE READY** in **Workspace → Console**. Use **Stop AI Bridge (Lua)** for the Lua worker or **Stop AI Bridge** for Python; an active operation finishes first. Clicking Start again won't create another worker.

If the menu is missing after installation, quit and reopen Resolve once. Refresh/restart your AI client's MCP server after setup or a tool-schema update.

The Lua connector is live-tested on **macOS / Resolve Free 21.1.2.10**. Python startup remains verified on **Free 21.0.3.7 / Python 3.14.6**. Windows, Linux and other builds still need live verification.

<br>

<details>
<summary>Console fallback and startup details</summary>

On **Free 21.1+**, open **Workspace → Console**, select **Lua**, paste this portable fallback and press Enter:

```lua
if fusion:GetData("ResolveAIBridge.NativeApp")~=tostring(fusion) then fusion:RunScript((os.getenv("RESOLVE_AI_BRIDGE_HOME") or ((os.getenv("USERPROFILE") or os.getenv("HOME")).."/.resolve-ai-bridge")).."/ResolveLua.lua") end
```

On Python-enabled builds, select **Py3** and use:

```python
import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())
```

**Live startup validation:** macOS, DaVinci Resolve **Free 21.0.3.7**, Python **3.14.6**: menu start, real status requests, repeated start, Stop, quit/reopen/start, and Console fallback passed. The separate native-file Lua connector supports the tested Free 21.1.2 build. Windows/Linux and other builds still need live verification.

The Lua menu worker stays in its native script context and uses `bmd.wait` between requests, keeping the editing UI usable. The Python menu route keeps a separate `fuscript` process alive; its Py3 fallback starts a daemon worker and returns after a short handshake. The Lua worker uses signed local file messages, with no socket or FFI dependency. No public MCP tool or AI startup call is added.

</details>

<br>

<details>
<summary>Studio: connect automatically with external scripting</summary>

Studio can use the same menu workflow. To allow direct attach, set **Preferences → System → General → External scripting using → Local**. When external scripting is available, the bridge connects directly. It probes that connection in a disposable process and uses the Console transport when direct attach is unavailable.

</details>

---

## What you can do

| In your edit | The bridge can help with |
| --- | --- |
| Find your bearings | Inspect clips, tracks, markers, media, project settings, and timeline health. |
| Build the timeline | Import media, place images and overlays, create timelines, and group compound clips. |
| Add movement | Set clip transforms, animate zooms, adjust supported speed controls, and stack spotlight/blur effects. |
| Work with color | Read and adjust supported grades, animate saturation, and add color shifts. |
| Review before committing | Try edits on duplicate timelines, compare structure, and mark candidate silence cuts. |
| Check source media | View source frames and analyze source audio levels, silence, and timing. |
| Deliver | Queue an approved render, follow its progress, and catch settings Resolve Free can't render. |

<br>

<details>
<summary>Full MCP tool list</summary>

| Tool | What it does |
| --- | --- |
| `resolve_status`, `bridge_capabilities` | Connection, version, current project and decoder/API availability. |
| `timeline_overview`, `project_info`, `list_timelines` | Inspect timeline structure, unique clip IDs, labels and settings. |
| `timeline_frame` | Return a native MCP image plus metadata. Composite capture is attempted first; FFmpeg source fallback is labeled explicitly. |
| `timeline_audio` | Source PCM peak/RMS per channel, silence intervals, energy envelope, onsets, activity clusters or a trimmed WAV. |
| `preview_timeline`, `compare_timelines` | Duplicate/open a review timeline and compare structure/properties/markers without switching during comparison. |
| `project_health` | Check active-timeline missing sources, gaps, disabled/locked tracks/clips, supplied delivery expectations and Resolve Free's UHD/60 fps render limits. |
| `review_silence`, `apply_silence_cuts` | Place candidate markers, then apply explicitly accepted intervals on a duplicate of an isolated dialogue clip or aligned AV pair. |
| `open_timeline`, `create_timeline`, `set_playhead`, `open_page` | Navigate Resolve. |
| `list_media`, `import_media`, `append_media`, `add_image` | Inspect/import/place media and duration-controlled stills. |
| `set_clip_transform`, `get_clip_transform`, `animate_zoom` | Static transforms and a keyframed Fusion zoom that keeps your other Fusion nodes connected. |
| `split_clip` | Rebuild a normal-speed clip into two pieces, with a verified timeline checkpoint first. See restrictions below. |
| `insert_title` | Best-effort title insertion; check `text_set`. |
| `create_compound_clip`, `change_clip_speed` | Compound creation and constant video speed through a bridge-owned TimeSpeed node. |
| `get_clip_grade`, `set_clip_grade`, `keyframe_clip_saturation`, `animate_color_fx` | Inspect/change available grade controls and Fusion color animation on bridge-owned nodes. |
| `apply_blur_effect`, `apply_spotlight_mask` | Stackable Fusion blurs (gaussian, defocus, directional) and spotlight masks, static or keyframed. |
| `inspect_fusion` | Read-only view of a clip's Fusion nodes and the bridge's effect chain. |
| `add_marker`, `delete_marker`, `set_clip_property`, `set_clip_color`, `set_clip_enabled` | Markers and clip metadata/state. |
| `add_track`, `set_track_name`, `delete_clips`, `save_project` | Track management, explicitly requested deletion, and saving. |
| `list_render_presets`, `render_current_timeline`, `render_status` | Inspect presets, queue/start an approved render, and follow its progress. |

</details>

<br>

### Motion graphics with Remotion

For custom typography, lower thirds, or animated callouts, your AI can create a Remotion video and import it with `append_media`. Remotion is a separate, optional toolchain; it isn't bundled into the bridge's Python runtime.

[Motion graphics workflows](docs/REMOTION.md) · [Editing recipes](docs/RECIPES.md)

---

## A few things to know

**Free support doesn't unlock Studio features.** Source frames exclude timeline effects, and source audio isn't the Fairlight mix. Some edits have limits: splits rebuild clips, title text is best effort, and silence cuts are restricted to supported clip layouts.

<br>

<details>
<summary>Editing workflow, clip IDs, and frame/timecode rules</summary>

1. Call `resolve_status` and `timeline_overview`.
2. Use each clip's **`id`**, which uses its Resolve unique ID when available. `label` values such as `V1.2` remain accepted but can change after insertions/deletions. Rebuilt and duplicated clips have new IDs.
3. Call `preview_timeline` before a batch of changes. It creates and opens a copy while keeping the original.
4. Get fresh IDs from `timeline_overview`, make edits, and inspect after each change.
5. Use `compare_timelines(original, preview)` to review structural changes. Audition/view the result in Resolve too: the comparison does not render pixels or compare all Fusion, color, or Fairlight data.

All public `frame` inputs and clip start/end positions use **absolute timeline frames**. Marker offsets are relative to timeline start. Timecodes support non-drop-frame and 29.97/59.94 drop-frame (`HH:MM:SS;FF`). Cut end positions are exclusive.

Fusion effects (`animate_zoom`, blur, spotlight, saturation, color fx) are the exception, because they live inside one clip: `start_frame`, `end_frame` and keyframe `frame` count from the clip's first frame (0). Pass `timeline_start_frame`, `timeline_end_frame` or keyframe `timeline_frame` to use absolute timeline frames instead.

</details>

<br>

<details>
<summary>Tool compatibility and limitations</summary>

- **Free edition:** Use the native-file Lua worker on Free 21.1+. It uses ordinary timeline, marker, clip and Fusion APIs and shares the existing Python editing implementation outside Resolve. No Studio AI transcription, Magic Mask, Smart Reframe, or neural feature was added.
- **Frame images:** Source fallback shows decoded source media, **not** the graded/composited viewer. It omits Fusion, transforms and overlays. `mode="composite"` fails explicitly if a composited still is unavailable. Without a resize utility, actual dimensions are reported rather than invented.
- **Audio:** Analysis reads source PCM, not the Fairlight mix. It excludes timeline gain, fades, mute, effects and retiming. Known source retiming is rejected. Silence uses 50 ms windows, not speech transcription. Results include the source offset, absolute timeline origin, exclusive ends and a truncation flag; default analysis limit is 300 seconds.
- **Splits:** Fusion clips, locked tracks, mixed rates and known retiming are rejected before deletion. A checkpoint is retained. Rebuilt clips restore static transforms, enabled state, clip color and the current color-grade layer. Audio links, fades, keyframes, other grade layers and all metadata are not guaranteed. On failure, the tool opens the checkpoint and reports any partial attempted timeline honestly.
- **Dialogue cuts:** Automatic application is restricted to one isolated clip or one aligned video/audio pair. It rejects stale review markers and complex multi-clip timelines. The original is kept intact. Review audio gain, fades and non-review markers on the result.
- **Fusion effects:** Zoom, blur, spotlight, saturation and color fx share one bridge-owned chain before MediaOut. Effects, speed and resets passed live checks through the Lua connector on macOS Free 21.1.2.10 and through Python on Free 21.0.3.7. Tests also cover preserving user nodes. Other builds, Studio and large comps need verification; inspect results with `inspect_fusion` or the Fusion page.
- **Speed:** Fusion mode changes video timing inside the clip, not timeline duration or linked audio. Resetting to 1× neutralizes only the updated bridge's own node; user-created and older untagged TimeSpeed nodes are left alone. Reverse mapping is not verified and is rejected. Clip-attributes mode changes **all uses of that media**, multiplying its current source FPS; it is not a per-clip reset or speed ramp.
- **Validation:** Automated tests cover mocked Resolve operations, source decoding and MCP responses. They do not certify every operation on every Free-version build or platform. See [testing guidance](docs/TESTING.md) for the manual integration checklist.

</details>

---

## Connect your AI client

Most setup is handled by the installer. For manual configuration, use the absolute-path entry in `~/.resolve-ai-bridge/mcp-config.json`. No token needs to be typed into your client; the server and worker share a local token file automatically.

<br>

<details>
<summary>Codex / ChatGPT desktop setup</summary>

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

</details>

<br>

<details>
<summary>Other clients, npm server mode, and generated commands</summary>

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

</details>

---

## Troubleshooting & updates

If the bridge is offline, open a project and choose **Start AI Bridge**. Run the doctor from the repository for a connection check:

```bash
python3 tools/doctor.py
```

Use `python3 tools/doctor.py --offline` for file checks without contacting Resolve.

Before an update, stop the worker and your MCP clients. The installer validates the replacement before activating it and keeps the previous runtime for recovery.

[Troubleshooting](docs/TROUBLESHOOTING.md) · [Testing](docs/TESTING.md) · [Release notes](RELEASE_NOTES.md)

<br>

<details>
<summary>Request safety, timeouts, and update recovery</summary>

Console requests carry a unique ID, deadline, worker session and the project/timeline IDs last observed by that MCP client. Inspect `resolve_status` or `timeline_overview` in each client before its first queued edit. Mutations validate that context immediately before execution; stale or unavailable IDs are rejected. Restart the Console worker after updating: older workers are refused by the new client. Only one Console worker should use a runtime directory.

The Lua route signs local request/reply/heartbeat bytes with HMAC-SHA256. Complete operations hold a cross-process lock and native lease; object handles and Stop requests belong to one session. Partial file reads are retried without resending edits. An uncertain response halts further native calls, records an unknown outcome and requires fresh inspection. Lua's heartbeat runs between native calls and can pause during a long native call; it is not a progress guarantee.

The heartbeat reports `busy`, `state` (`running`, `completed`, `failed`, or initial `idle`) and `request_id`. Its reporting thread makes no Resolve API calls; project/timeline details are cached during jobs. A fresh heartbeat proves the Python reporter is alive, not that a native operation is making progress. A native call holding Python's GIL may still prevent heartbeat updates.

A client timeout stops waiting; it **does not confirm cancellation**. Queued requests expire before execution, but active native work can finish later. Inspect `~/.resolve-ai-bridge/requests/<request-id>.json` and the timeline before attempting another edit. Completed/failed records retain results; a surviving `running` record after a crash means an unknown outcome and prevents replay of that ID. This is duplicate suppression, not an exactly-once guarantee. The worker cleans up on its own: completed/failed records after 7 days, `running` records after 30 days, unread replies after an hour, and it rotates its log at 1 MB. A newly submitted request has a new ID.

Direct attach falls back to Console only before dispatch. Unexpected exceptions after dispatch report an unknown outcome without replay. UI switches during native execution cannot be locked out: keep the intended project/timeline open while edits run. Context validation catches mismatches immediately before execution, not switches away and back between observations.

Before updating, stop the Console worker and MCP clients. The installer builds and validates a staged runtime and dependencies before activation, retains the old directory at `~/.resolve-ai-bridge.previous`, and restores it on a caught activation failure. A hard interruption can leave a sibling `.install-lock` and `.stage-*` directory; see troubleshooting for recovery. Configuration/menu registration follows activation and is not one transaction with it. Run `python3 tools/doctor.py --offline` for file diagnostics without contacting Resolve.

</details>

<br>

<details>
<summary>Development and verification</summary>

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

The package check creates and inspects a temporary npm tarball; it does not publish. GitHub Actions runs the suite, package check, website build and dependency audit on Linux, macOS and Windows. Install optional `lupa` (`python3 -m pip install lupa`) to run the Fusion Lua tests too. Maintainers: see [release instructions](docs/RELEASING.md).

</details>

---

## License

MIT. See [LICENSE](LICENSE).
