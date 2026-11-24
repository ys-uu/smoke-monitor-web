# -*- coding: utf-8 -*-
"""Web 在线推理引擎（单阶段香烟检测，唯一实现；供 M3 会话调用）。

蓝本：训练基地 scripts/infer_det_single.py 的整图检测 + 滑动窗口投票 + 橙框 HUD 逻辑。
本引擎只做“加载模型 / 对一帧推理并绘制 / 输出 JPEG 与状态”，**不读取摄像头、不写文件、不操作数据库、不依赖 Flask 上下文**，
以保证可单测、可复用，且不会在误 import 时触发窗口或下载。

坐标约定：所有框 xyxy 与绘制都在【原始输入帧像素坐标】；ultralytics boxes.xyxy 已还原到原图。
颜色/绘制：与训练 CLI 一致（BGR 橙框 (0,165,255)、顶部深色 HUD、ALARM 红底白字）。
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

# 首次加载 / CPU 路径时限制 CPU 线程，避免 torch 把笔记本核占满影响其他进程
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

CIG_LABEL = "cig"                    # 检测框标签（沿用 CLI 命名，模型为单类）
COLOR_BOX = (0, 165, 255)            # BGR 橙色检测框
COLOR_HUD_BG = (20, 20, 20)          # 顶部 HUD 深色背景
COLOR_HUD_TEXT = (235, 235, 235)     # HUD 浅灰字
COLOR_ALARM_BG = (0, 0, 200)         # ALARM 红底（BGR）
ALARM_BOX_WIDTH = 232                # ALARM 角标像素宽，与 CLI 相同
HUD_HEIGHT = 34                      # 顶部 HUD 高度


# ---------- 参数与运行状态 ----------

@dataclass
class InferParams:
    """一次会话的推理参数（由 M3 start 传入并做范围校验，运行中固定不变）。"""
    weights_path: str = ""    # .pt 绝对路径
    device: str = "auto"      # auto / 0（GPU）/ cpu
    imgsz: int = 640
    conf: float = 0.35
    iou: float = 0.70
    use_vote: bool = True     # False 时等价于窗口1/阈值1（直接按单帧 ALARM）
    vote_window: int = 4
    vote_threshold: int = 2

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

    def to_dict(self) -> dict:
        return {
            "weights_path": self.weights_path,
            "model_name": Path(self.weights_path).name,
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
    """滑动窗口投票状态：窗口内最近 N 帧是否有检出，>=阈值即整帧 ALARM。"""
    use_vote: bool = True
    window: int = 4
    threshold: int = 2
    queue: deque = field(init=False)

    def __post_init__(self) -> None:
        self.window = max(1, int(self.window))
        self.threshold = max(1, min(int(self.threshold), self.window))
        self.queue = deque(maxlen=self.window)

    def update(self, has_cig: bool) -> dict:
        """推入一帧检测结果，返回 vote_sum / vote_window / is_alarm。"""
        if not self.use_vote:
            return {"vote_sum": int(has_cig), "vote_window": 1, "is_alarm": bool(has_cig)}
        self.queue.append(1 if has_cig else 0)
        vote_sum = int(sum(self.queue))
        return {
            "vote_sum": vote_sum,
            "vote_window": self.window,
            "is_alarm": vote_sum >= self.threshold,
        }


# ---------- 绘制（只修改传入 frame，不做任何 IO） ----------

def draw_text(img, text: str, org, color=(255, 255, 255), scale: float = 0.55, thickness: int = 2):
    """带黑色描边文字（OpenCV 不支持中文，画面文字统一英文），与 CLI 一致。"""
    x, y = org
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _draw_hud(frame, frame_index: int, n_cig: int, fps_ema: float, vote: dict) -> None:
    """顶部状态条 + ALARM 角标，布局与训练 CLI 一致（窄帧时裁切角标而不是换行）。"""
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, HUD_HEIGHT), COLOR_HUD_BG, -1)
    hud = (f"[WEB full-frame] FPS {fps_ema:5.1f} | frame {frame_index} "
           f"| cig boxes {n_cig} | vote {vote['vote_sum']}/{vote['vote_window']}")
    cv2.putText(frame, hud, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.58, COLOR_HUD_TEXT, 2, cv2.LINE_AA)
    if vote["is_alarm"] and w > ALARM_BOX_WIDTH + 16:
        cv2.rectangle(frame, (w - ALARM_BOX_WIDTH, 4), (w - 8, 30), COLOR_ALARM_BG, -1)
        cv2.putText(frame, "SMOKING ALARM", (w - 222, 23), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2, cv2.LINE_AA)


# ---------- 模型引擎 ----------

class InferEngine:
    """一次 YOLO 权重加载 + 任意帧在线推理。

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
        weight = Path(params.weights_path)
        if not weight.is_file():
            raise FileNotFoundError(f"未找到香烟检测权重: {weight}")
        self.model_name = weight.name
        self.model = YOLO(str(weight))   # 本机自包含 models/*.pt，不联网下载
        # 预热一次，避免首帧明显卡顿；M3 加载失败可返回明确错误给前端
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        self.model.predict(dummy, imgsz=self.params.imgsz, conf=self.params.conf,
                           iou=self.params.iou, device=self.device, verbose=False)

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

    def process_frame(self, frame, state: VoteState, draw: bool = True):
        """对一帧推理并绘制，返回 (JPEG 字节, info 字典)。

        - frame：OpenCV BGR ndarray，函数内部复制后再绘制，**不会改动调用方持有的原帧**；
        - state：由 new_vote_state 创建并逐帧复用（会话内投票窗口跨帧累计）；
        - draw=False 时仅推理，返回的 JPEG 为原图（仍带检测信息，供未来“无框画面”选项使用）。
        """
        p = self.params
        t0 = time.time()
        results = self.model.predict(
            frame, imgsz=p.imgsz, conf=p.conf, iou=p.iou, device=self.device, verbose=False
        )
        infer_ms = (time.time() - t0) * 1000.0

        boxes = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            conf = float(box.conf[0])
            boxes.append({"xyxy": [x1, y1, x2, y2], "conf": round(conf, 4), "cls_name": CIG_LABEL})
        max_conf = max((b["conf"] for b in boxes), default=0.0)
        vote = state.update(has_cig=bool(boxes))

        # FPS 指数平滑：沿用 CLI 的 0.9 旧值 + 0.1 当前值
        inst_fps = 1.0 / max(time.time() - t0, 1e-6)
        fps_ema = getattr(state, "fps_ema", 0.0)
        fps_ema = inst_fps if fps_ema == 0 else 0.9 * fps_ema + 0.1 * inst_fps
        state.fps_ema = fps_ema

        out = frame.copy() if draw else frame
        frame_index = state.frame_index   # 先取当前帧号（从 1 起），绘制完成后自增
        if draw:
            for b in boxes:
                x1, y1, x2, y2 = b["xyxy"]
                cv2.rectangle(out, (x1, y1), (x2, y2), COLOR_BOX, 2)
                draw_text(out, f"{CIG_LABEL} {b['conf']:.2f}", (x1, max(15, y1 - 6)),
                          color=COLOR_BOX, scale=0.5)
            _draw_hud(out, frame_index, len(boxes), fps_ema, vote)

        ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("JPEG 编码失败")

        info = {
            "frame_index": frame_index,
            "cig_count": len(boxes),
            "max_conf": round(max_conf, 4),
            "infer_ms": round(infer_ms, 2),
            "fps_ema": round(fps_ema, 2),
            "device": self.device_desc,
            **vote,          # vote_sum / vote_window / is_alarm
            "boxes": boxes,
        }
        state.frame_index += 1
        return buf.tobytes(), info


def new_vote_state(params: InferParams) -> VoteState:
    """每个会话/视频源创建一份新的投票状态（避免跨会话累计）。"""
    state = VoteState(use_vote=params.use_vote, window=params.vote_window, threshold=params.vote_threshold)
    state.frame_index = 1   # 与 CLI 一致从 1 开始
    state.fps_ema = 0.0
    return state
