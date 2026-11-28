from pathlib import Path

from flask import Blueprint, current_app, request

from ..api import ApiError, api_ok, json_object
from ..services.model_catalog import list_stage1_models, list_stage2_models
from ..services.source_resolver import list_samples, probe_video, resolve_source, save_upload

bp = Blueprint("sources", __name__)


@bp.get("/api/config/defaults")
def defaults():
    config = current_app.config
    return api_ok({
        "conf": config["DEFAULT_CONF"], "iou": config["DEFAULT_IOU"], "imgsz": config["DEFAULT_IMGSZ"],
        "use_vote": config["DEFAULT_USE_VOTE"], "vote_window": config["DEFAULT_VOTE_WINDOW"],
        "vote_threshold": config["DEFAULT_VOTE_THRESHOLD"],
        "stage1_models": list_stage1_models(config),
        "stage2_models": list_stage2_models(config),
        "stage1_default": config["DEFAULT_STAGE1_CHOICE"],
        "stage2_default": config["DEFAULT_STAGE2_CHOICE"],
        "expand_pad": config["DEFAULT_EXPAND_PAD"],
        "expand_pad_min": config["EXPAND_PAD_MIN"], "expand_pad_max": config["EXPAND_PAD_MAX"],
        "alarm_hold_frames": config["DEFAULT_ALARM_HOLD_FRAMES"],
        "alarm_hold_min": config["ALARM_HOLD_MIN"], "alarm_hold_max": config["ALARM_HOLD_MAX"],
        "cooldown": config["EVENT_COOLDOWN_SEC"], "heartbeat": config["EVENT_HEARTBEAT_ENABLED"],
        "samples": list_samples(config), "camera_default": config["CAMERA_DEFAULT_INDEX"],
        "exts": sorted(config["ALLOWED_VIDEO_EXTS"]), "upload_max_mb": config["MAX_UPLOAD_MB"],
    })


@bp.get("/api/sources/samples")
def samples():
    return api_ok({"items": list_samples(current_app.config)})


@bp.post("/api/sources/resolve-local")
def resolve_local():
    body = json_object()
    source = resolve_source("local", body.get("path"), current_app.config)
    path = Path(source.capture_input)
    data = {"resolved_path": str(path), "exists": True, "is_file": True, "ext": path.suffix.lower(),
            "size_bytes": path.stat().st_size, "in_allowed_root": True}
    if body.get("probe", True):
        data["probe"] = probe_video(str(path))
    return api_ok(data)


@bp.post("/api/sources/upload")
def upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        raise ApiError("请选择要上传的视频")
    return api_ok(save_upload(file, current_app.config))
