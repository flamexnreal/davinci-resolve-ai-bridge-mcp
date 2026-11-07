import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from bridge.operations import ResolveOperations, OperationError
from fakes import Clip, Media, Project, Resolve

class OperationTests(unittest.TestCase):
    def setUp(self):
        self.project=Project([Clip()]);self.op=ResolveOperations(lambda:Resolve(self.project));self.timeline=self.project.current
    def test_playhead_boundary(self):
        left=self.timeline.clips[0];right=Clip(100,200);self.timeline.clips.append(right)
        with patch.object(self.op,'_playhead_frame',return_value=100):self.assertIs(self.op._resolve_one_item('playhead')[0],right)
    def test_disabled_clip_and_track_skipped(self):
        top=Clip(track=2);self.timeline.clips.append(top);top.enabled=False
        self.assertIs(self.op._resolve_one_item('playhead')[0],self.timeline.clips[0])
        top.enabled=True;self.timeline.disabled.add(('video',2));self.assertIs(self.op._resolve_one_item('playhead')[0],self.timeline.clips[0])
    def test_ids_survive_insertion_and_labels_still_work(self):
        clip=self.timeline.clips[0];clip.start=100;clip.end=200
        stable=self.op._op_timeline_overview({})['clips'][0]['id'];self.timeline.clips.insert(0,Clip(0,100))
        self.assertIs(self.op._find_timeline_items([stable])[0][0],clip)
        self.assertIs(self.op._find_timeline_items(['V1.2'])[0][0],clip)
    def test_timeline_rate_overrides_project(self):
        self.timeline.fps=60;self.assertEqual(self.op._project_rate(),60)
    def test_drop_frame_round_trip(self):
        for nominal in (30,60):
            fps=nominal/1.001
            for frame in (0,1,1798,1799,1800,17982,107892,1000000):
                self.assertEqual(self.op._tc_frames(self.op._frames_tc(frame,fps,True),fps),frame)
        self.assertEqual(self.op._tc_frames('01:00:00;00',29.97),107892)
    def test_invalid_timecodes_rejected(self):
        for tc in ('garbage','00:99:00:00','00:01:00;00'):
            with self.assertRaises(OperationError):self.op._tc_frames(tc,29.97)
    def test_split_success_retains_checkpoint(self):
        self.timeline.clips[0].props['ZoomX']=2
        r=self.op._op_split_clip({'frame':50})
        self.assertEqual([(c.start,c.end) for c in self.timeline.clips],[(0,50),(50,100)])
        self.assertEqual(len(self.project.timelines),2);self.assertEqual(len(self.project.timelines[1].clips),1)
        self.assertTrue(all(c.props['ZoomX']==2 for c in self.timeline.clips));self.assertIn('checkpoint',r)
    def test_failed_split_opens_intact_checkpoint(self):
        self.project.pool.append_limit=1
        with self.assertRaisesRegex(OperationError,'opened the checkpoint'):
            self.op._op_split_clip({'frame':50})
        self.assertIsNot(self.project.current,self.timeline)
        self.assertEqual([(c.start,c.end) for c in self.project.current.clips],[(0,100)])
    def test_split_refuses_fusion_before_mutation(self):
        self.timeline.clips[0].fusion=object()
        with self.assertRaises(OperationError):self.op._op_split_clip({'frame':50})
        self.assertEqual(self.timeline.delete_calls,0);self.assertEqual(len(self.project.timelines),1)
    def test_split_mixed_rate_refused(self):
        self.timeline.clips[0].media.props['FPS']='60'
        with self.assertRaises(OperationError):self.op._op_split_clip({'frame':50})
        self.assertEqual(self.timeline.delete_calls,0)
    def test_source_frame_uses_absolute_timeline_position(self):
        self.timeline.start=86400;self.timeline.start_tc='01:00:00:00';self.timeline.current='01:00:01:00'
        clip=self.timeline.clips[0];clip.start=86400;clip.end=86640
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.mov';path.touch();clip.media.props['File Path']=str(path)
            with patch.object(self.op,'_ffmpeg_path',return_value=None):
                with self.assertRaisesRegex(OperationError,'needs ffmpeg'):
                    self.op._op_timeline_frame({'mode':'source'})
    def test_preview_duplicate_and_compare(self):
        r=self.op._op_preview_timeline({});self.assertIsNot(self.project.current,self.timeline)
        before_id=self.timeline.GetUniqueId();after_id=self.project.current.GetUniqueId()
        self.assertTrue(self.op._op_compare_timelines({'original':before_id,'preview':after_id})['structurally_equal'])
        self.project.current.clips[0].props['ZoomX']=2
        self.assertFalse(self.op._op_compare_timelines({'original':before_id,'preview':after_id})['structurally_equal'])
        self.assertEqual(self.timeline.clips[0].props['ZoomX'],1)
    def test_failed_duplicate_does_not_delete(self):
        with patch.object(self.timeline,'DuplicateTimeline',return_value=None):
            with self.assertRaises(OperationError):self.op._op_split_clip({'frame':50})
        self.assertEqual(self.timeline.delete_calls,0)
    def test_split_never_deletes_if_original_timeline_did_not_reactivate(self):
        original = self.timeline

        def pretend_to_switch(timeline):
            if timeline is not original:
                self.project.current = timeline
            return True

        with patch.object(self.project, "SetCurrentTimeline", side_effect=pretend_to_switch), \
             patch.object(self.project.pool, "AppendToTimeline") as append:
            with self.assertRaisesRegex(OperationError, "Could not open the requested timeline"):
                self.op._op_split_clip({"frame": 50})
        append.assert_not_called()
        self.assertEqual(original.delete_calls, 0)
        self.assertEqual([(clip.start, clip.end) for clip in original.clips], [(0, 100)])

    def test_dialogue_rebuild_stops_if_active_timeline_changes_after_preview_delete(self):
        original = self.timeline
        marker = self.add_review()
        delete = type(original).DeleteClips

        def delete_then_switch(timeline, items, ripple):
            deleted = delete(timeline, items, ripple)
            self.project.current = original
            return deleted

        with patch.object(type(original), "DeleteClips", delete_then_switch), \
             patch.object(self.project.pool, "AppendToTimeline") as append:
            with self.assertRaisesRegex(OperationError, "active timeline changed.*Original .* is intact"):
                self.op._op_apply_silence_cuts({"marker_ids": [marker]})
        append.assert_not_called()
        self.assertEqual(original.delete_calls, 0)
        self.assertEqual([(clip.start, clip.end) for clip in original.clips], [(0, 100)])

    def test_open_timeline_does_not_guess_between_conflicting_or_ambiguous_selectors(self):
        duplicate = self.timeline.DuplicateTimeline(self.timeline.GetName())
        with self.assertRaisesRegex(OperationError, "ambiguous"):
            self.op._op_open_timeline({"name": duplicate.GetName()})
        with self.assertRaisesRegex(OperationError, "exactly one"):
            self.op._op_open_timeline({"timeline_id": duplicate.GetUniqueId(), "index": 1})
        self.assertIs(self.project.current, self.timeline)
        self.op._op_open_timeline({"timeline_id": duplicate.GetUniqueId()})
        self.assertIs(self.project.current, duplicate)

    def test_health_reports_missing_media_and_delivery(self):
        self.timeline.clips[0].media.props['File Path']='/does-not-exist/fixture.mov'
        r=self.op._op_project_health({'expected_width':3840})
        self.assertEqual({x['type'] for x in r['findings']},{'missing_source','delivery_mismatch'})
    def add_review(self):
        analysis={'item_id':self.timeline.clips[0].uid,'truncated':False,'cuts':[{'timeline_start_frame':20,'timeline_end_frame':40}]}
        with patch.object(self.op,'_op_timeline_audio',return_value=analysis):return self.op._op_review_silence({})['markers'][0]['marker_id']
    def test_health_flags_free_delivery_limits(self):
        self.timeline.fps=120
        with patch.object(self.op,'_project_resolution',return_value=(4096,2160)):
            types={f['type'] for f in self.op._op_project_health({})['findings']}
        self.assertTrue({'free_resolution_limit','free_frame_rate_limit'}<=types)
        with patch.object(self.op,'_project_resolution',return_value=(3840,2160)):
            self.timeline.fps=60;types={f['type'] for f in self.op._op_project_health({})['findings']}
        self.assertFalse({'free_resolution_limit','free_frame_rate_limit'}&types)
        with patch('fakes.Resolve.GetProductName',return_value='DaVinci Resolve Studio'):
            self.timeline.fps=120;self.assertEqual(self.op._free_limits(7680,4320,120),[])
    def test_render_status_reports_jobs(self):
        self.project.GetRenderJobList=lambda:[{'JobId':'j1','TimelineName':'Original','TargetDir':'/out','OutputFilename':'a.mp4'}]
        self.project.GetRenderJobStatus=lambda job:{'JobStatus':'Rendering','CompletionPercentage':42}
        self.project.IsRenderingInProgress=lambda:True
        r=self.op._op_render_status({})
        self.assertTrue(r['rendering']);self.assertEqual(r['jobs'][0]['percent'],42)
        self.assertEqual(r['jobs'][0]['output'],str(Path('/out')/'a.mp4'))
        with self.assertRaises(OperationError):self.op._op_render_status({'job_id':'missing'})
        self.project.GetRenderJobList=lambda:[];self.assertEqual(self.op._op_render_status({})['jobs'],[])
    def test_render_status_distinguishes_unavailable_from_idle_and_empty(self):
        with self.assertRaisesRegex(OperationError, "did not return a usable render queue"):
            self.op._op_render_status({})
        self.project.GetRenderJobList = lambda: {"1": {"JobId": "render-1"}}
        result = self.op._op_render_status({})
        self.assertEqual(result["jobs"][0]["job_id"], "render-1")
        self.assertIsNone(result["rendering"])
        self.project.IsRenderingInProgress = lambda: False
        self.project.GetRenderJobList = lambda: {}  # empty table from Lua
        result = self.op._op_render_status({})
        self.assertEqual(result["jobs"], [])
        self.assertIs(result["rendering"], False)

    def test_compound_clip_never_reports_source_as_new_item(self):
        source = self.timeline.clips[0]
        self.timeline.CreateCompoundClip = Mock(return_value=True)
        result = self.op._op_create_compound_clip({"item_id": source.GetUniqueId()})
        self.assertIsNone(result["created_compound_clip"]["id"])
        self.assertIsNone(result["created_compound_clip"]["start_frame"])
        self.assertIn("Inspect timeline_overview", result["note"])

    def test_title_text_requires_readback_and_supports_explicit_setter(self):
        clip = self.timeline.clips[0]
        self.timeline.InsertFusionTitleIntoTimeline = Mock(return_value=clip)
        inputs = {"StyledText": "Original"}
        title = SimpleNamespace(GetInput=inputs.get, SetInput=Mock(return_value=True))
        clip.fusion = SimpleNamespace(GetToolList=lambda _selected: {1: title})
        self.assertFalse(self.op._op_insert_title({"text": "Requested"})["text_set"])
        title.SetInput = inputs.__setitem__  # no boolean return; check the real value
        self.assertTrue(self.op._op_insert_title({"text": "Requested"})["text_set"])
        self.assertEqual(inputs["StyledText"], "Requested")

    def test_title_never_falls_back_after_an_uncertain_lua_setter(self):
        from bridge.lua_transport import _WireFailure

        clip = self.timeline.clips[0]
        self.timeline.InsertFusionTitleIntoTimeline = Mock(return_value=clip)
        title = SimpleNamespace(GetInput=lambda _attribute: "Previous", SetInput=Mock(side_effect=_WireFailure("lost reply")))
        other_tool = SimpleNamespace(GetInput=lambda _attribute: "Previous", SetInput=Mock())
        clip.fusion = SimpleNamespace(GetToolList=lambda _selected: {1: title, 2: other_tool})
        with self.assertRaises(_WireFailure):
            self.op._op_insert_title({"text": "Requested"})
        title.SetInput.assert_called_once_with("StyledText", "Requested")
        other_tool.SetInput.assert_not_called()

    def test_capabilities_find_decoder_in_explicit_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            decoder = home / "fixture-ffmpeg.exe"
            decoder.touch()
            decoder.chmod(0o700)
            (home / "ffmpeg-path.txt").write_text(decoder.name)
            op = ResolveOperations(lambda: Resolve(self.project), runtime_home=home)
            with patch.dict("os.environ", {"RESOLVE_AI_BRIDGE_HOME": str(home / "wrong"), "RESOLVE_AI_BRIDGE_FFMPEG": ""}), \
                 patch("shutil.which", return_value=None):
                self.assertTrue(op._op_bridge_capabilities({})["source_frame_decoder"])
    def test_edits_are_read_back(self):
        clip=self.timeline.clips[0];item=clip.GetUniqueId()
        self.assertEqual(self.op._op_set_clip_property({'item_id':item,'property_name':'ZoomX','value':2})['read_back'],2)
        clip.SetProperty=lambda key,value:True
        self.assertIn('note',self.op._op_set_clip_property({'item_id':item,'property_name':'ZoomX','value':3}))
        clip.SetClipEnabled=lambda value:True
        with self.assertRaises(OperationError):self.op._op_set_clip_enabled({'item_id':item,'enabled':False})
        clip.SetClipColor=lambda value:True
        with self.assertRaises(OperationError):self.op._op_set_clip_color({'item_id':item,'color':'Orange'})
    def test_silence_markers_are_non_destructive(self):
        self.add_review();self.assertEqual(len(self.timeline.clips),1);self.assertEqual(self.timeline.delete_calls,0)
    def test_selected_silence_applied_only_on_copy(self):
        key=self.add_review();r=self.op._op_apply_silence_cuts({'marker_ids':[key]})
        self.assertEqual(r['removed_frames'],20);self.assertEqual([(c.start,c.end) for c in self.project.current.clips],[(0,20),(20,80)])
        self.assertEqual([(c.start,c.end) for c in self.timeline.clips],[(0,100)])
    def test_stale_review_rejected(self):
        key=self.add_review();self.timeline.clips[0].props['ZoomX']=2
        with self.assertRaisesRegex(OperationError,'stale'):self.op._op_apply_silence_cuts({'marker_ids':[key]})
        self.assertEqual(len(self.project.timelines),1)
    def test_complex_timeline_refuses_automatic_cleanup(self):
        self.timeline.clips.extend([Clip(100,200),Clip(200,300)]);key=self.add_review()
        with self.assertRaisesRegex(OperationError,'isolated'):self.op._op_apply_silence_cuts({'marker_ids':[key]})
        self.assertEqual(self.timeline.delete_calls,0)
    def test_cleanup_failure_restores_original_selection(self):
        key=self.add_review();self.project.pool.append_limit=0
        with self.assertRaisesRegex(OperationError,'Original.*intact'):self.op._op_apply_silence_cuts({'marker_ids':[key]})
        self.assertIs(self.project.current,self.timeline);self.assertEqual(len(self.timeline.clips),1)

class SpeedTests(unittest.TestCase):
    def setup_graph(self,owned=True):
        clip=Clip();p=Project([clip]);op=ResolveOperations(lambda:Resolve(p))
        comp=Mock();node=Mock();node.GetData.return_value='resolve-ai-bridge.change_clip_speed.v1' if owned else None
        node.GetInput.return_value=1;comp.GetToolList.return_value={'node':node};clip.fusion=comp
        return op,comp,node
    def test_reset_neutralizes_owned_node_without_rewiring(self):
        op,comp,node=self.setup_graph();op._op_change_clip_speed({'speed':1})
        node.SetInput.assert_any_call('Speed',1);node.Delete.assert_not_called();comp.FindTool.assert_not_called()
    def test_user_node_not_reset(self):
        op,comp,node=self.setup_graph(False);r=op._op_change_clip_speed({'speed':1})
        self.assertFalse(r['changed']);node.SetInput.assert_not_called();node.Delete.assert_not_called()
    def test_invalid_speed_rejected(self):
        op,_,_=self.setup_graph()
        for value in (float('nan'),float('inf'),0,-1):
            with self.assertRaises(OperationError):op._op_change_clip_speed({'speed':value})
    def test_comp_unlocks_on_readback_failure(self):
        op,comp,node=self.setup_graph();node.GetInput.return_value=0
        with self.assertRaises(OperationError):op._op_change_clip_speed({'speed':0.5})
        comp.Unlock.assert_called_once()
