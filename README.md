# DaVinci Resolve AI Bridge

[![npm version](https://img.shields.io/npm/v/davinci-resolve-ai-bridge-mcp.svg)](https://www.npmjs.com/package/davinci-resolve-ai-bridge-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Resolve AI Bridge is an open-source local Model Context Protocol (MCP) bridge that lets AI coding assistants (Claude, Claude Code, Antigravity, Cursor, Windsurf, Codex, VS Code) inspect, analyze, and edit projects open in DaVinci Resolve (Free and Studio).

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

## How It Works

1. **Open DaVinci Resolve** and open any project or timeline.
2. **Direct attach (default)**: The bridge connects automatically through Resolve's native scripting interface.
3. **Fallback launcher**: If your build requires the internal console, choose **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge** in Resolve, or paste the activation command into the Py3 Console.

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
| **`add_marker`** / **`delete_marker`** | Place and remove timeline markers with color tags. |
| **`set_clip_property`** / **`set_clip_color`** / **`set_clip_enabled`** | Inspect and toggle clip parameters. |
| **`render_current_timeline`** | Start background timeline export with named presets. |

---

## Motion Graphics, Magnifiers & Remotion

- **Floating Magnifier Callouts (`magnifier-callout` skill)**:
  AI agents can generate luxury rounded-rectangle magnifier cards that zoom into buttons, search bars, and code lines at $1.8\times – 2.5\times$ magnification while smoothly blurring the full-scale background with Gaussian blur ($\sigma=45\text{px}$) and soft drop shadows.
- **Subpixel Lanczos Camera Keyframing**:
  Bypasses DaVinci Resolve Free's locked Edit-page spline scripting by generating continuous quintic smootherstep camera glides ($E(t) = 6t^5 - 15t^4 + 10t^3$) with zero stepped cuts and zero 1ms black flickers.
- **VAD Speech Clustering & Frame-Locked Captions**:
  Automatic 16-bit PCM normalization, acoustic energy peak alignment, and `-160ms` anticipatory lead for typography that lands synchronously with spoken words.
- **Remotion React-Based Video**:
  For programmatic motion graphics, lower thirds, and video overlays, AI coding agents can generate React components, render them, and place them directly onto the DaVinci Resolve timeline using `append_media`.

```bash
# Add Remotion AI agent skills
npx -y skills@latest add remotion-dev/skills -g -y
```

See [`docs/REMOTION.md`](./docs/REMOTION.md) for workflows and templates.

---

## Free vs Studio Version

Blackmagic Design's scripting APIs provide a common superset for both the Free and Studio versions of DaVinci Resolve. No feature in this bridge requires Studio-only tools. If external scripting is disabled in Resolve Preferences, the bridge falls back to the internal Console worker and all tools behave identically.

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
