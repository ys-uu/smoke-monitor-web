# -*- coding: utf-8 -*-
"""模型目录扫描与前端选择解析：动态发现一阶段/二阶段权重并做安全校验。

目录约定（见 config.py）：
- stage1/face、stage1/head：一阶段人脸 / 头部模型，扫描结果按 kind 分组；
- stage2：二阶段香烟模型。
前端只传相对 value（一阶段如 "face/yolov8n-face.pt"，二阶段为文件名），
本模块先比对扫描白名单、再做目录内安全解析，拦截路径穿越、非 .pt 与目录外文件。
"""
from __future__ import annotations

from pathlib import Path

from ..api import ApiError

MODEL_SUFFIX = ".pt"


def _model_files(directory: Path) -> list[Path]:
    """安全列出目录内一层的 .pt 文件（不递归），按文件名排序。"""
    if not directory.is_dir():
        return []
    files = [path for path in directory.iterdir()
             if path.is_file() and path.suffix.lower() == MODEL_SUFFIX]
    return sorted(files, key=lambda path: path.name.casefold())


def list_stage1_models(config) -> list[dict]:
    """扫描一阶段 face / head 两个目录，返回分组后的可选项。"""
    items = []
    for kind, directory in (("face", config["FACE_DIR"]), ("head", config["HEAD_DIR"])):
        for path in _model_files(directory):
            items.append({"kind": kind, "file": path.name, "value": f"{kind}/{path.name}"})
    return items


def list_stage2_models(config) -> list[dict]:
    """扫描二阶段目录，返回可选项。"""
    return [{"file": path.name, "value": path.name} for path in _model_files(config["STAGE2_DIR"])]


def _safe_join(directory: Path, filename: str) -> Path:
    """在指定目录内解析文件名，拦截路径穿越并确认文件存在且为 .pt。"""
    base = directory.resolve()
    target = (directory / filename).resolve()
    if not target.is_relative_to(base) or not target.is_file() or target.suffix.lower() != MODEL_SUFFIX:
        raise ApiError("非法的模型路径")
    return target


def resolve_stage1(choice, config) -> tuple[str, str]:
    """校验一阶段选择，返回 (detector_kind, 权重绝对路径)。"""
    allowed = {item["value"] for item in list_stage1_models(config)}
    if not isinstance(choice, str) or choice not in allowed:
        raise ApiError("一阶段模型不在可选列表中，请刷新后重新选择")
    kind, filename = choice.split("/", 1)
    directory = config["FACE_DIR"] if kind == "face" else config["HEAD_DIR"]
    return kind, str(_safe_join(directory, filename))


def resolve_stage2(choice, config) -> str:
    """校验二阶段选择，返回权重绝对路径。"""
    allowed = {item["value"] for item in list_stage2_models(config)}
    if not isinstance(choice, str) or choice not in allowed:
        raise ApiError("二阶段模型不在可选列表中，请刷新后重新选择")
    return str(_safe_join(config["STAGE2_DIR"], choice))
