---
name: youtube-video-inspector
description: Inspect, analyze, extract visual frames, examine motion graphics, typography, audio waveforms, and recreate video effects from YouTube URLs using fast headless download and frame sampling protocols.
---

# YouTube Video Inspector & Recreation Skill

This skill defines the standard procedure for inspecting, extracting, and visually analyzing YouTube videos when given a URL (with or without timestamps) to recreate typography, animations, transitions, or visual styles.

---

## 1. Core Rule: Never Claim Inability to View YouTube Videos

When the user provides a YouTube URL (e.g. `https://www.youtube.com/watch?v=...` or `https://youtu.be/...`):
- **NEVER** reply that you cannot view YouTube videos.
- **ALWAYS** use the headless extraction protocol below to download the relevant video format, extract video frames around the requested timecode, and visually inspect the frames via `view_file`.

---

## 2. Fast Headless Video Extraction Protocol

### Step A: Ensure `yt-dlp` is Available
If `yt-dlp` is not installed, install it in Python environment:
```bash
python3 -m pip install yt-dlp
```

### Step B: Download Small Single-Stream Video (No FFmpeg Merging Required)
To download in $< 3$ seconds without requiring external merging tools:
* Request format `134` (640x360 MP4 video-only) or format `18` (360p pre-muxed MP4):
```bash
python3 -m yt_dlp -f 134 "<YOUTUBE_URL>" -o "/Users/eram/.gemini/antigravity/scratch/ref_video_360p.mp4"
```
*(If format 134 is unavailable, list formats via `python3 -m yt_dlp -F "<URL>"` and pick the smallest direct mp4 format `160`, `133`, `134`, or `18`).*

---

## 3. Frame Sampling & Visual Analysis

### Step A: Extract Frames Around Timestamp
Given timestamp $t$ (in seconds, e.g. `t = 201s`):
```python
import cv2, numpy as np

video_path = '/Users/eram/.gemini/antigravity/scratch/ref_video_360p.mp4'
cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

target_sec = 201.0 # From URL &t=201s or user prompt
offsets = [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0]

thumbs = []
for offset in offsets:
    f_idx = int((target_sec + offset) * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if ret:
        thumbs.append(cv2.resize(frame, (640, 360)))
cap.release()

# Build 6-frame comparison grid
row1 = np.hstack([thumbs[0], thumbs[1], thumbs[2]])
row2 = np.hstack([thumbs[3], thumbs[4], thumbs[5]])
grid = np.vstack([row1, row2])
cv2.imwrite('/Users/eram/.gemini/antigravity/scratch/youtube_ref_grid.jpg', grid)
```

### Step B: Inspect with `view_file`
Call `view_file` on `youtube_ref_grid.jpg` to inspect:
1. **Typography**: Font family, weight, tracking, case, color hierarchy, and accent elements (arrows, icons).
2. **Layout & Positioning**: Horizontal alignment, scale ratios (e.g. $2.5\times$ impact words vs base text).
3. **Motion Dynamics**: Slide direction, S-curve smootherstep pacing, spring overshoot bounce ($1.15\times - 1.25\times$), and impact slam cushioning.

---

## 4. Recreating the Effect

1. **Synthesize & Render**:
   - Use Python PIL / OpenCV or Remotion to render the composition with exact font sizing, spring easing curves, and color palette.
2. **Verify Against Reference**:
   - Generate a 6-frame preview grid of the recreation and call `view_file` to confirm 1-to-1 visual parity with the YouTube reference grid.
3. **Inject onto Resolve Timeline**:
   - Import into DaVinci Resolve Media Pool via `import_media` and place onto the timeline via `append_media`.
