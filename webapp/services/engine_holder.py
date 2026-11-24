# -*- coding: utf-8 -*-
"""引擎单例与模型自检：把“加载 YOLO 权重”从 InferEngine 构造中单独管理，供 health / 自检接口复用。

- 同一份 (weights_path, device, imgsz, conf, iou) 参数命中缓存时不重复加载；
- 参数变化会替换引擎（M3 的“停止会话→改参→重启”复用这里，前端运行中不热更）；
- 本模块只管理引擎对象，不读视频、不写文件、不碰数据库；投票状态仍按会话单独 new_vote_state。
"""
from __future__ import annotations

import threading
import time

from .infer_engine import InferEngine, InferParams

_LOCK = threading.Lock()
_ENGINE: InferEngine | None = None
_KEY: tuple | None = None


def _key(params: InferParams) -> tuple:
    return (params.weights_path, params.device, params.imgsz, params.conf, params.iou)


def get_engine(params: InferParams) -> InferEngine:
    """按参数获取（必要时创建）引擎；并发调用由锁串行化，避免双份模型占显存。"""
    global _ENGINE, _KEY
    key = _key(params)
    with _LOCK:
        if _ENGINE is not None and _KEY == key:
            return _ENGINE
        engine = InferEngine(params)   # 可能抛异常，此时旧缓存被保留/清空由上层处理
        _ENGINE, _KEY = engine, key
        return engine


def cached_engine() -> InferEngine | None:
    return _ENGINE


def model_brief() -> dict:
    """给 /api/health 使用：只读缓存状态，不触发加载。"""
    e = _ENGINE
    if e is None:
        return {"loaded": False, "name": "", "device": ""}
    return {"loaded": True, "name": e.model_name, "device": e.device_desc}


def selftest(app) -> dict:
    """真实加载当前默认权重并跑一次引擎预热（已包含一次 dummy 推理）。

    不依赖视频文件，耗时几秒级；返回供前端直接展示的中文可读字段。
    """
    started = time.time()
    p = InferParams(
        weights_path=app.config["DEFAULT_WEIGHTS"],
        device=app.config.get("INFER_DEVICE", "auto"),
        imgsz=app.config["DEFAULT_IMGSZ"],
        conf=app.config["DEFAULT_CONF"],
        iou=app.config["DEFAULT_IOU"],
        vote_window=app.config["DEFAULT_VOTE_WINDOW"],
        vote_threshold=app.config["DEFAULT_VOTE_THRESHOLD"],
    )
    p.validate()
    engine = get_engine(p)
    elapsed_ms = round((time.time() - started) * 1000, 1)
    return {
        "ok": True,
        "model_name": engine.model_name,
        "weights_path": p.weights_path,
        "device": engine.device_desc,
        "elapsed_ms": elapsed_ms,
        "params": p.to_dict(),
        "message": f"模型 {engine.model_name} 加载并预热成功（{engine.device_desc}），M2 引擎可用。",
    }
