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
import os
import time
from pathlib import Path


AGENT_VERSION = "1.9.0"
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
        raw = call(self._project(), "GetSetting", "24", "timelineFrameRate") or "24"
        try:
            return float(str(raw).replace(" DF", "").strip())
        except ValueError:
            return 24.0

    def _project_resolution(self):
        project = self._project()
        try:
            width = int(call(project, "GetSetting", 1920, "timelineResolutionWidth") or 1920)
            height = int(call(project, "GetSetting", 1080, "timelineResolutionHeight") or 1080)
        except (TypeError, ValueError):
            width, height = 1920, 1080
        return width, height

    def _tc_frames(self, value, fps):
        parts = str(value).replace(";", ":").split(":")
        if len(parts) != 4:
            return 0
        try:
            hours, minutes, seconds, frames = [int(part) for part in parts]
        except ValueError:
            return 0
        rounded = max(1, int(round(fps)))
        return ((hours * 3600 + minutes * 60 + seconds) * rounded) + frames

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
        return {
            "id": "%s%d.%d" % (prefix, track_index, item_index),
            "unique_id": call(item, "GetUniqueId", None),
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
                if identifier in (str(info.get("id")), str(info.get("unique_id")), str(info.get("name")))
            ]
            if not matches:
                missing.append(identifier)
                continue
            exact = next(
                (
                    match
                    for match in matches
                    if match[1].get("id") == identifier or str(match[1].get("unique_id")) == identifier
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
            if int(start) <= frame <= int(end):
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
        """Best-effort id (like V1.2) for a freshly appended timeline item."""
        unique = call(created_item, "GetUniqueId", None)
        if unique is not None:
            for _, info in self._timeline_items():
                if str(info.get("unique_id")) == str(unique):
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
        return {
            "name": project.GetName(),
            "timeline": call(timeline, "GetName", None) if timeline else None,
            "timeline_count": call(project, "GetTimelineCount", 0),
            "frame_rate": call(project, "GetSetting", None, "timelineFrameRate"),
            "resolution_width": call(project, "GetSetting", None, "timelineResolutionWidth"),
            "resolution_height": call(project, "GetSetting", None, "timelineResolutionHeight"),
        }

    def _op_list_timelines(self, _params):
        project = self._project()
        current = project.GetCurrentTimeline()
        timelines = []
        for index in range(1, int(project.GetTimelineCount() or 0) + 1):
            item = project.GetTimelineByIndex(index)
            timelines.append({
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
        selected = None
        for item_index in range(1, int(project.GetTimelineCount() or 0) + 1):
            item = project.GetTimelineByIndex(item_index)
            if (index is not None and int(index) == item_index) or (name and item.GetName() == name):
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
        """Cut one timeline clip into two at a frame, synthesised from documented API.

        Resolve exposes no razor/split/trim call, so a cut is rebuilt: read the
        clip's source range and transform, delete it, then re-append the two
        halves at their original positions and re-apply the transform. Color
        grades and Fusion compositions on the clip are NOT carried onto the
        halves, because the API cannot copy them; that is reported in the result.
        """
        timeline = self._timeline()
        item, info = self._resolve_one_item(params.get("item_id"), params.get("track_index"))

        track_type = info.get("track_type")
        if track_type not in ("video", "audio"):
            raise OperationError(
                "split_clip works on video or audio clips. '%s' is a %s clip."
                % (info["id"], track_type)
            )

        clip_start = info.get("start")
        clip_end = info.get("end")
        duration = call(item, "GetDuration", None)
        if clip_start is None or clip_end is None or not duration:
            raise OperationError(
                "Resolve did not report this clip's frame range, so it cannot be split safely."
            )
        clip_start = int(clip_start)
        clip_end = int(clip_end)
        total_len = int(duration)

        # Where to cut, as an absolute timeline frame (the first frame of the
        # right-hand piece). Accept an explicit frame, a timecode, or the playhead.
        frame = params.get("frame")
        if frame is None and params.get("timecode"):
            fps = self._project_rate()
            frame = int(call(timeline, "GetStartFrame", 0) or 0) + max(
                0,
                self._tc_frames(params["timecode"], fps)
                - self._tc_frames(call(timeline, "GetStartTimecode", "00:00:00:00"), fps),
            )
        if frame is None:
            frame = self._playhead_frame(timeline)
        frame = int(frame)

        if not (clip_start < frame < clip_end):
            raise OperationError(
                "The cut frame %d is not inside clip %s (timeline frames %d..%d). Move the "
                "playhead onto the clip, or pass a frame strictly between its start and end."
                % (frame, info["id"], clip_start, clip_end - 1)
            )

        media_item = call(item, "GetMediaPoolItem", None)
        if media_item is None:
            raise OperationError(
                "Clip %s has no media pool source (it may be a generator, title, or compound "
                "clip). Those cannot be split by this tool yet." % info["id"]
            )
        source_start = call(item, "GetSourceStartFrame", None)
        if source_start is None:
            raise OperationError("Resolve did not report the clip's source start frame.")
        source_start = int(source_start)

        left_len = frame - clip_start
        right_len = total_len - left_len
        media_type = 1 if track_type == "video" else 2

        left_info = {
            "mediaPoolItem": media_item,
            "startFrame": source_start,
            "endFrame": source_start + left_len - 1,
            "recordFrame": clip_start,
            "trackIndex": int(info["track_index"]),
            "mediaType": media_type,
        }
        right_info = {
            "mediaPoolItem": media_item,
            "startFrame": source_start + left_len,
            "endFrame": source_start + total_len - 1,
            "recordFrame": frame,
            "trackIndex": int(info["track_index"]),
            "mediaType": media_type,
        }

        # Preserve the Edit-page transform so the two halves look like the original.
        transform = self._read_transform(item)

        pool = self._media_pool()
        if not timeline.DeleteClips([item], False):
            raise OperationError("Resolve refused to remove the original clip, so nothing was cut.")

        created = pool.AppendToTimeline([left_info, right_info]) or []
        if len(created) < 2:
            # Try to put the original back so a failed cut is not destructive.
            recovery = {
                "mediaPoolItem": media_item,
                "startFrame": source_start,
                "endFrame": source_start + total_len - 1,
                "recordFrame": clip_start,
                "trackIndex": int(info["track_index"]),
                "mediaType": media_type,
            }
            pool.AppendToTimeline([recovery])
            raise OperationError(
                "Resolve rebuilt %d of 2 halves, so the cut was rolled back to the original clip. "
                "This can happen if the neighbouring space is occupied." % len(created)
            )

        halves = []
        for piece, when in zip(created, ("left", "right")):
            self._apply_transform(piece, transform_params_from_props(transform))
            halves.append({
                "side": when,
                "id": self._item_id_after_rebuild(timeline, piece),
                "start": call(piece, "GetStart", None),
                "end": call(piece, "GetEnd", None),
                "duration": call(piece, "GetDuration", None),
            })

        return {
            "original": info["id"],
            "cut_frame": frame,
            "halves": halves,
            "transform_preserved": bool(transform),
            "note": (
                "Cut done by rebuilding the clip as two pieces. Position, scale, rotation, crop and "
                "opacity were re-applied. Color-page grades and Fusion compositions on the original "
                "are not copied onto the halves; re-grade if needed."
            ),
        }

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

    def _op_timeline_frame(self, params):
        import base64
        import shutil
        import subprocess
        import tempfile
        import time

        timeline = self._timeline()
        project = self._project()
        fps = self._project_rate()

        # 1. Handle optional seek if timecode or frame was provided
        requested_tc = params.get("timecode")
        requested_frame = params.get("frame")
        if requested_tc:
            timeline.SetCurrentTimecode(str(requested_tc).strip())
        elif requested_frame is not None:
            try:
                f_int = int(requested_frame)
                start_tc = call(timeline, "GetStartTimecode", "01:00:00:00")
                start_f = self._tc_frames(start_tc, fps)
                target_total_f = start_f + f_int
                r_fps = max(1, int(round(fps)))
                hrs = target_total_f // (3600 * r_fps)
                rem = target_total_f % (3600 * r_fps)
                mins = rem // (60 * r_fps)
                rem = rem % (60 * r_fps)
                secs = rem // r_fps
                frames = rem % r_fps
                tc_str = "%02d:%02d:%02d:%02d" % (hrs, mins, secs, frames)
                timeline.SetCurrentTimecode(tc_str)
            except Exception:
                pass

        current_tc = call(timeline, "GetCurrentTimecode", "00:00:00:00")
        current_frame = self._current_marker_frame(timeline)
        max_width = int(params.get("max_width") or 1280)
        mode = str(params.get("mode", "auto")).lower()
        fmt = str(params.get("format", "jpg")).lower().lstrip(".")
        if fmt not in ("jpg", "jpeg", "png"):
            fmt = "jpg"

        capture_dir = Path(tempfile.gettempdir()) / "resolve-frame-captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        temp_img = capture_dir / ("frame_%d_%s.%s" % (int(time.time() * 1000), current_tc.replace(":", "_"), fmt))

        extracted = False
        method_used = "unknown"
        clip_name = None

        # Attempt Tier 1: Native Direct Export (if mode is auto or composite)
        if mode in ("auto", "composite"):
            try:
                ok = call(project, "ExportCurrentFrameAsStill", False, str(temp_img))
                if ok and temp_img.exists() and temp_img.stat().st_size > 0:
                    extracted = True
                    method_used = "export_current_frame_as_still"
            except Exception:
                pass

        # Attempt Tier 2: Source Media Hardware Offset (if Tier 1 didn't succeed or mode is source)
        if not extracted and mode in ("auto", "source"):
            video_tracks = int(call(timeline, "GetTrackCount", 0, "video") or 0)
            target_item = None
            for t_idx in range(video_tracks, 0, -1):
                if not call(timeline, "GetIsTrackEnabled", True, "video", t_idx):
                    continue
                track_items = call(timeline, "GetItemListInTrack", [], "video", t_idx) or []
                for item in track_items:
                    start_f = call(item, "GetStart", None)
                    end_f = call(item, "GetEnd", None)
                    if start_f is not None and end_f is not None and start_f <= current_frame < end_f:
                        target_item = item
                        break
                if target_item is not None:
                    break

            if target_item is not None:
                clip_name = call(target_item, "GetName", "")
                media_item = call(target_item, "GetMediaPoolItem", None)
                file_path = call(media_item, "GetClipProperty", "", "File Path") if media_item else ""
                if file_path and Path(file_path).exists():
                    left_offset = call(target_item, "GetLeftOffset", 0) or 0
                    start_f = call(target_item, "GetStart", 0) or 0
                    source_frame = (current_frame - start_f) + left_offset
                    source_sec = max(0.0, float(source_frame) / max(1.0, fps))

                    try:
                        import cv2
                        cap = cv2.VideoCapture(str(file_path))
                        if cap.isOpened():
                            cap.set(cv2.CAP_PROP_POS_MSEC, source_sec * 1000.0)
                            ret, frame_img = cap.read()
                            cap.release()
                            if ret and frame_img is not None:
                                cv2.imwrite(str(temp_img), frame_img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                                if temp_img.exists() and temp_img.stat().st_size > 0:
                                    extracted = True
                                    method_used = "source_math_cv2"
                    except Exception:
                        pass

                    if not extracted:
                        ffmpeg_bin = shutil.which("ffmpeg")
                        if ffmpeg_bin:
                            cmd = [
                                ffmpeg_bin, "-y", "-ss", f"{source_sec:.3f}",
                                "-i", str(file_path), "-vframes", "1",
                                "-q:v", "2", str(temp_img)
                            ]
                            res = subprocess.run(cmd, capture_output=True)
                            if res.returncode == 0 and temp_img.exists() and temp_img.stat().st_size > 0:
                                extracted = True
                                method_used = "source_math_ffmpeg"

        if not extracted:
            raise OperationError(
                "Could not capture timeline frame at %s. Ensure Resolve is open with active media."
                % current_tc
            )

        width, height = 1920, 1080
        if max_width > 0:
            try:
                import cv2
                img = cv2.imread(str(temp_img))
                if img is not None:
                    orig_h, orig_w = img.shape[:2]
                    if orig_w > max_width:
                        ratio = max_width / float(orig_w)
                        new_h = int(orig_h * ratio)
                        resized = cv2.resize(img, (max_width, new_h), interpolation=cv2.INTER_AREA)
                        cv2.imwrite(str(temp_img), resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                        width, height = max_width, new_h
                    else:
                        width, height = orig_w, orig_h
            except Exception:
                pass

        with open(temp_img, "rb") as f:
            raw_bytes = f.read()
        b64_data = base64.b64encode(raw_bytes).decode("ascii")

        return {
            "timecode": current_tc,
            "frame": current_frame,
            "clip_name": clip_name,
            "method": method_used,
            "width": width,
            "height": height,
            "format": fmt,
            "image_base64": b64_data,
            "file_path": str(temp_img),
        }

    def _op_timeline_audio(self, params):
        import math
        import shutil
        import struct
        import subprocess
        import tempfile
        import time
        import wave

        timeline = self._timeline()
        fps = self._project_rate()
        action = str(params.get("action", "analyze")).lower()
        threshold_db = float(params.get("silence_threshold_db", -40.0))
        min_silence_duration = float(params.get("min_silence_duration", 0.3))
        track_index = int(params.get("track_index", 1)) if "track_index" in params else None

        # 1. Determine target item or active playhead frame
        requested_item_id = params.get("item_id")
        if requested_item_id:
            target_item, _ = self._find_timeline_items([requested_item_id])[0]
            target_track_type = "audio"
        else:
            target_item = None

        requested_tc = params.get("timecode")
        if requested_tc:
            timeline.SetCurrentTimecode(str(requested_tc).strip())
        current_frame = self._playhead_frame(timeline)
        current_tc = call(timeline, "GetCurrentTimecode", "00:00:00:00")

        # 2. Find target audio or video clip on timeline covering playhead
        if target_item is None:
            target_track_type = "audio"
            audio_tracks = int(call(timeline, "GetTrackCount", 0, "audio") or 0)
            video_tracks = int(call(timeline, "GetTrackCount", 0, "video") or 0)

            # Check audio tracks first
            track_search_range = [track_index] if (track_index and 1 <= track_index <= audio_tracks) else range(1, audio_tracks + 1)
            for a_idx in track_search_range:
                items = call(timeline, "GetItemListInTrack", [], "audio", a_idx) or []
                for item in items:
                    s = call(item, "GetStart", None)
                    e = call(item, "GetEnd", None)
                    if s is not None and e is not None and s <= current_frame < e:
                        # Ensure media pool item has accessible file on disk
                        mp = item.GetMediaPoolItem()
                        fp = (call(mp, "GetClipProperty", {}) or {}).get("File Path")
                        if fp and Path(fp).exists():
                            target_item = item
                            target_track_type = "audio"
                            break
                if target_item is not None:
                    break

            # If not under playhead in audio tracks, check video tracks
            if target_item is None:
                v_search_range = [track_index] if (track_index and 1 <= track_index <= video_tracks) else range(1, video_tracks + 1)
                for v_idx in v_search_range:
                    items = call(timeline, "GetItemListInTrack", [], "video", v_idx) or []
                    for item in items:
                        s = call(item, "GetStart", None)
                        e = call(item, "GetEnd", None)
                        if s is not None and e is not None and s <= current_frame < e:
                            target_item = item
                            target_track_type = "video"
                            break
                    if target_item is not None:
                        break

            # Fallback to first available clip with media on disk
            if target_item is None:
                a_fallback_range = [track_index] if (track_index and 1 <= track_index <= audio_tracks) else range(1, audio_tracks + 1)
                for a_idx in a_fallback_range:
                    items = call(timeline, "GetItemListInTrack", [], "audio", a_idx) or []
                    for it in items:
                        mp = it.GetMediaPoolItem()
                        fp = (call(mp, "GetClipProperty", {}) or {}).get("File Path")
                        if fp and Path(fp).exists():
                            target_item = it
                            target_track_type = "audio"
                            break
                    if target_item is not None:
                        break
            if target_item is None:
                for v_idx in range(1, video_tracks + 1):
                    items = call(timeline, "GetItemListInTrack", [], "video", v_idx) or []
                    if items:
                        target_item = items[0]
                        target_track_type = "video"
                        break

        if target_item is None:
            raise OperationError("No audio or video clips found on the active timeline.")

        clip_name = call(target_item, "GetName", "")
        media_item = call(target_item, "GetMediaPoolItem", None)
        file_path = call(media_item, "GetClipProperty", "", "File Path") if media_item else ""

        if not file_path or not Path(file_path).exists():
            raise OperationError("Media file for clip '%s' is offline or missing on disk." % clip_name)

        # 3. Calculate exact trimmed source offset
        clip_start = call(target_item, "GetStart", 0) or 0
        clip_end = call(target_item, "GetEnd", 0) or 0
        clip_duration = call(target_item, "GetDuration", 0) or max(1, clip_end - clip_start)
        left_offset = call(target_item, "GetLeftOffset", 0) or 0

        # Calculate where in the source media file the active playhead is
        if clip_start <= current_frame < clip_end:
            source_frame_start = (current_frame - clip_start) + left_offset
            remaining_frames = clip_end - current_frame
        else:
            source_frame_start = left_offset
            remaining_frames = clip_duration

        source_start_sec = max(0.0, float(source_frame_start) / max(1.0, fps))
        duration_sec = max(0.1, float(remaining_frames) / max(1.0, fps))

        # Extract to temporary WAV file using afconvert or ffmpeg
        audio_dir = Path(tempfile.gettempdir()) / "resolve-audio-analysis"
        audio_dir.mkdir(parents=True, exist_ok=True)
        temp_wav = audio_dir / ("audio_%d.wav" % int(time.time() * 1000))

        extracted = False
        afconvert_bin = shutil.which("afconvert")
        if afconvert_bin:
            cmd = [afconvert_bin, "-f", "WAVE", "-d", "LEI16@48000", "-c", "2", str(file_path), str(temp_wav)]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and temp_wav.exists() and temp_wav.stat().st_size > 44:
                extracted = True

        if not extracted:
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                cmd = [ffmpeg_bin, "-y", "-i", str(file_path), "-vn", "-ac", "2", "-ar", "48000", "-f", "wav", str(temp_wav)]
                res = subprocess.run(cmd, capture_output=True)
                if res.returncode == 0 and temp_wav.exists() and temp_wav.stat().st_size > 44:
                    extracted = True

        if not extracted:
            raise OperationError("Could not decode audio from media file '%s'." % file_path)

        # Read only the trimmed playhead slice
        with wave.open(str(temp_wav), "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            total_wav_frames = wf.getnframes()

            start_wav_pos = min(total_wav_frames, max(0, int(source_start_sec * sample_rate)))
            frames_to_read = min(total_wav_frames - start_wav_pos, int(duration_sec * sample_rate))

            wf.setpos(start_wav_pos)
            raw_bytes = wf.readframes(frames_to_read)

        num_samples = len(raw_bytes) // (2 * channels)
        fmt = "<%dh" % (num_samples * channels)
        raw_ints = struct.unpack(fmt, raw_bytes)

        if channels == 1:
            samples = [s / 32768.0 for s in raw_ints]
        else:
            samples = [((raw_ints[i * 2] + raw_ints[i * 2 + 1]) / 2.0) / 32768.0 for i in range(num_samples)]

        slice_duration = len(samples) / float(sample_rate)

        # Write trimmed slice to a dedicated WAV file for inspection / AI transcription
        slice_wav = audio_dir / ("slice_%d_%s.wav" % (int(time.time() * 1000), current_tc.replace(":", "_")))
        with wave.open(str(slice_wav), "wb") as wf_out:
            wf_out.setnchannels(channels)
            wf_out.setsampwidth(2)
            wf_out.setframerate(sample_rate)
            wf_out.writeframes(raw_bytes)

        duration = slice_duration

        # 1. Action: analyze
        if action == "analyze":
            peak_val = max(abs(s) for s in samples) if samples else 0.0
            sum_sq = sum(s * s for s in samples) if samples else 0.0
            rms_val = math.sqrt(sum_sq / len(samples)) if samples else 0.0
            peak_db = 20.0 * math.log10(max(1e-6, peak_val))
            rms_db = 20.0 * math.log10(max(1e-6, rms_val))
            return {
                "action": "analyze",
                "clip_name": clip_name,
                "track_type": target_track_type,
                "timecode": current_tc,
                "source_start_sec": round(source_start_sec, 3),
                "duration_sec": round(duration, 3),
                "sample_rate": sample_rate,
                "channels": channels,
                "peak_dbfs": round(peak_db, 2),
                "rms_dbfs": round(rms_db, 2),
                "is_clipping": bool(peak_db >= -0.05),
                "health": "healthy" if peak_db < -0.5 and rms_db > -35.0 else "warning_loud" if peak_db >= -0.5 else "warning_quiet",
                "wav_path": str(slice_wav),
            }

        # 2. Action: silence_cuts
        elif action == "silence_cuts":
            window_size = int(sample_rate * 0.05)
            num_windows = len(samples) // window_size
            silent_windows = []
            for i in range(num_windows):
                chunk = samples[i * window_size : (i + 1) * window_size]
                chunk_rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                chunk_db = 20.0 * math.log10(max(1e-6, chunk_rms))
                silent_windows.append(chunk_db <= threshold_db)

            cuts = []
            in_silence = False
            interval_start = 0.0
            for i, is_silent in enumerate(silent_windows):
                curr_t = i * 0.05
                if is_silent and not in_silence:
                    in_silence = True
                    interval_start = curr_t
                elif not is_silent and in_silence:
                    in_silence = False
                    d = curr_t - interval_start
                    if d >= min_silence_duration:
                        # Convert to timecode
                        s_f = int(interval_start * fps)
                        e_f = int(curr_t * fps)
                        cuts.append({
                            "start_sec": round(interval_start, 3),
                            "end_sec": round(curr_t, 3),
                            "duration_sec": round(d, 3),
                            "start_frame": s_f,
                            "end_frame": e_f,
                        })
            return {
                "action": "silence_cuts",
                "clip_name": clip_name,
                "threshold_db": threshold_db,
                "silence_intervals_count": len(cuts),
                "cuts": cuts,
            }

        # 3. Action: energy_envelope
        elif action == "energy_envelope":
            window_size = max(1, int(sample_rate * 0.05))
            num_windows = len(samples) // window_size
            envelope = []
            for i in range(min(num_windows, 200)):
                chunk = samples[i * window_size : (i + 1) * window_size]
                chunk_rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                chunk_db = 20.0 * math.log10(max(1e-6, chunk_rms))
                envelope.append({"time_sec": round(i * 0.05, 2), "rms_dbfs": round(chunk_db, 1)})
            return {
                "action": "energy_envelope",
                "clip_name": clip_name,
                "samples_count": len(envelope),
                "envelope": envelope,
            }

        # 4. Action: onsets
        elif action == "onsets":
            lead_ms = float(params.get("lead_offset_ms", 160.0))
            window_size = int(sample_rate * 0.01)
            num_windows = len(samples) // max(1, window_size)
            energies = [sum(s * s for s in samples[i * window_size : (i + 1) * window_size]) for i in range(num_windows)]
            onsets = []
            lead_sec = lead_ms / 1000.0
            for i in range(1, len(energies) - 1):
                diff = energies[i] - energies[i - 1]
                if diff > 0.04 and energies[i] > 0.008:
                    t = max(0.0, (i * 0.01) - lead_sec)
                    onsets.append({
                        "onset_sec": round(t, 3),
                        "frame": int(round(t * fps)),
                        "energy_delta": round(diff, 4)
                    })
            return {
                "action": "onsets",
                "clip_name": clip_name,
                "lead_offset_ms": lead_ms,
                "onsets_count": len(onsets),
                "onsets": onsets[:50]
            }

        # 5. Action: vad_clusters
        elif action == "vad_clusters":
            threshold_db = float(params.get("threshold_db", -34.0))
            frame_samples = max(1, int(sample_rate / fps))
            num_frames = len(samples) // frame_samples
            clusters = []
            in_speech = False
            c_start = 0
            for f in range(num_frames):
                chunk = samples[f * frame_samples : (f + 1) * frame_samples]
                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                db = 20.0 * math.log10(max(1e-6, rms))
                is_speech = (db > threshold_db)
                if is_speech and not in_speech:
                    in_speech = True
                    c_start = f
                elif not is_speech and in_speech:
                    in_speech = False
                    clusters.append({"start_frame": c_start, "end_frame": f - 1, "start_sec": round(c_start / fps, 3), "end_sec": round((f - 1) / fps, 3)})
            if in_speech:
                clusters.append({"start_frame": c_start, "end_frame": num_frames - 1, "start_sec": round(c_start / fps, 3), "end_sec": round((num_frames - 1) / fps, 3)})
            return {
                "action": "vad_clusters",
                "clip_name": clip_name,
                "threshold_db": threshold_db,
                "clusters_count": len(clusters),
                "clusters": clusters
            }

        # 6. Action: export_slice
        elif action == "export_slice":
            return {
                "action": "export_slice",
                "clip_name": clip_name,
                "wav_path": str(temp_wav),
                "duration_sec": round(duration, 3),
            }

        raise OperationError("Unknown audio action '%s'. Valid actions: analyze, silence_cuts, energy_envelope, onsets, vad_clusters, export_slice" % action)

    def _op_change_clip_speed(self, params):
        item, info = self._resolve_one_item(params.get("item_id"), track_hint=params.get("track_index") or "video")

        if info.get("track_type") == "audio":
            raise OperationError(
                "change_clip_speed currently supports video clips. DaVinci Resolve does not process "
                "audio in Fusion compositions; audio speed changes must be made via Fairlight or clip pitch/retime."
            )

        speed = params.get("speed")
        if speed is None:
            speed = params.get("speed_multiplier")
        if speed is None and params.get("speed_percent") is not None:
            try:
                speed = float(params["speed_percent"]) / 100.0
            except (ValueError, TypeError):
                pass
        if speed is None and params.get("slow_down_percent") is not None:
            try:
                speed = 1.0 - (float(params["slow_down_percent"]) / 100.0)
            except (ValueError, TypeError):
                pass
        if speed is None and params.get("speed_up_percent") is not None:
            try:
                speed = 1.0 + (float(params["speed_up_percent"]) / 100.0)
            except (ValueError, TypeError):
                pass

        if speed is None:
            raise OperationError("speed (e.g. 0.75), speed_percent (e.g. 75), or slow_down_percent (e.g. 25) is required.")

        try:
            speed = float(speed)
        except (ValueError, TypeError):
            raise OperationError("Invalid speed value: %s" % speed)

        if speed <= 0.0:
            raise OperationError("speed must be a positive number greater than 0.")

        method = str(params.get("method", "fusion")).lower()
        reverse = bool(params.get("reverse", False))

        if method in ("clip_attributes", "media_pool", "fps"):
            mpi = item.GetMediaPoolItem()
            if not mpi:
                raise OperationError("Clip %s has no Media Pool item to modify frame rate." % info.get("id"))
            fps = self._project_rate()
            # In Resolve clip attributes, conforming higher FPS footage to timeline rate produces slow motion (e.g. 24 / 0.75 = 32 fps).
            new_fps = round(fps / speed, 3)
            ok = call(mpi, "SetClipProperty", False, "FPS", str(new_fps))
            if not ok:
                raise OperationError("Resolve refused to update clip FPS to %s." % new_fps)
            return {
                "item_id": info["id"],
                "name": info.get("name"),
                "method": "clip_attributes_fps",
                "speed": speed,
                "speed_percent": round(speed * 100.0, 1),
                "timeline_fps": fps,
                "clip_fps": new_fps,
            }

        # Default method: Fusion native TimeSpeed
        comp = item.GetFusionCompByIndex(1)
        if not comp:
            comp = item.AddFusionComp()
        if not comp:
            raise OperationError("Could not access or create Fusion composition for clip %s." % info.get("id"))

        comp.Lock()
        try:
            media_in = comp.FindTool("MediaIn1")
            media_out = comp.FindTool("MediaOut1")
            if not media_in or not media_out:
                tools = comp.GetToolList(False) or {}
                tool_list = list(tools.values()) if isinstance(tools, dict) else list(tools)
                for t in tool_list:
                    reg_id = str(call(t, "GetAttrs", "", "TOOLS_RegID"))
                    if reg_id == "MediaIn":
                        media_in = t
                    elif reg_id == "MediaOut":
                        media_out = t

            if not media_in or not media_out:
                raise OperationError("Fusion composition for clip %s lacks MediaIn/MediaOut nodes." % info.get("id"))

            ts = comp.FindTool("TimeSpeed1")
            if not ts:
                tools = comp.GetToolList(False) or {}
                tool_list = list(tools.values()) if isinstance(tools, dict) else list(tools)
                for t in tool_list:
                    if str(call(t, "GetAttrs", "", "TOOLS_RegID")) == "TimeSpeed":
                        ts = t
                        break

            if abs(speed - 1.0) < 1e-5 and not reverse:
                if ts:
                    media_out.ConnectInput("Input", media_in)
                    ts.Delete()
                tool_name = None
            else:
                if not ts:
                    ts = comp.AddTool("TimeSpeed")
                    if not ts:
                        raise OperationError("Could not create TimeSpeed tool in Fusion composition.")
                    # Wire non-destructively: connect ts between current media_out input source and media_out
                    current_out_src = None
                    try:
                        out_inp = media_out.GetInput("Input")
                        if out_inp:
                            conn = out_inp.GetConnectedOutput()
                            if conn:
                                current_out_src = conn.GetTool()
                    except Exception:
                        pass
                    if current_out_src and current_out_src != ts:
                        ts.ConnectInput("Input", current_out_src)
                    else:
                        ts.ConnectInput("Input", media_in)
                    media_out.ConnectInput("Input", ts)
                else:
                    # ts already exists, ensure it's connected
                    ts_in = None
                    try:
                        inp = ts.GetInput("Input")
                        if inp and inp.GetConnectedOutput():
                            ts_in = inp.GetConnectedOutput().GetTool()
                    except Exception:
                        pass
                    if not ts_in:
                        ts.ConnectInput("Input", media_in)
                    media_out.ConnectInput("Input", ts)

                effective_speed = -speed if reverse else speed
                ts.SetInput("Speed", float(effective_speed))

                interpolate = bool(params.get("interpolate_frames", True))
                try:
                    ts.SetInput("InterpolateBetweenFrames", 1.0 if interpolate else 0.0)
                except Exception:
                    pass
                tool_name = getattr(ts, "Name", "TimeSpeed1")
        finally:
            comp.Unlock()

        slow_down = round((1.0 - speed) * 100.0, 1) if speed < 1.0 else 0.0
        speed_up = round((speed - 1.0) * 100.0, 1) if speed > 1.0 else 0.0

        return {
            "item_id": info["id"],
            "name": info.get("name"),
            "method": "fusion_timespeed",
            "speed": speed,
            "speed_percent": round(speed * 100.0, 1),
            "slow_down_percent": slow_down,
            "speed_up_percent": speed_up,
            "reverse": reverse,
            "tool": tool_name,
            "interpolate_frames": bool(params.get("interpolate_frames", True)),
        }

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

    # ------------------------------------------------------------- dispatch

    def handlers(self):
        return {
            "status": self._op_status,
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

    def heartbeat_payload(self, extra=None):
        payload = self._op_status({})
        payload.update({"pid": os.getpid(), "time": time.time()})
        if extra:
            payload.update(extra)
        return plain(payload)
