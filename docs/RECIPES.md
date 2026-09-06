# Editing Recipes

These prompts are written to encourage inspection and verification.

## Safe First Test

```text
Call resolve_status and timeline_overview. Do not change clips. Add a blue marker at the current playhead named Bridge test, then inspect again and report the marker frame.
```

## Put A Logo On The Timeline

```text
Add /absolute/path/to/logo.png to video track 2 for 4 seconds at the current playhead. Scale it to 35 percent and place it in the bottom right corner inside a safe margin. Then inspect the timeline and tell me the new item id and its real duration in frames.
```

## Build A Simple Title Card

```text
Create a new timeline named Title Card. Add /absolute/path/to/background.jpg to V1 for 5 seconds, then add /absolute/path/to/logo.png to V2 for 5 seconds at 30 percent scale, centred. Inspect and confirm both durations match before telling me you are done.
```

## Fade An Overlay

```text
Inspect the timeline and find the image on V2. Set its opacity to 40, then read the transform back and confirm the value Resolve stored.
```

## Push In On A Clip Over Time

```text
Inspect the timeline. Take the clip under the playhead and animate its zoom from 100 percent to 125 percent over the clip's first two seconds using animate_zoom. Report keyframes_created from the reply: if it is false, tell me a static zoom was applied instead and why, and do not claim the move is animated.
```

## Cut A Clip At The Playhead

```text
Inspect the timeline. Split the clip under the playhead at the current playhead frame with split_clip. Then inspect again and show me the two resulting item ids, their start and end frames, and report the retained checkpoint. Explain which clip data was preserved and which needs manual review.
```

## Import a Rendered Motion Graphic

```text
Inspect the project and current timeline. Import /absolute/path/to/out/video.mp4 into the current Media Pool. Confirm its media id, then ask me which video track and record frame to use before appending it.
```

## Organize With Clip Colors

```text
Inspect the timeline and list every clip id with its current color. Propose a simple color system for interviews, b-roll, graphics, and audio. Wait for approval, apply one category at a time, then verify.
```

## Disable Without Deleting

```text
Inspect the timeline and find the clip I describe. If its name is ambiguous, show me the matching ids. Disable the selected clip without deleting it, then verify its enabled state.
```

## Queue a Render

```text
Inspect the project and current timeline. Call list_render_presets and tell me which existing preset you plan to use and the output directory. Wait for approval. Add the render job but do not start rendering unless I separately approve it.
```

## Better Editing Brief

```text
Target: 30-second 16:9 product introduction
Audience: first-time customers
Pacing: calm, confident, no rapid montage
Must keep: all spoken lines and the final logo shot
May change: clip order, disabled takes, markers, clip colors, overlay graphics
Do not: delete source clips or start a render

First inspect the timeline. Summarize the existing story, propose an edit plan, and list anything the current MCP tools cannot perform reliably. Wait for approval before editing.
```

## Preview an edit

```text
Inspect my timeline, create a preview_timeline copy, and get fresh clip IDs. Apply the changes on that copy. Compare it with the original and tell me what changed, without deleting either timeline.
```

## Review dialogue pauses

```text
Inspect the timeline and call review_silence on my dialogue clip. Place review markers only. I will audition them and tell you which marker IDs to remove. Do not apply cuts yet.
```

## Project health

```text
Inspect the active timeline and run project_health for a 1920 by 1080, 24 fps delivery. Report missing sources and mismatches. List gaps and disabled tracks as items to review, not automatic mistakes.
```
