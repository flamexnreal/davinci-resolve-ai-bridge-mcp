# Resolve compatibility

## Free 21.1.2 is unsupported by v1.13.1

Live checked on macOS, **DaVinci Resolve Free 21.1.2.10**, on 2026-10-28:

- Python Console/menu startup is unavailable. Blackmagic moved Python scripting
  to Studio in [21.1's release notes](https://www.blackmagicdesign.com/support/readme/59dd4eef1f4941c29fb8dc48b33f5c87).
- The Lua Console still evaluates Lua 5.1, and ordinary Resolve API inspection
  succeeds. A disposable Lua menu script also creates a timeline and marker.
- Both Console and menu environments report `dofile`, `loadfile`, `require`,
  `io`, `package` and FFI unavailable. The native ZipFile wrapper also fails
  when it attempts to use FFI.
- The investigated loopback Lua connector requires those facilities and cannot
  start on this build. It is excluded from the stable package. No automated
  connection to current Free is claimed.

Earlier upstream Lua-bridge reports concerned other builds; a passing simulation
or an upstream report does not establish compatibility with Free 21.1.2.
Reinstalling Python does not restore the missing interpreter inside Resolve.

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
