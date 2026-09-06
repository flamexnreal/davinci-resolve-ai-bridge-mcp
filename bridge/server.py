"""MCP server for Resolve AI Bridge.

Talks to DaVinci Resolve over whichever transport is available: a direct attach
that needs nothing started inside Resolve, or the authenticated Console queue.
See ``bridge/transport.py``.

Never print to stdout from this process. MCP uses stdout for JSON-RPC.
"""

import json
import base64
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

from bridge import client, transport
from bridge.operations import AGENT_VERSION

# Ensure local runtime folders and token exist immediately
client._ensure_dirs()
client._token()


mcp = FastMCP(
    "Resolve AI Bridge",
    instructions=(
        "Inspect before editing. Call resolve_status, then timeline_overview. "
        "Prefer stable unique item ids from timeline_overview; V1.2 labels change after edits. Or pass item_id='playhead'. "
        "Use preview_timeline before a batch of edits, retaining the original. Verify after each change. Use add_image for stills and set_clip_transform "
        "to position them, animate_zoom for a scale that moves over time, "
        "split_clip to cut a clip in two, create_compound_clip to group clips into "
        "a compound container, and change_clip_speed for slow motion or speed changes. "
        "Never delete clips or start a render without explicit user approval."
    ),
)

try:  # Report our own version in the MCP handshake instead of the SDK's.
    mcp._mcp_server.version = AGENT_VERSION
except Exception:  # A future SDK may rename this; the handshake still works.
    pass


def _result(operation: str, params: Optional[dict[str, Any]] = None, timeout: float = 30.0) -> str:
    try:
        payload, used = transport.call(operation, params or {}, timeout=timeout)
        return json.dumps({"ok": True, "transport": used, "result": payload}, ensure_ascii=True, indent=2)
    except client.BridgeOffline as exc:
        return json.dumps(
            {"ok": False, "error": str(exc), "help": transport.offline_help()},
            ensure_ascii=True,
            indent=2,
        )
    except client.BridgeError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True, indent=2)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)},
            ensure_ascii=True,
            indent=2,
        )


# --------------------------------------------------------------- inspection


@mcp.tool()
def resolve_status() -> str:
    """Check how the bridge is connected, plus the Resolve version, open project, and timeline. Always call this first."""
    report = {"bridge_version": AGENT_VERSION, "connection": transport.describe()}
    try:
        payload, used = transport.call("status", {}, timeout=15.0)
        report.update({"ok": True, "transport": used, "result": payload})
    except Exception as exc:
        report.update({"ok": False, "error": str(exc), "help": transport.offline_help()})
    return json.dumps(report, ensure_ascii=True, indent=2)


@mcp.tool()
def project_info() -> str:
    """Return the current project's name, timeline, frame rate, resolution, and timeline count."""
    return _result("project_info")


@mcp.tool()
def list_timelines() -> str:
    """List every timeline in the open project and identify the current one."""
    return _result("list_timelines")


@mcp.tool()
def timeline_overview(max_items: int = 500) -> str:
    """Inspect stable unique clip IDs, positional labels, tracks, frame ranges and markers. Call before and after edits."""
    return _result("timeline_overview", {"max_items": max_items})


@mcp.tool()
def timeline_frame(
    timecode: Optional[str] = None,
    frame: Optional[int] = None,
    max_width: int = 1280,
    format: str = "jpg",
    mode: str = "auto",
) -> list[TextContent | ImageContent]:
    """Return a native MCP image of the requested absolute timeline frame or timecode.

    Auto attempts a composited still, then Free-compatible ffmpeg source extraction.
    Source fallback excludes timeline transforms, grades, Fusion and overlays.
    mode='composite' fails explicitly when a true timeline still is unavailable.
    """
    payload = json.loads(_result("timeline_frame", {"timecode": timecode, "frame": frame,
                          "max_width": max_width, "format": format, "mode": mode}, timeout=100))
    if not payload.get("ok"):
        return [TextContent(type="text", text=json.dumps(payload))]
    result = payload["result"]
    data = result.pop("image_base64", None)
    try:
        if not data:
            raise ValueError("empty image")
        base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": "Bridge returned invalid image data."}))]
    mime = "image/png" if result.get("format") == "png" else "image/jpeg"
    return [TextContent(type="text", text=json.dumps(payload)), ImageContent(type="image", data=data, mimeType=mime)]


@mcp.tool()
def timeline_audio(
    action: str = "analyze",
    track_index: int = 1,
    item_id: Optional[str] = None,
    silence_threshold_db: float = -40.0,
    min_silence_duration: float = 0.3,
    max_duration_seconds: float = 300,
    whole_clip: bool = False,
    lead_offset_ms: float = 160,
    threshold_db: float = -34,
) -> str:
    """Analyze selected source PCM, excluding Fairlight gain, fades, mute and the timeline mix.

    Actions: analyze (per-channel peak/RMS), silence_cuts, energy_envelope,
    export_slice, onsets, vad_clusters. Defaults to the range from playhead to clip end;
    whole_clip starts at the clip in-point. Decode is capped at max_duration_seconds.
    Cut end frames are exclusive; timeline_* fields use absolute timeline coordinates.
    Known retiming is rejected rather than guessed. Needs ffmpeg or macOS afconvert.
    """
    return _result("timeline_audio", {"action": action, "track_index": track_index, "item_id": item_id,
                   "silence_threshold_db": silence_threshold_db, "min_silence_duration": min_silence_duration,
                   "max_duration_seconds": max_duration_seconds, "whole_clip": whole_clip,
                   "lead_offset_ms": lead_offset_ms, "threshold_db": threshold_db}, timeout=120)


@mcp.tool()
def list_media(limit: int = 1000) -> str:
    """List media pool items recursively with unique ids, bin paths, file paths, frame counts, and durations."""
    return _result("list_media", {"limit": limit})


@mcp.tool()
def list_render_presets() -> str:
    """List the render presets and formats available in this project, for use with render_current_timeline."""
    return _result("list_render_presets")


@mcp.tool()
def preview_timeline(name: Optional[str] = None) -> str:
    """Duplicate and open the active timeline for reviewing edits while retaining the original.

    No edits are applied by this call. Get fresh clip IDs with timeline_overview,
    edit the preview, and compare_timelines before accepting it.
    """
    return _result("preview_timeline", {"name": name}, timeout=90)


@mcp.tool()
def compare_timelines(original: str, preview: str) -> str:
    """Compare two timelines by unique ID or exact name without changing the active timeline.

    Reports structural/property/marker changes; does not compare rendered pixels,
    internal Fusion graphs, full grades or Fairlight processing.
    """
    return _result("compare_timelines", {"original": original, "preview": preview})


@mcp.tool()
def project_health(expected_frame_rate: Optional[float] = None, expected_width: Optional[int] = None,
                   expected_height: Optional[int] = None) -> str:
    """Inspect active-timeline missing sources, gaps, disabled/locked tracks and clips.

    Optionally compare timeline resolution/rate against your delivery requirements.
    Gaps and disabled tracks can be intentional; this does not inspect Fairlight automation.
    """
    return _result("project_health", {"expected_frame_rate": expected_frame_rate,
                   "expected_width": expected_width, "expected_height": expected_height})


@mcp.tool()
def bridge_capabilities() -> str:
    """Report Resolve version, transport, API presence and source decoder availability.

    API presence does not guarantee operation success. New review workflows use
    ordinary timeline APIs and work through the Console worker in Resolve Free.
    """
    return _result("bridge_capabilities")


@mcp.tool()
def review_silence(item_id: Optional[str] = None, track_index: int = 1,
                   silence_threshold_db: float = -40, min_silence_duration: float = 0.3,
                   max_duration_seconds: float = 300) -> str:
    """Analyze source audio for a clip and place yellow review markers; never deletes clips.

    Analysis starts at the clip's in-point and excludes Fairlight processing.
    Audition the markers, then pass accepted marker IDs to apply_silence_cuts.
    """
    return _result("review_silence", {"item_id": item_id, "track_index": track_index,
                   "silence_threshold_db": silence_threshold_db, "min_silence_duration": min_silence_duration,
                   "max_duration_seconds": max_duration_seconds}, timeout=120)


@mcp.tool()
def apply_silence_cuts(marker_ids: list[str], name: Optional[str] = None) -> str:
    """Remove USER-ACCEPTED silence intervals on a new duplicate timeline, retaining the original.

    Supports an isolated normal-speed dialogue clip or one aligned video/audio pair.
    Complex timelines, Fusion clips, changed timelines and mixed frame rates are rejected.
    Requires explicit user approval of the selected cuts. Review the resulting preview:
    rebuilding does not guarantee preservation of fades, gain automation or all metadata.
    """
    return _result("apply_silence_cuts", {"marker_ids": marker_ids, "name": name}, timeout=120)


# ---------------------------------------------------------------- navigation


@mcp.tool()
def open_timeline(name: Optional[str] = None, index: Optional[int] = None, timeline_id: Optional[str] = None) -> str:
    """Open a timeline by unique ID, exact name or one-based index from list_timelines."""
    return _result("open_timeline", {"name": name, "index": index, "timeline_id": timeline_id})


@mcp.tool()
def create_timeline(name: str) -> str:
    """Create and open a new empty timeline with an exact name."""
    return _result("create_timeline", {"name": name})


@mcp.tool()
def set_playhead(timecode: str) -> str:
    """Move the current timeline playhead. Use HH:MM:SS:FF matching the timeline frame rate."""
    return _result("set_playhead", {"timecode": timecode})


@mcp.tool()
def open_page(page: str) -> str:
    """Switch the Resolve window to a page so the user can see a change: media, cut, edit, fusion, color, fairlight, or deliver."""
    return _result("open_page", {"page": page})


# --------------------------------------------------------------------- media


@mcp.tool()
def import_media(paths: list[str]) -> str:
    """Import existing local media files by absolute path into the Media Pool. This does not place them on the timeline."""
    return _result("import_media", {"paths": paths}, timeout=90.0)


@mcp.tool()
def append_media(
    media_ids: Optional[list[str]] = None,
    paths: Optional[list[str]] = None,
    track_index: Optional[int] = None,
    record_frame: Optional[int] = None,
    create_track: bool = True,
) -> str:
    """Append video or audio to the timeline from media pool ids or absolute file paths.

    Omit track_index and record_frame to append at the end of the timeline. For still
    images use add_image instead, which controls how long the still lasts.
    """
    return _result(
        "append_media",
        {
            "media_ids": media_ids or [],
            "paths": paths or [],
            "track_index": track_index,
            "record_frame": record_frame,
            "create_track": create_track,
        },
        timeout=90.0,
    )


@mcp.tool()
def add_image(
    path: str,
    duration_seconds: float = 5.0,
    duration_frames: Optional[int] = None,
    track_index: int = 1,
    record_frame: Optional[int] = None,
    at_playhead: bool = False,
    create_track: bool = True,
    pan_percent: Optional[float] = None,
    tilt_percent: Optional[float] = None,
    zoom: Optional[float] = None,
    rotation: Optional[float] = None,
    opacity: Optional[float] = None,
) -> str:
    """Put an image on the timeline: import the still, place it with a real duration, and optionally position it.

    This is the tool for logos, screenshots, overlays, title cards, and any generated
    picture. Use track_index=2 or higher to lay the image over existing footage; the
    track is created automatically when missing. Set at_playhead=True to place it at
    the current playhead instead of the end of the track.

    pan_percent and tilt_percent move the image as a percentage of frame width and
    height from centre. zoom is a scale multiplier where 1.0 is the original size.
    opacity runs from 0 to 100. Verify with timeline_overview afterwards, and read the
    returned actual_duration_frames: Resolve can shorten a still.
    """
    return _result(
        "add_image",
        {
            "path": path,
            "duration_seconds": duration_seconds,
            "duration_frames": duration_frames,
            "track_index": track_index,
            "record_frame": record_frame,
            "at_playhead": at_playhead,
            "create_track": create_track,
            "pan_percent": pan_percent,
            "tilt_percent": tilt_percent,
            "zoom": zoom,
            "rotation": rotation,
            "opacity": opacity,
        },
        timeout=90.0,
    )


# ------------------------------------------------------------ timeline edits


@mcp.tool()
def add_track(track_type: str = "video", count: int = 1) -> str:
    """Add one or more empty tracks. track_type is video, audio, or subtitle."""
    return _result("add_track", {"track_type": track_type, "count": count})


@mcp.tool()
def set_track_name(track_index: int, name: str, track_type: str = "video") -> str:
    """Rename one track, for example labelling V2 as Overlays."""
    return _result(
        "set_track_name", {"track_index": track_index, "name": name, "track_type": track_type}
    )


@mcp.tool()
def set_clip_transform(
    item_id: str,
    pan: Optional[float] = None,
    tilt: Optional[float] = None,
    pan_percent: Optional[float] = None,
    tilt_percent: Optional[float] = None,
    zoom: Optional[float] = None,
    zoom_x: Optional[float] = None,
    zoom_y: Optional[float] = None,
    rotation: Optional[float] = None,
    anchor_x: Optional[float] = None,
    anchor_y: Optional[float] = None,
    opacity: Optional[float] = None,
    composite_mode: Optional[str] = None,
    flip_x: Optional[bool] = None,
    flip_y: Optional[bool] = None,
    crop_left: Optional[float] = None,
    crop_right: Optional[float] = None,
    crop_top: Optional[float] = None,
    crop_bottom: Optional[float] = None,
    scaling: Optional[str] = None,
    resize_filter: Optional[str] = None,
    dynamic_zoom_ease: Optional[str] = None,
    retime_process: Optional[str] = None,
    motion_estimation: Optional[str] = None,
    track_index: Optional[int] = None,
) -> str:
    """Position, scale, rotate, fade, crop, or blend one timeline item.

    Use an id such as V2.1 from timeline_overview, or pass item_id="playhead" to
    act on the clip currently under the playhead so you need not look up the id.
    pan and tilt are in pixels from centre; pan_percent and tilt_percent are the
    same move as a percentage of the timeline width and height. zoom sets both
    axes at once, where 1.0 is original size; zoom_x and zoom_y scale one axis.
    opacity runs from 0 to 100. composite_mode accepts names such as normal,
    screen, multiply, add, overlay, or alpha. scaling is crop, fit, fill, or
    stretch. resize_filter, retime_process, and motion_estimation accept the
    Resolve mode names. This sets a static transform; for a scale that animates
    over time use animate_zoom instead.
    """
    return _result(
        "set_clip_transform",
        {
            "item_id": item_id,
            "pan": pan,
            "tilt": tilt,
            "pan_percent": pan_percent,
            "tilt_percent": tilt_percent,
            "zoom": zoom,
            "zoom_x": zoom_x,
            "zoom_y": zoom_y,
            "rotation": rotation,
            "anchor_x": anchor_x,
            "anchor_y": anchor_y,
            "opacity": opacity,
            "composite_mode": composite_mode,
            "flip_x": flip_x,
            "flip_y": flip_y,
            "crop_left": crop_left,
            "crop_right": crop_right,
            "crop_top": crop_top,
            "crop_bottom": crop_bottom,
            "scaling": scaling,
            "resize_filter": resize_filter,
            "dynamic_zoom_ease": dynamic_zoom_ease,
            "retime_process": retime_process,
            "motion_estimation": motion_estimation,
            "track_index": track_index,
        },
    )


@mcp.tool()
def get_clip_transform(item_id: str = "playhead", track_index: Optional[int] = None) -> str:
    """Read the current position, scale, rotation, crop, opacity, and blend mode of one timeline item.

    Pass an id such as V2.1, or leave item_id as "playhead" to read the clip under the playhead.
    """
    return _result("get_clip_transform", {"item_id": item_id, "track_index": track_index})


@mcp.tool()
def split_clip(
    item_id: str = "playhead",
    frame: Optional[int] = None,
    timecode: Optional[str] = None,
    track_index: Optional[int] = None,
) -> str:
    """Split a normal-speed clip at an absolute frame/timecode after creating a timeline checkpoint.

    Keeps static transforms, enabled state, color and current grade layer. Rejects Fusion
    compositions and mixed rates; audio links/fades/metadata are not guaranteed.
    On a failed rebuild, opens the checkpoint and reports the partial attempted timeline.
    Prefer unique IDs from timeline_overview. Verify the resulting halves.
    """
    return _result(
        "split_clip",
        {"item_id": item_id, "frame": frame, "timecode": timecode, "track_index": track_index},
    )


@mcp.tool()
def animate_zoom(
    item_id: str = "playhead",
    start_zoom: Optional[float] = None,
    end_zoom: Optional[float] = None,
    easing: str = "smootherstep",
    direction: str = "in",
    preset: str = "",
    start_frame: int = 0,
    end_frame: Optional[int] = None,
    target_center_x: float = 0.5,
    target_center_y: float = 0.5,
    keyframes: Optional[list[dict[str, Any]]] = None,
    reset: bool = False,
    track_index: Optional[int] = None,
) -> str:
    """Animate a clip's scale and framing over time (smooth zooms, punch-ins, rebounds, pull-outs, multi-keyframe paths).

    Supports full Zoom In and Zoom Out (`direction='out'`), all standard easing curves
    (`linear`, `ease_in`, `cubic_in`, `ease_out`, `cubic_out`, `ease`, `cubic_ease`,
    `circular_ease`, `rebound_in`, `rebound_out`, `elastic_out`), multi-keyframe arrays,
    and automated AI presets (`punch_in`, `pop_in`, `slow_push`, `dramatic`, `reveal`, `cinematic`).
    """
    params: dict[str, Any] = {
        "item_id": item_id,
        "easing": easing,
        "direction": direction,
        "preset": preset,
        "start_frame": start_frame,
        "target_center_x": target_center_x,
        "target_center_y": target_center_y,
        "reset": reset,
    }
    if keyframes is not None:
        params["keyframes"] = keyframes
    if start_zoom is not None:
        params["start_zoom"] = start_zoom
    if end_zoom is not None:
        params["end_zoom"] = end_zoom
    if end_frame is not None:
        params["end_frame"] = end_frame
    if track_index is not None:
        params["track_index"] = track_index
    return _result("animate_zoom", params, timeout=60.0)


@mcp.tool()
def change_clip_speed(
    item_id: Optional[str] = "playhead",
    speed: Optional[float] = None,
    speed_percent: Optional[float] = None,
    slow_down_percent: Optional[float] = None,
    speed_up_percent: Optional[float] = None,
    interpolate_frames: bool = True,
    reverse: bool = False,
    method: str = "fusion",
) -> str:
    """Change constant video speed through a bridge-owned Fusion TimeSpeed node.

    Existing Fusion connections are preserved. Timeline duration and linked audio are unchanged.
    Speed 1 neutralizes only bridge-owned nodes. Reverse is not currently verified.
    Clip-attributes mode changes EVERY use of the source media, relative to its current FPS.

    Args:
        item_id: Target clip id (e.g. 'V1.1', 'playhead', or clip name). Defaults to active clip under playhead.
        speed: Speed multiplier (e.g. 0.75 for 75% speed / 25% slower, 0.5 for half-speed, 2.0 for 2x speed, 1.0 for normal).
        speed_percent: Speed as a percentage (e.g. 75.0 for 75% speed).
        slow_down_percent: Slowdown percentage (e.g. 25.0 to slow down by 25% -> 0.75x speed).
        speed_up_percent: Speedup percentage (e.g. 50.0 to speed up by 50% -> 1.5x speed).
        interpolate_frames: Whether to enable smooth frame interpolation/blending (default True).
        reverse: Must be False; use Resolve manually for reverse playback.
        method: Implementation method: 'fusion' (native TimeSpeed node, default) or 'clip_attributes' (MediaPoolItem FPS).
    """
    return _result(
        "change_clip_speed",
        {
            "item_id": item_id,
            "speed": speed,
            "speed_percent": speed_percent,
            "slow_down_percent": slow_down_percent,
            "speed_up_percent": speed_up_percent,
            "interpolate_frames": interpolate_frames,
            "reverse": reverse,
            "method": method,
        },
    )


@mcp.tool()
def create_compound_clip(
    item_ids: Optional[list[str]] = None,
    item_id: Optional[str] = "playhead",
    name: Optional[str] = None,
    start_timecode: Optional[str] = None,
) -> str:
    """Create a compound clip combining one or more timeline items into a single container clip.

    Args:
        item_ids: List of timeline item ids to combine (e.g. ['V1.1', 'A1.1'] or ['A1.1']). If omitted, item_id is used.
        item_id: Single timeline item id to turn into a compound clip (e.g. 'V1.1' or 'playhead'). Defaults to 'playhead'.
        name: Name for the newly created compound clip (e.g. 'Voice Compound Clip').
        start_timecode: Optional custom starting timecode for the compound clip container.
    """
    return _result(
        "create_compound_clip",
        {
            "item_ids": item_ids,
            "item_id": item_id,
            "name": name,
            "start_timecode": start_timecode,
        },
    )


@mcp.tool()
def insert_title(
    title_name: str = "Text+",
    text: Optional[str] = None,
    opacity: Optional[float] = None,
) -> str:
    """Insert a title at the playhead on the current video track, best effort.

    Available title names depend on the Resolve version and installed templates;
    Text+ and Text are the common ones. Setting the text through scripting is not
    supported on every build, so check text_set in the result and tell the user to
    type it in the Inspector if it is false. For designed animated typography,
    Remotion produces a better result.
    """
    return _result("insert_title", {"title_name": title_name, "text": text, "opacity": opacity})


@mcp.tool()
def add_marker(
    name: str,
    note: str = "",
    color: str = "Blue",
    frame: Optional[int] = None,
    duration: int = 1,
) -> str:
    """Add a timeline marker. Omit frame to use the current playhead; frame values are relative to timeline start."""
    return _result(
        "add_marker",
        {"name": name, "note": note, "color": color, "frame": frame, "duration": duration},
    )


@mcp.tool()
def delete_marker(frame: int) -> str:
    """Delete the timeline marker at a frame relative to timeline start."""
    return _result("delete_marker", {"frame": frame})


@mcp.tool()
def set_clip_property(item_id: str, property_name: str, value: Any) -> str:
    """Set any documented Resolve timeline item property directly. Prefer set_clip_transform for common changes."""
    return _result(
        "set_clip_property",
        {"item_id": item_id, "property_name": property_name, "value": value},
    )


@mcp.tool()
def set_clip_enabled(item_id: str, enabled: bool) -> str:
    """Enable or disable one timeline item without deleting it."""
    return _result("set_clip_enabled", {"item_id": item_id, "enabled": enabled})


@mcp.tool()
def set_clip_color(item_id: str, color: str = "") -> str:
    """Set a standard Resolve clip color, or pass an empty string to clear it."""
    return _result("set_clip_color", {"item_id": item_id, "color": color})


@mcp.tool()
def get_clip_grade(item_id: str) -> str:
    """Inspect color grading nodes, versions, and Fusion compositions on a clip."""
    return _result("get_clip_grade", {"item_id": item_id})


@mcp.tool()
def set_clip_grade(
    item_id: str,
    saturation: Optional[float] = None,
    slope: str = "1.0 1.0 1.0",
    offset: str = "0.0 0.0 0.0",
    power: str = "1.0 1.0 1.0",
    node_index: int = 1,
    reset: bool = False,
) -> str:
    """Apply ASC-CDL color grading (saturation, slope/gain, offset/lift, power/gamma) to a clip. Pass saturation=0.0 for black & white."""
    return _result(
        "set_clip_grade",
        {
            "item_id": item_id,
            "saturation": saturation,
            "slope": slope,
            "offset": offset,
            "power": power,
            "node_index": node_index,
            "reset": reset,
        },
    )


@mcp.tool()
def keyframe_clip_saturation(
    item_id: str,
    start_saturation: float = 1.0,
    end_saturation: float = 0.0,
    start_frame: int = 0,
    end_frame: Optional[int] = None,
) -> str:
    """Animate a gradual color transition (e.g. from 1.0 full color to 0.0 black and white) across frames via Fusion BezierSpline on the clip."""
    params: dict[str, Any] = {
        "item_id": item_id,
        "start_saturation": start_saturation,
        "end_saturation": end_saturation,
        "start_frame": start_frame,
    }
    if end_frame is not None:
        params["end_frame"] = end_frame
    return _result("keyframe_clip_saturation", params)


@mcp.tool()
def animate_color_fx(
    item_id: str,
    rainbow: bool = True,
    rainbow_cycles: float = 1.5,
    tint_strength: float = 0.70,
    flicker: bool = True,
    flicker_amplitude: float = 0.05,
    flicker_frequency: float = 2.2,
    saturation: float = 1.3,
    start_frame: int = 0,
    end_frame: Optional[int] = None,
) -> str:
    """Animate dynamic color effects (rainbow hue rotation and subtle organic luminance flicker) over time via Fusion on a clip."""
    params: dict[str, Any] = {
        "item_id": item_id,
        "rainbow": rainbow_cycles if rainbow else 0.0,
        "tint_strength": tint_strength,
        "flicker": flicker_amplitude if flicker else 0.0,
        "flicker_frequency": flicker_frequency,
        "saturation": saturation,
        "start_frame": start_frame,
    }
    if end_frame is not None:
        params["end_frame"] = end_frame
    return _result("animate_color_fx", params)


@mcp.tool()
def apply_blur_effect(
    item_id: str = "playhead",
    blur_type: str = "gaussian",
    blur_size: float = 20.0,
    center_x: float = 0.50,
    center_y: float = 0.50,
    width: float = 1.0,
    height: float = 1.0,
    corner_radius: float = 0.0,
    soft_edge: float = 0.015,
    mask_shape: str = "rectangle",
    mask_name: str = "1",
    animate: bool = False,
    start_blur: float = 0.0,
    end_blur: float = 30.0,
    start_frame: int = 0,
    end_frame: Optional[int] = None,
    easing: str = "smootherstep",
    reset: bool = False,
    track_index: Optional[int] = None,
) -> str:
    """Apply a static or dynamic (gradual) blur effect to a full frame or masked bounding region on a timeline clip."""
    params: dict[str, Any] = {
        "item_id": item_id,
        "blur_type": blur_type,
        "blur_size": blur_size,
        "center_x": center_x,
        "center_y": center_y,
        "width": width,
        "height": height,
        "corner_radius": corner_radius,
        "soft_edge": soft_edge,
        "mask_shape": mask_shape,
        "mask_name": mask_name,
        "animate": animate,
        "start_blur": start_blur,
        "end_blur": end_blur,
        "start_frame": start_frame,
        "easing": easing,
        "reset": reset,
    }
    if end_frame is not None:
        params["end_frame"] = end_frame
    if track_index is not None:
        params["track_index"] = track_index
    return _result("apply_blur_effect", params)


@mcp.tool()
def apply_spotlight_mask(
    item_id: str = "playhead",
    center_x: float = 0.50,
    center_y: float = 0.50,
    radius: float = 0.20,
    width: Optional[float] = None,
    height: Optional[float] = None,
    soft_edge: float = 0.08,
    ambient_brightness: float = 0.08,
    spotlight_gain: float = 1.0,
    shape: str = "ellipse",
    mask_name: str = "1",
    keyframes: Optional[list[dict[str, Any]]] = None,
    animate: bool = False,
    expand: bool = False,
    start_radius: float = 0.20,
    end_radius: float = 2.0,
    start_frame: int = 0,
    end_frame: Optional[int] = None,
    easing: str = "cubic_out",
    reset: bool = False,
    track_index: Optional[int] = None,
) -> str:
    """Apply a dynamic or static spotlight reveal mask with adjustable feathering, ambient darkness, and animated sweep keyframes."""
    params: dict[str, Any] = {
        "item_id": item_id,
        "center_x": center_x,
        "center_y": center_y,
        "radius": radius,
        "soft_edge": soft_edge,
        "ambient_brightness": ambient_brightness,
        "spotlight_gain": spotlight_gain,
        "shape": shape,
        "mask_name": mask_name,
        "animate": animate,
        "expand": expand,
        "start_radius": start_radius,
        "end_radius": end_radius,
        "start_frame": start_frame,
        "easing": easing,
        "reset": reset,
    }
    if width is not None:
        params["width"] = width
    if height is not None:
        params["height"] = height
    if keyframes is not None:
        params["keyframes"] = keyframes
    if end_frame is not None:
        params["end_frame"] = end_frame
    if track_index is not None:
        params["track_index"] = track_index
    return _result("apply_spotlight_mask", params)


@mcp.tool()
def delete_clips(item_ids: list[str], ripple: bool = False, user_approved: bool = False) -> str:
    """Delete timeline items. Refuses unless the user explicitly approved this destructive action in the current conversation."""
    if not user_approved:
        return json.dumps(
            {
                "ok": False,
                "error": "Deletion requires explicit user approval. Ask first, then retry with user_approved=true.",
            },
            indent=2,
        )
    return _result("delete_clips", {"item_ids": item_ids, "ripple": ripple})


# ------------------------------------------------------------------ delivery


@mcp.tool()
def save_project() -> str:
    """Save the current Resolve project."""
    return _result("save_project")


@mcp.tool()
def render_current_timeline(
    output_dir: str,
    name: str = "",
    preset: str = "",
    start: bool = False,
    user_approved: bool = False,
) -> str:
    """Add a render job for the current timeline. Starting the render requires explicit user approval."""
    if start and not user_approved:
        return json.dumps(
            {
                "ok": False,
                "error": "Starting a render requires explicit user approval. Ask first, then retry with user_approved=true.",
            },
            indent=2,
        )
    return _result(
        "render_current_timeline",
        {"output_dir": output_dir, "name": name, "preset": preset, "start": start},
        timeout=180.0,
    )


@mcp.resource("resolve://guide")
def editing_guide() -> str:
    """Workflow and safety guide for editing with Resolve AI Bridge."""
    return """# Resolve AI Bridge editing guide

1. Call `resolve_status`. It reports which transport is live. Stop if no project or
   timeline is open, and pass the `help` text on to the user rather than guessing.
2. Call `timeline_overview` and refer to clips by ids such as `V1.2`, never by an
   ambiguous name.
3. Explain the edit plan and assumptions before changing anything.
4. Make one small change at a time and inspect again after each change.
5. Ask before deleting clips, using ripple delete, or starting a render.
6. Images: use `add_image`. Put overlays on `track_index` 2 or higher so footage on V1
   stays visible, then position with `set_clip_transform` or the pan/tilt/zoom
   arguments of `add_image`. Always check `actual_duration_frames` in the result,
   because Resolve can shorten a still to its default length.
7. Scale and reframe clips already on the timeline with `set_clip_transform` (a static
   size) or `animate_zoom` (a size that changes over time, built as a Fusion
   composition). Cut a clip in two with `split_clip`. All three accept
   `item_id="playhead"` to act on the clip under the playhead, so you need not look up
   the id first. `split_clip` rebuilds the clip and does not copy color grades or
   Fusion comps onto the halves; `animate_zoom` reports `keyframes_created` and falls
   back to a static zoom on builds that will not keyframe from scripting.
8. `insert_title` is best effort. If `text_set` is false, say so and ask the user to
   type the text in the Inspector.
9. Group multi-layer or related clips into a clean single block using `create_compound_clip`.
   Slow down or speed up playback using `change_clip_speed`.
10. Timeline item frames are absolute Resolve timeline frames unless a tool says
   otherwise. Marker frames are relative to the timeline start.
11. Prefer Remotion for designed motion graphics and animated typography. Render a
    clip, import it, then ask where to place it.
12. Resolve's public scripting API cannot perform every interactive Edit page action.
    If a tool is absent, explain the limitation instead of pretending it worked.
"""


@mcp.prompt(name="edit_video")
def edit_video_prompt(goal: str) -> str:
    """Create a cautious, verifiable Resolve editing workflow for a user goal."""
    return (
        "Goal: %s\n\n"
        "First call resolve_status and timeline_overview. Summarize the current timeline, then "
        "propose a short plan. Wait if the goal is ambiguous. Apply small edits, verify each "
        "result with a fresh timeline_overview, and request approval before deletion or rendering."
        % goal
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
