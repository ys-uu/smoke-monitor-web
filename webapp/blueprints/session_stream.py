from flask import Blueprint, Response, current_app, request

from ..api import ApiError, api_ok, json_object
from ..services.model_catalog import resolve_stage1, resolve_stage2
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

    # 模型选择：一阶段（face/head 由所选子目录推断）与二阶段，校验白名单并解析为绝对路径
    stage1_choice = body.get("stage1_model", config["DEFAULT_STAGE1_CHOICE"])
    stage2_choice = body.get("stage2_model", config["DEFAULT_STAGE2_CHOICE"])
    detector_kind, stage1_weights = resolve_stage1(stage1_choice, config)
    stage2_weights = resolve_stage2(stage2_choice, config)
    # 同时保留前端原始 value（供状态回传回填）与解析后的绝对路径（供构建引擎）
    settings["stage1_model"] = stage1_choice
    settings["stage2_model"] = stage2_choice
    settings["detector_kind"] = detector_kind
    settings["stage1_weights"] = stage1_weights
    settings["stage2_weights"] = stage2_weights

    # 第一阶段 ROI 固定像素外扩
    expand_pad = body.get("expand_pad", config["DEFAULT_EXPAND_PAD"])
    if type(expand_pad) is not int or not config["EXPAND_PAD_MIN"] <= expand_pad <= config["EXPAND_PAD_MAX"]:
        raise ApiError(f"外扩像素必须是 {config['EXPAND_PAD_MIN']} 到 {config['EXPAND_PAD_MAX']} 之间的整数")
    settings["expand_pad"] = expand_pad

    # 报警红框保持帧数
    hold_frames = body.get("alarm_hold_frames", config["DEFAULT_ALARM_HOLD_FRAMES"])
    if type(hold_frames) is not int or not config["ALARM_HOLD_MIN"] <= hold_frames <= config["ALARM_HOLD_MAX"]:
        raise ApiError(f"红框保持帧数必须是 {config['ALARM_HOLD_MIN']} 到 {config['ALARM_HOLD_MAX']} 之间的整数")
    settings["alarm_hold_frames"] = hold_frames
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
