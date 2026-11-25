import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from webapp.services.face_detector import FaceRegion, face_region
from webapp.services.infer_engine import InferEngine, InferParams, new_vote_state


class TwoStageInferenceTests(unittest.TestCase):
    def test_face_roi_expands_by_thirty_percent_and_clips_to_frame(self):
        region = face_region((2, 3, 22, 33), track_id=7, width=40, height=40)
        self.assertEqual(region, FaceRegion((2, 3, 22, 33), (0, 0, 28, 40), 7))
        self.assertIsNone(face_region((0, 0, 2, 2), track_id=None, width=40, height=40))

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
        state = new_vote_state(InferParams())
        self.assertEqual(state.update([(7, True), (9, False)]), [(1, True), (0, False)])
        self.assertEqual(state.update([(7, False)]), [(0, False)])

    @staticmethod
    def make_engine(faces):
        engine = InferEngine.__new__(InferEngine)
        engine.params = InferParams(use_vote=True, vote_window=4, vote_threshold=2)
        engine.device = "cpu"
        engine.face_detector = Mock()
        engine.face_detector.detect.return_value = faces
        engine.model = Mock()
        return engine
