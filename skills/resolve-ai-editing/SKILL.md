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
2. **Use Source Mapping Metadata**: Use timeline_audio's returned source_start_sec, timeline_start_frame and frame_rate. Do not assume source frames equal timeline frames on mixed-rate or retimed clips. Source analysis excludes Fairlight processing.
3. **Audio Formats**: Let timeline_audio normalize decoded media to 16-bit PCM. Do not infer timing errors solely from source bit depth.
4. **Timing Review**: Activity clusters are energy-based, not transcripts. Any anticipatory caption lead is an optional creative choice; audition the result rather than promising universal perceptual sync.
5. **GPU Cache Invalidation**: When placing newly rendered transparent subtitle or motion graphic videos onto the timeline, always use a unique timestamped filename or disable old overlapping clips on lower tracks so DaVinci Resolve's GPU video memory immediately displays the fresh render.

## Required Workflow

1. Call `resolve_status` before every editing session. It reports which transport is live.
2. Call `timeline_overview` before proposing an edit.
3. Summarize what is open and identify ambiguities.
4. State a short plan before changing the timeline.
5. Prefer the stable `id` from the latest overview. Positional `label` values such as `V1.2` can change after edits. Duplicates and rebuilt clips have new IDs. Do not target a repeated name.
6. Before a batch of changes, use `preview_timeline`, inspect its new IDs, and keep the original. Use `compare_timelines` plus visual/audio review afterward.
7. Make one logical change per tool call.
8. Call `timeline_overview` again to verify the result.
9. Ask for explicit approval before deletion, ripple deletion, or starting a render.

## Camera Motion, Smooth Zooms & Multi-Keyframing

Use `animate_zoom` to generate native Fusion camera keyframes directly on timeline clips:
- **14 Motion Curve Presets**: `linear`, `ease_in`, `quad_in`, `cubic_in`, `ease_out`, `quad_out`, `cubic_out`, `ease`, `quad_ease`, `cubic_ease`, `circular_ease`, `rebound_in`, `rebound_out`, `elastic_out`.
- **Zoom Out**: Pass `direction="out"` or `start_zoom > end_zoom` (e.g. `start_zoom=1.6, end_zoom=1.0`). Passing `zoom < 1.0` (e.g. `0.55x`) shrinks the video into a centered floating card with black letterbox/pillarbox canvas borders.
- **Multi-Keyframe Sequences (`keyframes`)**: Define multi-stage waypoint trajectories (e.g. fast punch-in -> typing hold -> gradual slow ease-in zoom out) with per-segment easing curves.
- **AI Scenario Presets**: `punch_in` (snappy 1.35x), `pop_in` (1.38x with overshoot), `slow_push` (subtle 1.15x push), `dramatic` (1.60x build-up), `reveal` (1.40x to 1.0x pull-out), and `cinematic` (1.25x smootherstep glide).

## Color Grading & Organic Shimmer Effects

- **Color Grades**: Use `set_clip_grade` and `get_clip_grade` to adjust saturation, slope, offset, and power via native ASC-CDL controls.
- **Color Transitions**: Use `keyframe_clip_saturation` to smoothly transition clips between 100% color and black-and-white.
- **Rainbow Cycles & Exposure Flicker**: Use `animate_color_fx` to generate continuous $360^\circ$ spectrum hue cycling and multi-harmonic organic lighting shimmer.

## Spotlight & Focus Masking

- **Spotlight Mask**: Use `apply_spotlight_mask` to darken the background (ambient brightness `0.0` for pure black shadow) and focus an animated, feathered spotlight circle/rectangle across key points on any timeline clip.

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
- `split_clip` creates a verified checkpoint before rebuilding a normal-rate clip. It copies static transforms and the current grade layer, but rejects Fusion comps and mixed rates. Other grade layers, fades, links and metadata are not guaranteed. Inspect the checkpoint and result; never describe a failed rebuild as fully rolled back.
- Group multiple timeline items into a clean single compound clip with `create_compound_clip(item_ids=['V1.1', 'A1.1'], name='Scene 1')` or `create_compound_clip(item_id='playhead')`.
- Adjust constant video speed with `change_clip_speed(speed=0.75)`. It edits a tagged bridge-owned TimeSpeed node and preserves existing connections. Speed 1 neutralizes that node. Timeline duration and linked audio are unchanged; reverse is rejected. Clip-FPS mode affects every use of the media.
- Clip-targeting operations that expose `item_id` accept `item_id="playhead"` to act on the clip under the playhead, so you need not look up the id first. Still confirm with `timeline_overview` afterwards.
- `split_clip` is only near-reversible: it deletes and re-adds the clip. Confirm the frame is right before cutting, and inspect the result.

## Remotion & Headless Compositor Workflow

Use Remotion when the user asks for complex animated typography, floating callouts, explainers, or designed motion scenes.

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
- On timeout or unknown outcome, never replay a mutation automatically. Inspect its request record and fresh timeline state first. Client timeout does not confirm cancellation.
- After a stale project/timeline rejection, inspect the intended context again before submitting a new edit.
- Read the error, inspect current state, and adjust the plan.
- Never report success based only on an attempted call.

## Source inspection and dialogue review

- timeline_frame returns a native MCP image. Check `composited`; source fallback excludes grades, Fusion, overlays and transforms. Do not verify a visual effect from a source-only image.
- timeline_audio uses per-channel peaks and channel energy. Check truncation and absolute timeline offsets; silence intervals use 50 ms windows and exclusive ends.
- review_silence places markers only. Audition candidates and obtain user approval of the selected marker IDs before apply_silence_cuts. Application creates a duplicate and supports an isolated clip or aligned AV pair; complex timelines stay manual.
- Stale markers are refused after timeline edits. Reanalyze rather than bypassing the check.
- project_health reports active-timeline source/gap/disabled-track issues; gaps can be intentional. It does not inspect the full Fairlight mix or render settings.
- Run bridge_capabilities for API/decoder availability. Free uses the Console worker; no Studio AI feature should be substituted.
