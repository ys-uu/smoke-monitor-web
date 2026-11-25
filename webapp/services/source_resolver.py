from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..api import ApiError
from ..config import PROJ_ROOT


@dataclass(frozen=True)
class VideoSource:
    kind: str
    key: str
    name: str
    capture_input: str | int


def _video_file(path: Path, config, root: Path | None = None) -> Path:
    if path.suffix.lower() not in config["ALLOWED_VIDEO_EXTS"]:
        raise ApiError("不支持该视频扩展名")
    try:
        path = path.resolve(strict=True)
        if root is not None and not path.is_relative_to(root.resolve()):
            raise ApiError("视频路径超出允许范围")
        if path.suffix.lower() not in config["ALLOWED_VIDEO_EXTS"] or not path.is_file():
            raise ApiError("所选路径必须是受支持的视频文件")
    except ApiError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ApiError("视频文件不存在或无法访问") from exc
    return path


def list_samples(config):
    root = config["SAMPLE_VIDEO_DIR"]
    items = []
    if root.is_dir():
        for path in sorted(root.iterdir(), key=lambda entry: entry.name.casefold()):
            try:
                resolved = _video_file(path, config, root)
                items.append({"name": path.name, "size_bytes": resolved.stat().st_size})
            except (ApiError, OSError):
                continue
    return items


def resolve_source(kind, source, config) -> VideoSource:
    if kind == "camera":
        index = config["CAMERA_DEFAULT_INDEX"] if source is None else source
        if type(index) is not int or not 0 <= index <= 99:
            raise ApiError("摄像头编号必须是 0 到 99 的整数")
        return VideoSource(kind, f"camera:{index}", f"摄像头 {index}", index)

    if kind not in ("sample", "local", "upload"):
        raise ApiError("不支持该视频来源")
    if not isinstance(source, str) or not source.strip() or "\0" in source:
        raise ApiError("请选择或填写视频来源")

    if kind == "sample":
        if any(char in source for char in "/\\:"):
            raise ApiError("样例来源必须是样例列表中的文件名")
        root = config["SAMPLE_VIDEO_DIR"]
        path = _video_file(root / source, config, root)
        key = f"sample:{source}"
        if len(key) > 64:
            key = "sample:" + hashlib.sha256(source.encode()).hexdigest()[:32]
        return VideoSource(kind, key, source[:255], str(path))

    if kind == "upload":
        if not re.fullmatch(r"[0-9a-f]{32}", source):
            raise ApiError("上传文件编号无效")
        root = config["UPLOAD_DIR"]
        folder = root / source
        try:
            if not folder.resolve().is_relative_to(root.resolve()):
                raise ApiError("上传路径超出允许范围")
            meta = json.loads((folder / "upload.json").read_text(encoding="utf-8"))
            extension = meta["extension"]
            name = meta["name"]
        except ApiError:
            raise
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            raise ApiError("已上传的视频不存在，请重新上传") from exc
        if not isinstance(name, str) or not isinstance(extension, str) or extension not in config["ALLOWED_VIDEO_EXTS"]:
            raise ApiError("已上传的视频格式无效")
        path = _video_file(folder / f"video{extension}", config, root)
        return VideoSource(kind, f"upload:{source}", name[:255], str(path))

    raw = source.strip().strip('"')
    if raw.startswith(("\\\\", "//")) or "://" in raw:
        raise ApiError("请输入本机视频路径")
    path = Path(raw).expanduser()
    path = _video_file(PROJ_ROOT / path, config)
    roots = config["LOCAL_PATH_ALLOWED_ROOTS"]
    if roots != "*" and not any(path.is_relative_to(root.resolve()) for root in roots):
        raise ApiError("视频路径超出允许范围")
    key = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:32]
    return VideoSource(kind, f"local:{key}", path.name[:255], str(path))


def save_upload(file, config):
    name = Path(file.filename.replace("\\", "/")).name
    extension = Path(name).suffix.lower()
    if extension not in config["ALLOWED_VIDEO_EXTS"]:
        raise ApiError("不支持该视频扩展名")
    upload_id = uuid4().hex
    folder = config["UPLOAD_DIR"] / upload_id
    folder.mkdir(parents=True)
    path = folder / f"video{extension}"
    metadata = folder / "upload.json"
    try:
        file.save(path)
        size = path.stat().st_size
        if not size:
            raise ApiError("上传的视频为空")
        probe_video(str(path))
        metadata.write_text(json.dumps({"name": name, "extension": extension}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        metadata.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        folder.rmdir()
        raise
    return {"upload_id": upload_id, "stored_relpath": path.relative_to(config["UPLOAD_DIR"]).as_posix(),
            "original_name": name, "size_bytes": size, "ext": extension}


def fps_or_default(fps):
    return fps if math.isfinite(fps) and fps > 0 else 25.0


def probe_video(path):
    import cv2

    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise ApiError("无法打开视频，请检查文件格式或编码")
        ok, frame = capture.read()
        if not ok:
            raise ApiError("视频没有可解码的画面")
        height, width = frame.shape[:2]
        fps = fps_or_default(capture.get(cv2.CAP_PROP_FPS))
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        count = int(frame_count) if math.isfinite(frame_count) and frame_count > 0 else 0
        return {"width": width, "height": height, "fps": round(fps, 2),
                "frame_count": count, "duration_sec": round(count / fps, 2) if count else None}
    finally:
        capture.release()
