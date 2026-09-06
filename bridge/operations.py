"""Resolve operation implementations shared by every transport.

This module is imported in two very different places:

* inside DaVinci Resolve, by ``ResolveConsole.py`` running in the Py3 Console
  or from the Workspace > Scripts menu
* outside DaVinci Resolve, by ``bridge/direct.py`` when the MCP server attaches
  to Resolve itself

Because of that it must stay dependent on the standard library only. Never
import ``mcp``, ``fusionscript``, or anything from ``bridge.server`` here.
"""

import json
import math
import os
import time
import uuid
from pathlib import Path


AGENT_VERSION = "1.11.0"
PROTOCOL_VERSION = 2

IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp",
    ".exr", ".dpx", ".tga", ".psd", ".heic", ".heif", ".jp2", ".cin",
}

# Names accepted by set_clip_transform for "composite_mode", mapped to the
# integer constants documented in Resolve's scripting README.
COMPOSITE_MODES = {
    "normal": 0, "add": 1, "subtract": 2, "diff": 3, "difference": 3,
    "multiply": 4, "screen": 5, "overlay": 6, "hardlight": 7, "hard_light": 7,
    "softlight": 8, "soft_light": 8, "darken": 9, "lighten": 10,
    "color_dodge": 11, "colordodge": 11, "color_burn": 12, "colorburn": 12,
    "exclusion": 13, "hue": 14, "saturate": 15, "colorize": 16,
    "luma_mask": 17, "divide": 18, "linear_dodge": 19, "linear_burn": 20,
    "linear_light": 21, "vivid_light": 22, "pin_light": 23, "hard_mix": 24,
    "lighter_color": 25, "darker_color": 26, "foreground": 27, "alpha": 28,
    "inverted_alpha": 29, "lum": 30, "inverted_lum": 31,
}

# Scalar transform keys exposed by set_clip_transform, mapped to the Resolve
# property key. Values are passed through float().
TRANSFORM_FLOATS = {
    "pan": "Pan",
    "tilt": "Tilt",
    "zoom_x": "ZoomX",
    "zoom_y": "ZoomY",
    "rotation": "RotationAngle",
    "anchor_x": "AnchorPointX",
    "anchor_y": "AnchorPointY",
    "pitch": "Pitch",
    "yaw": "Yaw",
    "crop_left": "CropLeft",
    "crop_right": "CropRight",
    "crop_top": "CropTop",
    "crop_bottom": "CropBottom",
    "crop_softness": "CropSoftness",
    "opacity": "Opacity",
    "distortion": "Distortion",
}

TRANSFORM_BOOLS = {
    "flip_x": "FlipX",
    "flip_y": "FlipY",
    "zoom_gang": "ZoomGang",
    "crop_retain": "CropRetain",
}

# Enum transform keys exposed by set_clip_transform. Each maps friendly names to
# the integer constants documented in Resolve's scripting README (section
# "Looking up Timeline item properties"). Names are matched lowercased with
# spaces turned into underscores.
DYNAMIC_ZOOM_EASE = {
    "linear": 0, "ease_in": 1, "in": 1, "ease_out": 2, "out": 2,
    "ease_in_and_out": 3, "ease_in_out": 3, "in_and_out": 3, "in_out": 3,
}
SCALING_MODES = {
    "use_project": 0, "project": 0, "crop": 1, "fit": 2, "fill": 3, "stretch": 4,
}
RESIZE_FILTERS = {
    "use_project": 0, "project": 0, "sharper": 1, "smoother": 2, "bicubic": 3,
    "bilinear": 4, "bessel": 5, "box": 6, "catmull_rom": 7, "cubic": 8,
    "gaussian": 9, "lanczos": 10, "mitchell": 11, "nearest_neighbor": 12,
    "nearest": 12, "quadratic": 13, "sinc": 14, "linear": 15,
}
RETIME_PROCESS = {
    "use_project": 0, "project": 0, "nearest": 1, "frame_blend": 2,
    "optical_flow": 3,
}
MOTION_ESTIMATION = {
    "use_project": 0, "project": 0, "standard_faster": 1, "standard_better": 2,
    "enhanced_faster": 3, "enhanced_better": 4, "speed_warp_better": 5,
    "speed_warp_faster": 6,
}

# param name -> (Resolve property key, name->int table)
TRANSFORM_ENUMS = {
    "dynamic_zoom_ease": ("DynamicZoomEase", DYNAMIC_ZOOM_EASE),
    "scaling": ("Scaling", SCALING_MODES),
    "resize_filter": ("ResizeFilter", RESIZE_FILTERS),
    "retime_process": ("RetimeProcess", RETIME_PROCESS),
    "motion_estimation": ("MotionEstimation", MOTION_ESTIMATION),
}

READABLE_TRANSFORM_KEYS = (
    "Pan", "Tilt", "ZoomX", "ZoomY", "ZoomGang", "RotationAngle",
    "AnchorPointX", "AnchorPointY", "Pitch", "Yaw", "FlipX", "FlipY",
    "CropLeft", "CropRight", "CropTop", "CropBottom", "CropSoftness",
    "CropRetain", "DynamicZoomEase", "CompositeMode", "Opacity", "Distortion",
    "RetimeProcess", "MotionEstimation", "Scaling", "ResizeFilter",
)

PAGES = ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver")


# Default unknown/new operations to mutations for queue context protection.
QUEUE_READ_ONLY = frozenset({
    "status", "project_info", "list_timelines", "timeline_overview", "list_media",
    "get_clip_transform", "get_clip_grade", "inspect_fusion", "list_render_presets",
    "bridge_capabilities", "project_health", "compare_timelines", "timeline_audio",
})


class OperationError(RuntimeError):
    """A Resolve operation failed for a reason the user or model can act on."""


def call(obj, method, default=None, *args):
    """Call an optional Resolve API method without raising."""
    try:
        function = getattr(obj, method, None)
        return function(*args) if callable(function) else default
    except Exception:
        return default


def plain(value):
    """Convert Resolve's native objects into JSON-safe values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return str(value)


def _absolute(value):
    return str(Path(str(value)).expanduser().resolve())


# Reverse of TRANSFORM_FLOATS/BOOLS: Resolve property key -> set_clip_transform
# param name, used to re-apply a read-back transform onto rebuilt clip halves.
# CompositeMode and the enum modes read back as their integer constant, which
# _apply_transform accepts directly, so they are mapped through too.
_PROP_TO_PARAM = {"CompositeMode": "composite_mode"}
for _pname, _pkey in list(TRANSFORM_FLOATS.items()) + list(TRANSFORM_BOOLS.items()):
    _PROP_TO_PARAM[_pkey] = _pname
for _pname, (_pkey, _table) in TRANSFORM_ENUMS.items():
    _PROP_TO_PARAM[_pkey] = _pname


def transform_params_from_props(props):
    """Turn a {"Pan": .., "ZoomX": ..} read-back into set_clip_transform params."""
    params = {}
    if not isinstance(props, dict):
        return params
    for key, value in props.items():
        name = _PROP_TO_PARAM.get(key)
        if name is not None:
            params[name] = value
    return params


class ResolveOperations:
    """Every bridge operation, implemented against a live Resolve object.

    ``provider`` is a zero-argument callable that returns the Resolve API
    object. It is called on every operation so a transport that can lose its
    connection (direct attach) is able to reconnect transparently.
    """

    def __init__(self, provider, token_id=None, transport="unknown"):
        self._provider = provider
        self.token_id = token_id
        self.transport = transport

    # ------------------------------------------------------------------ core

    @property
    def resolve(self):
        instance = self._provider()
        if instance is None:
            raise OperationError(
                "DaVinci Resolve is not reachable. Open Resolve with a project, then try again."
            )
        return instance

    def _project(self):
        manager = self.resolve.GetProjectManager()
        if manager is None:
            raise OperationError("Resolve did not return a Project Manager.")
        project = manager.GetCurrentProject()
        if project is None:
            raise OperationError("No project is open in Resolve. Open a project and try again.")
        return project

    def _timeline(self):
        timeline = self._project().GetCurrentTimeline()
        if timeline is None:
            raise OperationError("No timeline is open. Open or create a timeline, then try again.")
        return timeline

    def _media_pool(self):
        pool = self._project().GetMediaPool()
        if pool is None:
            raise OperationError("Resolve did not return a Media Pool.")
        return pool

    def _project_rate(self):
        project = self._project()
        timeline = call(project, "GetCurrentTimeline", None)
        raw = call(timeline, "GetSetting", None, "timelineFrameRate")
        raw = raw or call(project, "GetSetting", "24", "timelineFrameRate") or "24"
        try:
            rate = float(str(raw).replace(" DF", "").strip())
            for nominal in (24, 30, 48, 60, 120):
                if abs(rate - nominal / 1.001) < 0.002:
                    return nominal / 1.001
            return rate if math.isfinite(rate) and rate > 0 else 24.0
        except (ValueError, TypeError):
            return 24.0

    def _project_resolution(self):
        project = self._project()
        timeline = call(project, "GetCurrentTimeline", None)
        try:
            width = int(call(timeline, "GetSetting", None, "timelineResolutionWidth") or call(project, "GetSetting", 1920, "timelineResolutionWidth") or 1920)
            height = int(call(timeline, "GetSetting", None, "timelineResolutionHeight") or call(project, "GetSetting", 1080, "timelineResolutionHeight") or 1080)
        except (TypeError, ValueError):
            width, height = 1920, 1080
        return width, height

    def _tc_frames(self, value, fps):
        drop = ";" in str(value)
        parts = str(value).replace(";", ":").split(":")
        if len(parts) != 4:
            raise OperationError("Invalid timecode: %s. Use HH:MM:SS:FF or HH:MM:SS;FF." % value)
        try:
            hours, minutes, seconds, frames = [int(part) for part in parts]
        except ValueError:
            raise OperationError("Invalid timecode: %s." % value)
        rounded = max(1, int(round(fps)))
        if min(hours, minutes, seconds, frames) < 0 or minutes >= 60 or seconds >= 60 or frames >= rounded:
            raise OperationError("Timecode out of range: %s." % value)
        total = ((hours * 3600 + minutes * 60 + seconds) * rounded) + frames
        if drop:
            if rounded not in (30, 60) or abs(fps - rounded / 1.001) > 0.01:
                raise OperationError("Drop-frame timecode requires 29.97 or 59.94 fps.")
            skipped = 2 if rounded == 30 else 4
            if minutes % 10 and seconds == 0 and frames < skipped:
                raise OperationError("Timecode uses a skipped drop-frame label: %s." % value)
            total_minutes = hours * 60 + minutes
            total -= skipped * (total_minutes - total_minutes // 10)
        return total

    def _frames_tc(self, frame, fps, drop=False):
        """Convert a timecode frame count to a valid SMPTE label."""
        frame = int(frame)
        if frame < 0:
            raise OperationError("Timecode cannot be negative.")
        nominal = max(1, int(round(fps)))
        if drop:
            if nominal not in (30, 60) or abs(fps - nominal / 1.001) > 0.01:
                raise OperationError("Drop-frame timecode requires 29.97 or 59.94 fps.")
            skipped = 2 if nominal == 30 else 4
            ten_minutes = nominal * 600 - skipped * 9
            minute = nominal * 60 - skipped
            blocks, remainder = divmod(frame, ten_minutes)
            frame += skipped * 9 * blocks + skipped * max(0, (remainder - skipped) // minute)
        seconds, frames = divmod(frame, nominal)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return "%02d:%02d:%02d%s%02d" % (hours, minutes, seconds, ";" if drop else ":", frames)

    def _current_marker_frame(self, timeline):
        current = call(timeline, "GetCurrentTimecode", "00:00:00:00")
        start = call(timeline, "GetStartTimecode", "00:00:00:00")
        fps = self._project_rate()
        return max(0, self._tc_frames(current, fps) - self._tc_frames(start, fps))

    # -------------------------------------------------------------- lookups

    def _item_summary(self, item, track_type, track_index, item_index):
        prefix = "V" if track_type == "video" else "A" if track_type == "audio" else "S"
        media_item = call(item, "GetMediaPoolItem", None)
        media_id = call(media_item, "GetUniqueId", None) if media_item is not None else None
        unique_id = call(item, "GetUniqueId", None)
        label = "%s%d.%d" % (prefix, track_index, item_index)
        return {
            "id": str(unique_id) if unique_id else label,
            "label": label,
            "unique_id": unique_id,
            "name": call(item, "GetName", ""),
            "track_type": track_type,
            "track_index": track_index,
            "start": call(item, "GetStart", None),
            "end": call(item, "GetEnd", None),
            "duration": call(item, "GetDuration", None),
            "left_offset": call(item, "GetLeftOffset", 0),
            "right_offset": call(item, "GetRightOffset", 0),
            "enabled": call(item, "GetClipEnabled", None),
            "color": call(item, "GetClipColor", ""),
            "media_pool_id": media_id,
        }

    def _timeline_items(self):
        timeline = self._timeline()
        results = []
        for track_type in ("video", "audio", "subtitle"):
            count = int(call(timeline, "GetTrackCount", 0, track_type) or 0)
            for track_index in range(1, count + 1):
                items = call(timeline, "GetItemListInTrack", [], track_type, track_index) or []
                for item_index, item in enumerate(items, 1):
                    results.append(
                        (item, self._item_summary(item, track_type, track_index, item_index))
                    )
        return results

    def _find_timeline_items(self, identifiers):
        wanted = [str(item) for item in identifiers]
        all_items = self._timeline_items()
        found = []
        missing = []
        for identifier in wanted:
            token = identifier.strip().lower()
            if token in ("playhead", "current", "under_playhead", "at_playhead"):
                try:
                    found.append(self._resolve_one_item(identifier))
                    continue
                except Exception:
                    pass
            matches = [
                (item, info)
                for item, info in all_items
                if identifier in (str(info.get("id")), str(info.get("label")), str(info.get("unique_id")), str(info.get("name")))
            ]
            if not matches:
                missing.append(identifier)
                continue
            exact = next(
                (
                    match
                    for match in matches
                    if identifier in (match[1].get("id"), match[1].get("label"), str(match[1].get("unique_id")))
                ),
                None,
            )
            if exact is None and len(matches) > 1:
                raise OperationError(
                    "Clip name '%s' is ambiguous. Use an id such as V1.2 from timeline_overview."
                    % identifier
                )
            found.append(exact or matches[0])
        if missing:
            raise OperationError(
                "Timeline item not found: %s. Call timeline_overview for valid ids."
                % ", ".join(missing)
            )
        return found

    def _playhead_frame(self, timeline):
        """Absolute timeline frame under the playhead (same space as GetStart)."""
        return int(call(timeline, "GetStartFrame", 0) or 0) + self._current_marker_frame(timeline)

    def _resolve_one_item(self, item_id, track_hint=None):
        """Return a single (item, info) pair.

        ``item_id`` may be an explicit id such as V1.2, a unique id, or a clip
        name. It may also be empty or one of "playhead"/"current"/"under_playhead"
        to select the clip sitting under the playhead, so an AI can act on "the
        clip I am looking at" without first reading every id.
        """
        token = str(item_id or "").strip().lower()
        if token and token not in ("playhead", "current", "under_playhead", "at_playhead"):
            return self._find_timeline_items([item_id])[0]

        timeline = self._timeline()
        frame = self._playhead_frame(timeline)
        want_track = None
        want_type = "video"
        if track_hint is not None:
            hint_str = str(track_hint).strip().lower()
            if hint_str in ("audio", "video"):
                want_type = hint_str
            elif hint_str.isdigit():
                want_track = int(hint_str)
            elif isinstance(track_hint, int):
                want_track = int(track_hint)

        best = None
        for item, info in self._timeline_items():
            if want_type and info.get("track_type") != want_type:
                continue
            start = info.get("start")
            end = info.get("end")
            if start is None or end is None:
                continue
            if info.get("enabled") is False or call(timeline, "GetIsTrackEnabled", True, info.get("track_type"), info.get("track_index")) is False:
                continue
            if float(start) <= frame < float(end):
                if want_track is not None and info.get("track_index") != want_track:
                    continue
                # Prefer the highest track (topmost layer) at the playhead.
                if best is None or info.get("track_index", 0) > best[1].get("track_index", 0):
                    best = (item, info)
        if best is None:
            raise OperationError(
                "No %s clip sits under the playhead (timeline frame %d). Move the playhead "
                "onto a clip, or pass an explicit item_id from timeline_overview." % (want_type or "timeline", frame)
            )
        return best

    def _item_id_after_rebuild(self, timeline, created_item):
        """Unique ID (positional label only on older builds) after rebuilding."""
        unique = call(created_item, "GetUniqueId", None)
        for item, info in self._timeline_items():
            if (unique is not None and str(info.get("unique_id")) == str(unique)) or item == created_item:
                return info.get("id")
        return unique

    def _walk_media(self, folder, prefix="", limit=2000):
        output = []
        folder_name = call(folder, "GetName", "Media Pool")
        location = (prefix + "/" + folder_name).strip("/")
        for clip in call(folder, "GetClipList", []) or []:
            props = call(clip, "GetClipProperty", {}) or {}
            output.append({
                "id": call(clip, "GetUniqueId", None),
                "name": call(clip, "GetName", props.get("Clip Name", "")),
                "bin": location,
                "file_path": props.get("File Path"),
                "duration": props.get("Duration"),
                "frames": props.get("Frames"),
                "resolution": props.get("Resolution"),
                "type": props.get("Type"),
            })
            if len(output) >= limit:
                return output
        for child in call(folder, "GetSubFolderList", []) or []:
            remaining = max(0, limit - len(output))
            if not remaining:
                break
            output.extend(self._walk_media(child, location, remaining))
        return output

    def _find_media_items(self, identifiers):
        wanted = [str(value) for value in identifiers]
        found = []

        def visit(folder):
            for clip in call(folder, "GetClipList", []) or []:
                if str(call(clip, "GetUniqueId", "")) in wanted or str(call(clip, "GetName", "")) in wanted:
                    found.append(clip)
            for child in call(folder, "GetSubFolderList", []) or []:
                visit(child)

        visit(self._media_pool().GetRootFolder())
        if len(found) < len(wanted):
            raise OperationError(
                "One or more media items were not found. Call list_media and use unique ids."
            )
        return found

    def _ensure_video_track(self, timeline, track_index, allow_create=True):
        """Make sure video track ``track_index`` exists, adding tracks if allowed."""
        if track_index is None:
            return None
        wanted = int(track_index)
        if wanted < 1:
            raise OperationError("track_index must be 1 or greater.")
        count = int(call(timeline, "GetTrackCount", 0, "video") or 0)
        if wanted <= count:
            return wanted
        if not allow_create:
            raise OperationError(
                "Video track V%d does not exist. The timeline has %d video track(s)."
                % (wanted, count)
            )
        for _ in range(wanted - count):
            if not call(timeline, "AddTrack", False, "video"):
                raise OperationError(
                    "Resolve refused to add a video track. The timeline has %d video track(s)."
                    % int(call(timeline, "GetTrackCount", 0, "video") or 0)
                )
        return wanted

    def _apply_transform(self, item, params):
        """Apply the transform subset of ``params`` to one timeline item."""
        applied = {}
        rejected = {}
        width, height = self._project_resolution()

        requests = []
        if params.get("pan_percent") is not None:
            requests.append(("Pan", float(params["pan_percent"]) / 100.0 * width))
        if params.get("tilt_percent") is not None:
            requests.append(("Tilt", float(params["tilt_percent"]) / 100.0 * height))
        zoom = params.get("zoom")
        if zoom is not None:
            requests.append(("ZoomX", float(zoom)))
            requests.append(("ZoomY", float(zoom)))
        for name, key in TRANSFORM_FLOATS.items():
            if params.get(name) is not None:
                requests.append((key, float(params[name])))
        for name, key in TRANSFORM_BOOLS.items():
            if params.get(name) is not None:
                requests.append((key, bool(params[name])))
        mode = params.get("composite_mode")
        if mode is not None:
            if isinstance(mode, str):
                resolved = COMPOSITE_MODES.get(mode.strip().lower().replace(" ", "_"))
                if resolved is None:
                    raise OperationError(
                        "Unknown composite_mode '%s'. Valid names: %s"
                        % (mode, ", ".join(sorted(COMPOSITE_MODES)))
                    )
                requests.append(("CompositeMode", resolved))
            else:
                requests.append(("CompositeMode", int(mode)))

        for name, (key, table) in TRANSFORM_ENUMS.items():
            value = params.get(name)
            if value is None:
                continue
            if isinstance(value, str):
                resolved = table.get(value.strip().lower().replace(" ", "_"))
                if resolved is None:
                    raise OperationError(
                        "Unknown %s '%s'. Valid names: %s"
                        % (name, value, ", ".join(sorted(table)))
                    )
                requests.append((key, resolved))
            else:
                requests.append((key, int(value)))

        for key, value in requests:
            if call(item, "SetProperty", False, key, value):
                applied[key] = value
            else:
                rejected[key] = value
        return applied, rejected

    def _read_transform(self, item):
        values = {}
        snapshot = call(item, "GetProperty", None)
        if isinstance(snapshot, dict):
            for key in READABLE_TRANSFORM_KEYS:
                if key in snapshot:
                    values[key] = plain(snapshot[key])
            if values:
                return values
        for key in READABLE_TRANSFORM_KEYS:
            value = call(item, "GetProperty", None, key)
            if value is not None:
                values[key] = plain(value)
        return values

    def _newest_item_on_track(self, timeline, track_index):
        items = call(timeline, "GetItemListInTrack", [], "video", track_index) or []
        if not items:
            return None, None
        index = len(items)
        return items[-1], self._item_summary(items[-1], "video", track_index, index)

    # ----------------------------------------------------------- operations

    def _op_status(self, _params):
        instance = self._provider()
        manager = instance.GetProjectManager() if instance is not None else None
        project = manager.GetCurrentProject() if manager else None
        timeline = project.GetCurrentTimeline() if project else None
        return {
            "online": instance is not None,
            "transport": self.transport,
            "agent_version": AGENT_VERSION,
            "protocol": PROTOCOL_VERSION,
            "resolve_version": call(instance, "GetVersionString", None),
            "product": call(instance, "GetProductName", None),
            "page": call(instance, "GetCurrentPage", None),
            "project": call(project, "GetName", None) if project else None,
            "timeline": call(timeline, "GetName", None) if timeline else None,
            "token_id": self.token_id,
        }

    def _op_project_info(self, _params):
        project = self._project()
        timeline = project.GetCurrentTimeline()
        width, height = self._project_resolution()
        return {
            "name": project.GetName(),
            "timeline": call(timeline, "GetName", None) if timeline else None,
            "timeline_count": call(project, "GetTimelineCount", 0),
            "frame_rate": self._project_rate(),
            "resolution_width": width,
            "resolution_height": height,
        }

    def _op_list_timelines(self, _params):
        project = self._project()
        current = project.GetCurrentTimeline()
        timelines = []
        for index in range(1, int(project.GetTimelineCount() or 0) + 1):
            item = project.GetTimelineByIndex(index)
            timelines.append({
                "id": call(item, "GetUniqueId", None),
                "index": index,
                "name": call(item, "GetName", ""),
                "current": item == current,
                "start_frame": call(item, "GetStartFrame", None),
                "end_frame": call(item, "GetEndFrame", None),
            })
        return {"timelines": timelines}

    def _op_open_timeline(self, params):
        project = self._project()
        name = params.get("name")
        index = params.get("index")
        timeline_id = params.get("timeline_id")
        selected = None
        for item_index in range(1, int(project.GetTimelineCount() or 0) + 1):
            item = project.GetTimelineByIndex(item_index)
            if (index is not None and int(index) == item_index) or (name and item.GetName() == name) or (timeline_id and call(item, "GetUniqueId", None) == timeline_id):
                selected = item
                break
        if selected is None:
            raise OperationError("Timeline not found. Call list_timelines for valid names and indexes.")
        if not project.SetCurrentTimeline(selected):
            raise OperationError("Resolve refused to open the requested timeline.")
        return {"opened": selected.GetName()}

    def _op_timeline_overview(self, params):
        timeline = self._timeline()
        max_items = max(1, min(int(params.get("max_items", 500) or 500), 2000))
        tracks = []
        clips = []
        for track_type in ("video", "audio", "subtitle"):
            count = int(call(timeline, "GetTrackCount", 0, track_type) or 0)
            for track_index in range(1, count + 1):
                items = call(timeline, "GetItemListInTrack", [], track_type, track_index) or []
                tracks.append({
                    "type": track_type,
                    "index": track_index,
                    "name": call(timeline, "GetTrackName", "", track_type, track_index),
                    "enabled": call(timeline, "GetIsTrackEnabled", None, track_type, track_index),
                    "items": len(items),
                })
                for item_index, item in enumerate(items, 1):
                    if len(clips) < max_items:
                        clips.append(self._item_summary(item, track_type, track_index, item_index))
        return {
            "name": timeline.GetName(),
            "id": call(timeline, "GetUniqueId", None),
            "item_id_note": "id uses Resolve's unique ID when available; label (V1.2) is positional and can change after edits.",
            "start_frame": call(timeline, "GetStartFrame", None),
            "end_frame": call(timeline, "GetEndFrame", None),
            "current_timecode": call(timeline, "GetCurrentTimecode", None),
            "frame_rate": self._project_rate(),
            "tracks": tracks,
            "clips": clips,
            "clips_truncated": sum(track["items"] for track in tracks) > len(clips),
            "markers": plain(call(timeline, "GetMarkers", {}) or {}),
        }

    def _op_list_media(self, params):
        limit = max(1, min(int(params.get("limit", 1000) or 1000), 5000))
        items = self._walk_media(self._media_pool().GetRootFolder(), "", limit)
        return {"items": items, "count": len(items), "limited_to": limit}

    def _op_import_media(self, params):
        paths = [_absolute(value) for value in params.get("paths", [])]
        if not paths:
            raise OperationError("paths must contain at least one absolute media file path.")
        missing = [path for path in paths if not Path(path).exists()]
        if missing:
            raise OperationError("Media file not found: %s" % ", ".join(missing))
        imported = self._media_pool().ImportMedia(paths) or []
        if not imported:
            raise OperationError(
                "Resolve imported none of the requested files. Confirm the format is supported "
                "and that a project is open."
            )
        return {
            "imported": [
                {
                    "id": call(item, "GetUniqueId", None),
                    "name": call(item, "GetName", ""),
                    "frames": (call(item, "GetClipProperty", {}) or {}).get("Frames"),
                }
                for item in imported
            ],
            "requested": len(paths),
            "imported_count": len(imported),
        }

    def _op_append_media(self, params):
        media_ids = params.get("media_ids") or []
        paths = params.get("paths") or []
        items = None
        if paths:
            absolute = [_absolute(value) for value in paths]
            missing = [path for path in absolute if not Path(path).exists()]
            if missing:
                raise OperationError("Media file not found: %s" % ", ".join(missing))
            items = list(self._media_pool().ImportMedia(absolute) or [])
            if not items:
                raise OperationError("Resolve did not import any of the requested media files.")
        if items is None and not media_ids:
            raise OperationError(
                "Nothing to append. Pass either media_ids (unique ids from list_media, for clips "
                "already in the Media Pool) or paths (absolute file paths to import and append). "
                "For a still image, use add_image instead so its duration is set."
            )
        if items is None:
            items = self._find_media_items(media_ids)

        timeline = self._timeline()
        track_type = str(params.get("track_type", "audio" if int(params.get("media_type", 1)) == 2 else "video")).lower()
        media_type = int(params.get("media_type", 2 if track_type == "audio" else 1))
        track_index = params.get("track_index")
        if track_index is not None:
            if track_type == "audio" or media_type == 2:
                count = int(call(timeline, "GetTrackCount", 0, "audio") or 0)
                if int(track_index) > count:
                    for _ in range(int(track_index) - count):
                        call(timeline, "AddTrack", False, "audio")
            else:
                track_index = self._ensure_video_track(
                    timeline, track_index, bool(params.get("create_track", True))
                )
        record_frame = params.get("record_frame")

        payload = items
        if track_index is not None or record_frame is not None or params.get("start_frame") is not None:
            payload = []
            for item in items:
                clip_info = {"mediaPoolItem": item}
                if track_index is not None:
                    clip_info["trackIndex"] = int(track_index)
                if record_frame is not None:
                    clip_info["recordFrame"] = int(record_frame)
                clip_info["mediaType"] = media_type
                frames = (call(item, "GetClipProperty", {}) or {}).get("Frames")
                try:
                    total = int(frames)
                except (TypeError, ValueError):
                    total = 0
                sf = int(params.get("start_frame", 0) or 0)
                ef = params.get("end_frame")
                if ef is not None:
                    ef = int(ef)
                    sub = call(item, "CreateSubClip", None, f"sub_{sf}_{ef}", sf, ef)
                    if sub is not None:
                        clip_info["mediaPoolItem"] = sub
                    else:
                        clip_info.update({"startFrame": sf, "endFrame": ef})
                elif total > 1:
                    ef = total - 1
                    clip_info.update({"startFrame": sf, "endFrame": ef})
                payload.append(clip_info)

        created = self._media_pool().AppendToTimeline(payload) or []
        if not created:
            raise OperationError(
                "Resolve appended nothing. A still image needs add_image, and an explicit "
                "record_frame must land on empty space on that track."
            )
        return {
            "appended_count": len(created),
            "requested": len(items),
            "track_index": track_index,
            "record_frame": record_frame,
        }

    def _op_add_image(self, params):
        """Import one still image and place it on the timeline with a real duration."""
        raw_path = str(params.get("path", "")).strip()
        if not raw_path:
            raise OperationError("path is required and must be an absolute image file path.")
        path = _absolute(raw_path)
        if not Path(path).exists():
            raise OperationError("Image file not found: %s" % path)
        suffix = Path(path).suffix.lower()

        timeline = self._timeline()
        fps = self._project_rate()
        duration_frames = params.get("duration_frames")
        if duration_frames is None:
            seconds = params.get("duration_seconds")
            seconds = 5.0 if seconds is None else float(seconds)
            duration_frames = int(round(seconds * fps))
        duration_frames = max(1, int(duration_frames))

        track_index = self._ensure_video_track(
            timeline,
            params.get("track_index") or 1,
            bool(params.get("create_track", True)),
        )
        record_frame = params.get("record_frame")
        if record_frame is None and params.get("at_playhead"):
            record_frame = (
                int(call(timeline, "GetStartFrame", 0) or 0) + self._current_marker_frame(timeline)
            )

        pool = self._media_pool()
        existing = None
        for candidate in self._walk_media(pool.GetRootFolder(), "", 5000):
            if candidate.get("file_path") and _absolute(candidate["file_path"]) == path:
                existing = candidate.get("id")
                break
        if existing:
            media_item = self._find_media_items([existing])[0]
            reused = True
        else:
            imported = pool.ImportMedia([path]) or []
            if not imported:
                raise OperationError(
                    "Resolve could not import %s. Confirm the file is a supported image format." % path
                )
            media_item = imported[0]
            reused = False

        available = (call(media_item, "GetClipProperty", {}) or {}).get("Frames")
        try:
            available_frames = int(available)
        except (TypeError, ValueError):
            available_frames = 0

        clip_info = {
            "mediaPoolItem": media_item,
            "startFrame": 0,
            "endFrame": duration_frames - 1,
            "trackIndex": int(track_index),
        }
        if record_frame is not None:
            clip_info["recordFrame"] = int(record_frame)

        created = pool.AppendToTimeline([clip_info]) or []
        fallback_used = False
        if not created and available_frames > 1:
            # Some builds refuse an endFrame beyond the still's reported length.
            clip_info["endFrame"] = min(duration_frames, available_frames) - 1
            created = pool.AppendToTimeline([clip_info]) or []
            fallback_used = bool(created)
        if not created:
            clip_info.pop("startFrame", None)
            clip_info.pop("endFrame", None)
            created = pool.AppendToTimeline([clip_info]) or []
            fallback_used = bool(created)
        if not created:
            raise OperationError(
                "Resolve placed nothing on V%d. If record_frame was given, that space may already "
                "be occupied. Try another record_frame, another track_index, or omit both to append "
                "at the end of the track." % track_index
            )

        item = created[0]
        actual = call(item, "GetDuration", None)
        applied, rejected = self._apply_transform(item, params)
        _, info = self._newest_item_on_track(timeline, track_index)

        result = {
            "item": (info or {}).get("id"),
            "name": call(item, "GetName", ""),
            "media_pool_id": call(media_item, "GetUniqueId", None),
            "reused_existing_media": reused,
            "is_recognised_image_format": suffix in IMAGE_SUFFIXES,
            "track_index": track_index,
            "record_frame": record_frame,
            "start": call(item, "GetStart", None),
            "requested_duration_frames": duration_frames,
            "actual_duration_frames": actual,
            "frame_rate": fps,
            "transform_applied": applied,
        }
        if rejected:
            result["transform_rejected"] = rejected
        notes = []
        if fallback_used:
            notes.append(
                "Resolve would not honour the exact requested length, so a shorter or default "
                "still duration was used."
            )
        try:
            if actual is not None and int(actual) != duration_frames:
                notes.append(
                    "Requested %d frames, Resolve created %d. Raise Preferences > Editing > "
                    "Standard still duration if longer stills are needed."
                    % (duration_frames, int(actual))
                )
        except (TypeError, ValueError):
            pass
        if notes:
            result["notes"] = notes
        return result

    def _op_set_clip_transform(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), params.get("track_index"))
        applied, rejected = self._apply_transform(item, params)
        if not applied and not rejected:
            raise OperationError(
                "No transform values were supplied. Pass at least one of pan, tilt, pan_percent, "
                "tilt_percent, zoom, zoom_x, zoom_y, rotation, opacity, composite_mode, flip_x, "
                "flip_y, a crop value, or a mode such as scaling, resize_filter, dynamic_zoom_ease, "
                "retime_process, or motion_estimation."
            )
        result = {"item": info["id"], "applied": applied, "current": self._read_transform(item)}
        if rejected:
            result["rejected"] = rejected
            result["note"] = (
                "Resolve rejected the listed keys. Confirm they are supported on this clip type "
                "and Resolve version."
            )
        return result

    def _op_get_clip_transform(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), params.get("track_index"))
        width, height = self._project_resolution()
        return {
            "item": info["id"],
            "timeline_resolution": {"width": width, "height": height},
            "transform": self._read_transform(item),
        }

    def _op_split_clip(self, params):
        """Rebuild a normal-speed clip, keeping a verified timeline checkpoint."""
        timeline = self._timeline()
        item, info = self._resolve_one_item(params.get("item_id"), params.get("track_index"))
        if info.get("track_type") not in ("video", "audio"):
            raise OperationError("Only normal-speed media clips can be split.")
        if call(item, "GetFusionCompCount", 0):
            raise OperationError("This clip has Fusion effects. Rebuilding would lose them; split it in Resolve instead.")
        if call(timeline, "GetIsTrackLocked", False, info["track_type"], info["track_index"]):
            raise OperationError("The clip's track is locked.")
        start, end = float(info["start"]), float(info["end"])
        if not start.is_integer() or not end.is_integer():
            raise OperationError("Subframe audio boundaries cannot be rebuilt safely by this tool.")
        start, end = int(start), int(end)
        frame = params.get("frame")
        if frame is not None and params.get("timecode"):
            raise OperationError("Pass frame or timecode, not both.")
        if frame is None and params.get("timecode"):
            fps = self._project_rate()
            frame = int(timeline.GetStartFrame()) + self._tc_frames(params["timecode"], fps) - self._tc_frames(timeline.GetStartTimecode(), fps)
        frame = self._playhead_frame(timeline) if frame is None else int(frame)
        if not start < frame < end:
            raise OperationError("Cut frame must be strictly inside the clip's [%d, %d) range." % (start, end))
        media = call(item, "GetMediaPoolItem", None)
        source_start = call(item, "GetSourceStartFrame", None)
        if media is None or source_start is None:
            raise OperationError("Resolve did not provide a media source range; nothing was changed.")
        # Source extraction's range validation also catches detectable retiming.
        self._source_window(item, start)
        source_fps = call(media, "GetClipProperty", None, "FPS")
        try:
            if source_fps and abs(float(source_fps) - self._project_rate()) > 0.01:
                raise OperationError("Mixed source/timeline frame rates cannot be split safely by reconstruction. Use Resolve's razor.")
        except (TypeError, ValueError):
            raise OperationError("Source frame rate could not be verified.")
        checkpoint, checkpoint_info = self._duplicate_current("Before split", open_duplicate=False)
        checkpoint_items = call(checkpoint, "GetItemListInTrack", [], info["track_type"], info["track_index"]) or []
        # The checkpoint is verified in track order; retain the copied item for grade copying.
        original_items = timeline.GetItemListInTrack(info["track_type"], info["track_index"]) or []
        source_index = next((index for index, candidate in enumerate(original_items)
                             if (info.get("unique_id") is not None and call(candidate, "GetUniqueId", None) == info.get("unique_id")) or candidate == item), None)
        if source_index is None or source_index >= len(checkpoint_items):
            raise OperationError("Could not identify the checkpoint clip; original was not removed.")
        saved_item = checkpoint_items[source_index]
        transform = self._read_transform(item)
        color = call(item, "GetClipColor", "")
        enabled = call(item, "GetClipEnabled", None)
        source_start = int(source_start)
        segments = []
        for begin, finish in ((start, frame), (frame, end)):
            segments.append({"mediaPoolItem": media, "startFrame": source_start + begin - start,
                             "endFrame": source_start + finish - start - 1, "recordFrame": begin,
                             "trackIndex": info["track_index"], "mediaType": 1 if info["track_type"] == "video" else 2})
        if not timeline.DeleteClips([item], False):
            raise OperationError("Resolve refused to remove the original clip. Checkpoint: %s." % checkpoint_info["name"])
        try:
            created = self._media_pool().AppendToTimeline(segments) or []
            if len(created) != 2:
                raise OperationError("Resolve created %d of 2 halves." % len(created))
            for piece, segment in zip(created, segments):
                expected_end = segment["recordFrame"] + segment["endFrame"] - segment["startFrame"] + 1
                if call(piece, "GetStart", None) != segment["recordFrame"] or call(piece, "GetEnd", None) != expected_end:
                    raise OperationError("Resolve rebuilt a half at an unexpected position or duration.")
                _, rejected = self._apply_transform(piece, transform_params_from_props(transform))
                if rejected:
                    raise OperationError("Resolve rejected restored transforms: %s." % sorted(rejected))
                if enabled is not None and not call(piece, "SetClipEnabled", False, enabled):
                    raise OperationError("Could not restore clip enabled state.")
                if color and not call(piece, "SetClipColor", False, color):
                    raise OperationError("Could not restore clip color.")
            # CopyGrades is part of the regular Resolve API, not a Studio AI feature.
            grade_copied = bool(call(saved_item, "CopyGrades", False, created)) if info["track_type"] == "video" else None
            if info["track_type"] == "video" and not grade_copied:
                raise OperationError("Could not preserve the current color-grade layer.")
        except Exception as exc:
            reopened = bool(self._project().SetCurrentTimeline(checkpoint))
            raise OperationError("Split failed: %s. Checkpoint '%s' contains the pre-edit timeline; %s. The attempted timeline may contain partial edits and has been retained."
                                 % (exc, checkpoint_info["name"], "opened the checkpoint for recovery" if reopened else "open that checkpoint manually"))
        return {"original": info["id"], "cut_frame": frame, "checkpoint": checkpoint_info,
                "halves": [{"side": side, "id": self._item_id_after_rebuild(timeline, piece),
                            "start": call(piece, "GetStart", None), "end": call(piece, "GetEnd", None), "duration": call(piece, "GetDuration", None)}
                           for side, piece in zip(("left", "right"), created)],
                "transform_preserved": True, "current_grade_layer_copied": grade_copied,
                "note": "Checkpoint retained. Rebuilt halves preserve static transforms, enabled state, clip color and current grade layer. Other grade layers, audio links, clip markers, fades and keyframes are not guaranteed; compare with the checkpoint before continuing."}

    def _build_ease_func(self, easing_name):
        import math
        easing = str(easing_name).lower().strip()

        def ease_fn(t):
            t_clamp = max(0.0, min(1.0, t))
            if easing in ("linear", "none_linear"):
                return t_clamp
            elif easing in ("ease_in", "quad_in"):
                return t_clamp * t_clamp
            elif easing in ("cubic_in",):
                return t_clamp * t_clamp * t_clamp
            elif easing in ("ease_out", "quad_out"):
                return 1.0 - (1.0 - t_clamp) * (1.0 - t_clamp)
            elif easing in ("cubic_out", "snap_in", "punch_in"):
                return 1.0 - math.pow(1.0 - t_clamp, 3)
            elif easing in ("ease", "quad_ease", "ease_in_out", "smoothstep"):
                return 2.0 * t_clamp * t_clamp if t_clamp < 0.5 else 1.0 - math.pow(-2.0 * t_clamp + 2.0, 2) / 2.0
            elif easing in ("cubic_ease", "smootherstep", "cinematic"):
                return t_clamp * t_clamp * t_clamp * (t_clamp * (t_clamp * 6.0 - 15.0) + 10.0)
            elif easing in ("circular_ease", "circ_ease", "circular"):
                return (1.0 - math.sqrt(1.0 - math.pow(2.0 * t_clamp, 2))) / 2.0 if t_clamp < 0.5 else (math.sqrt(1.0 - math.pow(-2.0 * t_clamp + 2.0, 2)) + 1.0) / 2.0
            elif easing in ("rebound_in", "back_in", "anticipation"):
                c1 = 1.70158
                c3 = c1 + 1.0
                return c3 * t_clamp * t_clamp * t_clamp - c1 * t_clamp * t_clamp
            elif easing in ("rebound_out", "back_out", "overshoot", "pop"):
                c1 = 1.70158
                c3 = c1 + 1.0
                return 1.0 + c3 * math.pow(t_clamp - 1.0, 3) + c1 * math.pow(t_clamp - 1.0, 2)
            elif easing in ("rebound_ease", "back_ease", "back_in_out"):
                c1 = 1.70158 * 1.525
                return (math.pow(2.0 * t_clamp, 2) * ((c1 + 1.0) * 2.0 * t_clamp - c1)) / 2.0 if t_clamp < 0.5 else (math.pow(2.0 * t_clamp - 2.0, 2) * ((c1 + 1.0) * (t_clamp * 2.0 - 2.0) + c1) + 2.0) / 2.0
            elif easing in ("elastic_out", "elastic", "spring"):
                c4 = (2.0 * math.pi) / 3.0
                return 0.0 if t_clamp == 0 else (1.0 if t_clamp == 1 else math.pow(2.0, -10.0 * t_clamp) * math.sin((t_clamp * 10.0 - 0.75) * c4) + 1.0)
            elif easing in ("none", "step"):
                return 1.0 if t_clamp >= 1.0 else 0.0
            return t_clamp * t_clamp * t_clamp * (t_clamp * (t_clamp * 6.0 - 15.0) + 10.0)

        return ease_fn

    def _op_animate_zoom(self, params):
        """Animate a clip's scale and framing over time using a Fusion composition with comprehensive curve presets.

        Supports all standard video editing curves (Linear, Ease In, Quad In, Cubic In,
        Ease Out, Quad Out, Cubic Out, Ease, Quad Ease, Cubic Ease, Circular Ease,
        Rebound In / Anticipation, Rebound Out / Overshoot, Elastic Spring), full Zoom Out
        direction support, multi-keyframe arrays, and automatic AI scenario heuristics.
        """
        item, info = self._resolve_one_item(params.get("item_id"), params.get("track_index"))
        
        # 1. Preset & Direction Resolution
        preset = str(params.get("preset", params.get("scenario", ""))).lower().strip()
        direction = str(params.get("direction", params.get("zoom_type", "in"))).lower().strip()
        
        raw_start_zoom = params.get("start_zoom")
        raw_end_zoom = params.get("end_zoom")
        easing = str(params.get("easing", "")).lower().strip()

        # Handle Presets
        if preset in ("punch_in", "snap_in"):
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.0)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.35)
            if not easing:
                easing = "cubic_out"
        elif preset in ("pop_in", "rebound", "overshoot"):
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.0)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.38)
            if not easing:
                easing = "rebound_out"
        elif preset in ("slow_push", "ken_burns"):
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.0)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.15)
            if not easing:
                easing = "linear"
        elif preset in ("dramatic", "build_up"):
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.0)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.60)
            if not easing:
                easing = "cubic_in"
        elif preset in ("reveal", "zoom_out") or direction in ("out", "zoom_out"):
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.40)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.0)
            if not easing:
                easing = "cubic_out"
        elif preset in ("cinematic", "glide"):
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.0)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.25)
            if not easing:
                easing = "cubic_ease"
        else:
            start_zoom = float(raw_start_zoom if raw_start_zoom is not None else 1.0)
            end_zoom = float(raw_end_zoom if raw_end_zoom is not None else 1.5)
            if not easing:
                easing = "smootherstep"

        # Explicit direction="out" override if start_zoom was default 1.0 and end_zoom was default 1.5
        if direction in ("out", "zoom_out") and start_zoom < end_zoom:
            start_zoom, end_zoom = end_zoom, start_zoom

        if start_zoom <= 0 or end_zoom <= 0:
            raise OperationError("start_zoom and end_zoom must be greater than 0 (1.0 is original size).")

        start_cx = float(params.get("start_center_x", params.get("center_x", 0.5)))
        start_cy = float(params.get("start_center_y", params.get("center_y", 0.5)))
        end_cx = float(params.get("target_center_x", params.get("target_x", 0.5)))
        end_cy = float(params.get("target_center_y", params.get("target_y", 0.5)))

        duration = int(call(item, "GetDuration", 0) or 0)
        start_frame = max(0, int(params.get("start_frame", 0) or 0))
        end_frame = params.get("end_frame")
        end_frame = max(start_frame + 1, duration - 1 if duration else start_frame + 1) \
            if end_frame is None else int(end_frame)

        ease_func = self._build_ease_func(easing)

        trace = []

        comp = call(item, "GetFusionCompByIndex", None, 1)
        if comp is None:
            comp = call(item, "AddFusionComp", None)
            trace.append("added a new Fusion composition" if comp is not None else "AddFusionComp returned nothing")
        else:
            trace.append("reused the clip's existing Fusion composition")
        if comp is None:
            raise OperationError(
                "Resolve did not return a Fusion composition for %s, so an animated zoom could not "
                "be built. This clip type may not accept Fusion effects." % info["id"]
            )

        media_in = call(comp, "FindTool", None, "MediaIn1")
        media_out = call(comp, "FindTool", None, "MediaOut1")

        transform = call(comp, "FindTool", None, "AIBridgeZoom")
        if transform is None:
            transform = call(comp, "AddTool", None, "Transform", -32768, -32768)
            if transform is not None:
                try:
                    transform.SetAttrs({"TOOLS_Name": "AIBridgeZoom"})
                except Exception:
                    pass
            trace.append("added a Transform node" if transform is not None else "AddTool(Transform) failed")
        else:
            trace.append("reused the AIBridgeZoom Transform node")
        if transform is None:
            raise OperationError(
                "Resolve created a Fusion composition but would not add a Transform node. "
                "Animated zoom needs Fusion tool scripting, which this build did not expose. "
                "Trace: %s" % "; ".join(trace)
            )

        # Wire MediaIn -> Transform -> MediaOut when the endpoints are visible.
        try:
            if media_in is not None:
                transform.ConnectInput("Input", media_in)
                trace.append("connected MediaIn into the Transform")
            if media_out is not None:
                media_out.ConnectInput("Input", transform)
                trace.append("connected the Transform into MediaOut")
        except Exception as exc:
            trace.append("wiring the nodes raised %s (Fusion may have auto-connected)" % exc)

        keyframes_created = False
        raw_keyframes = params.get("keyframes")
        is_reset = bool(params.get("reset", False))
        trace.append("debug_params: is_reset=%s, raw_kfs_type=%s, count=%s" % (is_reset, type(raw_keyframes).__name__, len(raw_keyframes) if isinstance(raw_keyframes, list) else 0))

        try:
            comp.Lock()
            try:
                if is_reset:
                    # Reset Transform to identity (1.0x, center (0.5, 0.5))
                    lua_lines = [
                        "AIBridgeZoom.Size = 1.0",
                        "AIBridgeZoom.Center = Point(0.5, 0.5)"
                    ]
                    comp.Execute("\n".join(lua_lines))
                    keyframes_created = True
                    trace.append("reset AIBridgeZoom Transform to 1.0x scale and centered framing")
                elif raw_keyframes and isinstance(raw_keyframes, list) and len(raw_keyframes) >= 2:
                    # Sort keyframes by frame
                    sorted_kfs = sorted(raw_keyframes, key=lambda k: int(k.get("frame", 0)))
                    lua_lines = [
                        "AIBridgeZoom.Size = BezierSpline()",
                        "AIBridgeZoom.Center = Path()"
                    ]
                    # Generate multi-segment interpolation
                    for i in range(len(sorted_kfs) - 1):
                        k_curr = sorted_kfs[i]
                        k_next = sorted_kfs[i + 1]
                        
                        f_start = int(k_curr.get("frame", 0))
                        f_end = int(k_next.get("frame", f_start + 1))
                        span = max(1, f_end - f_start)
                        
                        z_start = float(k_curr.get("zoom", k_curr.get("size", 1.0)))
                        z_end = float(k_next.get("zoom", k_next.get("size", 1.0)))
                        
                        cx_start = float(k_curr.get("center_x", k_curr.get("cx", 0.5)))
                        cx_end = float(k_next.get("center_x", k_next.get("cx", 0.5)))
                        
                        cy_start = float(k_curr.get("center_y", k_curr.get("cy", 0.5)))
                        cy_end = float(k_next.get("center_y", k_next.get("cy", 0.5)))
                        
                        seg_easing = str(k_next.get("easing", k_curr.get("easing", "smootherstep"))).lower().strip()
                        seg_ease_fn = self._build_ease_func(seg_easing)
                        
                        for f in range(f_start, f_end + (1 if i == len(sorted_kfs) - 2 else 0)):
                            t = (f - f_start) / float(span)
                            e = seg_ease_fn(t)
                            z_val = z_start + (z_end - z_start) * e
                            cx_val = cx_start + (cx_end - cx_start) * e
                            cy_val = cy_start + (cy_end - cy_start) * e
                            
                            lua_lines.append("AIBridgeZoom.Size[%f] = %f" % (float(f), z_val))
                            lua_lines.append("AIBridgeZoom.Center[%f] = {%f, %f}" % (float(f), cx_val, cy_val))
                    
                    comp.Execute("\n".join(lua_lines))
                    keyframes_created = True
                    trace.append("generated multi-segment keyframe spline across %d control points" % len(sorted_kfs))
                else:
                    total_span = max(1, end_frame - start_frame)
                    has_center_anim = (end_cx != 0.5 or end_cy != 0.5 or start_cx != 0.5 or start_cy != 0.5)
                    lua_lines = [
                        "AIBridgeZoom.Size = BezierSpline()"
                    ]
                    if has_center_anim:
                        lua_lines.append("AIBridgeZoom.Center = Path()")

                    if start_frame > 0:
                        lua_lines.append("AIBridgeZoom.Size[0] = %f" % start_zoom)
                        if has_center_anim:
                            lua_lines.append("AIBridgeZoom.Center[0] = {%f, %f}" % (start_cx, start_cy))
                    
                    for f in range(start_frame, end_frame + 1):
                        t = (f - start_frame) / float(total_span)
                        val = start_zoom + (end_zoom - start_zoom) * ease_func(t)
                        lua_lines.append("AIBridgeZoom.Size[%f] = %f" % (float(f), val))
                        if has_center_anim:
                            cx = start_cx + (end_cx - start_cx) * ease_func(t)
                            cy = start_cy + (end_cy - start_cy) * ease_func(t)
                            lua_lines.append("AIBridgeZoom.Center[%f] = {%f, %f}" % (float(f), cx, cy))

                    if duration and end_frame < duration - 1:
                        lua_lines.append("AIBridgeZoom.Size[%f] = %f" % (float(duration - 1), end_zoom))
                        if has_center_anim:
                            lua_lines.append("AIBridgeZoom.Center[%f] = {%f, %f}" % (float(duration - 1), end_cx, end_cy))

                    comp.Execute("\n".join(lua_lines))
                    keyframes_created = True
                    trace.append(
                        "generated %d %s keyframes for Size (%.3f @f%d -> %.3f @f%d)"
                        % (total_span + 1, easing, start_zoom, start_frame, end_zoom, end_frame)
                    )
            finally:
                comp.Unlock()
        except Exception as exc:
            trace.append("keyframing raised %s" % exc)

        if not keyframes_created:
            try:
                transform.Size = end_zoom
                trace.append("set a static Size of %.3f as a fallback" % end_zoom)
            except Exception as exc:
                trace.append("static fallback raised %s" % exc)

        if raw_keyframes and isinstance(raw_keyframes, list) and len(raw_keyframes) >= 2:
            start_zoom = float(raw_keyframes[0].get("zoom", 1.0))
            end_zoom = float(raw_keyframes[-1].get("zoom", 1.0))
            start_frame = int(raw_keyframes[0].get("frame", 0))
            end_frame = int(raw_keyframes[-1].get("frame", duration - 1))
            easing = "multi_segment_keyframes"

        result = {
            "item": info["id"],
            "keyframes_created": keyframes_created,
            "start_zoom": start_zoom,
            "end_zoom": end_zoom,
            "easing": easing,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "trace": trace,
        }
        if not keyframes_created:
            result["note"] = (
                "A Fusion Transform was created but its Size could not be keyframed through scripting "
                "on this build. A static zoom was applied instead. Open the clip on the Fusion page to "
                "animate it, or use set_clip_transform for a static scale."
            )
        else:
            result["note"] = (
                "Butter-smooth %s animation generated in Fusion on %s (Frames %d to %d)."
                % (easing, info["id"], start_frame, end_frame)
            )
        return result

    def _op_add_track(self, params):
        timeline = self._timeline()
        track_type = str(params.get("track_type", "video")).strip().lower()
        if track_type not in ("video", "audio", "subtitle"):
            raise OperationError("track_type must be video, audio, or subtitle.")
        count = max(1, min(int(params.get("count", 1) or 1), 8))
        added = 0
        for _ in range(count):
            if call(timeline, "AddTrack", False, track_type):
                added += 1
            else:
                break
        if not added:
            raise OperationError("Resolve refused to add a %s track." % track_type)
        return {
            "track_type": track_type,
            "added": added,
            "total": call(timeline, "GetTrackCount", 0, track_type),
        }

    def _op_set_track_name(self, params):
        timeline = self._timeline()
        track_type = str(params.get("track_type", "video")).strip().lower()
        index = int(params.get("track_index", 1))
        name = str(params.get("name", "")).strip()
        if not name:
            raise OperationError("name is required.")
        if not call(timeline, "SetTrackName", False, track_type, index, name):
            raise OperationError("Resolve refused to rename %s track %d." % (track_type, index))
        return {"track_type": track_type, "track_index": index, "name": name}

    def _op_insert_title(self, params):
        """Insert a title at the playhead. Text setting is best effort."""
        timeline = self._timeline()
        title = str(params.get("title_name", "") or "Text+").strip()
        item = None
        used = None
        for method in ("InsertFusionTitleIntoTimeline", "InsertTitleIntoTimeline"):
            function = getattr(timeline, method, None)
            if not callable(function):
                continue
            try:
                candidate = function(title)
            except Exception:
                candidate = None
            if candidate:
                item, used = candidate, method
                break
        if item is None:
            raise OperationError(
                "Resolve did not insert a title named '%s'. Use the exact name shown in the Edit "
                "page Titles list, for example 'Text+' or 'Text'. This depends on the Resolve "
                "version and installed title templates." % title
            )

        text = params.get("text")
        text_set = None
        if text is not None:
            text_set = self._set_title_text(item, str(text))
        applied, rejected = self._apply_transform(item, params)
        result = {
            "inserted": call(item, "GetName", title),
            "method": used,
            "start": call(item, "GetStart", None),
            "duration": call(item, "GetDuration", None),
            "text_set": text_set,
            "transform_applied": applied,
        }
        if rejected:
            result["transform_rejected"] = rejected
        if text is not None and not text_set:
            result["note"] = (
                "The title was inserted but its text could not be set through the scripting API. "
                "Type the text in the Inspector, or render the text with Remotion instead."
            )
        return result

    def _set_title_text(self, item, text):
        count = call(item, "GetFusionCompCount", 0) or 0
        for index in range(1, int(count) + 1):
            comp = call(item, "GetFusionCompByIndex", None, index)
            if comp is None:
                continue
            tools = call(comp, "GetToolList", None, False) or {}
            candidates = tools.values() if isinstance(tools, dict) else list(tools)
            for tool in candidates:
                for attribute in ("StyledText", "Text"):
                    try:
                        target = getattr(tool, attribute, None)
                        if target is None:
                            continue
                        setattr(tool, attribute, text)
                        return True
                    except Exception:
                        continue
        return False

    def _op_create_timeline(self, params):
        name = str(params.get("name", "")).strip()
        if not name:
            raise OperationError("name is required.")
        timeline = self._media_pool().CreateEmptyTimeline(name)
        if timeline is None:
            raise OperationError(
                "Resolve could not create the timeline. The name may already be in use."
            )
        self._project().SetCurrentTimeline(timeline)
        return {"created": timeline.GetName()}

    def _op_set_playhead(self, params):
        timecode = str(params.get("timecode", "")).strip()
        if not timecode:
            raise OperationError("timecode is required in HH:MM:SS:FF format.")
        if not self._timeline().SetCurrentTimecode(timecode):
            raise OperationError(
                "Resolve rejected the timecode. Use the timeline's frame rate and HH:MM:SS:FF."
            )
        return {"timecode": timecode}

    def _op_open_page(self, params):
        page = str(params.get("page", "")).strip().lower()
        if page not in PAGES:
            raise OperationError("page must be one of: %s" % ", ".join(PAGES))
        self.resolve.OpenPage(page)
        return {"page": call(self.resolve, "GetCurrentPage", page)}

    def _op_add_marker(self, params):
        timeline = self._timeline()
        frame = params.get("frame")
        if frame is None:
            frame = self._current_marker_frame(timeline)
        color = str(params.get("color", "Blue"))
        name = str(params.get("name", "AI marker"))
        note = str(params.get("note", ""))
        duration = max(1, int(params.get("duration", 1) or 1))
        custom_data = str(params.get("custom_data", "resolve-ai-bridge"))
        if not timeline.AddMarker(int(frame), color, name, note, duration, custom_data):
            raise OperationError(
                "Resolve could not add the marker. A marker may already exist at frame %d, or the "
                "colour name may be invalid." % int(frame)
            )
        return {"frame": int(frame), "color": color, "name": name}

    def _op_delete_marker(self, params):
        frame = int(params.get("frame"))
        if not self._timeline().DeleteMarkerAtFrame(frame):
            raise OperationError("No marker was deleted at frame %d." % frame)
        return {"deleted_frame": frame}

    def _op_set_clip_property(self, params):
        item, info = self._find_timeline_items([params.get("item_id")])[0]
        name = str(params.get("property_name", "")).strip()
        if not name:
            raise OperationError("property_name is required.")
        value = params.get("value")
        if not item.SetProperty(name, value):
            available = plain(call(item, "GetProperty", {}) or {})
            raise OperationError(
                "Resolve rejected property '%s'. Current values: %s" % (name, json.dumps(available))
            )
        return {"item": info["id"], "property": name, "value": value}

    def _op_set_clip_enabled(self, params):
        item, info = self._find_timeline_items([params.get("item_id")])[0]
        enabled = bool(params.get("enabled", True))
        if not item.SetClipEnabled(enabled):
            raise OperationError("Resolve could not change the clip enabled state.")
        return {"item": info["id"], "enabled": enabled}

    def _op_set_clip_color(self, params):
        item, info = self._find_timeline_items([params.get("item_id")])[0]
        color = str(params.get("color", "")).strip()
        ok = item.SetClipColor(color) if color else item.ClearClipColor()
        if not ok:
            raise OperationError(
                "Resolve rejected the clip color. Use a standard Resolve color name, or an empty "
                "value to clear it."
            )
        return {"item": info["id"], "color": color or None}

    def _op_get_clip_grade(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), track_hint="video")
        graph = call(item, "GetNodeGraph")
        num_nodes = call(graph, "GetNumNodes", 0) if graph else 0
        comp_count = call(item, "GetFusionCompCount", 0) or 0
        comp_names = call(item, "GetFusionCompNameList", []) or []
        versions = call(item, "GetVersionNameList", [], 0) or []
        current_version = call(item, "GetCurrentVersion", {}) or {}
        return {
            "item": info["id"],
            "name": info["name"],
            "num_color_nodes": num_nodes,
            "fusion_comp_count": comp_count,
            "fusion_comp_names": comp_names,
            "versions": versions,
            "current_version": current_version,
        }

    def _op_set_clip_grade(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), track_hint="video")
        saturation = params.get("saturation")
        slope = params.get("slope", "1.0 1.0 1.0")
        offset = params.get("offset", "0.0 0.0 0.0")
        power = params.get("power", "1.0 1.0 1.0")
        node_index = str(params.get("node_index", 1))
        reset = bool(params.get("reset", False))

        graph = call(item, "GetNodeGraph")
        if reset and graph:
            call(graph, "ResetAllGrades")

        cdl_map = {"NodeIndex": str(node_index)}
        if saturation is not None:
            cdl_map["Saturation"] = str(float(saturation))
        if slope:
            cdl_map["Slope"] = " ".join(str(v) for v in slope) if isinstance(slope, (list, tuple)) else str(slope)
        if offset:
            cdl_map["Offset"] = " ".join(str(v) for v in offset) if isinstance(offset, (list, tuple)) else str(offset)
        if power:
            cdl_map["Power"] = " ".join(str(v) for v in power) if isinstance(power, (list, tuple)) else str(power)

        ok = item.SetCDL(cdl_map)
        return {
            "item": info["id"],
            "name": info["name"],
            "cdl": cdl_map,
            "applied": bool(ok),
        }

    def _op_keyframe_clip_saturation(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), track_hint="video")
        comp = item.GetFusionCompByIndex(1)
        if not comp:
            comp = item.AddFusionComp()
        if not comp:
            raise OperationError("Could not access or create Fusion composition on clip.")

        duration = int(call(item, "GetDuration", 75) or 75)
        start_sat = float(params.get("start_saturation", 1.0))
        end_sat = float(params.get("end_saturation", 0.0))
        start_frame = int(params.get("start_frame", 0))
        end_frame = int(params.get("end_frame", max(1, duration - 1)))

        comp.Lock()
        cc = None
        tool_debug = {}
        try:
            all_tools = comp.GetToolList(False) or {}
            tool_items = list(all_tools.values()) if isinstance(all_tools, dict) else list(all_tools)
            media_in = None
            media_out = None

            for t in tool_items:
                t_name = getattr(t, "Name", str(t))
                if "BrightnessContrast" in t_name or "ColorCorrector" in t_name:
                    cc = t
                elif "MediaIn" in t_name:
                    media_in = t
                elif "MediaOut" in t_name:
                    media_out = t

            if not cc:
                # BrightnessContrast has direct "Saturation" property in Fusion
                cc = comp.AddTool("BrightnessContrast")
                if not cc:
                    cc = comp.AddTool("ColorCorrector")

            if cc and media_in and media_out:
                try:
                    cc.Input = media_in
                except Exception:
                    try:
                        cc.ConnectInput("Input", media_in)
                    except Exception:
                        pass
                try:
                    media_out.Input = cc
                except Exception:
                    try:
                        media_out.ConnectInput("Input", cc)
                    except Exception:
                        pass

            if cc:
                lua_cmd = """
                ColorCorrector1.Saturation1 = BezierSpline()
                ColorCorrector1.Saturation1[%f] = %f
                ColorCorrector1.Saturation1[%f] = %f
                """ % (float(start_frame), start_sat, float(end_frame), end_sat)
                try:
                    comp.Execute(lua_cmd)
                    tool_debug["lua_execute_success"] = True
                except Exception as e:
                    tool_debug["lua_err"] = str(e)

        finally:
            comp.Unlock()

        return {
            "item": info["id"],
            "name": info["name"],
            "duration": duration,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_saturation": start_sat,
            "end_saturation": end_sat,
            "tool_type": getattr(cc, "Name", str(cc)) if cc else None,
            "tool_debug": tool_debug,
            "applied": True,
        }

    def _op_animate_color_fx(self, params):
        import math
        import random

        item, info = self._resolve_one_item(params.get("item_id"), track_hint="video")
        comp = item.GetFusionCompByIndex(1)
        if not comp:
            comp = item.AddFusionComp()
        if not comp:
            raise OperationError("Could not access or create Fusion composition on clip.")

        duration = int(call(item, "GetDuration", 75) or 75)
        start_frame = int(params.get("start_frame", 0))
        end_frame = int(params.get("end_frame", max(1, duration - 1)))
        
        rainbow = params.get("rainbow", True)
        rainbow_cycles = float(rainbow) if isinstance(rainbow, (int, float)) and not isinstance(rainbow, bool) else (1.5 if rainbow else 0.0)
        tint_strength = float(params.get("tint_strength", 0.70))
        
        flicker = params.get("flicker", True)
        flicker_amp = float(flicker) if isinstance(flicker, (int, float)) and not isinstance(flicker, bool) else (0.05 if flicker else 0.0)
        flicker_freq = float(params.get("flicker_frequency", 2.2))
        
        saturation = float(params.get("saturation", 1.3))

        comp.Lock()
        tool_debug = {}
        try:
            all_tools = comp.GetToolList(False) or {}
            tool_items = list(all_tools.values()) if isinstance(all_tools, dict) else list(all_tools)
            cc = None
            media_in = None
            media_out = None

            for t in tool_items:
                t_name = getattr(t, "Name", str(t))
                if "ColorCorrector" in t_name:
                    cc = t
                elif "MediaIn" in t_name:
                    media_in = t
                elif "MediaOut" in t_name:
                    media_out = t

            if not cc:
                cc = comp.AddTool("ColorCorrector")
                if media_in and media_out and cc:
                    cc.ConnectInput("Input", media_in)
                    media_out.ConnectInput("Input", cc)

            lua_lines = [
                "ColorCorrector1.Saturation1 = %f" % saturation,
                "ColorCorrector1.WheelSaturation1 = %f" % saturation,
            ]

            if rainbow_cycles > 0:
                lua_lines.append("ColorCorrector1.WheelTintLength1 = %f" % tint_strength)
                lua_lines.append("ColorCorrector1.WheelTintAngle1 = BezierSpline()")
                num_steps = max(16, (end_frame - start_frame) // 2)
                for step in range(num_steps + 1):
                    t = float(start_frame) + (float(end_frame - start_frame) * step / num_steps)
                    angle = (step / num_steps) * rainbow_cycles
                    lua_lines.append("ColorCorrector1.WheelTintAngle1[%f] = %f" % (t, angle))

            if flicker_amp > 0:
                lua_lines.append("ColorCorrector1.MasterRGBGain = BezierSpline()")
                rng = random.Random(42)
                for f in range(start_frame, end_frame + 1):
                    wave1 = math.sin(f * flicker_freq * 0.8) * 0.55
                    wave2 = math.cos(f * flicker_freq * 1.6) * 0.30
                    noise = (rng.random() - 0.5) * 0.30
                    gain = 1.0 + (wave1 + wave2 + noise) * flicker_amp
                    lua_lines.append("ColorCorrector1.MasterRGBGain[%f] = %f" % (float(f), gain))

            full_lua = "\n".join(lua_lines)
            comp.Execute(full_lua)
            tool_debug["lua_executed"] = True
        finally:
            comp.Unlock()

        return {
            "item": info["id"],
            "name": info["name"],
            "duration": duration,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "rainbow_cycles": rainbow_cycles,
            "tint_strength": tint_strength,
            "flicker_amplitude": flicker_amp,
            "saturation": saturation,
            "applied": True,
        }

    def _op_apply_blur_effect(self, params):
        """Apply a static or dynamic (gradual) blur effect to a full frame or masked bounding region."""
        import math
        item, info = self._resolve_one_item(params.get("item_id"), track_hint=params.get("track_index"))
        comp = item.GetFusionCompByIndex(1)
        if not comp:
            comp = item.AddFusionComp()
        if not comp:
            raise OperationError("Could not create or access Fusion composition on %s." % info["id"])

        duration = int(call(item, "GetDuration", 0) or 0)
        start_frame = max(0, int(params.get("start_frame", 0) or 0))
        end_frame = params.get("end_frame")
        end_frame = max(start_frame + 1, duration - 1 if duration else start_frame + 1) \
            if end_frame is None else int(end_frame)

        blur_type = str(params.get("blur_type", "gaussian")).lower().strip()
        blur_size = float(params.get("blur_size", params.get("size", 20.0)))
        
        cx = float(params.get("center_x", params.get("x", 0.50)))
        cy = float(params.get("center_y", params.get("y", 0.50)))
        w = float(params.get("width", params.get("w", 1.0)))
        h = float(params.get("height", params.get("h", 1.0)))
        corner_radius = float(params.get("corner_radius", 0.0))
        soft_edge = float(params.get("soft_edge", 0.015))
        mask_shape = str(params.get("mask_shape", "rectangle")).lower().strip()

        mask_name = str(params.get("mask_name", params.get("name", "1"))).strip()
        safe_tag = "".join(c for c in mask_name if c.isalnum()) or "1"
        blur_node_name = "AIBridgeBlur_" + safe_tag
        mask_node_name = "AIBridgeMask_" + safe_tag

        animate = bool(params.get("animate", False))
        start_blur = float(params.get("start_blur", 0.0))
        end_blur = float(params.get("end_blur", blur_size))
        easing = str(params.get("easing", "smootherstep")).lower().strip()
        ease_fn = self._build_ease_func(easing)

        is_reset = bool(params.get("reset", False))

        comp.Lock()
        trace = []
        try:
            # Check existing tools
            all_tools = comp.GetToolList(False) or {}
            tool_items = list(all_tools.values()) if isinstance(all_tools, dict) else list(all_tools)
            media_in = None
            media_out = None
            existing_blur_nodes = []

            for t in tool_items:
                t_name = getattr(t, "Name", str(t))
                if t_name == "MediaIn1" or (not media_in and "MediaIn" in t_name):
                    media_in = t
                elif t_name == "MediaOut1" or (not media_out and "MediaOut" in t_name):
                    media_out = t
                elif t_name.startswith("AIBridgeBlur_") or t_name in ("FavoritesBlur", "PrivacyBlur"):
                    existing_blur_nodes.append(t)

            if is_reset:
                # Remove all blur nodes and reconnect MediaIn1 -> MediaOut1 (or zoom)
                lua_cleanup = []
                for b in existing_blur_nodes:
                    b_name = getattr(b, "Name", str(b))
                    lua_cleanup.append("local b = comp:FindTool('%s'); if b then b:Delete() end" % b_name)
                if media_in and media_out:
                    lua_cleanup.append("MediaOut1:ConnectInput('Input', MediaIn1)")
                comp.Execute("\n".join(lua_cleanup))
                trace.append("reset all blur nodes")
                return {
                    "item": info["id"],
                    "reset": True,
                    "trace": trace,
                    "note": "Reset and removed all blur nodes from %s." % info["id"]
                }

            # Map blur type to Fusion RegID
            reg_id = "Blur"
            if "defocus" in blur_type:
                reg_id = "Defocus"
            elif "mosaic" in blur_type or "pixel" in blur_type:
                reg_id = "MosaicBlur"
            elif "directional" in blur_type or "motion" in blur_type:
                reg_id = "DirectionalBlur"

            lua_lines = []
            # Create or reuse blur tool
            lua_lines.append("local blur = comp:FindTool('%s') or comp:AddTool('%s', -32768, -32768)" % (blur_node_name, reg_id))
            lua_lines.append("blur:SetAttrs({TOOLS_Name = '%s'})" % blur_node_name)

            # Create or reuse mask if localized
            raw_keyframes = params.get("keyframes")
            has_mask = (w < 0.999 or h < 0.999 or cx != 0.50 or cy != 0.50 or bool(raw_keyframes))
            if has_mask:
                mask_reg_id = "EllipseMask" if "ellipse" in mask_shape or "circle" in mask_shape else "RectangleMask"
                lua_lines.append("local mask = comp:FindTool('%s') or comp:AddTool('%s', -32768, -32768)" % (mask_node_name, mask_reg_id))
                lua_lines.append("mask:SetAttrs({TOOLS_Name = '%s'})" % mask_node_name)
                lua_lines.append("mask.Center = {%f, %f}" % (cx, cy))
                lua_lines.append("mask.Width = %f" % w)
                lua_lines.append("mask.Height = %f" % h)
                if mask_reg_id == "RectangleMask":
                    lua_lines.append("mask.CornerRadius = %f" % corner_radius)
                lua_lines.append("mask.SoftEdge = %f" % soft_edge)
                lua_lines.append("blur:ConnectInput('EffectMask', mask)")

            # Configure blur size or dynamic keyframes
            raw_keyframes = params.get("keyframes")
            if raw_keyframes and isinstance(raw_keyframes, list) and len(raw_keyframes) >= 2:
                sorted_kfs = sorted(raw_keyframes, key=lambda k: int(k.get("frame", 0)))
                lua_lines.append("blur.XBlurSize = BezierSpline()")
                lua_lines.append("blur.YBlurSize = BezierSpline()")
                if has_mask:
                    lua_lines.append("mask.Width = BezierSpline()")
                    lua_lines.append("mask.Height = BezierSpline()")
                    lua_lines.append("mask.Center = XYPath()")
                    lua_lines.append("local xy = mask.Center:GetConnectedOutput():GetTool()")
                    lua_lines.append("xy.X = BezierSpline()")
                    lua_lines.append("xy.Y = BezierSpline()")

                for i in range(len(sorted_kfs) - 1):
                    k_curr = sorted_kfs[i]
                    k_next = sorted_kfs[i + 1]
                    f_start = int(k_curr.get("frame", 0))
                    f_end = int(k_next.get("frame", f_start + 1))
                    span = max(1, f_end - f_start)

                    b_start = float(k_curr.get("blur_size", k_curr.get("size", blur_size)))
                    b_end = float(k_next.get("blur_size", k_next.get("size", blur_size)))

                    cx_start = float(k_curr.get("center_x", k_curr.get("cx", cx)))
                    cx_end = float(k_next.get("center_x", k_next.get("cx", cx)))

                    cy_start = float(k_curr.get("center_y", k_curr.get("cy", cy)))
                    cy_end = float(k_next.get("center_y", k_next.get("cy", cy)))

                    w_start = float(k_curr.get("width", k_curr.get("w", w)))
                    w_end = float(k_next.get("width", k_next.get("w", w)))

                    h_start = float(k_curr.get("height", k_curr.get("h", h)))
                    h_end = float(k_next.get("height", k_next.get("h", h)))

                    seg_easing = str(k_next.get("easing", k_curr.get("easing", "smootherstep"))).lower().strip()
                    seg_ease_fn = self._build_ease_func(seg_easing)

                    for f in range(f_start, f_end + (1 if i == len(sorted_kfs) - 2 else 0)):
                        t = (f - f_start) / float(span)
                        e = seg_ease_fn(t)
                        b_val = b_start + (b_end - b_start) * e
                        lua_lines.append("blur.XBlurSize[%f] = %f" % (float(f), b_val))
                        lua_lines.append("blur.YBlurSize[%f] = %f" % (float(f), b_val))
                        if has_mask:
                            cx_val = cx_start + (cx_end - cx_start) * e
                            cy_val = cy_start + (cy_end - cy_start) * e
                            w_val = w_start + (w_end - w_start) * e
                            h_val = h_start + (h_end - h_start) * e
                            lua_lines.append("mask.Width[%f] = %f" % (float(f), w_val))
                            lua_lines.append("mask.Height[%f] = %f" % (float(f), h_val))
                            lua_lines.append("xy.X[%f] = %f" % (float(f), cx_val))
                            lua_lines.append("xy.Y[%f] = %f" % (float(f), cy_val))
                trace.append("generated multi-segment keyframe blur spline across %d waypoints" % len(sorted_kfs))
            elif animate:
                lua_lines.append("blur.XBlurSize = BezierSpline()")
                lua_lines.append("blur.YBlurSize = BezierSpline()")
                total_span = max(1, end_frame - start_frame)
                if start_frame > 0:
                    lua_lines.append("blur.XBlurSize[0] = %f" % start_blur)
                    lua_lines.append("blur.YBlurSize[0] = %f" % start_blur)
                for f in range(start_frame, end_frame + 1):
                    t = (f - start_frame) / float(total_span)
                    val = start_blur + (end_blur - start_blur) * ease_fn(t)
                    lua_lines.append("blur.XBlurSize[%f] = %f" % (float(f), val))
                    lua_lines.append("blur.YBlurSize[%f] = %f" % (float(f), val))
                if duration and end_frame < duration - 1:
                    lua_lines.append("blur.XBlurSize[%f] = %f" % (float(duration - 1), end_blur))
                    lua_lines.append("blur.YBlurSize[%f] = %f" % (float(duration - 1), end_blur))
                trace.append("animated blur %.1f -> %.1f across frames %d..%d" % (start_blur, end_blur, start_frame, end_frame))
            else:
                lua_lines.append("blur.XBlurSize = %f" % blur_size)
                lua_lines.append("blur.YBlurSize = %f" % blur_size)
                trace.append("set static blur size %.1f" % blur_size)

            # Wiring: Chain with existing nodes
            lua_lines.append('''
                local mi = comp:FindTool("MediaIn1")
                local mo = comp:FindTool("MediaOut1")
                local b_fav = comp:FindTool("AIBridgeBlur_favorites")
                local b_search = comp:FindTool("AIBridgeBlur_search")
                local b_priv = comp:FindTool("AIBridgeBlur_privacy")
                local zoom = comp:FindTool("AIBridgeZoom")
                local cc = comp:FindTool("ColorCorrector1")

                local prev = mi
                if b_fav then
                    b_fav:ConnectInput("Input", prev)
                    prev = b_fav
                end
                if b_search then
                    b_search:ConnectInput("Input", prev)
                    prev = b_search
                end
                if b_priv then
                    b_priv:ConnectInput("Input", prev)
                    prev = b_priv
                end
                if zoom then
                    zoom:ConnectInput("Input", prev)
                    prev = zoom
                end
                if cc then
                    cc:ConnectInput("Input", prev)
                    prev = cc
                end
                if mo then
                    mo:ConnectInput("Input", prev)
                end
            ''')

            comp.Execute("\n".join(lua_lines))
            trace.append("successfully compiled and wired %s in Fusion" % blur_node_name)
        finally:
            comp.Unlock()

        return {
            "item": info["id"],
            "blur_node": blur_node_name,
            "mask_node": mask_node_name if has_mask else None,
            "blur_size": blur_size,
            "animated": animate,
            "start_blur": start_blur if animate else None,
            "end_blur": end_blur if animate else None,
            "start_frame": start_frame if animate else None,
            "end_frame": end_frame if animate else None,
            "center": [cx, cy] if has_mask else [0.5, 0.5],
            "dimensions": [w, h] if has_mask else [1.0, 1.0],
            "trace": trace,
            "note": "Applied %s %s effect on %s." % ("dynamic" if animate else "static", blur_type, info["id"])
        }

    def _op_apply_spotlight_mask(self, params):
        """Apply a dynamic or static spotlight reveal mask with adjustable feathering and ambient darkness."""
        item, info = self._resolve_one_item(params.get("item_id"), track_hint=params.get("track_index"))
        comp = item.GetFusionCompByIndex(1)
        if not comp:
            comp = item.AddFusionComp()
        if not comp:
            raise OperationError("Could not create or access Fusion composition on %s." % info["id"])

        duration = int(call(item, "GetDuration", 0) or 0)
        start_frame = max(0, int(params.get("start_frame", 0) or 0))
        end_frame = params.get("end_frame")
        end_frame = max(start_frame + 1, duration - 1 if duration else start_frame + 1) \
            if end_frame is None else int(end_frame)

        cx = float(params.get("center_x", params.get("x", 0.50)))
        cy = float(params.get("center_y", params.get("y", 0.50)))
        radius = float(params.get("radius", params.get("size", 0.20)))
        w = float(params.get("width", params.get("w", radius * 2 if "radius" in params or "size" in params else 0.40)))
        h = float(params.get("height", params.get("h", radius * 2 if "radius" in params or "size" in params else 0.40)))
        soft_edge = float(params.get("soft_edge", params.get("feather", 0.08)))
        ambient_brightness = max(0.0, min(1.0, float(params.get("ambient_brightness", params.get("base_gain", 0.08)))))
        spotlight_gain = float(params.get("spotlight_gain", params.get("gain", 1.0)))
        mask_shape = str(params.get("shape", params.get("mask_shape", "ellipse"))).lower().strip()

        mask_name = str(params.get("mask_name", params.get("name", "1"))).strip()
        safe_tag = "".join(c for c in mask_name if c.isalnum()) or "1"
        base_node_name = "AIBridgeSpotlightBase_" + safe_tag
        mask_node_name = "AIBridgeSpotlightMask_" + safe_tag
        merge_node_name = "AIBridgeSpotlightMerge_" + safe_tag
        fg_gain_node_name = "AIBridgeSpotlightGain_" + safe_tag

        is_reset = bool(params.get("reset", False))

        comp.Lock()
        trace = []
        try:
            all_tools = comp.GetToolList(False) or {}
            tool_items = list(all_tools.values()) if isinstance(all_tools, dict) else list(all_tools)
            media_in = None
            media_out = None
            existing_spotlight_nodes = []

            for t in tool_items:
                t_name = getattr(t, "Name", str(t))
                if t_name == "MediaIn1" or (not media_in and "MediaIn" in t_name):
                    media_in = t
                elif t_name == "MediaOut1" or (not media_out and "MediaOut" in t_name):
                    media_out = t
                elif t_name.startswith("AIBridgeSpotlight"):
                    existing_spotlight_nodes.append(t)

            if is_reset:
                lua_cleanup = []
                for node in existing_spotlight_nodes:
                    n_name = getattr(node, "Name", str(node))
                    lua_cleanup.append("local n = comp:FindTool('%s'); if n then n:Delete() end" % n_name)
                if media_in and media_out:
                    lua_cleanup.append("MediaOut1:ConnectInput('Input', MediaIn1)")
                comp.Execute("\n".join(lua_cleanup))
                trace.append("reset all spotlight mask nodes")
                return {
                    "item": info["id"],
                    "reset": True,
                    "trace": trace,
                    "note": "Reset and removed all spotlight mask nodes from %s." % info["id"]
                }

            lua_lines = []
            # 1. Base Dark Layer (BrightnessContrast)
            lua_lines.append("local base = comp:FindTool('%s') or comp:AddTool('BrightnessContrast', -32768, -32768)" % base_node_name)
            lua_lines.append("base:SetAttrs({TOOLS_Name = '%s'})" % base_node_name)
            lua_lines.append("base.Gain = %f" % ambient_brightness)

            # 2. Foreground Gain Layer (if spotlight_gain != 1.0)
            use_fg_gain = (abs(spotlight_gain - 1.0) > 0.001)
            if use_fg_gain:
                lua_lines.append("local fg_gain = comp:FindTool('%s') or comp:AddTool('BrightnessContrast', -32768, -32768)" % fg_gain_node_name)
                lua_lines.append("fg_gain:SetAttrs({TOOLS_Name = '%s'})" % fg_gain_node_name)
                lua_lines.append("fg_gain.Gain = %f" % spotlight_gain)

            # 3. Spotlight Mask (EllipseMask or RectangleMask)
            mask_reg_id = "RectangleMask" if "rect" in mask_shape else "EllipseMask"
            lua_lines.append("local mask = comp:FindTool('%s') or comp:AddTool('%s', -32768, -32768)" % (mask_node_name, mask_reg_id))
            lua_lines.append("mask:SetAttrs({TOOLS_Name = '%s'})" % mask_node_name)
            lua_lines.append("mask.Center = {%f, %f}" % (cx, cy))
            lua_lines.append("mask.Width = %f" % w)
            lua_lines.append("mask.Height = %f" % h)
            lua_lines.append("mask.SoftEdge = %f" % soft_edge)

            # 4. Merge Node
            lua_lines.append("local merge = comp:FindTool('%s') or comp:AddTool('Merge', -32768, -32768)" % merge_node_name)
            lua_lines.append("merge:SetAttrs({TOOLS_Name = '%s'})" % merge_node_name)

            # 5. Keyframing
            raw_keyframes = params.get("keyframes")
            if raw_keyframes and isinstance(raw_keyframes, list) and len(raw_keyframes) >= 2:
                sorted_kfs = sorted(raw_keyframes, key=lambda k: int(k.get("frame", 0)))
                lua_lines.append("mask.Width = BezierSpline()")
                lua_lines.append("mask.Height = BezierSpline()")
                lua_lines.append("mask.Center = XYPath()")
                lua_lines.append("local xy = mask.Center:GetConnectedOutput():GetTool()")
                lua_lines.append("xy.X = BezierSpline()")
                lua_lines.append("xy.Y = BezierSpline()")

                for i in range(len(sorted_kfs) - 1):
                    k_curr = sorted_kfs[i]
                    k_next = sorted_kfs[i + 1]
                    f_start = int(k_curr.get("frame", 0))
                    f_end = int(k_next.get("frame", f_start + 1))
                    span = max(1, f_end - f_start)

                    cx_start = float(k_curr.get("x", k_curr.get("center_x", cx)))
                    cy_start = float(k_curr.get("y", k_curr.get("center_y", cy)))
                    cx_end = float(k_next.get("x", k_next.get("center_x", cx)))
                    cy_end = float(k_next.get("y", k_next.get("center_y", cy)))

                    rad_start = float(k_curr.get("radius", k_curr.get("size", radius)))
                    rad_end = float(k_next.get("radius", k_next.get("size", radius)))
                    w_start = float(k_curr.get("width", k_curr.get("w", rad_start * 2)))
                    w_end = float(k_next.get("width", k_next.get("w", rad_end * 2)))
                    h_start = float(k_curr.get("height", k_curr.get("h", rad_start * 2)))
                    h_end = float(k_next.get("height", k_next.get("h", rad_end * 2)))

                    seg_easing = str(k_next.get("easing", k_curr.get("easing", "smootherstep"))).lower().strip()
                    seg_ease_fn = self._build_ease_func(seg_easing)

                    for f in range(f_start, f_end + (1 if i == len(sorted_kfs) - 2 else 0)):
                        t = (f - f_start) / float(span)
                        e = seg_ease_fn(t)
                        cx_val = cx_start + (cx_end - cx_start) * e
                        cy_val = cy_start + (cy_end - cy_start) * e
                        w_val = w_start + (w_end - w_start) * e
                        h_val = h_start + (h_end - h_start) * e
                        lua_lines.append("mask.Width[%f] = %f" % (float(f), w_val))
                        lua_lines.append("mask.Height[%f] = %f" % (float(f), h_val))
                        lua_lines.append("xy.X[%f] = %f" % (float(f), cx_val))
                        lua_lines.append("xy.Y[%f] = %f" % (float(f), cy_val))
                trace.append("animated spotlight mask across %d keyframe waypoints" % len(sorted_kfs))
            elif params.get("animate"):
                animate_expand = bool(params.get("expand", False))
                start_rad = float(params.get("start_radius", radius))
                end_rad = float(params.get("end_radius", 2.0 if animate_expand else radius))
                easing = str(params.get("easing", "cubic_out")).lower().strip()
                ease_fn = self._build_ease_func(easing)
                total_span = max(1, end_frame - start_frame)

                lua_lines.append("mask.Width = BezierSpline()")
                lua_lines.append("mask.Height = BezierSpline()")
                for f in range(start_frame, end_frame + 1):
                    t = (f - start_frame) / float(total_span)
                    r_val = start_rad + (end_rad - start_rad) * ease_fn(t)
                    lua_lines.append("mask.Width[%f] = %f" % (float(f), r_val * 2))
                    lua_lines.append("mask.Height[%f] = %f" % (float(f), r_val * 2))
                trace.append("animated spotlight radius %.2f -> %.2f across frames %d..%d" % (start_rad, end_rad, start_frame, end_frame))

            # Wiring:
            # MediaIn1 -> base -> merge.Background
            # MediaIn1 -> (fg_gain) -> merge.Foreground
            # mask -> merge.EffectMask
            # merge -> MediaOut1
            lua_lines.append('''
                local mi = comp:FindTool("MediaIn1")
                local mo = comp:FindTool("MediaOut1")
                local base = comp:FindTool("%s")
                local mask = comp:FindTool("%s")
                local merge = comp:FindTool("%s")
                local fg_gain = comp:FindTool("%s")

                if mi and base then
                    base:ConnectInput("Input", mi)
                end
                if base and merge then
                    merge:ConnectInput("Background", base)
                end
                if mi and merge then
                    if fg_gain then
                        fg_gain:ConnectInput("Input", mi)
                        merge:ConnectInput("Foreground", fg_gain)
                    else
                        merge:ConnectInput("Foreground", mi)
                    end
                end
                if mask and merge then
                    merge:ConnectInput("EffectMask", mask)
                end
                if merge and mo then
                    mo:ConnectInput("Input", merge)
                end
            ''' % (base_node_name, mask_node_name, merge_node_name, fg_gain_node_name))

            comp.Execute("\n".join(lua_lines))
            trace.append("successfully compiled and wired spotlight mask graph in Fusion")
        finally:
            comp.Unlock()

        return {
            "item": info["id"],
            "base_node": base_node_name,
            "mask_node": mask_node_name,
            "merge_node": merge_node_name,
            "ambient_brightness": ambient_brightness,
            "spotlight_gain": spotlight_gain,
            "center": [cx, cy],
            "dimensions": [w, h],
            "soft_edge": soft_edge,
            "trace": trace,
            "note": "Applied spotlight reveal mask to %s." % info["id"]
        }

    def _op_inspect_fusion(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), track_hint="video")
        comp = item.GetFusionCompByIndex(1)
        if not comp:
            comp = item.AddFusionComp()
        if not comp:
            return {"error": "No Fusion composition found on clip"}
        
        comp.Lock()
        result = {"tools": {}, "comp_attrs": {}}
        try:
            if params.get("exec_lua"):
                comp.Execute(params["exec_lua"])
                result["lua_executed"] = True
            result["comp_attrs"] = {
                "global_start": call(comp, "GetAttrs", 0, "COMPN_GlobalStart"),
                "global_end": call(comp, "GetAttrs", 0, "COMPN_GlobalEnd"),
                "render_start": call(comp, "GetAttrs", 0, "COMPN_RenderStart"),
                "render_end": call(comp, "GetAttrs", 0, "COMPN_RenderEnd"),
                "current_time": call(comp, "GetAttrs", 0, "COMPN_CurrentTime"),
            }
            tools = comp.GetToolList(False) or {}
            tool_items = list(tools.values()) if isinstance(tools, dict) else list(tools)
            for tool in tool_items:
                name = getattr(tool, "Name", str(tool))
                inputs = []
                inps = tool.GetInputList() or {}
                inp_list = list(inps.values()) if isinstance(inps, dict) else list(inps)
                for inp in inp_list:
                    try:
                        inp_id = str(inp.GetAttrs("INPS_ID"))
                        inp_name = str(inp.GetAttrs("INPS_Name"))
                        conn = inp.GetConnectedOutput()
                        connected_tool = None
                        if conn:
                            parent = conn.GetTool()
                            connected_tool = getattr(parent, "Name", str(parent)) if parent else str(conn)
                        inputs.append({"id": inp_id, "name": inp_name, "connected_to": connected_tool})
                    except Exception as e:
                        inputs.append({"err": str(e)})
                
                # Check main outputs
                outs = tool.GetOutputList() or {}
                out_list = list(outs.values()) if isinstance(outs, dict) else list(outs)
                output_names = []
                for out in out_list:
                    try:
                        output_names.append(str(out.GetAttrs("OUTS_ID")))
                    except Exception:
                        pass

                # Get current input values for Transform, MediaIn, and TimeSpeed
                val_info = {}
                for inp_key in ("Size", "Center", "GlobalIn", "GlobalOut", "HoldFirstFrame", "HoldLastFrame", "Speed", "InterpolateBetweenFrames"):
                    try:
                        v = tool.GetInput(inp_key, 8.0)
                        if v is not None:
                            val_info[inp_key] = str(v)
                    except Exception:
                        pass

                result["tools"][name] = {
                    "reg_id": str(call(tool, "GetAttrs", "", "TOOLS_RegID")),
                    "inputs": [i for i in inputs if i.get("connected_to") or i.get("id") in ("Input", "Size", "Center", "Saturation1")],
                    "outputs": output_names,
                    "values_at_f8": val_info,
                }
        finally:
            comp.Unlock()
        return result

    def _op_delete_clips(self, params):
        ids = params.get("item_ids") or []
        if not ids:
            raise OperationError("item_ids is required. Call timeline_overview for valid ids.")
        targets = self._find_timeline_items(ids)
        ripple = bool(params.get("ripple", False))
        if not self._timeline().DeleteClips([item for item, _ in targets], ripple):
            raise OperationError("Resolve refused to delete the selected clips.")
        return {"deleted": [info["id"] for _, info in targets], "ripple": ripple}

    def _op_save_project(self, _params):
        if not self.resolve.GetProjectManager().SaveProject():
            raise OperationError("Resolve could not save the current project.")
        return {"saved": True, "project": self._project().GetName()}

    def _op_list_render_presets(self, _params):
        project = self._project()
        return {
            "presets": plain(call(project, "GetRenderPresetList", []) or []),
            "formats": plain(call(project, "GetRenderFormats", {}) or {}),
        }

    def _op_render_current_timeline(self, params):
        project = self._project()
        raw_output_dir = str(params.get("output_dir", "")).strip()
        if not raw_output_dir:
            raise OperationError("output_dir is required.")
        output_dir = _absolute(raw_output_dir)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        preset = str(params.get("preset", "")).strip()
        if preset and not project.LoadRenderPreset(preset):
            raise OperationError(
                "Render preset '%s' was not found. Call list_render_presets for valid names."
                % preset
            )
        settings = {"TargetDir": output_dir}
        if params.get("name"):
            settings["CustomName"] = str(params["name"])
        if not project.SetRenderSettings(settings):
            raise OperationError("Resolve rejected the render settings.")
        job_id = project.AddRenderJob()
        if not job_id:
            raise OperationError("Resolve could not add a render job.")
        started = bool(project.StartRendering(job_id)) if params.get("start") else False
        return {
            "job_id": job_id,
            "started": started,
            "output_dir": output_dir,
            "preset": preset or None,
        }

    def _source_window(self, item, timeline_frame):
        """Normal-speed source mapping; refuse known retiming rather than guessing."""
        fps = self._project_rate()
        media = call(item, "GetMediaPoolItem", None)
        source_fps = call(media, "GetClipProperty", None, "FPS")
        try:
            source_fps = float(source_fps)
            if not math.isfinite(source_fps) or source_fps <= 0:
                source_fps = fps
        except (ValueError, TypeError):
            source_fps = fps
        start = float(call(item, "GetStart", 0) or 0)
        end = float(call(item, "GetEnd", start) or start)
        source_start = call(item, "GetSourceStartFrame", None)
        if source_start is None:
            source_start = call(item, "GetLeftOffset", 0) or 0
        source_end = call(item, "GetSourceEndFrame", None)
        if source_end is not None:
            source_seconds = (float(source_end) - float(source_start) + 1) / source_fps
            if abs(source_seconds - (end - start) / fps) > max(2 / source_fps, 2 / fps):
                raise OperationError("Source extraction cannot map this retimed clip reliably. Use a rendered clip or normal-speed source.")
        position = min(max(float(timeline_frame), start), end)
        return float(source_start) / source_fps + (position - start) / fps, max(0, (end - position) / fps)

    @staticmethod
    def _ffmpeg_path():
        """Find a user-installed decoder or the installer's optional private binary."""
        import shutil
        binary = os.environ.get("RESOLVE_AI_BRIDGE_FFMPEG") or shutil.which("ffmpeg")
        if binary:
            return binary
        home = Path(os.environ.get("RESOLVE_AI_BRIDGE_HOME", Path.home() / ".resolve-ai-bridge")).expanduser()
        try:
            path = Path((home / "ffmpeg-path.txt").read_text(encoding="utf-8").strip())
            return str(path) if path.is_file() and os.access(path, os.X_OK) else None
        except OSError:
            return None

    @staticmethod
    def _image_dimensions(path):
        """Read PNG/JPEG dimensions without optional Python image libraries."""
        import struct
        with Path(path).open("rb") as handle:
            header = handle.read(24)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) == 24:
                return struct.unpack(">II", header[16:24])
            if header[:2] == b"\xff\xd8":
                handle.seek(2)
                while True:
                    byte = handle.read(1)
                    if not byte:
                        break
                    if byte != b"\xff":
                        continue
                    marker = handle.read(1)
                    while marker == b"\xff":
                        marker = handle.read(1)
                    if not marker or marker in (b"\xda", b"\xd9"):
                        break
                    if marker == b"\x01" or 0xD0 <= marker[0] <= 0xD8:
                        continue
                    length = handle.read(2)
                    if len(length) != 2:
                        break
                    length = struct.unpack(">H", length)[0]
                    if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        data = handle.read(5)
                        if len(data) == 5:
                            height, width = struct.unpack(">HH", data[1:])
                            return width, height
                        break
                    if length < 2:
                        break
                    handle.seek(length - 2, 1)
        return None, None

    def _op_timeline_frame(self, params):
        import base64
        import shutil
        import subprocess
        import tempfile

        timeline = self._timeline()
        fps = self._project_rate()
        requested_tc = params.get("timecode")
        requested_frame = params.get("frame")
        if requested_tc and requested_frame is not None:
            raise OperationError("Pass timecode or frame, not both.")
        if requested_frame is not None:
            # Public frame inputs are absolute, like timeline_overview and split_clip.
            start_tc = call(timeline, "GetStartTimecode", "00:00:00:00")
            offset = int(requested_frame) - int(call(timeline, "GetStartFrame", 0) or 0)
            requested_tc = self._frames_tc(self._tc_frames(start_tc, fps) + offset, fps, ";" in start_tc)
        if requested_tc:
            self._tc_frames(requested_tc, fps)
            if not timeline.SetCurrentTimecode(str(requested_tc)):
                raise OperationError("Resolve refused to seek to %s." % requested_tc)
        current_tc = call(timeline, "GetCurrentTimecode", "00:00:00:00")
        current_frame = self._playhead_frame(timeline)
        mode = str(params.get("mode", "auto")).lower()
        if mode not in ("auto", "source", "composite"):
            raise OperationError("mode must be auto, source, or composite.")
        fmt = str(params.get("format", "jpg")).lower().lstrip(".")
        if fmt == "jpeg":
            fmt = "jpg"
        if fmt not in ("png", "jpg"):
            raise OperationError("format must be jpg or png.")
        max_width = int(params.get("max_width", 1280))
        capture_dir = Path(tempfile.gettempdir()) / "resolve-frame-captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        path = capture_dir / ("frame_%s.%s" % (uuid.uuid4().hex, fmt))
        method = None
        clip_name = None
        if mode in ("auto", "composite"):
            if call(self._project(), "ExportCurrentFrameAsStill", False, str(path)) and path.exists() and path.stat().st_size:
                method = "export_current_frame_as_still"
        if method is None and mode in ("auto", "source"):
            item, info = self._resolve_one_item("playhead")
            clip_name = info.get("name")
            media = call(item, "GetMediaPoolItem", None)
            file_path = call(media, "GetClipProperty", "", "File Path")
            if not file_path or not Path(file_path).is_file():
                raise OperationError("The visible clip has no readable source file. Source fallback cannot capture generators or offline media.")
            source_seconds, _ = self._source_window(item, current_frame) if Path(file_path).suffix.lower() not in IMAGE_SUFFIXES else (0.0, 0.0)
            ffmpeg = self._ffmpeg_path()
            if not ffmpeg:
                raise OperationError("Source capture needs ffmpeg on PATH (Free-compatible). Composite capture was unavailable.")
            try:
                result = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", "%.9f" % source_seconds, "-i", str(file_path), "-frames:v", "1", str(path)], capture_output=True, timeout=45)
            except subprocess.TimeoutExpired:
                raise OperationError("Source frame extraction timed out.")
            if result.returncode == 0 and path.exists() and path.stat().st_size:
                method = "source_ffmpeg"
        if method is None:
            raise OperationError("Composite capture is unavailable on this Resolve build. Try mode='source' with ffmpeg installed; source images exclude timeline effects.")
        width, height = self._image_dimensions(path)
        resized = False
        if width and max_width > 0 and width > max_width:
            target = path.with_name(path.stem + "_small" + path.suffix)
            ffmpeg = self._ffmpeg_path()
            sips = shutil.which("sips")
            command = ([ffmpeg, "-v", "error", "-y", "-i", str(path), "-vf", "scale=%d:-1" % max_width, str(target)] if ffmpeg else
                       [sips, "--resampleWidth", str(max_width), str(path), "--out", str(target)] if sips else None)
            if command:
                try:
                    result = subprocess.run(command, capture_output=True, timeout=30)
                    if result.returncode == 0 and target.exists() and target.stat().st_size:
                        path.unlink()
                        path = target
                        width, height = self._image_dimensions(path)
                        resized = True
                except (OSError, subprocess.TimeoutExpired):
                    pass
        return {"timecode": current_tc, "frame": current_frame, "frame_space": "absolute_timeline",
                "clip_name": clip_name, "method": method, "composited": method == "export_current_frame_as_still",
                "note": "Source fallback excludes grades, Fusion, transforms, overlays and timeline retiming." if method == "source_ffmpeg" else "Native timeline still.",
                "width": width, "height": height, "resized": resized, "format": fmt,
                "image_base64": base64.b64encode(path.read_bytes()).decode("ascii"), "file_path": str(path)}

    def _op_timeline_audio(self, params):
        import array
        import shutil
        import subprocess
        import sys
        import tempfile
        import wave

        timeline = self._timeline()
        fps = self._project_rate()
        action = str(params.get("action", "analyze")).lower()
        actions = ("analyze", "silence_cuts", "energy_envelope", "onsets", "vad_clusters", "export_slice")
        if action not in actions:
            raise OperationError("Unknown audio action. Choose: %s" % ", ".join(actions))
        current_frame = self._playhead_frame(timeline)
        requested = params.get("item_id")
        if requested:
            target, info = self._find_timeline_items([requested])[0]
        else:
            track = int(params.get("track_index", 1))
            candidates = [(item, info) for item, info in self._timeline_items()
                          if info["track_type"] in ("audio", "video") and info["track_index"] == track
                          and info.get("enabled") is not False
                          and call(timeline, "GetIsTrackEnabled", True, info["track_type"], track) is not False
                          and float(info["start"]) <= current_frame < float(info["end"])]
            candidates.sort(key=lambda pair: pair[1]["track_type"] != "audio")
            if not candidates:
                raise OperationError("No enabled audio/video clip under the playhead on track %d. Pass an explicit item_id." % track)
            target, info = candidates[0]
        media = call(target, "GetMediaPoolItem", None)
        file_path = call(media, "GetClipProperty", "", "File Path")
        if not file_path or not Path(file_path).is_file():
            raise OperationError("Selected clip has no readable source audio file.")
        clip_start = float(call(target, "GetStart", 0) or 0)
        clip_end = float(call(target, "GetEnd", 0) or 0)
        origin = current_frame if clip_start <= current_frame < clip_end else clip_start
        if params.get("whole_clip"):
            origin = clip_start
        source_seconds, duration = self._source_window(target, origin)
        max_seconds = float(params.get("max_duration_seconds", 300))
        if not math.isfinite(max_seconds) or not 0 < max_seconds <= 3600:
            raise OperationError("max_duration_seconds must be between 0 and 3600.")
        duration = min(duration, max_seconds)
        if duration <= 0:
            raise OperationError("The selected source range is empty.")
        threshold = float(params.get("silence_threshold_db", -40))
        minimum = float(params.get("min_silence_duration", 0.3))
        if not math.isfinite(threshold) or not -120 <= threshold <= 0 or not math.isfinite(minimum) or minimum < 0:
            raise OperationError("Use a finite threshold from -120 to 0 dBFS and a nonnegative silence duration.")
        audio_dir = Path(tempfile.gettempdir()) / "resolve-audio-analysis"
        audio_dir.mkdir(parents=True, exist_ok=True)
        slice_path = audio_dir / ("slice_%s.wav" % uuid.uuid4().hex)
        full_path = audio_dir / ("decode_%s.wav" % uuid.uuid4().hex)
        ffmpeg, afconvert = self._ffmpeg_path(), shutil.which("afconvert")
        try:
            if ffmpeg:
                command = [ffmpeg, "-v", "error", "-y", "-ss", "%.9f" % source_seconds, "-i", str(file_path), "-t", "%.9f" % duration,
                           "-vn", "-acodec", "pcm_s16le", "-ar", "48000", str(slice_path)]
                result = subprocess.run(command, capture_output=True, timeout=90)
                if result.returncode:
                    raise OperationError("ffmpeg could not decode the selected audio range: %s" % result.stderr.decode(errors="replace")[-500:])
            elif afconvert:
                result = subprocess.run([afconvert, "-f", "WAVE", "-d", "LEI16@48000", str(file_path), str(full_path)], capture_output=True, timeout=90)
                if result.returncode:
                    raise OperationError("afconvert could not decode audio. Install ffmpeg for additional formats.")
                with wave.open(str(full_path), "rb") as source:
                    source.setpos(min(source.getnframes(), round(source_seconds * source.getframerate())))
                    raw = source.readframes(round(duration * source.getframerate()))
                    with wave.open(str(slice_path), "wb") as output:
                        output.setparams(source.getparams())
                        output.writeframes(raw)
            else:
                raise OperationError("Audio analysis requires ffmpeg or macOS afconvert; neither requires Resolve Studio.")
            with wave.open(str(slice_path), "rb") as source:
                channels, rate = source.getnchannels(), source.getframerate()
                if source.getsampwidth() != 2:
                    raise OperationError("Decoder did not return 16-bit PCM audio.")
                samples = array.array("h", source.readframes(source.getnframes()))
                if sys.byteorder != "little":
                    samples.byteswap()
        except subprocess.TimeoutExpired:
            slice_path.unlink(missing_ok=True)
            raise OperationError("Audio decoding timed out; select a shorter source or install ffmpeg for efficient range decoding.")
        except Exception:
            slice_path.unlink(missing_ok=True)
            raise
        finally:
            full_path.unlink(missing_ok=True)
        count = len(samples) // channels
        if not count:
            slice_path.unlink(missing_ok=True)
            raise OperationError("No audio samples were decoded in the selected range.")
        duration = count / rate
        report = {"action": action, "item_id": info.get("id"), "clip_name": call(target, "GetName", ""),
                  "track_type": info.get("track_type"), "timecode": call(timeline, "GetCurrentTimecode", None),
                  "source_start_sec": source_seconds, "timeline_start_frame": origin, "frame_rate": fps,
                  "duration_sec": duration, "sample_rate": rate, "channels": channels,
                  "truncated": duration + 1 / fps < (clip_end - origin) / fps,
                  "scope": "source_audio", "note": "Source PCM only: excludes timeline gain, mute, fades, Fairlight effects, mixing and Fusion retiming."}
        def db(value):
            return 20 * math.log10(max(1e-6, value))
        def windows(seconds):
            size = max(1, round(rate * seconds))
            for begin in range(0, count, size):
                finish = min(count, begin + size)
                block = samples[begin * channels:finish * channels]
                energy = sum(float(s) * s for s in block) / len(block) / (32768.0 ** 2)
                yield begin / rate, finish / rate, db(math.sqrt(energy))
        def interval(begin, finish):
            relative_start, relative_end = round(begin * fps), round(finish * fps)
            return {"start_sec": begin, "end_sec": finish, "duration_sec": finish - begin,
                    "start_frame": relative_start, "end_frame": relative_end,
                    "timeline_start_frame": origin + relative_start, "timeline_end_frame": origin + relative_end}
        if action == "analyze":
            levels = []
            for channel in range(channels):
                values = samples[channel::channels]
                peak = max(abs(v) for v in values) / 32768.0
                rms = math.sqrt(sum(float(v) * v for v in values) / len(values)) / 32768.0
                levels.append({"channel": channel + 1, "peak_dbfs": round(db(peak), 2), "rms_dbfs": round(db(rms), 2), "is_clipping": peak >= 32767 / 32768})
            peak = max(level["peak_dbfs"] for level in levels)
            rms = db(math.sqrt(sum(float(v) * v for v in samples) / len(samples)) / 32768.0)
            report.update(peak_dbfs=peak, rms_dbfs=round(rms, 2), is_clipping=any(level["is_clipping"] for level in levels),
                          channel_levels=levels, health="warning_loud" if peak >= -0.5 else "warning_quiet" if rms <= -35 else "healthy")
        elif action in ("silence_cuts", "vad_clusters"):
            speech = action == "vad_clusters"
            boundary = float(params.get("threshold_db", -34)) if speech else threshold
            if not math.isfinite(boundary):
                raise OperationError("threshold_db must be finite.")
            regions, beginning = [], None
            for begin, finish, level in windows(0.05):
                selected = level > boundary if speech else level <= boundary
                if selected and beginning is None:
                    beginning = begin
                if not selected and beginning is not None:
                    if begin - beginning + 1e-9 >= (0 if speech else minimum):
                        regions.append(interval(beginning, begin))
                    beginning = None
            if beginning is not None and duration - beginning + 1e-9 >= (0 if speech else minimum):
                regions.append(interval(beginning, duration))
            report.update(threshold_db=boundary, frame_space="slice_relative; timeline_* fields are absolute", end_exclusive=True)
            report.update({"clusters" if speech else "cuts": regions, "clusters_count" if speech else "silence_intervals_count": len(regions)})
        elif action == "energy_envelope":
            envelope = [{"time_sec": begin, "rms_dbfs": round(level, 2)} for begin, _, level in windows(0.05)]
            report.update(envelope=envelope, samples_count=len(envelope))
        elif action == "onsets":
            previous, onsets = -120, []
            lead = float(params.get("lead_offset_ms", 160)) / 1000
            if not math.isfinite(lead):
                raise OperationError("lead_offset_ms must be finite.")
            for begin, _, level in windows(0.01):
                if level > -34 and level - previous > 6:
                    moment = max(0, begin - lead)
                    onsets.append({"onset_sec": moment, "frame": round(moment * fps), "timeline_frame": origin + round(moment * fps)})
                previous = level
            report.update(onsets=onsets, onsets_count=len(onsets), lead_offset_ms=lead * 1000)
        if action in ("analyze", "export_slice"):
            report["wav_path"] = str(slice_path)
        else:
            slice_path.unlink(missing_ok=True)
        return report

    def _op_change_clip_speed(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), track_hint=params.get("track_index") or "video")
        if info.get("track_type") != "video":
            raise OperationError("Fusion speed changes support video only; linked audio is unchanged.")
        supplied = [(key, params[key]) for key in ("speed", "speed_multiplier", "speed_percent", "slow_down_percent", "speed_up_percent") if params.get(key) is not None]
        if len(supplied) != 1:
            raise OperationError("Provide exactly one speed value: speed, speed_percent, slow_down_percent, or speed_up_percent.")
        key, value = supplied[0]
        try:
            speed = float(value)
            if key == "speed_percent":
                speed /= 100
            elif key == "slow_down_percent":
                speed = 1 - speed / 100
            elif key == "speed_up_percent":
                speed = 1 + speed / 100
        except (ValueError, TypeError):
            raise OperationError("Invalid speed value.")
        if not math.isfinite(speed) or speed <= 0:
            raise OperationError("speed must be finite and greater than zero.")
        method = str(params.get("method", "fusion")).lower()
        reverse = bool(params.get("reverse", False))
        if method in ("clip_attributes", "media_pool", "fps"):
            if reverse:
                raise OperationError("Clip FPS attributes cannot reverse playback.")
            media = call(item, "GetMediaPoolItem", None)
            try:
                original_fps = float(call(media, "GetClipProperty", None, "FPS"))
            except (ValueError, TypeError):
                raise OperationError("Resolve did not report the source frame rate.")
            new_fps = round(original_fps * speed, 6)
            if not math.isfinite(new_fps) or new_fps <= 0 or not call(media, "SetClipProperty", False, "FPS", str(new_fps)):
                raise OperationError("Resolve refused the new source frame rate.")
            actual = call(media, "GetClipProperty", None, "FPS")
            if actual is None or abs(float(actual) - new_fps) > 0.01:
                raise OperationError("Clip FPS read-back differs from the request. Inspect clip attributes before continuing.")
            return {"item_id": info["id"], "method": "clip_attributes_fps", "speed": speed,
                    "previous_clip_fps": original_fps, "clip_fps": actual,
                    "scope": "media_pool", "note": "Changes source interpretation for EVERY use of this media, relative to its current FPS. Does not provide a per-clip reset."}
        if method != "fusion":
            raise OperationError("method must be fusion or clip_attributes.")
        if reverse:
            raise OperationError("Reverse TimeSpeed source-range mapping is not verified; use Resolve's Change Clip Speed dialog for reverse playback.")
        comp = call(item, "GetFusionCompByIndex", None, 1)
        if not comp and abs(speed - 1) < 1e-9:
            return {"item_id": info["id"], "speed": 1.0, "changed": False, "note": "No bridge-owned speed node to reset."}
        comp = comp or call(item, "AddFusionComp", None)
        if not comp:
            raise OperationError("Could not access this clip's Fusion composition.")
        owner = "resolve-ai-bridge.change_clip_speed.v1"
        comp.Lock()
        created = False
        node = None
        output_input = None
        previous_output = None
        try:
            tools = comp.GetToolList(False) or {}
            values = list(tools.values()) if isinstance(tools, dict) else list(tools)
            owned = [tool for tool in values if call(tool, "GetData", None, "ResolveAIBridgeOwner") == owner]
            if len(owned) > 1:
                raise OperationError("Multiple bridge speed nodes found. Inspect Fusion before changing speed.")
            node = owned[0] if owned else None
            if node is None and abs(speed - 1) < 1e-9:
                return {"item_id": info["id"], "speed": 1.0, "changed": False,
                        "note": "No bridge-owned speed node to reset. Existing user/legacy TimeSpeed nodes were preserved."}
            if node is None:
                media_out = comp.FindTool("MediaOut1")
                if not media_out:
                    raise OperationError("Cannot locate MediaOut1; inspect Fusion before changing speed.")
                output_input = media_out.FindMainInput(1)
                previous_output = output_input.GetConnectedOutput() if output_input else None
                if not previous_output:
                    raise OperationError("MediaOut has no connected source; nothing was changed.")
                node = comp.AddTool("TimeSpeed")
                if not node:
                    raise OperationError("Resolve could not create the Free-compatible TimeSpeed node.")
                created = True
                node.SetAttrs({"TOOLS_Name": "ResolveAIBridgeTimeSpeed"})
                node.SetData("ResolveAIBridgeOwner", owner)
                if call(node, "GetData", None, "ResolveAIBridgeOwner") != owner:
                    raise OperationError("Could not mark the bridge-owned speed node.")
                if not node.FindMainInput(1).ConnectTo(previous_output):
                    raise OperationError("Could not connect the speed node to the existing Fusion chain.")
            # Neutral speed leaves every pre-existing connection intact.
            node.SetInput("Speed", speed)
            actual = call(node, "GetInput", None, "Speed")
            if actual is None or not math.isfinite(float(actual)) or abs(float(actual) - speed) > 1e-6:
                raise OperationError("TimeSpeed did not accept the requested speed; inspect Fusion.")
            interpolate = bool(params.get("interpolate_frames", True))
            interpolation_set = bool(call(node, "SetInput", False, "InterpolateBetweenFrames", 1.0 if interpolate else 0.0))
            if created and not output_input.ConnectTo(node.FindMainOutput(1)):
                raise OperationError("Could not connect the speed node to MediaOut.")
        except Exception:
            if created and node:
                if output_input and previous_output:
                    output_input.ConnectTo(previous_output)
                node.Delete()
            raise
        finally:
            comp.Unlock()
        return {"item_id": info["id"], "name": info.get("name"), "method": "fusion_timespeed", "speed": speed,
                "speed_percent": speed * 100, "reverse": False, "tool": getattr(node, "Name", "ResolveAIBridgeTimeSpeed"),
                "interpolate_frames": interpolate, "interpolation_set": interpolation_set,
                "note": "Video-only constant speed. Timeline duration and linked audio are unchanged. Existing Fusion connections are preserved; 1x neutralizes only the bridge-owned node."}

    def _op_create_compound_clip(self, params):
        timeline = self._timeline()
        ids = params.get("item_ids")
        if not ids:
            item_id = params.get("item_id")
            if item_id:
                ids = [item_id]
        if not ids:
            ids = ["playhead"]

        targets = self._find_timeline_items(ids)
        items = [item for item, _ in targets]

        clip_info = {}
        name = params.get("name")
        if name:
            clip_info["name"] = str(name).strip()
        tc = params.get("start_timecode")
        if tc:
            clip_info["startTimecode"] = str(tc).strip()

        created_item = timeline.CreateCompoundClip(items, clip_info) if clip_info else timeline.CreateCompoundClip(items)
        if not created_item:
            raise OperationError("Resolve could not create compound clip from the specified items.")

        new_id = self._item_id_after_rebuild(timeline, created_item) if not isinstance(created_item, bool) else None
        if not new_id and targets:
            new_id = targets[0][1].get("id")

        return {
            "created_compound_clip": {
                "id": new_id,
                "name": str(call(created_item, "GetName", clip_info.get("name", "Compound Clip"))) if not isinstance(created_item, bool) else clip_info.get("name", "Compound Clip"),
                "duration": int(call(created_item, "GetDuration", 0) or 0) if not isinstance(created_item, bool) else 0,
                "start_frame": int(call(created_item, "GetStart", 0) or 0) if not isinstance(created_item, bool) else 0,
                "end_frame": int(call(created_item, "GetEnd", 0) or 0) if not isinstance(created_item, bool) else 0,
                "unique_id": str(call(created_item, "GetUniqueId", "")) if not isinstance(created_item, bool) else "",
            },
            "source_items": [info["id"] for _, info in targets],
        }

    def _timeline_snapshot(self, timeline):
        """Read comparable structure without changing the active timeline."""
        tracks = []
        for kind in ("video", "audio", "subtitle"):
            for index in range(1, int(call(timeline, "GetTrackCount", 0, kind) or 0) + 1):
                clips = []
                for position, item in enumerate(call(timeline, "GetItemListInTrack", [], kind, index) or [], 1):
                    info = self._item_summary(item, kind, index, position)
                    # Copies have new UUIDs, but identical source ranges and properties.
                    for key in ("id", "unique_id"):
                        info.pop(key, None)
                    info["source_start"] = call(item, "GetSourceStartFrame", None)
                    info["source_end"] = call(item, "GetSourceEndFrame", None)
                    info["properties"] = plain(call(item, "GetProperty", {}) or {})
                    info["fusion_count"] = call(item, "GetFusionCompCount", 0)
                    clips.append(info)
                tracks.append({"type": kind, "index": index, "name": call(timeline, "GetTrackName", "", kind, index),
                               "enabled": call(timeline, "GetIsTrackEnabled", None, kind, index),
                               "locked": call(timeline, "GetIsTrackLocked", None, kind, index), "clips": clips})
        return {"start": call(timeline, "GetStartFrame", None), "end": call(timeline, "GetEndFrame", None),
                "settings": {key: call(timeline, "GetSetting", None, key) for key in ("timelineFrameRate", "timelineResolutionWidth", "timelineResolutionHeight")},
                "tracks": tracks}

    def _timeline_fingerprint(self, timeline):
        import hashlib
        return hashlib.sha256(json.dumps(self._timeline_snapshot(timeline), sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _timeline_identity(timeline):
        return {"id": call(timeline, "GetUniqueId", None), "name": call(timeline, "GetName", "")}

    def _duplicate_current(self, name, open_duplicate=True):
        project, original = self._project(), self._timeline()
        before = self._timeline_snapshot(original)
        unique_name = "%s — %s" % (str(name or (original.GetName() + " preview"))[:120], uuid.uuid4().hex[:8])
        duplicate = call(original, "DuplicateTimeline", None, unique_name)
        if duplicate is None or isinstance(duplicate, bool):
            raise OperationError("Timeline duplication is unavailable on this Resolve build; no edit was attempted.")
        try:
            if self._timeline_snapshot(duplicate) != before:
                raise OperationError("The duplicate did not match the original timeline structure; no edit was attempted.")
            if self._timeline_snapshot(original) != before:
                raise OperationError("Timeline changed while it was being copied; inspect both timelines before editing.")
            target = duplicate if open_duplicate else original
            if not project.SetCurrentTimeline(target):
                raise OperationError("Could not open the requested timeline after duplication.")
        except Exception:
            project.SetCurrentTimeline(original)
            raise
        return duplicate, self._timeline_identity(duplicate)

    def _op_preview_timeline(self, params):
        original = self._timeline_identity(self._timeline())
        _, preview = self._duplicate_current(params.get("name"), open_duplicate=True)
        return {"original": original, "preview": preview, "active": "preview",
                "note": "Original retained. Call timeline_overview for NEW clip IDs, apply edits to the preview, then compare_timelines. No edits have been applied yet."}

    def _find_timeline(self, identifier):
        matches = []
        project = self._project()
        for index in range(1, int(project.GetTimelineCount() or 0) + 1):
            item = project.GetTimelineByIndex(index)
            if str(identifier) in (str(call(item, "GetUniqueId", None)), str(call(item, "GetName", ""))):
                matches.append(item)
        if len(matches) != 1:
            raise OperationError("Timeline identifier is missing or ambiguous. Use a unique ID from list_timelines.")
        return matches[0]

    def _op_compare_timelines(self, params):
        original = self._find_timeline(params.get("original"))
        preview = self._find_timeline(params.get("preview"))
        before, after = self._timeline_snapshot(original), self._timeline_snapshot(preview)
        changes = []
        for key in ("start", "end", "settings"):
            if before[key] != after[key]:
                changes.append({"field": key, "before": before[key], "after": after[key]})
        old = {(track["type"], track["index"]): track for track in before["tracks"]}
        new = {(track["type"], track["index"]): track for track in after["tracks"]}
        for key in sorted(old.keys() | new.keys()):
            if old.get(key) != new.get(key):
                changes.append({"track": "%s%d" % key, "before": old.get(key), "after": new.get(key)})
        before_markers = plain(call(original, "GetMarkers", {}) or {})
        after_markers = plain(call(preview, "GetMarkers", {}) or {})
        if before_markers != after_markers:
            changes.append({"field": "markers", "before": before_markers, "after": after_markers})
        return {"original": self._timeline_identity(original), "preview": self._timeline_identity(preview),
                "structurally_equal": not changes, "changes": changes,
                "limitations": "Compares tracks, ranges, source references, readable clip properties, Fusion counts and markers. Does not compare rendered pixels, internal Fusion graphs, full color grades or Fairlight processing."}

    def _op_project_health(self, params):
        timeline, project = self._timeline(), self._project()
        findings = []
        start, end = float(timeline.GetStartFrame()), float(timeline.GetEndFrame())
        for track in self._timeline_snapshot(timeline)["tracks"]:
            label = "%s%d" % (track["type"], track["index"])
            if track["enabled"] is False:
                findings.append({"type": "disabled_track", "track": label, "severity": "info"})
            if track["locked"]:
                findings.append({"type": "locked_track", "track": label, "severity": "info"})
            cursor = start
            for clip in sorted(track["clips"], key=lambda clip: clip["start"]):
                if clip["enabled"] is False:
                    findings.append({"type": "disabled_clip", "clip": clip["label"], "severity": "info"})
                if clip["start"] > cursor:
                    findings.append({"type": "gap", "track": label, "start_frame": cursor, "end_frame": clip["start"], "severity": "info"})
                cursor = max(cursor, clip["end"])
            if track["clips"] and cursor < end:
                findings.append({"type": "gap", "track": label, "start_frame": cursor, "end_frame": end, "severity": "info"})
        seen = set()
        for item, info in self._timeline_items():
            media = call(item, "GetMediaPoolItem", None)
            path = call(media, "GetClipProperty", "", "File Path")
            if path and not Path(path).exists() and path not in seen:
                findings.append({"type": "missing_source", "item_id": info["id"], "path": path, "severity": "warning"})
                seen.add(path)
        expected_fps = params.get("expected_frame_rate")
        expected_width, expected_height = params.get("expected_width"), params.get("expected_height")
        width, height = self._project_resolution()
        for field, actual, expected in (("frame_rate", self._project_rate(), expected_fps), ("width", width, expected_width), ("height", height, expected_height)):
            if expected is not None and abs(float(actual) - float(expected)) > 0.01:
                findings.append({"type": "delivery_mismatch", "field": field, "actual": actual, "expected": expected, "severity": "warning"})
        return {"project": project.GetName(), "timeline": self._timeline_identity(timeline), "findings": findings,
                "warning_count": sum(f["severity"] == "warning" for f in findings),
                "scope": "Active timeline. Gaps/disabled tracks can be intentional. Missing-file checks may flag image-sequence patterns. Delivery settings are compared only with the expectations you supply; this does not inspect Fairlight mute automation or queued render settings."}

    def _op_bridge_capabilities(self, _params):
        import shutil
        instance = self.resolve
        project = call(call(instance, "GetProjectManager", None), "GetCurrentProject", None)
        timeline = call(project, "GetCurrentTimeline", None)
        return {"bridge_version": AGENT_VERSION, "resolve_version": call(instance, "GetVersionString", None),
                "product": call(instance, "GetProductName", None), "transport": self.transport,
                "timeline_open": timeline is not None,
                "api_present": {method: callable(getattr(timeline, method, None)) if timeline is not None else None for method in ("DuplicateTimeline", "GetMarkers", "AddMarker", "DeleteClips", "GetUniqueId")},
                "source_frame_decoder": self._ffmpeg_path() is not None,
                "source_audio_decoder": bool(self._ffmpeg_path() or shutil.which("afconvert")),
                "free_workflow": "Start the Console worker inside Resolve Free. These review tools use regular timeline/marker APIs and external source decoding; no Studio AI features are used.",
                "limitations": ["API presence is not proof a call will succeed on this build; each operation checks its result.",
                                "Composite frame export is attempted at capture time; source fallback needs ffmpeg and excludes timeline effects.",
                                "Audio analysis reads source PCM, not the processed timeline mix.",
                                "Dialogue cut application supports an isolated clip or one aligned video/audio pair; complex timelines receive markers for manual review."]}

    def _op_review_silence(self, params):
        timeline = self._timeline()
        fingerprint = self._timeline_fingerprint(timeline)
        analysis_params = dict(params, action="silence_cuts", whole_clip=True)
        analysis = self._op_timeline_audio(analysis_params)
        if self._timeline_fingerprint(timeline) != fingerprint:
            raise OperationError("Timeline changed during analysis; no markers were added. Inspect the timeline and retry.")
        existing = call(timeline, "GetMarkers", {}) or {}
        markers, skipped = [], []
        timeline_start = float(timeline.GetStartFrame())
        for cut in analysis["cuts"]:
            start, end = cut["timeline_start_frame"], cut["timeline_end_frame"]
            marker_frame = start - timeline_start
            if end <= start or marker_frame in existing or str(marker_frame) in existing:
                skipped.append(cut)
                continue
            marker_id = uuid.uuid4().hex
            data = {"bridge": "silence-review-v1", "id": marker_id, "timeline_id": call(timeline, "GetUniqueId", None),
                    "fingerprint": fingerprint, "item_id": analysis["item_id"], "start": start, "end": end}
            ok = timeline.AddMarker(marker_frame, "Yellow", "Review silence", "Source audio appears silent; review before cutting.", end - start, json.dumps(data))
            if ok:
                markers.append(dict(cut, marker_id=marker_id, marker_frame=marker_frame))
            else:
                skipped.append(cut)
        return {"item_id": analysis["item_id"], "timeline": self._timeline_identity(timeline), "markers": markers,
                "skipped": skipped, "analysis_truncated": analysis["truncated"],
                "note": "Markers only; no clips removed. Audition candidates, then pass selected marker_ids to apply_silence_cuts. Selection applies on a new duplicate timeline."}

    def _op_apply_silence_cuts(self, params):
        """Apply reviewed ranges only to a dedicated dialogue clip or aligned AV pair."""
        timeline = self._timeline()
        wanted = params.get("marker_ids") or []
        if not wanted or len(wanted) != len(set(wanted)):
            raise OperationError("Provide a nonempty list of distinct reviewed marker_ids.")
        fingerprint = self._timeline_fingerprint(timeline)
        reviews = {}
        for marker in (call(timeline, "GetMarkers", {}) or {}).values():
            try:
                data = json.loads(marker.get("customData", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("bridge") == "silence-review-v1":
                reviews[data.get("id")] = data
        selected = []
        for key in wanted:
            data = reviews.get(key)
            if not data or data.get("timeline_id") != call(timeline, "GetUniqueId", None) or data.get("fingerprint") != fingerprint:
                raise OperationError("A review marker is missing or stale. Run review_silence again after timeline edits.")
            selected.append(data)
        if len({data["item_id"] for data in selected}) != 1:
            raise OperationError("Select review markers from one dialogue clip at a time.")
        targets = self._timeline_items()
        # Whole-timeline ripple across arbitrary clips is deliberately not guessed.
        if not 1 <= len(targets) <= 2 or any(info["track_type"] not in ("audio", "video") for _, info in targets):
            raise OperationError("Automatic cleanup needs an isolated dialogue clip or one aligned video/audio pair. Use the review markers for manual cuts on this multi-clip timeline.")
        starts = {info["start"] for _, info in targets}
        ends = {info["end"] for _, info in targets}
        if len(starts) != 1 or len(ends) != 1 or (len(targets) == 2 and {info["track_type"] for _, info in targets} != {"audio", "video"}):
            raise OperationError("The video/audio pair must have identical timeline boundaries.")
        start, end = float(next(iter(starts))), float(next(iter(ends)))
        if not start.is_integer() or not end.is_integer():
            raise OperationError("Subframe clip boundaries cannot be rebuilt by this workflow.")
        start, end = int(start), int(end)
        ranges = sorted((int(data["start"]), int(data["end"])) for data in selected)
        if any(a < start or b > end or a >= b for a, b in ranges) or any(ranges[i][0] < ranges[i-1][1] for i in range(1, len(ranges))):
            raise OperationError("Selected silence ranges are invalid or overlap.")
        kept, cursor = [], start
        for begin, finish in ranges:
            if begin > cursor:
                kept.append((cursor, begin))
            cursor = finish
        if cursor < end:
            kept.append((cursor, end))
        if not kept:
            raise OperationError("These cuts would remove the entire dialogue clip. Nothing was changed.")
        originals = []
        for item, info in targets:
            if call(item, "GetFusionCompCount", 0) or call(timeline, "GetIsTrackLocked", False, info["track_type"], info["track_index"]):
                raise OperationError("Unlock tracks and use dialogue clips without Fusion compositions for automatic cleanup.")
            self._source_window(item, start)
            media = call(item, "GetMediaPoolItem", None)
            source = call(item, "GetSourceStartFrame", None)
            raw_fps = call(media, "GetClipProperty", None, "FPS")
            if media is None or source is None or (raw_fps and abs(float(raw_fps) - self._project_rate()) > 0.01):
                raise OperationError("Cannot safely rebuild this source range or mixed frame rate.")
            originals.append((item, info, media, int(source), self._read_transform(item)))
        original_identity = self._timeline_identity(timeline)
        preview, preview_identity = self._duplicate_current(params.get("name") or "Dialogue cleanup", open_duplicate=True)
        try:
            copied = [item for item, _ in self._timeline_items()]
            if not preview.DeleteClips(copied, False):
                raise OperationError("Resolve refused to replace the copied dialogue clips.")
            batches = []
            record = start
            for begin, finish in kept:
                segment_items = []
                for original, info, media, source, transform in originals:
                    request = {"mediaPoolItem": media, "startFrame": source + begin - start,
                               "endFrame": source + finish - start - 1, "recordFrame": record,
                               "trackIndex": info["track_index"], "mediaType": 1 if info["track_type"] == "video" else 2}
                    created = self._media_pool().AppendToTimeline([request]) or []
                    if len(created) != 1 or call(created[0], "GetStart", None) != record or call(created[0], "GetEnd", None) != record + finish - begin:
                        raise OperationError("Resolve returned an incorrect rebuilt dialogue segment.")
                    piece = created[0]
                    _, rejected = self._apply_transform(piece, transform_params_from_props(transform))
                    if rejected:
                        raise OperationError("Could not restore the dialogue transform.")
                    if info.get("enabled") is not None and not call(piece, "SetClipEnabled", False, info["enabled"]):
                        raise OperationError("Could not restore enabled state.")
                    if info.get("color") and not call(piece, "SetClipColor", False, info["color"]):
                        raise OperationError("Could not restore clip color.")
                    if info["track_type"] == "video" and not call(original, "CopyGrades", False, [piece]):
                        raise OperationError("Could not copy the current grade layer.")
                    segment_items.append(piece)
                if len(segment_items) == 2 and not preview.SetClipsLinked(segment_items, True):
                    raise OperationError("Could not link the rebuilt video/audio segment.")
                batches.append({"start": record, "end": record + finish - begin, "item_ids": [call(piece, "GetUniqueId", None) for piece in segment_items]})
                record += finish - begin
            # Markers refer to the original timing. Clear only bridge review markers on the copy;
            # other markers remain, explicitly reported below rather than silently re-timed.
            for offset, marker in (call(preview, "GetMarkers", {}) or {}).items():
                try:
                    data = json.loads(marker.get("customData", ""))
                    if isinstance(data, dict) and data.get("bridge") == "silence-review-v1":
                        if not preview.DeleteMarkerAtFrame(offset):
                            raise OperationError("Could not remove stale review markers on the preview.")
                except (ValueError, TypeError):
                    pass
        except Exception as exc:
            reopened = bool(self._project().SetCurrentTimeline(timeline))
            raise OperationError("Dialogue cleanup failed: %s. Original '%s' is intact%s. Partial preview '%s' retained for inspection."
                                 % (exc, original_identity["name"], " and reopened" if reopened else "; open it manually", preview_identity["name"]))
        return {"original": original_identity, "preview": preview_identity, "removed_frames": sum(b-a for a, b in ranges),
                "segments": batches, "selected_marker_ids": wanted,
                "note": "Original retained. Only selected intervals removed, with remaining segments closed up. Current grade layer and static transforms copied. Review fades, audio gain, other grade layers, clip metadata and any non-review markers before accepting the preview."}


    # ------------------------------------------------------------- dispatch

    def handlers(self):
        return {
            "status": self._op_status,
            "preview_timeline": self._op_preview_timeline,
            "compare_timelines": self._op_compare_timelines,
            "project_health": self._op_project_health,
            "bridge_capabilities": self._op_bridge_capabilities,
            "review_silence": self._op_review_silence,
            "apply_silence_cuts": self._op_apply_silence_cuts,
            "project_info": self._op_project_info,
            "list_timelines": self._op_list_timelines,
            "open_timeline": self._op_open_timeline,
            "timeline_overview": self._op_timeline_overview,
            "list_media": self._op_list_media,
            "import_media": self._op_import_media,
            "append_media": self._op_append_media,
            "add_image": self._op_add_image,
            "insert_title": self._op_insert_title,
            "set_clip_transform": self._op_set_clip_transform,
            "get_clip_transform": self._op_get_clip_transform,
            "split_clip": self._op_split_clip,
            "animate_zoom": self._op_animate_zoom,
            "add_track": self._op_add_track,
            "set_track_name": self._op_set_track_name,
            "create_timeline": self._op_create_timeline,
            "set_playhead": self._op_set_playhead,
            "open_page": self._op_open_page,
            "add_marker": self._op_add_marker,
            "delete_marker": self._op_delete_marker,
            "set_clip_property": self._op_set_clip_property,
            "set_clip_enabled": self._op_set_clip_enabled,
            "set_clip_color": self._op_set_clip_color,
            "get_clip_grade": self._op_get_clip_grade,
            "set_clip_grade": self._op_set_clip_grade,
            "keyframe_clip_saturation": self._op_keyframe_clip_saturation,
            "animate_color_fx": self._op_animate_color_fx,
            "apply_blur_effect": self._op_apply_blur_effect,
            "apply_spotlight_mask": self._op_apply_spotlight_mask,
            "apply_mask": self._op_apply_spotlight_mask,
            "inspect_fusion": self._op_inspect_fusion,
            "delete_clips": self._op_delete_clips,
            "save_project": self._op_save_project,
            "list_render_presets": self._op_list_render_presets,
            "render_current_timeline": self._op_render_current_timeline,
            "timeline_frame": self._op_timeline_frame,
            "timeline_audio": self._op_timeline_audio,
            "create_compound_clip": self._op_create_compound_clip,
            "change_clip_speed": self._op_change_clip_speed,
        }

    def dispatch(self, operation, params=None):
        handlers = self.handlers()
        handler = handlers.get(str(operation))
        if handler is None:
            raise OperationError(
                "Unknown operation '%s'. Available: %s" % (operation, ", ".join(sorted(handlers)))
            )
        return plain(handler(params or {}))

    def queue_context(self):
        project = self.resolve.GetProjectManager().GetCurrentProject()
        timeline = project.GetCurrentTimeline() if project is not None else None
        def identity(obj):
            if obj is None:
                return None
            value = call(obj, "GetUniqueId", None)
            if not value:
                raise OperationError("Stable project/timeline identity unavailable; queued edits refused.")
            return str(value)
        return {"project_id": identity(project), "timeline_id": identity(timeline)}

    def heartbeat_payload(self, extra=None):
        payload = self._op_status({})
        payload.update({"pid": os.getpid(), "time": time.time()})
        if extra:
            payload.update(extra)
        return plain(payload)
