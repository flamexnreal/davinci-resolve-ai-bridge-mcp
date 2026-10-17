"""Bridge Fusion effects share one chain before MediaOut and never cut out user nodes.

These run against tests/fusion_fakes.py, not a real Resolve.
"""

import unittest

from bridge.operations import FUSION_OWNER, OperationError, ResolveOperations
from fakes import Clip, Project, Resolve
from fusion_fakes import Comp, lupa

LUA = unittest.skipUnless(lupa, "install lupa to run generated Fusion Lua")


class FusionChainTests(unittest.TestCase):
    def make(self, user_nodes=(), render_start=0, start=0, end=100):
        clip = Clip(start, end)
        clip.fusion = Comp(render_start, user_nodes)
        project = Project([clip])
        return ResolveOperations(lambda: Resolve(project)), clip.fusion, clip.GetUniqueId()

    def test_default_blur_is_wired(self):
        op, comp, item = self.make()
        result = op._op_apply_blur_effect({"item_id": item})
        self.assertEqual(comp.chain(), ["AIBridgeBlur_1", "MediaIn1"])
        self.assertEqual(result["fusion_chain"]["stages"], ["blur:1"])
        self.assertEqual(comp.locks, 0)

    def test_effects_stack_and_keep_user_nodes(self):
        op, comp, item = self.make(user_nodes=("Glow",))
        op._op_animate_zoom({"item_id": item, "end_zoom": 1.2})
        op._op_apply_blur_effect({"item_id": item, "mask_name": "face", "width": 0.3, "height": 0.3})
        op._op_apply_spotlight_mask({"item_id": item})
        op._op_keyframe_clip_saturation({"item_id": item})
        op._op_animate_color_fx({"item_id": item})
        chain = op._op_inspect_fusion({"item_id": item})["bridge_chain"]
        self.assertEqual(chain, {"source": "Glow1", "stages_before_media_out": [
            "blur:face", "spotlight:1", "zoom", "saturation", "color_fx"]})
        self.assertIs(comp.FindTool("AIBridgeSpotlightGain_1").inputs["Input"].source.tool, comp.FindTool("AIBridgeBlur_face"))
        if not lupa:  # Lua makes the connections inside each effect.
            return
        self.assertEqual(comp.chain(), ["AIBridgeColorFX", "AIBridgeSaturation", "AIBridgeZoom",
                                        "AIBridgeSpotlightMerge_1", "AIBridgeSpotlightBase_1",
                                        "AIBridgeBlur_face", "Glow1", "MediaIn1"])
        merge = comp.FindTool("AIBridgeSpotlightMerge_1")
        self.assertIs(merge.inputs["Foreground"].source.tool, comp.FindTool("AIBridgeSpotlightGain_1"))
        self.assertIs(comp.FindTool("AIBridgeBlur_face").inputs["EffectMask"].source.tool, comp.FindTool("AIBridgeMask_face"))

    def test_reapplying_reuses_nodes(self):
        op, comp, item = self.make()
        for _ in range(3):
            op._op_animate_zoom({"item_id": item})
        self.assertEqual(sum(t.reg_id == "Transform" for t in comp.tools), 1)

    def test_reset_removes_only_bridge_nodes(self):
        op, comp, item = self.make(user_nodes=("Glow",))
        op._op_apply_blur_effect({"item_id": item})
        op._op_animate_zoom({"item_id": item})
        user_blur = comp.AddTool("Blur")
        user_blur.SetAttrs({"TOOLS_Name": "PrivacyBlur"})
        result = op._op_apply_blur_effect({"item_id": item, "reset": True})
        self.assertEqual(result["removed"], ["blur:1"])
        self.assertEqual(comp.chain(), ["AIBridgeZoom", "Glow1", "MediaIn1"])
        self.assertIsNotNone(comp.FindTool("PrivacyBlur"))
        op._op_animate_zoom({"item_id": item, "reset": True})
        self.assertEqual(comp.chain(), ["Glow1", "MediaIn1"])

    def test_reset_without_comp_creates_nothing(self):
        op, comp, item = self.make()
        clip = op._find_timeline_items([item])[0][0]
        clip.fusion = None
        self.assertEqual(op._op_animate_zoom({"item_id": item, "reset": True})["removed"], [])

    def test_legacy_names_are_adopted(self):
        op, comp, item = self.make()
        old = comp.AddTool("Blur")
        old.SetAttrs({"TOOLS_Name": "AIBridgeBlur_privacy"})  # never wired by older versions
        op._op_animate_zoom({"item_id": item})
        self.assertEqual(comp.chain(), ["AIBridgeZoom", "AIBridgeBlur_privacy", "MediaIn1"])

    def test_bridge_node_before_user_node_is_left_in_place(self):
        op, comp, item = self.make()
        op._op_animate_zoom({"item_id": item})
        glow = comp.AddTool("Glow")
        out = comp.FindTool("MediaOut1").FindMainInput(1)
        glow.FindMainInput(1).ConnectTo(out.GetConnectedOutput())
        out.ConnectTo(glow.main_output)
        result = op._op_apply_blur_effect({"item_id": item})
        self.assertEqual(result["fusion_chain"]["left_in_place"], ["zoom"])
        self.assertEqual(comp.chain(), ["AIBridgeBlur_1", "Glow1", "AIBridgeZoom", "MediaIn1"])
        with self.assertRaises(OperationError):
            op._op_animate_zoom({"item_id": item, "reset": True})
        self.assertIsNotNone(comp.FindTool("AIBridgeZoom"))

    def test_changed_blur_type_replaces_node(self):
        op, comp, item = self.make()
        op._op_apply_blur_effect({"item_id": item})
        op._op_apply_blur_effect({"item_id": item, "blur_type": "defocus"})
        self.assertEqual([t.reg_id for t in comp.tools if t.reg_id in ("Blur", "Defocus")], ["Defocus"])
        self.assertEqual(comp.chain(), ["AIBridgeBlur_1", "MediaIn1"])

    def test_unknown_blur_tool_fails_cleanly(self):
        op, comp, item = self.make()
        before = list(comp.tools)
        with self.assertRaises(OperationError):
            op._op_apply_blur_effect({"item_id": item, "blur_type": "mosaic"})
        self.assertEqual(comp.tools, before)
        self.assertEqual(comp.chain(), ["MediaIn1"])

    def test_failed_lua_connects_nothing(self):
        op, comp, item = self.make()
        comp.fail_lua = True
        with self.assertRaises(OperationError):
            op._op_apply_blur_effect({"item_id": item})
        self.assertEqual(comp.chain(), ["MediaIn1"])
        self.assertEqual(len(comp.tools), 2)
        result = op._op_animate_zoom({"item_id": item, "end_zoom": 1.3})
        self.assertFalse(result["keyframes_created"])
        self.assertIn("static Size", result["note"])

    def test_unreadable_marker_is_reported_not_claimed(self):
        op, comp, item = self.make()
        comp.GetData = lambda key: None  # a build that never reports comp data
        result = op._op_keyframe_clip_saturation({"item_id": item})
        self.assertEqual(comp.chain(), ["AIBridgeSaturation", "MediaIn1"])
        # Lua ran (lupa): the read-back decides. No Lua ran: the value never changed.
        self.assertIs(result["verified"], bool(lupa))
        self.assertEqual("note" in result, not lupa)
        node = comp.FindTool("AIBridgeSaturation")
        node.GetInput = lambda *args: 0.5 if len(args) == 1 else None  # input exists, value unreadable
        result = op._op_keyframe_clip_saturation({"item_id": item})
        self.assertIsNone(result["verified"])
        self.assertIn("did not let the bridge read", result["note"])

    def test_nodes_are_tagged(self):
        op, comp, item = self.make()
        op._op_apply_spotlight_mask({"item_id": item})
        tagged = [t for t in comp.tools if t.GetData("ResolveAIBridgeOwner") == FUSION_OWNER]
        self.assertEqual(len(tagged), 4)

    def test_frames_outside_clip_rejected(self):
        op, comp, item = self.make(start=200, end=300)
        for params in ({"start_frame": 50, "end_frame": 150}, {"timeline_start_frame": 100},
                       {"keyframes": [{"frame": 0, "zoom": 1}, {"frame": 0, "zoom": 2}]}):
            with self.assertRaises(OperationError):
                op._op_animate_zoom(dict(params, item_id=item))
        self.assertEqual(len(comp.tools), 2)

    def test_inspect_is_read_only(self):
        op, comp, item = self.make(user_nodes=("Glow",))
        op._op_animate_zoom({"item_id": item})
        before = len(comp.scripts)
        result = op._op_inspect_fusion({"item_id": item, "exec_lua": "error('no')"})
        self.assertEqual(len(comp.scripts), before)
        self.assertEqual(result["bridge_chain"]["stages_before_media_out"], ["zoom"])
        self.assertEqual(result["bridge_chain"]["source"], "Glow1")
        clip = op._find_timeline_items([item])[0][0]
        clip.fusion = None
        self.assertFalse(op._op_inspect_fusion({"item_id": item})["has_fusion"])


@LUA
class FusionLuaTests(unittest.TestCase):
    make = FusionChainTests.make

    def test_zoom_keys_land_on_clip_frames(self):
        op, comp, item = self.make(render_start=1000, start=500, end=600)
        result = op._op_animate_zoom({"item_id": item, "start_zoom": 1, "end_zoom": 2, "easing": "linear",
                                      "timeline_start_frame": 510, "timeline_end_frame": 520})
        zoom = comp.FindTool("AIBridgeZoom")
        self.assertTrue(result["keyframes_verified"], getattr(comp, "last_error", ""))
        self.assertEqual((result["start_frame"], result["end_frame"]), (10, 20))
        self.assertAlmostEqual(zoom.GetInput("Size", 1010), 1.0)
        self.assertAlmostEqual(zoom.GetInput("Size", 1015), 1.5)
        self.assertEqual(sorted(zoom.inputs["Size"].keys)[0], 1010.0)

    def test_center_path_and_static_reset(self):
        op, comp, item = self.make()
        op._op_animate_zoom({"item_id": item, "target_center_x": 0.7, "end_frame": 10, "easing": "linear"})
        zoom = comp.FindTool("AIBridgeZoom")
        self.assertAlmostEqual(zoom.GetInput("Center", 10)[0], 0.7)
        op._op_animate_zoom({"item_id": item, "end_frame": 10})
        self.assertEqual(zoom.GetInput("Center", 10), (0.5, 0.5))

    def test_keyframed_masked_blur(self):
        op, comp, item = self.make()
        result = op._op_apply_blur_effect({"item_id": item, "keyframes": [
            {"frame": 0, "blur_size": 0, "center_x": 0.2, "width": 0.1},
            {"frame": 30, "blur_size": 40, "center_x": 0.8, "width": 0.3}]})
        self.assertTrue(result["verified"], getattr(comp, "last_error", ""))
        mask = comp.FindTool("AIBridgeMask_1")
        self.assertAlmostEqual(mask.GetInput("Width", 30), 0.3)
        self.assertAlmostEqual(mask.GetInput("Center", 30)[0], 0.8)
        result = op._op_apply_blur_effect({"item_id": item})
        self.assertIsNone(comp.FindTool("AIBridgeMask_1"))
        self.assertTrue(result["verified"])

    def test_every_effect_script_runs(self):
        op, comp, item = self.make()
        for name, params in (("_op_apply_spotlight_mask", {"animate": True, "expand": True}),
                             ("_op_keyframe_clip_saturation", {}),
                             ("_op_animate_color_fx", {}),
                             ("_op_apply_blur_effect", {"blur_type": "directional", "animate": True})):
            result = getattr(op, name)(dict(params, item_id=item))
            self.assertNotIn("stopped", str(result.get("note")), getattr(comp, "last_error", ""))
        self.assertAlmostEqual(comp.FindTool("AIBridgeSaturation").GetInput("Saturation", 99), 0.0)

    def test_long_animation_is_chunked(self):
        op, comp, item = self.make(end=9000)
        op._op_animate_zoom({"item_id": item})
        self.assertGreaterEqual(comp.scripts[-1].count("aib_keys(function"), 5)
        self.assertEqual(len(comp.FindTool("AIBridgeZoom").inputs["Size"].keys), 9000)

    def test_missing_input_stops_script(self):
        op, comp, item = self.make()
        result = op._op_animate_zoom({"item_id": item})
        from bridge.operations import FusionEdit
        edit = FusionEdit(op, comp, "zoom")
        self.assertFalse(edit.lua([edit.bind("z", comp.FindTool("AIBridgeZoom")), "z.Nope = 1"]))
        self.assertTrue(result["keyframes_created"])


if __name__ == "__main__":
    unittest.main()
