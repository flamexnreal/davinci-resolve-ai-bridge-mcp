# DaVinci Resolve AI Bridge


<img width="768" alt="demo_preview" src="https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/assets/demo.gif" />

[![npm version](https://img.shields.io/npm/v/davinci-resolve-ai-bridge-mcp.svg)](https://www.npmjs.com/package/davinci-resolve-ai-bridge-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![DaVinci Resolve Free & Studio](https://img.shields.io/badge/DaVinci%20Resolve-Free%20%26%20Studio-brightgreen.svg)](https://www.blackmagicdesign.com/products/davinciresolve)

Resolve AI Bridge is an ultra-lightweight Model Context Protocol (MCP) bridge that lets AI coding assistants (Claude, Claude Code, Antigravity, Cursor, Windsurf, Codex, VS Code) inspect, analyze, and edit projects open in DaVinci Resolve (Free and Studio).

> ### 100% Free, Lighter & Faster
> * **No $295 Studio Paywall**: Full feature parity on **DaVinci Resolve Free** with zero restrictions.
> * **Significantly Lighter & Faster**: Takes up far less storage and starts up noticeably faster than other DaVinci Resolve MCP servers, with zero dependency bloat.
> * **Minimal Token Context**: Compact tool schema so your AI responds immediately without eating your context window.

**Prerequisite:** Requires Python 3.10 or newer (download from [python.org/downloads](https://www.python.org/downloads/) if not already on your computer).

> ⭐ **If you enjoy this repo and find Resolve AI Bridge helpful, please consider giving it a star! It really helps out the project and lets more creators discover it.**

---

## Quick Setup

### Option A: Run directly with npx (Recommended for Node / npm users)

```bash
npx davinci-resolve-ai-bridge-mcp
```

### Option B: One-Line Shell Install

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/install.sh | bash
```

**Windows PowerShell:**
```powershell
irm https://raw.githubusercontent.com/flamexnreal/davinci-resolve-ai-bridge-mcp/main/install.ps1 | iex
```

*(Alternatively, if you cloned the repository or downloaded the ZIP, double-click `install-macos.command` / `install-windows.bat` or run `python3 install.py`).*

The installer sets up the local isolated runtime environment, installs dependencies, and automatically configures detected AI tools (Claude Desktop, Cursor, Windsurf, VS Code, Claude Code, Codex, and Antigravity).

---

## How to Connect to DaVinci Resolve

### For Free Version Users (Standard Setup)

1. Open **DaVinci Resolve** with any project or timeline.
2. In the top menu bar, click **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**.
   * *This opens the Console window and automatically copies the activation command directly to your clipboard.*
3. In the Console window, click the **Py3** tab at the top, press **Cmd+V** (macOS) or **Ctrl+V** (Windows) to paste, and press **Enter**.

*(Backup: If the command did not copy automatically, copy and paste this line into the Py3 tab:)*
```python
import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())
```

Once activated, the bridge stays live and auto-reloading for your entire editing session.

---

### For Studio Version Users ($295 License)

DaVinci Resolve Studio supports background external socket scripting with zero clicks:
1. Open **DaVinci Resolve > Preferences > System > General**.
2. Set **External scripting using** to **Local** and click **Save**.
3. The bridge connects **automatically in the background with zero clicks** whenever Resolve is open.

---

## MCP Client Configuration

If you are adding the MCP server manually to your AI client configuration:

### Claude Desktop (`claude_desktop_config.json`) / Cursor / Antigravity

```json
{
  "mcpServers": {
    "resolve-ai-bridge": {
      "command": "sh",
      "args": [
        "-c",
        "exec \"$HOME/.resolve-ai-bridge/.venv/bin/python\" \"$HOME/.resolve-ai-bridge/bridge/server.py\""
      ]
    }
  }
}
```

Or using the installed global binary:

```json
{
  "mcpServers": {
    "resolve-ai-bridge": {
      "command": "resolve-ai-bridge"
    }
  }
}
```

### Claude Code CLI

```bash
claude mcp add resolve-ai-bridge -- resolve-ai-bridge
```

---

## Motion Graphics & Remotion

Remotion is a framework that lets developers and AI agents create video animations and motion graphics programmatically using React code.

- **React-Based Video & 3D Mockups**:
  Build custom motion graphics, animated 3D laptop/device mockups, and dynamic lower thirds in React. AI coding agents can write the code, render the video clip, and place it directly onto the DaVinci Resolve timeline using `append_media`.
- **Kinetic Typography & Bouncy Text**:
  Generate modern word-by-word spring reveals, letter-by-letter waterfall bounce animations, and contrast font pairings that land in sync with dialogue.
- **Smooth Zooms & Camera Moves**:
  Create natural, smooth camera glides and keyframed punch-ins with zero stepped cuts or black flickers on both Free and Studio timelines.
- **Extra Visual Effects & Callouts**:
  Floating glass magnifier cards (`magnifier-callout` skill), spotlight blur masks, saturation transitions, and animated color shifts.

```bash
# Add Remotion AI agent skills
npx -y skills@latest add remotion-dev/skills -g -y
```

See [`docs/REMOTION.md`](./docs/REMOTION.md) for workflows and templates.

---

## Available MCP Tools

| Tool | Description |
| :--- | :--- |
| **`resolve_status`** | Check bridge connection, Resolve version, active project, and timeline. |
| **`timeline_overview`** | Inspect tracks, clips, stable item IDs (`V1.1`, `V2.1`), timecode, and markers. |
| **`timeline_frame`** | Capture a visual frame snapshot at the playhead or specified timecode. |
| **`timeline_audio`** | Analyze timeline audio for Peak/RMS loudness, clipping, silence cuts, and beat sync. |
| **`project_info`** | Get project frame rate, resolution, and timeline counts. |
| **`list_timelines`** / **`open_timeline`** / **`create_timeline`** | Create, switch, and list timelines. |
| **`list_media`** / **`import_media`** / **`append_media`** | Search, import, and place media pool assets. |
| **`add_image`** | Place still images or graphics overlays with custom duration and track target. |
| **`set_clip_transform`** | Modify pan, tilt, zoom, rotation, opacity, and retiming properties. |
| **`split_clip`** | Razor cut clips at specific frame numbers, timecodes, or playhead position. |
| **`animate_zoom`** | Apply keyframed zoom in/out Fusion compositions across clip ranges. |
| **`insert_title`** | Add customizable text titles directly onto the timeline. |
| **`keyframe_clip_saturation`** | Smoothly animate color saturation (e.g. full color to black and white) across frames. |
| **`animate_color_fx`** | Apply animated rainbow color shifting and subtle organic luminance flicker. |
| **`set_clip_grade`** / **`get_clip_grade`** | Control and inspect ASC-CDL saturation, gain/slope, lift/offset, and gamma/power. |
| **`add_marker`** / **`delete_marker`** | Place and remove timeline markers with color tags. |
| **`set_clip_property`** / **`set_clip_color`** / **`set_clip_enabled`** | Inspect and toggle clip parameters. |
| **`render_current_timeline`** | Start background timeline export with named presets. |

---

## Free vs Studio Version

Most other DaVinci Resolve scripting and automation tools require you to purchase the **$295 DaVinci Resolve Studio** license because Blackmagic Design restricts standard external API access in the free version.

**Resolve AI Bridge is completely free and works identically on both the Free and Studio versions of DaVinci Resolve.**

* **Dual-Transport Architecture**: If external scripting is restricted or disabled in Resolve Preferences, the bridge automatically attaches via the internal Console worker (`ResolveConsole.py`).
* **Subpixel Compositor Roundtrips**: Bypasses the Free edition's locked Edit-page spline scripting to deliver broadcast-quality keyframing, floating magnifier callouts, and kinetic typography.
* **100% Feature Parity**: Timeline inspection, audio loudness analysis, frame capture, title generation, VAD speech sync, and media placement work on the Free version without any paid license or watermark.

---

## Verification and Troubleshooting

Run the diagnostic tool before editing files:

```bash
python3 tools/doctor.py
```

- **Bridge reported offline**: Ensure DaVinci Resolve is open with a project. Check **Preferences > System > General > External scripting using** is set to **Local**. If needed, click **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**.
- **Missing Scripts Menu**: Fully quit and reopen DaVinci Resolve so it rescans the script directories.
- Detailed troubleshooting guides are available in [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md).

---

## License

MIT. See [`LICENSE`](./LICENSE).
