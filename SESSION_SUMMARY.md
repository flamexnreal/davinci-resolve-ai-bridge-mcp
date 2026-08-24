# DaVinci Resolve AI Bridge MCP — Comprehensive Master Technical Archive

**Document Version**: 2.0 (Exhaustive Technical & Operational Reference)  
**Date**: August 23, 2026  
**Primary Repository**: [`flamexnreal/davinci-resolve-ai-bridge-mcp`](https://github.com/flamexnreal/davinci-resolve-ai-bridge-mcp)  
**Package Registry**: [`davinci-resolve-ai-bridge-mcp@1.6.1`](https://www.npmjs.com/package/davinci-resolve-ai-bridge-mcp) on npm  
**Target Environment**: DaVinci Resolve 21.0.3.7 (macOS Sonoma / Apple Silicon, Windows 11, Linux)  
**License**: MIT (100% Free & Open Source)  

---

## Table of Contents

1. [Executive Summary & Core Philosophy](#1-executive-summary--core-philosophy)
2. [DaVinci Resolve Architecture: Free vs. Studio Scripting Reality](#2-davinci-resolve-architecture-free-vs-studio-scripting-reality)
3. [IPC Protocol & Bridge Runtime Mechanics](#3-ipc-protocol--bridge-runtime-mechanics)
4. [The 1-Click Clipboard Activation Workflow](#4-the-1-click-clipboard-activation-workflow)
5. [Remotion Kinetic Motion Design Engine](#5-remotion-kinetic-motion-design-engine)
6. [YouTube Video Inspection & Visual Recreation Protocol](#6-youtube-video-inspection--visual-recreation-protocol)
7. [Audio Waveform & Content-Aware Take Curation Pipeline](#7-audio-waveform--content-aware-take-curation-pipeline)
8. [Competitive Research & Analysis: Samuel Gursky vs. Flamexnreal](#8-competitive-research--analysis-samuel-gursky-vs-flamexnreal)
9. [Skills, Custom Rules & AI Directives](#9-skills-custom-rules--ai-directives)
10. [Release History & Versioning Log](#10-release-history--versioning-log)
11. [Local Filesystem Sitemap & Directory Layout](#11-local-filesystem-sitemap--directory-layout)
12. [Instructions for Future AI Agents](#12-instructions-for-future-ai-agents)

---

## 1. Executive Summary & Core Philosophy

The **DaVinci Resolve AI Bridge MCP** is an autonomous video editing and motion design bridge that connects AI coding assistants (Google Antigravity, Claude Code, Cursor, Windsurf, Claude Desktop, Codex) directly to DaVinci Resolve.

### The Problem in Existing Tools:
* **The $295 Paywall**: Almost all existing DaVinci Resolve automation tools (including Blackmagic's official external API) require DaVinci Resolve Studio ($295).
* **Missing Motion Design**: Existing tools only manipulate raw timeline cuts; they cannot generate custom animations, spring physics typography, or floating callouts.
* **Network & Port Instabilities**: Other open-source bridges rely on local TCP/HTTP servers that frequently suffer from port conflicts, zombie process locks, and complicated shell path setup.

### The Solution:
* **100% Free & Studio Parity**: Full timeline editing, audio sync, marker placement, and animation capabilities on the standard Free version of DaVinci Resolve.
* **Built-in Remotion React Motion Engine**: Direct rendering of transparent ProRes 4444 / H.264 motion graphics, kinetic subtitles, bouncing text, and magnifier boxes.
* **Zero-Port Atomic File IPC**: Guaranteed crash-resilience with zero zombie socket locks and zero port collisions.
* **Autonomous Multimedia Intelligence**: Built-in YouTube video inspection, AI speech energy analysis, and semantic best-take curation.

---

## 2. DaVinci Resolve Architecture: Free vs. Studio Scripting Reality

Understanding Blackmagic Design's internal scripting architecture is vital to understanding how this bridge functions:

### 2.1 DaVinci Resolve Studio ($295 License)
* **Mechanism**: Blackmagic unlocks external TCP/socket scripting via `DaVinciResolveScript.py` and `fusionscript.so` / `fusionscript.dll`.
* **Behavior**: Any external Python or Node.js process running outside Resolve can call `import DaVinciResolveScript as dvr_script; resolve = dvr_script.scriptapp("Resolve")`.
* **User Experience**: Zero clicks. When Resolve is open with `Preferences > System > General > External scripting using = Local`, the bridge connects automatically in the background.

### 2.2 DaVinci Resolve Free ($0 Standard Version)
* **The Restriction**: Blackmagic **intentionally blocks external socket connections** from third-party processes. Calling `scriptapp("Resolve")` from outside Resolve returns `None` or refuses the connection.
* **The Internal Exception**: Blackmagic allows Python and Lua scripts to run *inside* Resolve via two channels:
  1. `Workspace > Scripts` menu.
  2. `Workspace > Console` (interactive Py3 tab).

### 2.3 Why `Workspace > Scripts` Cannot Run a Background Worker Directly
* **Single-Threaded Main Process**: Scripts launched from `Workspace > Scripts` execute on Resolve's main GUI thread.
* **The Freezing Trap**: If a script enters an infinite `while True:` loop to listen for AI commands, **it completely freezes DaVinci Resolve's entire user interface** (spinning beachball / Not Responding).
* **The Teardown Trap**: If the script spawns a background `threading.Thread` and exits (to keep Resolve interactive), Resolve's Python engine **instantly destroys the script's execution context and terminates any background threads**.

### 2.4 Why the Interactive `Py3 Console` is the Permanent Fix
* The **Interactive Console (`Workspace > Console > Py3`)** is a persistent interactive REPL session that stays alive in memory as long as DaVinci Resolve is open.
* When the bridge worker is initialized inside the `Py3` tab, it spawns the background listener thread in an active REPL session that **never gets torn down and never freezes the GUI**.

---

## 3. IPC Protocol & Bridge Runtime Mechanics

The bridge uses a lightweight, robust, file-based atomic IPC protocol designed for maximum reliability across macOS, Windows, and Linux.

### 3.1 IPC Directory Structure (`~/.resolve-ai-bridge/`)
```text
~/.resolve-ai-bridge/
├── agent.json              # Live heartbeat file (updated every 2.0s)
├── token.txt               # 12-char random authentication token
├── mcp-config.json         # Ready-to-use MCP configuration
├── claude-command.txt      # CLI one-liner for Claude Code
├── codex-command.txt       # CLI one-liner for Codex
├── console-command.txt     # The portable Py3 activation string
├── inbox/                  # AI -> Resolve request queue
│   └── <request_id>.json   # Incoming atomic JSON requests
├── outbox/                 # Resolve -> AI response queue
│   └── <request_id>.json   # Completed atomic JSON responses
├── logs/
│   └── agent.log           # Rotating log of worker execution
├── bridge/                 # Python MCP server implementation
│   ├── server.py           # FastMCP server entrypoint
│   ├── operations.py       # Resolve API dispatcher & operation handlers
│   ├── transport.py        # IPC transport layer
│   ├── direct.py           # Studio direct-attach transport
│   ├── client.py           # Python client API
│   ├── frame_capture.py    # Playhead viewport frame grabber
│   └── audio_analysis.py   # Acoustic waveform analysis
└── ResolveConsole.py       # The Console worker engine
```

### 3.2 Atomic Request/Response Flow
1. **AI Agent Request**:
   * The AI MCP client writes `inbox/<request_id>.json.tmp` containing:
     ```json
     {
       "id": "7f8b9a2c-...",
       "op": "append_media",
       "params": {"paths": ["/path/to/video.mp4"], "record_frame": 86400},
       "token": "43e9eefd0690",
       "version": 2
     }
     ```
   * It atomically renames `.tmp` to `.json`.
2. **Worker Polling & Execution**:
   * `ResolveConsole.py` runs a low-latency loop (`wait(0.08s)`) checking `inbox/*.json`.
   * It validates the token, hot-reloads `operations.py` (allowing live updates without restarting Resolve), dispatches the call against the live `resolve` object, and measures execution time.
3. **Response Delivery**:
   * The worker writes `outbox/<request_id>.json.tmp` and renames to `.json`:
     ```json
     {
       "id": "7f8b9a2c-...",
       "ok": true,
       "result": {"appended_count": 1, "record_frame": 86400},
       "took_ms": 12
     }
     ```
   * It unlinks the inbox file and updates its served request counter.

### 3.3 Heartbeat File (`agent.json`)
Every 2 seconds, the worker updates `agent.json`:
```json
{
  "online": true,
  "transport": "console",
  "agent_version": "1.6.1",
  "protocol": 2,
  "resolve_version": "21.0.3.7",
  "product": "DaVinci Resolve",
  "page": "edit",
  "project": "yoo",
  "timeline": "Timeline 1",
  "token_id": "43e9eefd0690",
  "pid": 32774,
  "time": 1787516802.35,
  "started_at": 1787516643.66,
  "thread_alive": true,
  "served": 14
}
```
If `time.time() - agent.json['time'] > 25.0s`, clients treat the worker as stale or stopped.

---

## 4. The 1-Click Clipboard Activation Workflow

To minimize user effort on the Free edition, we engineered an automatic clipboard hook into `Start AI Bridge.py`:

### 4.1 Script Location in DaVinci Resolve:
* **macOS**: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/Resolve AI Bridge/Start AI Bridge.py`
* **Windows**: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\Resolve AI Bridge\Start AI Bridge.py`
* **Linux**: `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/Resolve AI Bridge/Start AI Bridge.py`

### 4.2 Implementation in `Start AI Bridge.py`:
```python
#!/usr/bin/env python
"""Workspace > Scripts > Resolve AI Bridge > Start AI Bridge."""

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
    print("Command to paste (if it didn't copy automatically):")
    print("   " + PORTABLE_CMD + "\n")
    print("Next steps:")
    print("1. Click the 'Py3' tab at the top of this Console window.")
    print("2. Press %s (Paste) and hit Enter." % paste_key)
    print("=" * 72 + "\n")

if __name__ == "__main__":
    main()
```

### 4.3 The 2-Step User Experience:
1. Click **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**.
2. In the Console window, click **Py3**, press **Cmd+V**, and hit **Enter**.

---

## 5. Remotion Kinetic Motion Design Engine

The bridge integrates seamlessly with a local Remotion project at `/Users/eram/Documents/remotion-motion-design/` to generate production-ready motion graphics directly on timeline tracks.

### 5.1 Assets & Compositions Created
1. **`yoo_capping_captions.mov` & `yoo2_transparent_captions.mov`**:
   * Word-by-word dynamic kinetic subtitles rendered in Apple ProRes 4444 with full alpha transparency.
   * Highlight colors, pop-in spring physics, and zero-delay alignment.
2. **`safari_magnifier_large.mp4` & `safari_magnifier_perfect.mp4`**:
   * Broadcast-grade floating magnifier callout box.
   * Smooth zoom on target UI, rounded corners ($24\text{px}$ radius), crisp white border, drop shadow, and soft frosted-glass background blur (`backdrop-filter: blur(12px)`).
3. **`typography_minimal_v2.mp4` & `typography_perfect_sync.mp4`**:
   * Minimalist, elegant typography matching spoken words with zero neon glare.
4. **`youtube_typography_replica_v3.mp4`**:
   * High-impact replica of reference YouTube motion graphics with SVG curved arrow animation, slide-in spring physics, and heavy slam impact.

---

## 6. YouTube Video Inspection & Visual Recreation Protocol

To enable AI agents to analyze and recreate effects from any YouTube video without manual downloading, we built the `youtube-video-inspector` skill.

### 6.1 Skill Definition (`~/.gemini/config/skills/youtube-video-inspector/SKILL.md`)
* **Instant Headless Download**:
  ```bash
  python3 -m yt_dlp -f 134 "<URL>" -o "scratch/ref_video_360p.mp4"
  ```
  *(Format 134 is a dedicated 360p MP4 stream that downloads in $<3$ seconds without requiring ffmpeg stream merging).*
* **Frame Grid Extraction**:
  * Samples 6 equidistant frames around the target timestamp using OpenCV.
  * Stitches them into a $2\times 3$ grid (`scratch/youtube_ref_grid.jpg`).
  * Visual inspection is performed via `view_file` to analyze layout, typography, spring curves, and colors.
* **Direct Asset Recreation**:
  * Agent writes a Remotion component matching the exact geometry, renders the MP4/MOV, and places it into DaVinci Resolve via `import_media` and `append_media`.

### 6.2 Reference Videos Tested & Inspected:
1. **`https://www.youtube.com/watch?v=Shgr6TkJTDI&t=201s`**:
   * Extracted kinetic typography: `"animating text ↗ like this"`.
   * Built SVG arrow vector, S-curve slide, and heavy impact slam in Remotion.
   * Placed on Video Track 2 (`V2.1`) at `01:00:00:00`.
2. **`https://www.youtube.com/watch?v=o95OFktH7ig`**:
   * Video by Andy Diep reviewing `samuelgursky/davinci-resolve-mcp`.
   * Analyzed Free edition podcast clipping workflow and skills.

---

## 7. Audio Waveform & Content-Aware Take Curation Pipeline

To handle raw, unedited recordings containing countdown beeps, dead silence, stumbles, and retakes, we developed an autonomous two-stage audio processing pipeline:

### 7.1 Stage 1: Silence & Dead Gap Trimming
* **Algorithm**:
  * Decodes audio to $48\text{kHz}$ 16-bit mono PCM via `PyAV`.
  * Computes RMS energy across sliding $40\text{ms}$ windows with $10\text{ms}$ hops.
  * Establishes adaptive threshold based on background noise floor: $\text{threshold} = \max(-45.0\text{ dB}, P_{20} + 8.0\text{ dB})$.
  * Adds natural breath buffers: $-150\text{ms}$ before speech onset, $+180\text{ms}$ after speech tail.
  * Merges adjacent segments separated by $<300\text{ms}$ of silence.
* **Results on `2026-08-17 17-34-23.mov`**:
  * Original: $111.55\text{s}$
  * Removed **`32.28 seconds`** of dead pauses.
  * Generated tight edit: $79.25\text{s}$ (`screen_rec_tight_edit.mp4`).

### 7.2 Stage 2: Content-Aware Semantic Best-Take Curation
* **Algorithm**:
  * Transcribes spoken content using Gemini Flash with millisecond timestamps.
  * Categorizes each sentence into `repeated_take`, `false_start`, `stumble`, or `clean_final_delivery`.
  * Selects ONLY the single best, most authoritative delivery for each idea.
  * Trims stumbles and redundant attempts while maintaining lockstep video/audio sync with monotonic PTS timestamps.
* **Editorial Cuts on `2026-08-17 17-34-23.mov`**:

| # | Selected Best Take (Kept) | Eliminated Bad Takes (Cut) |
| :--- | :--- | :--- |
| **Take 1** | `8.35s – 12.50s` (*"All right, as you can see it just finished and it made the airplane spin around the text."*) | Cut incomplete false start: `0.0s – 8.2s` (*"All right, so as you can see it made the..."*) |
| **Take 2** | `13.45s – 20.30s` (*"And it has a lot of potential. That took me like 1 minute to set up, and I only waited like 2 minutes..."*) | Cut long silence gaps and heavy breathing |
| **Take 3** | `22.95s – 25.60s` (*"So it clearly shows what you're able to do with it."*) | Cut false start stumble: `20.0s – 23.0s` (*"So you can see what..."*) |
| **Take 4** | `57.30s – 65.70s` (*"So imagine what you would be able to do by prompting it for a few hours. You could probably create better motion graphics..."*) | Cut 4 abandoned retakes: `25.5s – 57.3s` (*"So imagine... you can make unbelievable..."*) |
| **Take 5** | `91.00s – 97.35s` (*"You could probably create great motion graphic designs that would normally take several hours, but in a fraction of the time with this."*) | Cut 4 stumbling retakes: `65.7s – 91.0s` (*"You could probably... in one hour... normally require several hours..."*) |
| **Take 6** | `105.50s – 109.55s` (*"So like and subscribe if this video helped you out, and that's it."*) | Cut incomplete outro take: `97.3s – 105.5s` |

* **Results**:
  * Eliminated **`79.08 seconds`** of stumbles and false starts.
  * Curated master edit: **`32.45 seconds`** (`screen_rec_master_curated_edit.mp4`).
  * Placed onto Video Track 1 (`V1.1`) and Audio Track 1 (`A1.1`) at `01:00:00:00` in DaVinci Resolve.

---

## 8. Competitive Research & Analysis: Samuel Gursky vs. Flamexnreal

### 8.1 Analysis of `samuelgursky/davinci-resolve-mcp`
* **Author**: Samuel Gursky (promoted in video by Andy Diep / *Diep Digital Media*).
* **Target Audience**: Hollywood colorists, DITs, post-production houses.
* **Architecture on Free**:
  * Starts a local HTTP/TCP loopback web server (`resolve_bridge.py`) on an internal port (e.g. `127.0.0.1:8765`).
  * Uses HMAC-SHA256 request signatures with one-use nonces.
  * Requires setting macOS environment variable `launchctl setenv PYTHON3HOME ...` in Terminal and restarting the machine.
  * Suffers from zombie `fuscript.exe` processes holding network ports on Windows/macOS if Resolve crashes.
  * Exposes up to 353 individual raw API tools (heavy context footprint for LLMs).

### 8.2 Side-by-Side Comparison Matrix

| Dimension | Samuel Gursky (`davinci-resolve-mcp`) | Your Bridge (`davinci-resolve-ai-bridge-mcp`) |
| :--- | :--- | :--- |
| **Primary Focus** | Deep color science, node graphs, offline `.drx`/`.drp` parsing | **Autonomous Video Creation, Motion Design, Kinetic Typography, Audio Curation** |
| **Free Edition Transport** | Local HTTP loopback socket (prone to port locks & zombie processes) | **Atomic File IPC Queue + Auto-Clipboard Py3 Console** (zero port locks, zero zombie hangs) |
| **macOS Setup Complexity** | High (requires `launchctl setenv PYTHON3HOME` and system restarts) | **Zero-Config** (single-click menu copies command, paste and run) |
| **Motion Design Integration** | ❌ None | ✅ **Built-in Remotion Engine** (spring physics, kinetic typography, bouncing text) |
| **Magnifier Callout Boxes** | ❌ None | ✅ **Built-in Magnifier Callout Skill** (frosted background blur, subpixel camera zooms) |
| **YouTube Effect Recreation** | ❌ None | ✅ **Built-in `youtube-video-inspector`** (fast headless extraction, visual sampling, recreation) |
| **AI Voiceovers (TTS)** | ❌ None | ✅ **Built-in Gemini 3.1 Flash TTS** (30 prebuilt voices, style/pace controls) |
| **Silence & Take Curation** | ❌ None | ✅ **Built-in Acoustic Energy & Semantic Take Curation Engine** |
| **LLM Context Economy** | ⚠️ Heavy (up to 353 granular tools) | ✅ **Lean & Compound** (designed specifically for agentic loops like Antigravity, Claude, and Cursor) |

### 8.3 Safe YouTube Comment for Andy Diep's Video
```text
Hey Andy, great breakdown on using AI with the free version of Resolve!

Inspired by this workflow, I built an open-source MCP bridge called davinci-resolve-ai-bridge-mcp (by flamexnreal on GitHub) designed specifically around the free version. It includes built-in Remotion support for custom motion graphics and kinetic typography, plus smooth keyframing and floating magnifier callouts directly on the timeline.

Would love to hear your thoughts on it if you get a chance to try it out!
```

---

## 9. Skills, Custom Rules & AI Directives

### 9.1 Custom Rules Configured in `~/.gemini/config/AGENTS.md`
1. **YouTube Video Inspection Rule**:
   * Antigravity agents MUST NEVER claim inability to view YouTube videos.
   * Agents must download format 134 via `yt-dlp` in $<3\text{s}$, extract visual frames, view with `view_file`, and recreate assets directly.
2. **Plain-English Release Notes Rule**:
   * Prohibits academic jargon (e.g. "subpixel Lanczos", "quintic smootherstep", "VAD energy clustering").
   * Enforces creator-friendly terms (e.g. "Smooth Zooms", "Magnifier Boxes", "Word-by-Word Subtitles").
   * Prohibits unnecessary/corny emojis in official changelogs.
3. **Autonomous Empirical Verification Loop Rule**:
   * Enforces subagent isolation, disk checkpointing, and dynamic convergence across testing cycles.

### 9.2 Installed Skills Directory:
* `~/.gemini/config/skills/youtube-video-inspector/SKILL.md`
* `~/.gemini/config/skills/magnifier-callout/SKILL.md`
* `~/.gemini/config/skills/gemini-tts-editing/SKILL.md`
* `~/.gemini/config/skills/resolve-ai-editing/SKILL.md`
* `~/.gemini/config/skills/autonomous-empirical-loop/SKILL.md`
* `~/.gemini/config/skills/gauntlet-loop/SKILL.md`

---

## 10. Release History & Versioning Log

* **v1.1.0 – v1.4.0**: Initial direct-attach transport, image-on-timeline operations, basic MCP server.
* **v1.5.0**: Vision and audio timeline inspection tools (`timeline_audio`, `timeline_frame`).
* **v1.5.2 – v1.5.3**: Zero-token auto-configuration, self-healing worker heartbeat, hot-reloading operations module.
* **v1.6.0**:
  * Added Remotion motion graphics integration.
  * Added floating magnifier callout box generator with frosted glass blur.
  * Added `youtube-video-inspector` headless video sampling skill.
  * Added prominent Free Version ($0 vs. $295 Studio) compatibility badge and header callout.
  * Plain-English release copy overhaul.
* **v1.6.1** (Current Live Release):
  * Automated clipboard copy (`pbcopy`/`clip`) in `Start AI Bridge.py`.
  * Explicit fallback activation command displayed in Console output.
  * Rewrote README connection guide with clear Free vs. Studio sections.
  * Content-aware acoustic silence trimming and semantic best-take curation pipeline.

---

## 11. Local Filesystem Sitemap & Directory Layout

| Absolute Path | Description |
| :--- | :--- |
| `/Users/eram/Projects/davinci-resolve-ai-bridge-mcp` | Local Git repository root |
| `/Users/eram/.resolve-ai-bridge` | Installed global runtime directory (virtualenv, configs, logs) |
| `/Users/eram/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/Resolve AI Bridge` | Installed DaVinci Resolve menu scripts |
| `/Users/eram/Documents/remotion-motion-design` | Local Remotion React motion design project |
| `/Users/eram/Movies/2026-08-17 17-34-23.mov` | Raw screen recording media asset ($111.55\text{s}$) |
| `/Users/eram/Documents/remotion-motion-design/out/screen_rec_master_curated_edit.mp4` | Rendered 32.45s master curated cut |
| `/Users/eram/.gemini/config/AGENTS.md` | Global Antigravity AI rules and instructions |
| `/Users/eram/.gemini/config/skills/` | Installed Antigravity AI skills |
| `/Users/eram/Projects/davinci-resolve-ai-bridge-mcp/SESSION_SUMMARY.md` | Persistent copy of this master session archive |

---

## 12. Instructions for Future AI Agents

When continuing work on this codebase in a future session:

1. **Verify Live Bridge Connection**:
   * Call MCP tool `resolve_status` (or run `python3 tools/doctor.py`).
   * If offline on Free edition: Remind user to click **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**, click **Py3** tab, and press **Cmd+V $\rightarrow$ Enter**.
2. **Motion Design & Video Generation**:
   * Use Remotion under `/Users/eram/Documents/remotion-motion-design/`.
   * Render transparent overlays with ProRes 4444 (`--codec=prores --prores-profile=4444 --pixel-format=yuva444p10le`).
   * Place onto timeline tracks using `import_media` and `append_media`.
3. **YouTube Video Recreation**:
   * Follow `youtube-video-inspector` skill: download format 134 via `yt-dlp`, sample 6-frame grid with OpenCV, view with `view_file`, and recreate in Remotion.
4. **Publishing Releases**:
   * Bump version across `package.json`, `pyproject.toml`, `bridge/operations.py`.
   * Sync updated files to `~/.resolve-ai-bridge/`.
   * Commit, tag with `git tag -a vX.X.X`, push to GitHub, and run `npm publish`.
   * Maintain plain English (no pretentious math/graphics jargon, no corny emojis).
