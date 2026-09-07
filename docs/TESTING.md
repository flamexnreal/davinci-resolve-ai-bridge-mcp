# Testing

## Automated checks

Use Python 3.10+ with `requirements.txt` installed:

```bash
python3 -m unittest discover -s tests -v
node tools/check-package.mjs
npm run build
python3 tools/doctor.py
```

The standard-library unit tests use in-memory Resolve API doubles and synthetic PCM. MCP-specific tests use the actual installed MCP SDK, with an isolated bridge home. Tests never invoke live editing or publishing. The package check validates a real temporary tarball, including requirements.txt and excluding website runtime dependencies/assets.

The doctor is a separate installed-runtime diagnostic. It can make a read-only status round trip to Resolve. A missing/stopped Console worker is a runtime warning, not proof of a code failure.

## Manual Resolve Free integration checklist

Use a disposable project/timeline with short media. Start the Console worker, then refresh your MCP client. Do not use valuable edits for first-run integration testing.

1. Confirm `resolve_status` reports DaVinci Resolve (Free), then inspect `bridge_capabilities` and `timeline_overview`.
2. On a timeline starting at 01:00:00:00, request a source `timeline_frame` at the playhead. Confirm it is visible as an image and labeled source-only.
3. Place adjacent clips and target the exact cut frame. Confirm `get_clip_transform(item_id="playhead")` selects the right-hand clip.
4. Call `preview_timeline`, edit a static transform, then compare the original and preview by timeline IDs. Confirm the original remains untouched.
5. Split a normal-rate clip with a simple grade. Inspect both halves and the retained checkpoint. Use Resolve manually for Fusion clips, speed changes or advanced clip metadata.
6. On a clip with a pre-existing Fusion effect, use `change_clip_speed(speed=0.75)` then `speed=1`. Confirm the existing effect chain remains connected. Reset does not claim ownership of legacy/user TimeSpeed nodes.
7. Analyze stereo audio, trailing silence, and a trimmed source range. Confirm each channel's peak is visible and exported WAV duration matches the selection.
8. On one isolated dialogue clip or aligned AV pair, call `review_silence`. Audition yellow markers. Pass only accepted marker IDs to `apply_silence_cuts`. Confirm the original is intact and the preview closes the selected gaps. Check audio gain, fades and sync manually.
9. Move/trim a clip after creating review markers. Confirm applying the stale markers is refused.
10. Supply delivery dimensions to `project_health`; verify mismatch findings. Treat track gaps and disabled clips as informational until reviewed.

Record Resolve version, edition, OS, decoder, result, and limitations in the release notes. A passing mock test is not a claim of live Free-version validation.

## Reliability regressions

`tests/test_reliability.py` uses mocks and temporary runtime directories: no native Resolve imports or live project edits. It covers uncertain direct dispatch, safe pre-dispatch fallback, deadline rejection, context changes, concurrent clients, duplicate records, busy heartbeat/client timeout and installer failure/interruption. Run the full unittest suite and npm package/build checks. Doctor `--offline` checks installation without contacting Resolve.

Manual Free verification remains required on a disposable project: run a job longer than 25 seconds, observe busy heartbeats and eventual completion after client timeout, queue edits from two clients then switch timelines/projects, confirm stale work is rejected, and restart after an interrupted job to inspect its durable record. Do not use a production project for these checks. Also validate update/recovery on macOS, Windows and Linux. Native calls holding the GIL, UI changes during execution and power-loss filesystem durability are outside mock guarantees.


## One-click startup validation

`tests/test_startup.py` covers real cross-process OS locking, crash lock release,
legacy-worker exclusion, startup/install exclusion, main-thread Console output,
non-blocking Console startup, duplicate starts, authenticated session-bound Stop,
and Stop waiting for active work. Native Resolve objects are mocked in these tests.

Live checked on 2026-09-06: macOS, Resolve **Free 21.0.3.7**, Python **3.14.6**,
with an empty open project. No timeline edits or rendering were needed:

- A Workspace > Scripts invocation receives working injected Resolve objects.
- It runs as `fuscript`, a child of Resolve, and normally exits when the script returns.
- Start AI Bridge starts the updated queue worker without opening/pasting into Py3.
- A real authenticated `status` request succeeds; repeated Start retains one session/PID.
- Stop from the menu removes the heartbeat and ends the menu worker.
- Quit Resolve while the worker runs: both processes exit and the heartbeat is removed.
- Reopen Resolve/project and Start again: a new session serves a real status request.
- The Py3 Console fallback prints READY, returns control, serves status, and can be stopped from the menu.

The menu worker was about 44 MiB RSS in one idle snapshot (not a cross-platform
benchmark). No dependency or AI call was added. Existing queue polling remains;
Stop checks and a twice-per-second parent-lifetime check are the added recurring work.
Windows/Linux and other Resolve/Python builds have not been live-tested here.
This evidence validates startup/lifetime, not every editing operation.
