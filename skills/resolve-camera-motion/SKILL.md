---
name: resolve-camera-motion
description: Create smooth camera motions, zoom punch-ins, pull-outs, and multi-keyframe paths in DaVinci Resolve using 14 standard easing curves and AI presets.
---

# Resolve Camera Motion & Zoom Keyframing

Use this skill whenever a request involves zooming, camera movement, punch-ins, pull-outs, framing adjustments, or multi-stage camera keyframing on timeline clips in DaVinci Resolve (Free and Studio).

---

## 1. Core Tool: `animate_zoom`

The `animate_zoom` tool builds native Fusion transform splines directly on the timeline clip. It supports single-range zooms, automated AI presets, and multi-waypoint keyframe arrays.

### A. Single Range Zooms
```python
# Punch in on clip V1.1 from 1.0x to 1.40x with cubic ease-out
animate_zoom(
    item_id="V1.1",
    start_zoom=1.0,
    end_zoom=1.40,
    easing="cubic_out",
    start_frame=0,
    end_frame=24
)

# Pull out / Zoom out from 1.50x close-up to 1.0x full view
animate_zoom(
    item_id="V1.1",
    direction="out",
    start_zoom=1.50,
    end_zoom=1.0,
    easing="cubic_out"
)
```

### B. Multi-Keyframe Waypoint Paths (`keyframes`)
To create complex multi-stage camera sequences (e.g. fast punch-in to a search bar -> hold close-up while typing -> gradual slow ease-in zoom out on page load):

```python
animate_zoom(
    item_id="V1.1",
    keyframes=[
        {"frame": 0, "zoom": 1.0, "center_x": 0.50, "center_y": 0.50},
        {"frame": 16, "zoom": 2.40, "center_x": 0.50, "center_y": -0.65, "easing": "cubic_out"},
        {"frame": 88, "zoom": 2.42, "center_x": 0.50, "center_y": -0.65, "easing": "linear"},
        {"frame": 208, "zoom": 0.55, "center_x": 0.50, "center_y": 0.50, "easing": "cubic_in"}
    ]
)
```

---

## 2. 14 Supported Easing Curves

| Preset Name | `easing` Parameter | Motion Profile & Best Use Case |
| :--- | :--- | :--- |
| **Linear** | `"linear"` | Constant speed throughout. Subtle slow documentary push. |
| **Ease In / Quad In** | `"ease_in"`, `"quad_in"` | Slow start, accelerates forward. Good for building anticipation. |
| **Cubic In** | `"cubic_in"` | Dramatic slow start that ramps up into a cut or transition. |
| **Ease Out / Quad Out** | `"ease_out"`, `"quad_out"` | Fast start with smooth deceleration to a gentle stop. |
| **Cubic Out** | `"cubic_out"` | Snappy, punchy zoom with a smooth landing. Best for punch-ins. |
| **Ease / Quad Ease** | `"ease"`, `"quad_ease"` | Balanced S-curve acceleration and deceleration. |
| **Cubic Ease** | `"cubic_ease"` | Broadcast cinematic glide with zero hard starts or stops. |
| **Circular Ease** | `"circular_ease"` | Circular arc acceleration and deceleration. |
| **Rebound In** | `"rebound_in"` | Pulls backward slightly before launching forward into the zoom. |
| **Rebound Out** | `"rebound_out"` | Overshoots the zoom target slightly and snaps back into place. |
| **Rebound Ease** | `"rebound_ease"` | Rebound on both start and finish. |
| **Elastic Out** | `"elastic_out"` | Springy bounce that settles onto the target. |
| **Step / None** | `"none"` | Instant jump cut to the zoom level. |

---

## 3. Automated AI Scenario Presets

Pass `preset` to automatically configure zoom levels and curve profiles:
- **`preset="punch_in"`**: Fast 1.0x -> 1.35x punch with `cubic_out`.
- **`preset="pop_in"`**: 1.0x -> 1.38x with `rebound_out` overshoot pop.
- **`preset="slow_push"`**: Subtle 1.0x -> 1.15x push with `linear`.
- **`preset="dramatic"`**: 1.0x -> 1.60x tension builder with `cubic_in`.
- **`preset="reveal"`**: 1.40x -> 1.0x pull-out with `cubic_out`.
- **`preset="cinematic"`**: 1.0x -> 1.25x continuous glide with `cubic_ease`.

---

## 4. Viewport Coordinate Calibration in Fusion

In Fusion's `Transform` node:
- **Center X (`0.50`)**: Horizontal center.
- **Center Y (`0.50`)**: Vertical center.
- **Focusing on Top Elements (e.g. Search Bars, Navigation)**:
  - When zooming in 2.0x - 2.5x, set `center_y = -0.60` to `-0.70` to bring the top toolbar/search bar down into the center of the frame.
- **Zoom-Out Scale**: Setting `zoom < 1.0` (e.g. `0.55x` or `0.60x`) creates a centered floating card with clean black canvas borders all around it.
