"""YOLO face boxes and BoT-SORT IDs for each video session."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from ultralytics.utils import ROOT, IterableSimpleNamespace, yaml_load

from .model_loader import load_yolo

Box = tuple[int, int, int, int]
FACE_IMGSZ = 640


@dataclass(frozen=True)
class FaceRegion:
    box: Box
    crop: Box
    track_id: int | None = None


def new_face_tracker():
    from ultralytics.trackers.bot_sort import BOTSORT

    config = IterableSimpleNamespace(**yaml_load(ROOT / "cfg/trackers/botsort.yaml"))
    return BOTSORT(args=config, frame_rate=30)


class FaceDetector:
    def __init__(self, weights_path: str, confidence: float, device: str):
        weights = Path(weights_path).expanduser()
        if not weights.is_file():
            raise FileNotFoundError(f"未找到 YOLO 人脸检测权重：{weights}")
        if find_spec("lap") is None:
            raise RuntimeError("人脸跟踪需要 lapx，请安装 requirements-web.txt 中的依赖")
        self.model_name = weights.name
        self.confidence = confidence
        self.device = device
        self.model = load_yolo(weights, face=True)

    def predict(self, frame):
        return self.model.predict(frame, imgsz=FACE_IMGSZ, conf=self.confidence,
                                  device=self.device, verbose=False)[0].boxes

    def detect(self, frame, tracker, expand_pad: int) -> list[FaceRegion]:
        boxes = self.predict(frame)
        if boxes is None or not len(boxes):
            return []
        detections = boxes.cpu().numpy()

        # Match the result selection of Ultralytics track(persist=True).
        tracks = tracker.update(detections, frame)
        if len(tracks):
            observations = [(row[:4], int(row[4])) for row in tracks]
        else:
            observations = [(box, None) for box in detections.xyxy]

        height, width = frame.shape[:2]
        regions = []
        for coordinates, track_id in observations:
            region = face_region(coordinates, track_id, width, height, expand_pad)
            if region is not None:
                regions.append(region)
        return regions


def face_region(coordinates, track_id: int | None, width: int, height: int,
                expand_pad: int) -> FaceRegion | None:
    x1, y1, x2, y2 = map(int, coordinates)
    if x2 <= x1 or y2 <= y1:
        return None
    # 固定像素外扩（宽高同一值），不随框大小变化，再裁剪到画面边界
    pad_x = pad_y = int(expand_pad)
    roi = (max(0, x1 - pad_x), max(0, y1 - pad_y), min(width, x2 + pad_x), min(height, y2 + pad_y))
    if roi[2] - roi[0] < 4 or roi[3] - roi[1] < 4:
        return None
    return FaceRegion((x1, y1, x2, y2), roi, track_id)
