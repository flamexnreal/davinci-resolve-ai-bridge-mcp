# Release Notes

## v1.12.0 — One-click startup in Resolve Free (2026-09-06)

This release brings 1-click startup to DaVinci Resolve Free directly from the Workspace menu, prevents background crashes during startup, and adds clean process locking and shutdown controls.

### Added
- **1-Click Free Menu Startup**: Choose `Workspace > Scripts > Resolve AI Bridge > Start AI Bridge` to start the bridge worker directly using Resolve's built-in API connection, eliminating the need to paste code into the Console.
- **Cross-Process Worker Lock**: Added an OS worker lock and update exclusion so repeated menu starts reuse the running worker instead of creating duplicate competing processes.
- **Session-Bound Clean Stop**: `Stop AI Bridge` cleanly stops the worker after any active operation finishes, and quitting Resolve automatically cleans up the background script process.
- **Fast Console Fallback**: The Console startup line remains fully supported with a one-second handshake for users who prefer starting via the DaVinci Resolve Console.

### Fixed
- **Startup Crash Prevention**: Fixed background thread output issues that could trigger Python capsule and system errors during startup in DaVinci Resolve Free.
- **Zero Overhead**: No new dependencies, listening ports, public MCP tools, or AI calls added.

### Validation & Limits
- Live startup and lifecycle verified on macOS with **DaVinci Resolve Free 21.0.3.7** and **Python 3.14.6** (menu start, queue status, repeated start, Stop, quit/reopen, and Console fallback).
- Windows, Linux, and other Python/Resolve versions were not live-tested for this specific fix. Timeline editing capabilities remain unchanged.


## v1.11.0 — Concurrency protection, guarded edits and crash-proof updates (2026-09-06)

This release hardens the bridge against accidental duplicate edits, prevents tasks from targeting the wrong timeline, eliminates false timeouts during long operations, and makes installations crash-proof with automatic rollback.

### Added
- **Multi-Timeline Context Protection**: Queued edits are bound to the client's observed project and timeline IDs, preventing accidental edits if you switch timelines in Resolve while a request is pending.
- **Durable Request Journals**: Added request records in `~/.resolve-ai-bridge/requests/` to detect and suppress duplicate commands.
- **Dedicated Liveness Heartbeat**: Heartbeat reporting runs on a dedicated thread without touching Resolve APIs, keeping the worker alive during heavy jobs without false 25-second timeouts.
- **Safe Staged Installation (`install.py`)**: Validates new bridge files in a staging area before activating them, while preserving previous working installations at `~/.resolve-ai-bridge.previous` for automatic rollback.
- **Offline Doctor Check**: Added `python3 tools/doctor.py --offline` to verify file health without requiring Resolve to be open.
- **Cross-Platform CI**: Added GitHub Actions workflow to run regression tests and package checks across Ubuntu, macOS, and Windows.
- **Reliability Test Suite**: Added 11 new tests covering connection drops, context switching, long-running jobs, and interrupted installs (53 tests total).

### Fixed
- **No Accidental Duplicate Replays**: Stopped blind fallback to the Console queue after an uncertain direct dispatch failure. If a connection drops mid-flight, it reports an unknown outcome rather than re-cutting or duplicating media.
- **Request Expiration Deadlines**: Stale queued requests now expire rather than executing unexpectedly minutes later.
- **Clear Timeout vs. Cancellation**: Clarified that client timeouts do not cancel native operations already executing inside Resolve.


## v1.10.0 — Free-compatible review workflows and reliability (2026-09-06)

This release improves reliability for DaVinci Resolve Free's Console-worker workflow and adds ways to inspect and review edits while retaining the original timeline.

### Added

- `preview_timeline` and `compare_timelines`: keep the original, edit a duplicate and review structural/property/marker differences.
- `project_health`: active-timeline missing source, gap, disabled/locked track/clip checks and optional delivery expectations.
- `bridge_capabilities`: Resolve version, transport, ordinary API presence and source decoder availability, including when no timeline is open.
- `review_silence`: candidate source-audio silence markers, with stale-review detection.
- `apply_silence_cuts`: apply explicitly accepted marker intervals to a duplicate of an isolated dialogue clip or one aligned video/audio pair. Complex timelines remain manual.
- Optional `--with-ffmpeg` private source decoder, Windows-aware Python discovery and explicit npm `--serve` mode.
- Regression tests, real-decoder checks, native MCP image/schema tests, cross-platform CI and real npm tarball validation.

### Fixed

- npm package includes the requirements.txt file used by installation.
- Malformed client JSON is preserved; valid merges receive timestamped backups and atomic writes.
- Playhead targeting uses exclusive end boundaries and ignores disabled clips/tracks.
- Source frame capture uses absolute timeline positions, including timelines starting at 01:00:00:00.
- Timeline-specific rates/resolution and drop-frame timecode conversion are respected.
- Stereo peak/clipping analysis no longer averages opposite-polarity channels into silence.
- Trailing/all-silent intervals are closed correctly; analysis returns explicit source/timeline coordinates and truncation.
- export_slice returns the trimmed WAV rather than the full decoded source.
- Failed clip rebuilds retain a checkpoint and report partial failure instead of claiming an unverified rollback.
- Speed 1 neutralizes a bridge-owned TimeSpeed node without bypassing existing Fusion connections.

### Changed / upgrade notes

- `timeline_overview.id` prefers the Resolve unique ID; `label` retains V1.2-style positional references. Old labels remain accepted, but duplicates/rebuilt clips have new IDs.
- `timeline_frame` returns native MCP image content plus text metadata. Its frame argument is now an absolute timeline frame, consistent with editing tools.
- Source-only images/audio are labeled accurately; no claim of rendered viewer or Fairlight mix equivalence.
- Splits reject Fusion clips, locked tracks, mixed source rates and known retiming. They preserve static transforms, clip state/color and the current grade layer; advanced metadata, links and fades still require review.
- Fusion speed changes leave timeline duration and linked audio unchanged. Untagged legacy/user TimeSpeed nodes are preserved; they require manual reset. Reverse source mapping is unverified and rejected. Clip-FPS mode multiplies current source FPS and affects every use of the media.
- Removed unused duplicate audio/image helper modules. Website libraries are development dependencies and the built website is excluded from the npm CLI package.
- Installer version derives from the bridge version. README, agent instructions, recipes, troubleshooting and release/testing guidance describe current behavior.

### Validation and Free-version scope

- 42 automated tests passed locally, including synthetic audio, mocked Resolve operations, actual FFmpeg source decoding and MCP image conversion.
- Website build, real npm package-content validation and Python source checks passed.
- A live MCP handshake advertised 44 tools. Read-only resolve_status and bridge_capabilities succeeded through the Console worker on **DaVinci Resolve Free 21.0.3.7 (macOS)**.
- Doctor: zero failures; external direct attach was unavailable and the intended Console route answered successfully.
- No live timeline edits were performed. Use docs/TESTING.md for manual Free-version edit checks before claiming those were verified. New workflows use ordinary timeline/marker/Fusion functionality, not Studio AI calls.

Earlier release sections below are historical; current restrictions and setup are documented above and in README.md.


## v1.9.0 — Compound Clips and Clip Speed Changes

This release introduces two major timeline editing capabilities for DaVinci Resolve (Free and Studio):

### Compound Clips
- `create_compound_clip`: Group one or more timeline items (`V1.1`, `A1.1`, or `item_id="playhead"`) into a clean, single compound clip container.
- Keeps original source in/out cuts, audio sync, and Edit-page sizing intact.
- Works 100% on free DaVinci Resolve via native timeline compound clip creation.

### Clip Speed and Slow Motion
- `change_clip_speed`: Adjust playback speed for any video clip with a single command.
- Supports speed multipliers (e.g. `speed=0.75` for 75% speed / 25% slower), slowdown percentages (`slow_down_percent=25.0`), speed-ups, and reverse playback.
- Automatically enables smooth subframe interpolation for fluid slow-motion playback.

## v1.2.0 — Reliable launcher, and real timeline editing

This release makes the one-click launcher dependable and gives your AI three things it could not do before: **scale** the clips already on your timeline, **animate** that scale over time, and **cut** clips in two. It also tidies the Workspace > Scripts menu so only the bridge's own entries remain.

### The launcher works every time now

Clicking **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge** sometimes did nothing, and the only fix was to repaste the Console line. Cause: the menu launcher relied on Resolve injecting its `resolve` object into the script's globals, which Resolve does not always do for a Scripts-menu run.

The worker no longer depends on that injection. When the object is not handed to it, it imports Resolve's own scripting library from disk (`fusionscript` / `DaVinciResolveScript`, with a direct load of `fusionscript.so`/`.dll` as a final step) and asks Resolve for the app itself — exactly what a Console paste does. The launcher also collects every host object it can see and forwards it to the worker, and on failure it prints the reason, the log path, and the Console fallback instead of dying silently. The menu path uses a non-daemon worker so Resolve does not tear it down when the one-shot script returns; a Console paste retains its daemon behavior. **The menu click now remains connected without repasting.**

### Scale clips you already placed

`set_clip_transform` was built for positioning stills; it now drives the clips you cut in yourself:

- Independent `zoom_x` / `zoom_y`, plus `scaling` (crop, fit, fill, stretch), `resize_filter`, `retime_process`, and `motion_estimation` — the full documented sizing surface.
- Pass `item_id="playhead"` to act on the clip under the playhead, so the AI can work on "the clip I am looking at" without first listing every id.

### Animate a push-in or pull-out

`animate_zoom` makes a scale that actually moves over time. Resolve's Edit-page sizing cannot be keyframed through scripting, so this builds a **Fusion composition** on the clip with a keyframed Transform node from `start_zoom` to `end_zoom` across a frame range you choose.

It is honest about the result: the reply includes `keyframes_created` and a step-by-step `trace`. On a build that refuses scripted keyframes it applies a static zoom and says so, rather than claiming an animation that is not there.

### Cut clips on the timeline

`split_clip` razors a clip in two at a frame, a timecode, or the playhead. Resolve's scripting API has **no razor, blade, split, or trim call**, so the cut is synthesised: the clip's source range and transform are read, the clip is removed, and two adjacent pieces are re-appended at the original positions with the transform re-applied. If the rebuild cannot place both halves, the original is restored so a failed cut is never destructive.

Honest limitation, stated in every reply: color-page grades and Fusion compositions on the original are **not** copied onto the halves, because the API cannot copy them.

Example prompt:

> Take the clip under the playhead. Push it in from 100 to 130 percent over its first two seconds, then split it where the playhead is. Show me the timeline before and after each step.

### A tidier Scripts menu

The installer now moves superseded, hand-made scripts (old `RFAIB_*` probes, duplicate launchers with hard-coded paths, one-off overlay scripts) out of Resolve's `Utility` folder into `~/.resolve-ai-bridge/removed-scripts-backup/`. They are **moved, not deleted**, so nothing is lost and you can bin the backup yourself. Only the three **Resolve AI Bridge** entries remain in the menu.

### Also new

- Clearer `append_media` error that spells out `media_ids` vs `paths` and points stills at `add_image`.
- `get_clip_transform` and `split_clip` accept the same `item_id="playhead"` shorthand.
- Editing guide, MCP instructions, `00_START_HERE.html`, and the web guide all document the new tools and stay in agreement.

### Compatibility

- Built against **free DaVinci Resolve** (validated on 21.0.3.7). No tool here uses a Studio-only or paid AI call.
- New operations were written against Blackmagic's own scripting README. **They were not run against a live Resolve for this release** (Resolve was not open during the build), which is why cuts and animations are synthesised from documented primitives and every reply reports what Resolve actually returned. Verify on your build with `timeline_overview` and `python3 tools/doctor.py`.

### Upgrading from 1.1.0

1. Download this release and run `python3 install.py` (`py install.py` on Windows). Your token is preserved.
2. Restart DaVinci Resolve once so it re-scans the Scripts menu and the tidy-up takes effect.
3. Run `python3 tools/doctor.py` with a project open.

No tool names changed. Three tools were added (`split_clip`, `animate_zoom`, and the extended `set_clip_transform`).

---

## v1.1.0 — Zero-paste setup, images on the timeline

Version 1.0 worked, but two things tripped people up: you had to hand-edit `YOUR_NAME` into the Console line, and you had to repaste that line every single time you opened DaVinci Resolve. Both are gone.

### Nothing to edit

The Console line is now one portable command that is identical on every computer and every operating system:

```python
import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())
```

Python expands `~` inside Resolve's own interpreter, so there is no user name to substitute and no personal path in anything you copy.

### Nothing to repaste

The bridge now picks its own route into Resolve:

- **Direct attach (default).** The MCP server talks to the running Resolve through Blackmagic's native scripting library. Open Resolve and your AI is connected. To turn the bridge off, disconnect the MCP server in your AI client.
- **One-click launcher (fallback).** The installer adds **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**, plus **Bridge Status** and **Stop AI Bridge**. Restart Resolve once after installing so it picks up the new menu.
- **Console line (last resort).** Still there, still works, now with nothing to edit.

`resolve_status` and `tools/doctor.py` both report which route is live and why, so an offline bridge produces an actionable message instead of a shrug.

### Images and overlays

An AI client can now put a picture on your timeline and place it:

- `add_image` imports a still and places it with a real duration on a chosen track, creating the track when needed. Appending a still as ordinary footage produced a one-frame clip; this does not.
- `set_clip_transform` and `get_clip_transform` move, scale, rotate, crop, fade, and blend any timeline item, in pixels or as a percentage of frame size.
- `add_track` and `set_track_name` create and label the overlay tracks images need.

Example prompt:

> Put /Users/me/Desktop/logo.png on video track 2 for 4 seconds at the playhead, scaled to 40 percent and tucked into the bottom right corner. Then show me the timeline to confirm it.

### Also new

- `insert_title` inserts a title at the playhead and reports honestly whether its text could be set through the API.
- `open_page` switches Resolve to a page so you can see what changed.
- `list_render_presets` removes the guesswork before queueing a render.
- `timeline_overview` now reports track enabled state and the timeline frame rate; `list_media` reports frame counts and resolution.
- Every operation now lives in one shared module, so both transports execute exactly the same code.
- The installer verifies whether a direct attach works on your machine and tells you the result, and the doctor round-trips a real request over whichever transport is live.

### Compatibility

- Works with **free DaVinci Resolve**. Blackmagic's scripting documentation states the scripting APIs are a common superset for the free and Studio versions, and no tool here depends on a Studio-only or paid AI feature.
- If a build or preference refuses a direct attach, the bridge silently falls back to the Console worker and every tool behaves identically.
- Loading Resolve's native module is probed in a disposable subprocess first, so an incompatible Python can never take down the MCP server.

### Upgrading from 1.0.0

1. Download this release and run `python3 install.py` (`py install.py` on Windows). Your existing token is preserved, so your AI client's MCP entry keeps working.
2. Restart DaVinci Resolve once so the Workspace > Scripts menu appears.
3. Run `python3 tools/doctor.py` with Resolve open.

No breaking changes to the MCP tool names from 1.0.0. Six tools were added.
