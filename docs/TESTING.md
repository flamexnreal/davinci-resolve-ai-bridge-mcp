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
