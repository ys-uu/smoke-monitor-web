import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from webapp.services.face_detector import FaceRegion, face_region
from webapp.services.head_detector import head_region
from webapp.services.infer_engine import InferEngine, InferParams, new_vote_state


class TwoStageInferenceTests(unittest.TestCase):
    def test_face_roi_expands_by_fixed_pad_and_clips_to_frame(self):
        # 固定外扩 3 像素：(2,3,22,33) → 左上被画面裁到 0，右下 (25,36)
        region = face_region((2, 3, 22, 33), track_id=7, width=40, height=40, expand_pad=3)
        self.assertEqual(region, FaceRegion((2, 3, 22, 33), (0, 0, 25, 36), 7))
        # 外扩 0 时 2×2 小框 ROI 不足 4 像素，应判无效
        self.assertIsNone(face_region((0, 0, 2, 2), track_id=None, width=40, height=40, expand_pad=0))

    def test_head_roi_expands_by_fixed_pad_and_clips_to_frame(self):
        # 头部框与人脸框同口径，固定外扩 3 像素 → ROI (0,0,25,36)
        region = head_region((2, 3, 22, 33), track_id=7, width=40, height=40, expand_pad=3)
        self.assertEqual(region, FaceRegion((2, 3, 22, 33), (0, 0, 25, 36), 7))
        # 退化框（x2<=x1）无论外扩多少都应判无效
        self.assertIsNone(head_region((5, 5, 5, 5), track_id=None, width=40, height=40, expand_pad=3))

    def test_infer_params_validates_detector_kind(self):
        head = InferParams(weights_path="cig.pt", detector_kind="head", head_weights_path="h.pt")
        head.validate()  # head 模式参数齐全应通过
        missing = InferParams(weights_path="cig.pt", detector_kind="head")
        with self.assertRaises(ValueError):
            missing.validate()  # head 模式缺权重应报错
        bad = InferParams(weights_path="cig.pt", detector_kind="body")
        with self.assertRaises(ValueError):
            bad.validate()  # 非法 kind 应报错

    def test_infer_params_validates_expand_pad(self):
        ok_kwargs = dict(weights_path="cig.pt", detector_kind="head", head_weights_path="h.pt")
        InferParams(expand_pad=0, **ok_kwargs).validate()    # 下界 0 应通过
        InferParams(expand_pad=200, **ok_kwargs).validate()  # 上界 200 应通过
        with self.assertRaises(ValueError):
            InferParams(expand_pad=-1, **ok_kwargs).validate()
        with self.assertRaises(ValueError):
            InferParams(expand_pad=201, **ok_kwargs).validate()

    def test_no_face_skips_cigarette_model_and_clears_votes(self):
        engine = self.make_engine([])
        state = new_vote_state(engine.params)
        state.update([(7, True)])
        state.update([(7, True)])
        frame = np.zeros((100, 120, 3), dtype=np.uint8)

        _, info = engine.process_frame(frame, state, draw=False)
        self.assertEqual(info["face_count"], 0)
        self.assertEqual(info["cig_count"], 0)
        self.assertEqual(info["boxes"], [])
        self.assertFalse(info["is_alarm"])
        self.assertEqual(state.histories, {})
        engine.model.predict.assert_not_called()

    def test_overlapping_crops_map_to_frame_and_deduplicate_cigarettes(self):
        engine = self.make_engine([
            FaceRegion((20, 12, 55, 32), (10, 10, 70, 60), 7),
            FaceRegion((35, 13, 62, 36), (30, 20, 100, 75), 9),
        ])
        first = SimpleNamespace(boxes=[SimpleNamespace(xyxy=np.array([[30, 25, 43, 34]]), conf=[0.91])])
        second = SimpleNamespace(boxes=[SimpleNamespace(xyxy=np.array([[14, 15, 27, 24]]), conf=[0.88])])
        engine.model.predict.side_effect = [[first], [second], [first], [second]]
        frame = np.zeros((100, 120, 3), dtype=np.uint8)
        state = new_vote_state(engine.params)
        _, info = engine.process_frame(frame, state, draw=False)

        self.assertEqual(info["face_count"], 2)
        self.assertEqual(info["boxes"], [{"xyxy": [40, 35, 53, 44], "conf": 0.91, "cls_name": "cig"}])
        crops = [call.args[0] for call in engine.model.predict.call_args_list]
        self.assertEqual([crop.shape[:2] for crop in crops], [(50, 60), (55, 70)])
        self.assertTrue(np.all(crops[0][0, 0] == 180))
        self.assertFalse(frame.any())
        self.assertEqual(info["vote_sum"], 1)
        self.assertFalse(info["is_alarm"])
        _, second_frame = engine.process_frame(frame, state, draw=False)
        self.assertTrue(second_frame["is_alarm"])
        self.assertEqual(second_frame["alarm_persons"], 2)

    def test_votes_do_not_accumulate_across_people_or_unassigned_detections(self):
        state = new_vote_state(InferParams(use_vote=True, vote_window=4, vote_threshold=2))
        self.assertEqual(state.update([(7, True), (9, False)]), [(1, False), (0, False)])
        self.assertEqual(state.update([(7, False), (9, True)]), [(1, False), (1, False)])
        self.assertEqual(state.update([(9, True), (None, True), (None, True)]), [(2, True), (1, False), (1, False)])
        self.assertEqual(set(state.histories), {9})

    def test_vote_disabled_matches_current_frame_only(self):
        # 显式关闭红框保持，回到"仅看当前帧"的原始口径
        state = new_vote_state(InferParams(alarm_hold_frames=0))
        self.assertEqual(state.update([(7, True), (9, False)]), [(1, True), (0, False)])
        state.frame_index += 1
        self.assertEqual(state.update([(7, False)]), [(0, False)])

    def test_alarm_hold_keeps_red_box_during_short_miss(self):
        # hold=3：第1帧报警，随后漏检在保持期内仍判报警，超过保持帧数才退出
        state = new_vote_state(InferParams(alarm_hold_frames=3))
        self.assertEqual(state.update([(7, True)]), [(1, True)])
        for expected in ((0, True), (0, True), (0, True)):
            state.frame_index += 1
            self.assertEqual(state.update([(7, False)]), [expected])
        state.frame_index += 1
        self.assertEqual(state.update([(7, False)]), [(0, False)])  # 第5帧差 4>3，退出

    def test_alarm_hold_zero_disables_holding(self):
        state = new_vote_state(InferParams(alarm_hold_frames=0))
        self.assertEqual(state.update([(7, True)]), [(1, True)])
        state.frame_index += 1
        self.assertEqual(state.update([(7, False)]), [(0, False)])  # 立即退出，不保持

    def test_alarm_hold_ignores_unassigned_detection(self):
        # 无跟踪 ID 无法跨帧保持，下一帧立即恢复
        state = new_vote_state(InferParams(alarm_hold_frames=5))
        self.assertEqual(state.update([(None, True)]), [(1, True)])
        state.frame_index += 1
        self.assertEqual(state.update([(None, False)]), [(0, False)])

    @staticmethod
    def make_engine(faces):
        engine = InferEngine.__new__(InferEngine)
        engine.params = InferParams(use_vote=True, vote_window=4, vote_threshold=2)
        engine.device = "cpu"
        engine.face_detector = Mock()
        engine.face_detector.detect.return_value = faces
        engine.model = Mock()
        return engine
