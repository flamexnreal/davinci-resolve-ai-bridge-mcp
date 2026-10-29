"""Regressions found during review; use temporary runtimes and Resolve doubles."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from bridge import client
from bridge.operations import OperationError, ResolveOperations
from fakes import Clip, Media, Project, Resolve, Timeline

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class MediaRegressionTests(unittest.TestCase):
    def test_cleanup_removes_review_markers_with_string_frame_keys(self):
        project = Project([Clip()])
        op = ResolveOperations(lambda: Resolve(project))
        analysis = {"item_id": project.current.clips[0].uid, "truncated": False,
                    "cuts": [{"timeline_start_frame": 20, "timeline_end_frame": 40}]}
        with patch.object(op, "_op_timeline_audio", return_value=analysis):
            marker = op._op_review_silence({})["markers"][0]["marker_id"]
        def markers(timeline):
            return {str(key): value for key, value in timeline.markers.items()}
        with patch.object(Timeline, "GetMarkers", markers):
            result = op._op_apply_silence_cuts({"marker_ids": [marker]})
        self.assertEqual(result["removed_frames"], 20)
        self.assertFalse(project.current.markers)

    def test_split_accepts_verified_read_only_defaults(self):
        project = Project([Clip()])
        project.current.clips[0].props.update(AnchorPointX=0, AnchorPointY=0)
        original = Clip.SetProperty
        def setter(item, key, value):
            return False if key.startswith("AnchorPoint") else original(item, key, value)
        def getter(item, key=None):
            props = {"AnchorPointX": 0, "AnchorPointY": 0, **item.props}
            return props.get(key) if key else props
        op = ResolveOperations(lambda: Resolve(project))
        with patch.object(Clip, "SetProperty", setter), patch.object(Clip, "GetProperty", getter):
            self.assertTrue(op._op_split_clip({"frame": 50})["transform_preserved"])

    def test_split_recovers_when_transform_readback_differs(self):
        project = Project([Clip()])
        project.current.clips[0].props["ZoomX"] = 2
        op = ResolveOperations(lambda: Resolve(project))
        # A success return alone must not claim preservation.
        with patch.object(Clip, "SetProperty", return_value=True):
            with self.assertRaisesRegex(OperationError, "opened the checkpoint"):
                op._op_split_clip({"frame": 50})
        self.assertEqual(project.current.clips[0].props["ZoomX"], 2)

    def test_duplicate_and_compare_handle_inactive_track_flags(self):
        project = Project([Clip()])
        original = project.current
        duplicate = original.DuplicateTimeline
        def activate_copy(name):
            copy = duplicate(name)
            project.SetCurrentTimeline(copy)
            return copy
        def enabled(timeline, kind, index):
            return project.current is timeline and (kind, index) not in timeline.disabled
        op = ResolveOperations(lambda: Resolve(project))
        with patch.object(original, "DuplicateTimeline", side_effect=activate_copy), \
                patch.object(Timeline, "GetIsTrackEnabled", enabled):
            result = op._op_preview_timeline({})
            comparison = op._op_compare_timelines({"original": result["original"]["id"], "preview": result["preview"]["id"]})
        self.assertTrue(comparison["structurally_equal"], comparison)
        self.assertIsNot(project.current, original)

    def test_add_image_returns_created_item_before_later_clip(self):
        later = Clip(200, 300)
        project = Project([later])
        op = ResolveOperations(lambda: Resolve(project))
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "overlay.png"
            image.touch()
            media = Media(image)
            project.pool.GetRootFolder = lambda: object()
            project.pool.ImportMedia = lambda paths: [media]

            def append(requests):
                request = requests[0]
                item = Clip(request["recordFrame"], request["recordFrame"] + 24, media)
                project.current.clips.append(item)
                return [item]

            project.pool.AppendToTimeline = append
            with patch.object(op, "_walk_media", return_value=[]):
                result = op._op_add_image({"path": str(image), "record_frame": 0, "duration_frames": 24})
            created = project.current.clips[-1]
            self.assertEqual(result["item"], created.uid)
            self.assertNotEqual(result["item"], later.uid)

    def test_positioned_append_preserves_audio_by_default(self):
        project = Project([Clip()])
        op = ResolveOperations(lambda: Resolve(project))
        media = Media()
        media.props["Frames"] = "48"
        project.pool.AppendToTimeline = Mock(return_value=[Clip()])
        with patch.object(op, "_find_media_items", return_value=[media]):
            op._op_append_media({"media_ids": [media.uid], "record_frame": 100})
        payload = project.pool.AppendToTimeline.call_args.args[0][0]
        self.assertNotIn("mediaType", payload, "Omit mediaType to retain both audio and video")
        self.assertEqual(payload["endFrame"] - payload["startFrame"], 48)

    def test_explicit_inclusive_source_end_maps_to_native_exclusive_end(self):
        project = Project([Clip()])
        op = ResolveOperations(lambda: Resolve(project))
        media = Media()
        project.pool.AppendToTimeline = Mock(return_value=[Clip()])
        with patch.object(op, "_find_media_items", return_value=[media]):
            op._op_append_media({"media_ids": [media.uid], "start_frame": 10, "end_frame": 33})
        payload = project.pool.AppendToTimeline.call_args.args[0][0]
        self.assertEqual(payload["endFrame"] - payload["startFrame"], 24)

    def test_audio_only_append_honors_media_type_without_position(self):
        project = Project([Clip()])
        op = ResolveOperations(lambda: Resolve(project))
        media = Media()
        media.props["Frames"] = "48"
        project.pool.AppendToTimeline = Mock(return_value=[Clip(kind="audio")])
        with patch.object(op, "_find_media_items", return_value=[media]):
            op._op_append_media({"media_ids": [media.uid], "media_type": 2})
        payload = project.pool.AppendToTimeline.call_args.args[0][0]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["mediaType"], 2)


class InstallerRegressionTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX launcher execution")
    def test_launcher_preserves_custom_runtime_with_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "runtime with spaces"
            python = home / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$RESOLVE_AI_BRIDGE_HOME"\n')
            python.chmod(0o700)
            with patch.object(installer, "HOME", home), patch.object(Path, "home", return_value=Path(directory)):
                launchers = installer.install_global_launcher()
            result = subprocess.run([launchers[0]], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), [str(home)])

    def test_client_configuration_preserves_home_and_venv_path(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            python = home / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            if os.name != "nt":
                import sys
                python.symlink_to(sys.executable)
            with patch.object(installer, "HOME", home):
                entry, config, _, command = installer.write_configs()
            self.assertEqual(entry["env"]["RESOLVE_AI_BRIDGE_HOME"], str(home))
            self.assertIn("--env", command)
            self.assertIn("RESOLVE_AI_BRIDGE_HOME=", command)
            self.assertEqual(Path(entry["command"]), home / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
            self.assertEqual(config["mcpServers"]["resolve-ai-bridge"], entry)

    def test_custom_home_forwarded_to_client_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = {"command": "private-python", "args": ["server.py"], "env": {"RESOLVE_AI_BRIDGE_HOME": "custom-runtime"}}
            with patch.object(Path, "home", return_value=Path(directory)), \
                    patch("shutil.which", side_effect=lambda name: name if name == "codex" else None), \
                    patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                installer.auto_configure_clients(entry)
            self.assertIn("RESOLVE_AI_BRIDGE_HOME=custom-runtime", run.call_args.args[0])

    def test_private_decoder_survives_activation_and_update(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "runtime"

            def run(command, **kwargs):
                # Model the bundled executable returned by imageio-ffmpeg.
                binary = installer.HOME / ".venv" / "decoder" / "ffmpeg"
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("fixture")
                binary.chmod(0o700)
                return subprocess.CompletedProcess(command, 0, stdout=str(binary) + "\n")

            with patch.object(installer, "HOME", home), patch.object(installer, "install_dependencies"), \
                    patch.object(installer.subprocess, "run", side_effect=run):
                for _ in range(2):
                    installer.prepare_runtime(skip=True, with_ffmpeg=True)
                    with patch.dict(os.environ, RESOLVE_AI_BRIDGE_HOME=str(home)), \
                            patch.dict(os.environ, {"RESOLVE_AI_BRIDGE_FFMPEG": ""}), \
                            patch("shutil.which", return_value=None):
                        decoder = ResolveOperations._ffmpeg_path()
                    self.assertIsNotNone(decoder)
                    self.assertTrue(Path(decoder).is_file())
                    self.assertTrue(Path(decoder).is_relative_to(home))

    def test_runtime_validation_uses_staging_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "runtime"
            with patch.object(installer, "HOME", home), patch.object(installer, "install_dependencies"), \
                    patch.object(installer.subprocess, "run") as run:
                installer.prepare_runtime()
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs["env"]["RESOLVE_AI_BRIDGE_HOME"], str(kwargs["cwd"]))


@unittest.skipIf(os.name == "nt", "POSIX mode bits; Windows permissions use ACLs")
class QueuePermissionTests(unittest.TestCase):
    def test_request_token_is_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            previous_umask = os.umask(0)
            try:
                client._atomic_json(path, {"token": "fixture-only"})
            finally:
                os.umask(previous_umask)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["token"], "fixture-only")

    def test_existing_public_runtime_directory_is_made_private(self):
        from bridge import lifecycle
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "runtime"
            home.mkdir(mode=0o755)
            token = lifecycle.load_token(home / "token.txt")
            self.assertTrue(token.startswith("rab_"))
            self.assertEqual(home.stat().st_mode & 0o777, 0o700)
