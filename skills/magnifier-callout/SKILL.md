---
name: magnifier-callout
description: Create broadcast-quality floating rounded-rectangle/circular magnifier callouts and background blur focus effects for screen recordings and video clips, seamlessly integrated with DaVinci Resolve timelines.
---

# Magnifier & Spotlight Callout Skill

This skill defines the standard procedure for creating high-precision, visually stunning floating magnifier callouts and background blur effects on screen recordings and video clips in DaVinci Resolve.

---

## 1. Core Architecture: The Headless Subpixel Compositor Roundtrip

Rather than relying on locked DaVinci Resolve Free Fusion node graphs (which often lack input binding and render black screens), this skill uses an external subpixel Lanczos rendering pipeline that roundtrips directly back onto the Resolve timeline.

```
+--------------------------+
| Live Timeline Inspection |  --> timeline_overview (fetches left_offset, duration, record_frame)
+--------------------------+
             |
             v
+--------------------------+
| Feature Coordinate Bounding| --> Detects element width & height in 1080p/4K coordinates
+--------------------------+
             |
             v
+--------------------------+
| Subpixel Lanczos Render  |  --> Renders Gaussian background blur + floating rounded glass box
+--------------------------+
             |
             v
+--------------------------+
| Sample-Accurate Injection|  --> import_media + append_media (0ms gap, 0ms flicker, 0 overlap)
+--------------------------+
```

---

## 2. Mathematical Equations & Design Rules

### A. Easing Curve (Quintic Smootherstep)
For all box expansions, opacity fades, and background blur ramps:
$$E(t) = 6t^5 - 15t^4 + 10t^3 \quad \text{for } t \in [0, 1]$$
This guarantees $C^2$-continuity (zero jerk, zero sudden stops).

### B. Element Bounding & Zero-Cutoff Math
To prevent clipping the left/right edges of search bars or buttons:
1. Measure feature bounding box: `feature_w`, `feature_h`, `feature_cx`, `feature_cy`.
2. Add comfortable margin padding: `crop_w = feature_w + 2 * padding` (typically $120\text{px}$ to $160\text{px}$).
3. Calculate zoom factor based on desired card width:
   $$\text{zoom\_factor} = \frac{\text{box\_w}}{\text{crop\_w}}$$
   $$\text{crop\_h} = \frac{\text{box\_h}}{\text{zoom\_factor}}$$
4. Set crop bounds:
   $$X_1 = \max(0, \text{search\_cx} - \text{crop\_w} / 2), \quad X_2 = \min(\text{width}, \text{search\_cx} + \text{crop\_w} / 2)$$
   $$Y_1 = \max(0, \text{search\_cy} - \text{crop\_h} / 2), \quad Y_2 = \min(\text{height}, \text{search\_cy} + \text{crop\_h} / 2)$$

---

## 3. Standard Visual Specifications

| Parameter | Recommended Value (1080p) | 4K Equivalent |
| :--- | :--- | :--- |
| **Card Dimensions (`box_w` $\times$ `box_h`)** | $1680\text{px} \times 320\text{px}$ | $3360\text{px} \times 640\text{px}$ |
| **Corner Radius** | $28\text{px} – 32\text{px}$ | $56\text{px} – 64\text{px}$ |
| **Border** | $2.5\text{px} – 3.0\text{px}$ Soft Frosted Glow (`#FFFFFFE6`) | $5.0\text{px} – 6.0\text{px}$ |
| **Drop Shadow** | Blur $\sigma = 60\text{px}$, Opacity $75\%$, Offset $+12\text{px}$ $Y$ | Blur $\sigma = 120\text{px}$, Opacity $75\%$, Offset $+24\text{px}$ $Y$ |
| **Background Blur** | Gaussian Blur $\sigma = 45\text{px}$, Dimming $30\%$ | Gaussian Blur $\sigma = 90\text{px}$, Dimming $30\%$ |
| **Spring Scale** | $0.90\times \rightarrow 1.0\times$ over $12\text{ frames}$ ($0.5\text{s}$) | $0.90\times \rightarrow 1.0\times$ over $12\text{ frames}$ |

---

## 4. Timeline Replacement Protocol

1. `import_media(paths=[out_video])`
2. `delete_clips(item_ids=[old_item_id], user_approved=True)`
3. `append_media(paths=[out_video], record_frame=record_frame, track_index=target_track)`
4. `set_playhead(timecode="01:00:00:00")`
