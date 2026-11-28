# -*- coding: utf-8 -*-
"""YOLO 头部检测与 BoT-SORT 跟踪：第一阶段的 head 方案（含侧脸、背面）。

与 face_detector.py 的区别：
- 人脸检测器只在能看到五官时检出，背面/大侧脸会漏；
- 本检测器标注整个头部（含后脑勺），各种朝向都能定位，跟踪 ID 同样用 BoT-SORT。
接口与 FaceDetector 保持一致（detect 返回 FaceRegion 列表），InferEngine 无需区分即可复用。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .face_detector import FaceRegion, new_face_tracker
from .model_loader import load_yolo

HEAD_IMGSZ = 640


@dataclass(frozen=True)
class HeadDetector:
    """头部检测器：结构与 FaceDetector 平行，加载标准 YOLO head 权重。"""
    weights_path: str
    confidence: float
    device: str
    model_name: str
    model: object

    @classmethod
    def build(cls, weights_path: str, confidence: float, device: str) -> "HeadDetector":
        weights = Path(weights_path).expanduser()
        if not weights.is_file():
            raise FileNotFoundError(f"未找到头部检测权重：{weights}")
        model = load_yolo(weights, face=False)   # 标准检测权重，无需旧人脸兼容
        return cls(str(weights), confidence, device, weights.name, model)

    def predict(self, frame):
        return self.model.predict(frame, imgsz=HEAD_IMGSZ, conf=self.confidence,
                                 device=self.device, verbose=False)[0].boxes

    def detect(self, frame, tracker, expand_pad: int) -> list[FaceRegion]:
        boxes = self.predict(frame)
        if boxes is None or not len(boxes):
            return []
        detections = boxes.cpu().numpy()

        # 与 FaceDetector 同一套跟踪匹配口径
        tracks = tracker.update(detections, frame)
        if len(tracks):
            observations = [(row[:4], int(row[4])) for row in tracks]
        else:
            observations = [(box, None) for box in detections.xyxy]

        height, width = frame.shape[:2]
        regions = []
        for coordinates, track_id in observations:
            region = head_region(coordinates, track_id, width, height, expand_pad)
            if region is not None:
                regions.append(region)
        return regions


def head_region(coordinates, track_id: int | None, width: int, height: int,
                expand_pad: int) -> FaceRegion | None:
    """头部框按固定像素外扩并裁剪到画面边界，返回与 FaceRegion 同构的区域。"""
    x1, y1, x2, y2 = map(int, coordinates)
    if x2 <= x1 or y2 <= y1:
        return None
    # 固定像素外扩（宽高同一值），不随框大小变化，再裁剪到画面边界
    pad_x = pad_y = int(expand_pad)
    roi = (max(0, x1 - pad_x), max(0, y1 - pad_y),
           min(width, x2 + pad_x), min(height, y2 + pad_y))
    if roi[2] - roi[0] < 4 or roi[3] - roi[1] < 4:
        return None
    return FaceRegion((x1, y1, x2, y2), roi, track_id)
