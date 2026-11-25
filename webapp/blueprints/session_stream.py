from flask import Blueprint, Response, current_app, request

from ..api import ApiError, api_ok, json_object
from ..services.source_resolver import resolve_source

bp = Blueprint("session_stream", __name__)


def _settings(body, config):
    settings = {}
    for key, default, low, high in (
        ("conf", "DEFAULT_CONF", 0.05, 0.95), ("iou", "DEFAULT_IOU", 0.10, 0.90),
        ("cooldown", "EVENT_COOLDOWN_SEC", config["EVENT_COOLDOWN_MIN"], config["EVENT_COOLDOWN_MAX"]),
    ):
        value = body.get(key, config[default])
        if type(value) not in (int, float) or not low <= value <= high:
            raise ApiError(f"{key} 必须在 {low} 到 {high} 之间")
        settings[key] = float(value)

    size = body.get("imgsz", config["DEFAULT_IMGSZ"])
    if type(size) is not int or not 32 <= size <= 1920 or size % 32:
        raise ApiError("推理尺寸必须是 32 到 1920 之间的 32 的倍数")
    window = body.get("vote_window", config["DEFAULT_VOTE_WINDOW"])
    threshold = body.get("vote_threshold", config["DEFAULT_VOTE_THRESHOLD"])
    if type(window) is not int or not 1 <= window <= 15:
        raise ApiError("投票窗口必须是 1 到 15 的整数")
    if type(threshold) is not int or not 1 <= threshold <= window:
        raise ApiError("投票阈值必须是 1 到窗口大小之间的整数")
    settings.update(imgsz=size, vote_window=window, vote_threshold=threshold)

    for key, default in (("loop", False), ("heartbeat", config["EVENT_HEARTBEAT_ENABLED"]),
                         ("save_snapshot", True), ("use_vote", config["DEFAULT_USE_VOTE"])):
        value = body.get(key, default)
        if type(value) is not bool:
            raise ApiError(f"{key} 必须为布尔值")
        settings[key] = value
    return settings


@bp.post("/api/session/start")
def start():
    body = json_object()
    config = current_app.config
    source = resolve_source(body.get("source_type"), body.get("source"), config)
    settings = _settings(body, config)
    if source.kind == "camera":
        settings["loop"] = False
    manager = current_app.extensions["smoke_session"]
    return api_ok({"session_id": manager.start(source, settings), "applied": settings})


@bp.post("/api/session/stop")
def stop():
    manager = current_app.extensions["smoke_session"]
    manager.stop()
    return api_ok(manager.status())


@bp.get("/api/session/status")
def status():
    return api_ok(current_app.extensions["smoke_session"].status())


@bp.get("/api/stream.mjpeg")
def stream():
    session_id = request.args.get("session_id", type=int)
    frames = current_app.extensions["smoke_session"].stream(session_id)
    return Response(frames, content_type="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-store"})
