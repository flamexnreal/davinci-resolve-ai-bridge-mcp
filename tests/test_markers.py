"""Marker positions: Resolve keys markers by offset from timeline start."""
import unittest

from bridge.operations import OperationError, ResolveOperations
from fakes import Clip, Project, Resolve


class MarkerFrameTests(unittest.TestCase):
    def setUp(self):
        self.clip = Clip(86400, 86496)
        self.project = Project([self.clip])
        self.timeline = self.project.current
        self.timeline.start = 86400
        self.timeline.start_tc = '01:00:00:00'
        self.op = ResolveOperations(lambda: Resolve(self.project))

    def test_absolute_timeline_frame_converts_to_offset(self):
        result = self.op._op_add_marker({'name': 'Onset', 'timeline_frame': 86424})
        self.assertEqual(set(self.timeline.markers), {24})
        self.assertEqual((result['frame'], result['timeline_frame']), (24, 86424))

    def test_relative_frame_is_unchanged(self):
        result = self.op._op_add_marker({'name': 'Offset', 'frame': 24})
        self.assertEqual(set(self.timeline.markers), {24})
        self.assertEqual(result['timeline_frame'], 86424)

    def test_playhead_default(self):
        self.timeline.current = '01:00:01:12'
        result = self.op._op_add_marker({'name': 'Here'})
        self.assertEqual((result['frame'], result['timeline_frame']), (36, 86436))

    def test_absolute_frame_passed_as_offset_is_refused_with_hint(self):
        with self.assertRaisesRegex(OperationError, 'timeline_frame'):
            self.op._op_add_marker({'name': 'Wrong space', 'frame': 86424})
        self.assertEqual(self.timeline.markers, {})

    def test_frame_before_start_is_refused(self):
        with self.assertRaisesRegex(OperationError, 'outside this timeline'):
            self.op._op_add_marker({'name': 'Early', 'timeline_frame': 86399})

    def test_both_spaces_rejected(self):
        with self.assertRaisesRegex(OperationError, 'not both'):
            self.op._op_add_marker({'name': 'Both', 'frame': 1, 'timeline_frame': 86401})

    def test_existing_marker_reported_accurately(self):
        self.op._op_add_marker({'name': 'First', 'timeline_frame': 86410})
        with self.assertRaisesRegex(OperationError, 'already exists at offset 10'):
            self.op._op_add_marker({'name': 'Second', 'frame': 10})

    def test_delete_by_absolute_frame(self):
        self.op._op_add_marker({'name': 'Cut', 'frame': 48})
        result = self.op._op_delete_marker({'timeline_frame': 86448})
        self.assertEqual((result['deleted_frame'], result['timeline_frame']), (48, 86448))
        self.assertEqual(self.timeline.markers, {})

    def test_delete_requires_a_position(self):
        with self.assertRaisesRegex(OperationError, 'Pass frame'):
            self.op._op_delete_marker({})

    def test_audio_onset_frame_round_trips(self):
        # timeline_audio reports absolute timeline_* frames; they must place markers directly.
        onset = {'timeline_frame': 86460}
        self.op._op_add_marker({'name': 'Caption', 'timeline_frame': onset['timeline_frame']})
        self.assertIn(60, self.timeline.markers)


if __name__ == '__main__':
    unittest.main()
