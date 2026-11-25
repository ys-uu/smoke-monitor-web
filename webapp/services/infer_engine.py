# -*- coding: utf-8 -*-
"""Web 推理引擎：检测人脸、在局部区域检测香烟，然后投票和编码 JPEG。"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
from ..config import FACE_WEIGHTS
from .face_detector import FaceDetector, FaceRegion, new_face_tracker
from .model_loader import load_yolo

# 首次加载 / CPU 路径时限制 CPU 线程，避免 torch 把笔记本核占满影响其他进程
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

CIG_LABEL = "cig"                    # 检测框标签（沿用 CLI 命名，模型为单类）
COLOR_BOX = (0, 165, 255)            # BGR 橙色检测框
COLOR_ROI = (180, 180, 180)          # BGR 灰色搜索区域
COLOR_FACE_NORMAL = (0, 255, 0)
COLOR_FACE_ALARM = (0, 0, 255)
COLOR_HUD_BG = (20, 20, 20)          # 顶部 HUD 深色背景
COLOR_HUD_TEXT = (235, 235, 235)     # HUD 浅灰字
COLOR_ALARM_BG = (0, 0, 200)         # ALARM 红底（BGR）
ALARM_BOX_WIDTH = 232                # ALARM 角标像素宽，与 CLI 相同
HUD_HEIGHT = 34                      # 顶部 HUD 高度
GLOBAL_NMS_IOU = 0.40


# ---------- 参数与运行状态 ----------

@dataclass
class InferParams:
    """一次会话的推理参数（由 M3 start 传入并做范围校验，运行中固定不变）。"""
    weights_path: str = ""    # .pt 绝对路径
    device: str = "auto"      # auto / 0（GPU）/ cpu
    imgsz: int = 960
    conf: float = 0.35
    iou: float = 0.70
    use_vote: bool = False
    vote_window: int = 1
    vote_threshold: int = 1
    face_weights_path: str = str(FACE_WEIGHTS)
    face_conf: float = 0.35

    def validate(self) -> None:
        if not (0.01 <= self.conf <= 1.0):
            raise ValueError("conf 应在 [0.01, 1.0] 范围")
        if not (0.0 < self.iou <= 1.0):
            raise ValueError("iou 应在 (0, 1.0] 范围")
        if self.imgsz < 32 or self.imgsz > 1920:
            raise ValueError("imgsz 应在 [32, 1920] 范围")
        if self.vote_window < 1 or self.vote_window > 120:
            raise ValueError("vote_window 应在 [1, 120] 范围")
        if not (1 <= self.vote_threshold <= self.vote_window):
            raise ValueError("vote_threshold 应在 [1, vote_window] 范围")
        if not self.weights_path:
            raise ValueError("weights_path 不能为空")
        if not self.face_weights_path:
            raise ValueError("face_weights_path 不能为空")
        if not (0.01 <= self.face_conf <= 1.0):
            raise ValueError("face_conf 应在 [0.01, 1.0] 范围")

    def to_dict(self) -> dict:
        return {
            "weights_path": self.weights_path,
            "model_name": Path(self.weights_path).name,
            "face_weights_path": self.face_weights_path,
            "face_model_name": Path(self.face_weights_path).name,
            "face_conf": self.face_conf,
            "device": self.device,
            "imgsz": self.imgsz,
            "conf": self.conf,
            "iou": self.iou,
            "use_vote": self.use_vote,
            "vote_window": self.vote_window,
            "vote_threshold": self.vote_threshold,
        }


@dataclass
class VoteState:
    """Tracker, votes and frame counters for one video session."""
    use_vote: bool
    window: int
    threshold: int
    tracker: object
    frame_index: int = 1
    fps_ema: float = 0.0
    histories: dict[int, deque] = field(default_factory=dict)

    def update(self, observations: list[tuple[int | None, bool]]) -> list[tuple[int, bool]]:
        if not self.use_vote:
            return [(int(has_cig), has_cig) for _, has_cig in observations]

        active = set()
        votes = []
        for track_id, has_cig in observations:
            count = int(has_cig)
            if track_id is not None:
                active.add(track_id)
                if track_id not in self.histories:
                    self.histories[track_id] = deque(maxlen=self.window)
                history = self.histories[track_id]
                history.append(count)
                count = sum(history)
            votes.append((count, count >= self.threshold))
        for track_id in self.histories.keys() - active:
            del self.histories[track_id]
        return votes


# ---------- 绘制（只修改传入 frame，不做任何 IO） ----------

def draw_text(img, text: str, org, color=(255, 255, 255), scale: float = 0.55, thickness: int = 2):
    """带黑色描边文字（OpenCV 不支持中文，画面文字统一英文），与 CLI 一致。"""
    x, y = org
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _draw_hud(frame, frame_index: int, n_faces: int, n_cig: int, fps_ema: float, alarm_persons: int) -> None:
    """顶部状态条 + ALARM 角标，布局与训练 CLI 一致（窄帧时裁切角标而不是换行）。"""
    w = frame.shape[1]
    cv2.rectangle(frame, (0, 0), (w, HUD_HEIGHT), COLOR_HUD_BG, -1)
    hud = (f"[TWO face-ROI] FPS {fps_ema:5.1f} | frame {frame_index} | faces {n_faces} "
           f"| cig boxes {n_cig} | alarm persons {alarm_persons}")
    cv2.putText(frame, hud, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.58, COLOR_HUD_TEXT, 2, cv2.LINE_AA)
    if alarm_persons and w > ALARM_BOX_WIDTH + 16:
        cv2.rectangle(frame, (w - ALARM_BOX_WIDTH, 4), (w - 8, 30), COLOR_ALARM_BG, -1)
        cv2.putText(frame, "SMOKING ALARM", (w - 222, 23), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2, cv2.LINE_AA)


def _draw_detections(frame, faces, boxes, votes, state):
    for box in boxes:
        x1, y1, x2, y2 = box["xyxy"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_BOX, 2)
        draw_text(frame, f"{CIG_LABEL} {box['conf']:.2f}", (x1, max(15, y1 - 6)), color=COLOR_BOX, scale=0.5)
    for face, (count, is_alarm) in zip(faces, votes, strict=True):
        x1, y1, x2, y2 = face.box
        color = COLOR_FACE_ALARM if is_alarm else COLOR_FACE_NORMAL
        track_id = face.track_id if face.track_id is not None else -1
        tag = f"ID{track_id} {'SMOKE' if is_alarm else 'normal'}"
        if state.use_vote:
            tag += f" {count}/{state.window}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        draw_text(frame, tag, (x1, max(15, y1 - 8)), color=color, scale=0.55)


def _cigarette_in_region(region, boxes) -> bool:
    left, top, right, bottom = region
    for box in boxes:
        x1, y1, x2, y2 = box["xyxy"]
        if left <= (x1 + x2) / 2 <= right and top <= (y1 + y2) / 2 <= bottom:
            return True
    return False


# ---------- 模型引擎 ----------

class InferEngine:
    """预热两个 YOLO 模型后，对传入的视频帧执行两阶段推理。

    使用方式（M3 会话线程）：
        engine = InferEngine(InferParams(...))   # 仅此处做一次模型加载
        state = new_vote_state(engine.params)    # 每个新会话/新视频源各建一份
        for frame in frames:
            jpeg, info = engine.process_frame(frame, state)
    """

    def __init__(self, params: InferParams):
        params.validate()
        self.params = params
        self.device = self._resolve_device(params.device)
        weight = Path(params.weights_path).expanduser()
        if not weight.is_file():
            raise FileNotFoundError(f"未找到香烟检测权重: {weight}")
        self.model_name = weight.name
        self.face_detector = FaceDetector(params.face_weights_path, params.face_conf, self.device)
        self.face_model_name = self.face_detector.model_name
        self.model = load_yolo(weight)
        # 预热一次，避免首帧明显卡顿；M3 加载失败可返回明确错误给前端
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        self.face_detector.predict(dummy)
        self._predict_crop(dummy)

    @staticmethod
    def _resolve_device(device: str) -> str:
        """auto 优先 CUDA，否则 cpu；显式 '0'/'cuda:0' 但 CUDA 不可用时回退 cpu。"""
        d = (device or "auto").strip()
        if d == "auto":
            return "cuda:0" if torch.cuda.is_available() else "cpu"
        if d in ("0", "cuda:0") and not torch.cuda.is_available():
            return "cpu"
        return "cuda:0" if d == "0" else d

    @property
    def device_desc(self) -> str:
        if str(self.device).startswith("cuda"):
            try:
                return f"{self.device} {torch.cuda.get_device_name(0)}"
            except Exception:
                return self.device
        return "CPU"

    def _predict_crop(self, crop):
        p = self.params
        return self.model.predict(crop, imgsz=p.imgsz, conf=p.conf, iou=p.iou,
                                  device=self.device, verbose=False)[0].boxes

    def _detect_cigarettes(self, frame, faces: list[FaceRegion]) -> list[dict]:
        candidates = []
        for face in faces:
            left, top, right, bottom = face.crop
            cv2.rectangle(frame, (left, top), (right, bottom), COLOR_ROI, 1)
            crop = frame[top:bottom, left:right].copy()
            for box in self._predict_crop(crop):
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                x1, y1 = max(left, int(left + x1)), max(top, int(top + y1))
                x2, y2 = min(right, int(left + x2)), min(bottom, int(top + y2))
                if x2 > x1 and y2 > y1:
                    candidates.append(([x1, y1, x2 - x1, y2 - y1], float(box.conf[0])))

        # Neighboring faces can produce overlapping crops and detect the same cigarette twice.
        if not candidates:
            return []
        rectangles, scores = zip(*candidates)
        kept = cv2.dnn.NMSBoxes(rectangles, scores, 0.0, GLOBAL_NMS_IOU)
        boxes = []
        for index in kept:
            x, y, width, height = rectangles[index]
            boxes.append({"xyxy": [x, y, x + width, y + height],
                          "conf": scores[index], "cls_name": CIG_LABEL})
        return boxes

    def process_frame(self, frame, state: VoteState, draw: bool = True):
        """对一帧推理并绘制，返回 (JPEG 字节, info 字典)。

        - frame：OpenCV BGR ndarray，函数内部复制后再绘制，**不会改动调用方持有的原帧**；
        - state：由 new_vote_state 创建并逐帧复用（会话内投票窗口跨帧累计）；
        - draw=False 时仅推理，返回的 JPEG 为原图（仍带检测信息，供未来“无框画面”选项使用）。
        """
        t0 = time.perf_counter()
        faces = self.face_detector.detect(frame, state.tracker)
        # The reference script draws each ROI guide before extracting that crop.
        marked = frame.copy() if draw or faces else frame
        boxes = self._detect_cigarettes(marked, faces)
        infer_seconds = time.perf_counter() - t0
        max_conf = max((b["conf"] for b in boxes), default=0.0)
        votes = state.update([(face.track_id, _cigarette_in_region(face.crop, boxes)) for face in faces])
        alarm_persons = sum(is_alarm for _, is_alarm in votes)

        out = marked if draw else frame
        frame_index = state.frame_index
        if draw:
            _draw_detections(out, faces, boxes, votes, state)

        # FPS 指数平滑：沿用 CLI 的 0.9 旧值 + 0.1 当前值
        inst_fps = 1.0 / max(time.perf_counter() - t0, 1e-6)
        fps_ema = state.fps_ema
        fps_ema = inst_fps if fps_ema == 0 else 0.9 * fps_ema + 0.1 * inst_fps
        state.fps_ema = fps_ema

        if draw:
            _draw_hud(out, frame_index, len(faces), len(boxes), fps_ema, alarm_persons)

        ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("JPEG 编码失败")

        info = {
            "frame_index": frame_index,
            "face_count": len(faces),
            "cig_count": len(boxes),
            "alarm_persons": alarm_persons,
            "max_conf": round(max_conf, 4),
            "infer_ms": round(infer_seconds * 1000.0, 2),
            "fps_ema": round(fps_ema, 2),
            "device": self.device_desc,
            "vote_sum": max((count for count, _ in votes), default=0),
            "vote_window": state.window if state.use_vote else 1,
            "is_alarm": alarm_persons > 0,
            "boxes": [{**box, "conf": round(box["conf"], 4)} for box in boxes],
        }
        state.frame_index += 1
        return buf.tobytes(), info


def new_vote_state(params: InferParams) -> VoteState:
    """每个会话/视频源创建一份新的投票状态（避免跨会话累计）。"""
    return VoteState(params.use_vote, params.vote_window, params.vote_threshold, new_face_tracker())
