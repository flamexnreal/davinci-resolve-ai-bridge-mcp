# Resolve compatibility

## Current Free: native-file Lua connector (v1.14.0)

Live-tested on **macOS DaVinci Resolve Free 21.1.2.10**, 2026-10-29,
using synthetic media in a separate disposable project library.

The existing Python route is unavailable inside this Free build. Lua still
runs the ordinary Resolve and Fusion APIs. Its `io`, `dofile`, `loadfile`,
`require`, `package` and FFI facilities are absent, so the earlier socket/FFI
prototype could not start. That failure did not establish that all Lua
connectors were impossible.

**The replacement uses native Fusion `OpenFile` and native script contexts.**
Live probes read and wrote files on Free 21.1.2.10. These host methods are
covered in Blackmagic's [Fusion scripting reference](https://documents.blackmagicdesign.com/UserManuals/Fusion8_Scripting_Guide.pdf).
The connector loads its own bundled modules through the native file reader.
There is no socket, FFI, embedded Python dependency or binary modification.
Python runs the existing `bridge/operations.py` outside Resolve and calls
session-scoped native objects over signed local file messages.

### Measured behavior

- A full 37-operation native-file editing run passed: AV import retained audio
  and all 192 frames; preview/original isolation, transforms, image IDs, source
  frame/audio decoding, timeline comparison and split checkpoints passed.
- Animated zoom including moving center, masked blur, spotlight, saturation,
  color effects, speed changes/reset and resets of all five effects passed.
- A separate 16-check stereo/silence workflow passed, including accepted cuts
  on a duplicate, numeric marker positions and stale-review refusal.
- Installer staging and a custom runtime home containing spaces passed.
- Native menu startup after app restart, repeated Start retaining one session,
  menu Stop staying stopped, stale-session Stop refusal and Stop waiting for
  the complete active operation passed. Console startup was also checked.
- Requests/replies use HMAC-SHA256, session checks, deadlines, nonce replay
  protection, bounded handles and a cross-process lock for complete operations.
  Lost replies halt further dispatch and are recorded as unknown; an edit is
  never automatically replayed through Python or another transport.
- Native IPC slots retain their pre-created POSIX 0600 permissions inside the
  private 0700 runtime. Partial file reads are retried without resending edits.

The same public MCP tools and shared operation implementation are retained.
This restores the tested editing workflows on current Free; it does not unlock
Studio-only AI/effects or promise every API on every platform/build.

### Remaining limits

Live current-Free validation covers macOS only. Windows/Linux native Resolve,
Studio, render completion and large timelines remain unverified. Native render
calls and uncommon tool paths still need manual checks. Still images may use
Resolve's default duration rather than the requested one; replies report the
actual result. Source frame/audio decoding excludes timeline compositing and
Fairlight processing. Existing reconstruction/metadata limitations still apply.

## v1.13.1 historical result

That release excluded the failed socket/FFI Lua prototype and accurately
reported Free 21.1.2 unsupported by its shipped connector. Upgrade to v1.14.0
and use **Start AI Bridge (Lua)**. Reinstalling Python alone cannot restore Py3.

## Free 21.0.3.7

The existing Python startup/lifecycle route was live-verified on **macOS Free
21.0.3.7**, Python **3.14.6**. See [TESTING.md](TESTING.md).

The v1.13.1 **released Python worker** was live-checked on that build in an
isolated test library on 2026-10-29. AV import retained audio and all 192 frames;
preview/original isolation, image placement/IDs, transform readback, split
checkpoints, source decoding, stereo/silence analysis, cleanup/stale-review
refusal, zoom (including an animated center), masked blur, spotlight, saturation,
color effects, speed/reset and effect resets passed. Console effects use native
Fusion input/modifier APIs, since a resident worker can block queued Lua scripts.
Doctor reported zero failures with the Console transport active.

During the Lua investigation, synthetic media in a disposable project on that
build passed AV import, duplicate editing, static transform readback, split
checkpoints, source frame/audio decoding, silence markers/cleanup, stale-review
rejection, Fusion effect stacking/reset and speed/reset. These results helped
identify ordinary editing bugs fixed in v1.13.1. They used an experimental Lua
transport; the separate Python checks above validate the released path's listed
operations.

Still-image duration remained Resolve's default 120 frames when 24 were
requested. The tool reports the actual duration and a warning. Timeline comparison
omits enabled/locked track flags because inactive timelines may report them
incorrectly. Source decoding excludes timeline compositing and Fairlight mixing.

## Other builds and platforms

Studio supports the existing Python scripting route, subject to its settings
and Python/native-module compatibility. This release's live validation does not
cover Studio, Windows, Linux, every tool, large timelines or performance under
load. Automated tests and CI use simulated Resolve objects.
