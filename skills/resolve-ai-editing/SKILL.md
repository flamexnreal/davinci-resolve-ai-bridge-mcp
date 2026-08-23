---
name: resolve-ai-editing
description: Plan, perform, and verify careful edits in an open DaVinci Resolve project through Resolve AI Bridge MCP tools.
---

# Resolve AI Editing

Use this skill whenever a request involves the open DaVinci Resolve project.

## Mandatory Live Timeline Audit Protocol

**CRITICAL RULE FOR AI AGENTS**:
Before analyzing audio, generating subtitles/captions, rendering motion graphics, or proposing any edit:
1. **Always Call `timeline_overview` First**: Never assume previous timeline state, cached clip names, or raw files on disk. The user frequently records new microphone audio, cuts clips, trims in-points (`GetLeftOffset`), moves the playhead, or switches projects/timelines in DaVinci Resolve between prompts.
2. **Target Active Playhead & In-Point Offset**: Always compute `source_frame = (playhead_frame - start_frame) + left_offset` to ensure exact sample-accurate alignment with what is visible in the viewer.
3. **Normalize Audio to 16-bit PCM**: Always convert 24-bit/32-bit Fairlight audio files to 16-bit linear PCM (`LEI16@48000`) before seeking or analyzing to prevent 150% time dilation.
4. **VAD Energy Snapping & -160ms Anticipatory Lead**: Group words into natural breath groups, snap word highlights strictly to physical acoustic energy peaks ($> -34\text{ dBFS}$), clear the screen during pauses, and apply an anticipatory lead offset of `-160ms` ($-4\text{ frames}$ at 24fps) so visual typography matches the consonant attack instantly with zero perceptual lag.
5. **GPU Cache Invalidation**: When placing newly rendered transparent subtitle or motion graphic videos onto the timeline, always use a unique timestamped filename or disable old overlapping clips on lower tracks so DaVinci Resolve's GPU video memory immediately displays the fresh render.

## Required Workflow

1. Call `resolve_status` before every editing session. It reports which transport is live.
2. Call `timeline_overview` before proposing an edit.
3. Summarize what is open and identify ambiguities.
4. State a short plan before changing the timeline.
5. Use ids such as `V1.2` from the latest overview. Do not target a clip by a repeated name.
6. Make one logical change per tool call.
7. Call `timeline_overview` again to verify the result.
8. Ask for explicit approval before deletion, ripple deletion, or starting a render.

## When The Bridge Is Offline

`resolve_status` returns a `help` string. Pass it on rather than guessing. The order that fixes it:

1. Open DaVinci Resolve with a project.
2. **Workspace > Scripts > Resolve AI Bridge > Start AI Bridge**.
3. Paste the line in `~/.resolve-ai-bridge/console-command.txt` into **Workspace > Console**, Py3 tab.

Never claim an edit succeeded while the bridge is offline.

## Images And Overlays

- Use `add_image` for any still. Do not use `append_media` for a picture; that produces a one-frame clip.
- Give a real `duration_seconds`. Read `actual_duration_frames` in the reply and report it if it differs from the request.
- Put overlays on `track_index` 2 or higher so footage on V1 stays visible. The track is created automatically.
- Position with `pan_percent`, `tilt_percent`, `zoom`, and `opacity`, or afterwards with `set_clip_transform`.
- `pan` and `tilt` are pixels from centre. The percent variants are relative to the timeline resolution, which `project_info` reports.
- After placing an image, call `timeline_overview` and confirm the new item id before making further changes.

## Titles

`insert_title` is best effort. Available names depend on the Resolve version and installed templates. Check `text_set` in the reply. When it is false, say the text must be typed in the Inspector, or offer to build the title in Remotion instead.

## Editing Clips On The Timeline

- Scale, reframe, or blend an existing clip with `set_clip_transform`. It takes `zoom`, `zoom_x`/`zoom_y`, `pan`/`tilt` (pixels), the percent variants, `rotation`, crop, `opacity`, `composite_mode`, and modes such as `scaling`, `resize_filter`, `retime_process`, and `motion_estimation`. This is a static transform.
- **Continuous Camera Keyframing & Zooms (Subpixel Compositor Roundtrip)**:
  - In DaVinci Resolve Free, Edit-page spline keyframes are locked in Python scripting, and `AddFusionComp()` frequently disconnects `MediaIn1` producing black screens.
  - **The Golden Method**: Extract the exact timeline subclip `(file_path, left_offset, duration, record_frame)`, render the camera zoom/pan using the **Subpixel Lanczos Compositor / Remotion Roundtrip** with continuous quintic smootherstep easing ($E(t) = 6t^5 - 15t^4 + 10t^3$), and swap the rendered clip back onto the timeline at `record_frame`. This guarantees $C^2$-smooth, 60fps/24fps broadcast-grade camera motion with zero stepped cuts, zero 1ms black flickers, and zero black screens.
- **Floating Magnifier & Spotlight Callouts**:
  - Use the `magnifier-callout` skill when zooming into specific UI elements (search bars, code blocks, buttons).
  - Keep the base video at 100% scale with progressive Gaussian blur ($\sigma = 45\text{px}$) and a $30\%$ dark vignette.
  - Float a sleek rounded-rectangle frosted glass card ($1680\text{px} \times 320\text{px}$, $28\text{px}$ radius, $3\text{px}$ glow border, $60\text{px}$ drop shadow) with $1.8\times - 2.2\times$ magnification.
  - Always calculate margin padding (`crop_w = feature_w + 140\text{px}`) to ensure end-caps, icons, and text are 100% visible with zero cutoffs.
- Cut a clip in two with `split_clip`, choosing the point by `frame`, `timecode`, or the playhead. It rebuilds the clip as two pieces. It does NOT copy color grades or Fusion comps onto the halves — tell the user when that matters.
- All operations accept `item_id="playhead"` to act on the clip under the playhead, so you need not look up the id first. Still confirm with `timeline_overview` afterwards.
- `split_clip` is only near-reversible: it deletes and re-adds the clip. Confirm the frame is right before cutting, and inspect the result.

## Remotion & Headless Compositor Workflow

Use Remotion / Headless Compositor when the user asks for complex animated typography, smooth camera keyframes, floating callouts, explainers, or designed motion scenes.

1. Inspect `timeline_overview` to obtain the exact `(start_frame, duration, left_offset, file_path)`.
2. Render the animation or effect to a high-quality video in `out/`.
3. Import the file with `import_media(paths=[...])`.
4. Replace or place on the timeline at `record_frame = start_frame` using `append_media`.
5. If useless pauses or dead time were trimmed, ripple-shift all downstream clips on all tracks so there are **zero gaps and zero overlaps**.
6. Set playhead and verify the timeline visually.

## API Boundaries

The public Resolve scripting API does not expose every action from the Edit page. Do not claim that transitions, arbitrary clip repositioning, or advanced Fusion animation worked unless a returned result and a fresh timeline inspection confirm it. If a requested action has no MCP tool, explain the limitation and offer a safe alternative.

## Failure Behavior

- If `resolve_status` reports no connection, stop and give the start instructions above.
- If a tool returns an error, do not repeat it unchanged more than once.
- Read the error, inspect current state, and adjust the plan.
- Never report success based only on an attempted call.
