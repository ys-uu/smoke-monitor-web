# -*- coding: utf-8 -*-
"""集中配置：路径、数据库、推理默认值、视频源策略。

工程定位：本文件属于独立 Web 应用工程 smoke-monitor-web（Flask + 原生 JS + MySQL）。
目录约定（webapp/config.py 上两级 = Web 工程根）：
- models/stage1/face、models/stage1/head   一阶段人脸/头部检测权重（.pt）
- models/stage2/                          二阶段香烟检测权重（.pt），目录内新增模型后前端下拉自动同步
- samples/                        随 Web 工程自包含的样例视频
- data/web_events、web_uploads/   运行时违规快照与上传文件
- deploy/mysql/.env               docker compose 与 run_web.py 共用的环境变量文件

约定：所有“大写”类属性都会被 Flask 的 app.config.from_object 加载；
环境变量优先（deploy/mysql/.env 由 run_web.py 预先 load_dotenv）。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent  # <Web 工程根>/smoke-monitor-web/
# 模型分阶段目录：一阶段（人脸/头部）与二阶段（香烟）分开，目录内新增 .pt 后前端可选项自动同步
MODELS_DIR = PROJ_ROOT / "models"
STAGE1_DIR = MODELS_DIR / "stage1"
FACE_DIR = STAGE1_DIR / "face"
HEAD_DIR = STAGE1_DIR / "head"
STAGE2_DIR = MODELS_DIR / "stage2"
FACE_WEIGHTS = FACE_DIR / "yolov8n-face.pt"
HEAD_WEIGHTS = HEAD_DIR / "head_crowdhuman_best.pt"   # 整个头部检测（CrowdHuman 自训，含侧脸/背面）
CIG_WEIGHTS = STAGE2_DIR / "smoke_cig_clean_n960_e100_best.pt"
# 前端下拉的默认选中值（相对各自目录的 value）
DEFAULT_STAGE1_CHOICE = "face/yolov8n-face.pt"
DEFAULT_STAGE2_CHOICE = "smoke_cig_clean_n960_e100_best.pt"


def _parse_local_roots(raw: str, proj_root: Path):
    """解析本机路径直读白名单。

    - ``*``：允许任意本机绝对路径（默认；仅因服务只绑定 127.0.0.1，课设单机使用）；
    - 否则按 Windows 分号 ``;`` 分隔允许根目录，相对路径相对工程根解析，并始终包含工程根。
    """
    text = (raw or "*").strip().strip('"')
    if text == "*":
        return "*"
    roots: list[Path] = [proj_root]
    for part in text.split(";"):
        part = part.strip().strip('"')
        if not part:
            continue
        path = Path(part).expanduser()
        if not path.is_absolute():
            path = (proj_root / path).resolve()
        if path not in roots:
            roots.append(path)
    return roots


class Config:
    VERSION = "0.2.0"
    SECRET_KEY = os.getenv("SMOKE_SECRET_KEY", "smoke-detection-local-dev-only")

    # ----- 数据库：默认本机 Docker MySQL；可用 SMOKE_DATABASE_URL 覆盖为应急 SQLite -----
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SMOKE_DATABASE_URL",
        "mysql+pymysql://smoke:smoke123456@127.0.0.1:3307/smoke_detection?charset=utf8mb4",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # pool_pre_ping：取连接前探活，避免容器重启 / MySQL 断连后拿到失效连接
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 3600}

    # ----- Web 监听 -----
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", "8010"))

    # ----- 运行目录（均在 Web 工程根内）-----
    SNAPSHOT_DIR = PROJ_ROOT / "data" / "web_events"
    UPLOAD_DIR = PROJ_ROOT / "data" / "web_uploads"
    # 样例视频默认读工程内 samples/（自包含）；可用 SMOKE_SAMPLE_VIDEO_DIR 指向外部目录（如训练基地）
    SAMPLE_VIDEO_DIR = Path(os.getenv("SMOKE_SAMPLE_VIDEO_DIR", str(PROJ_ROOT / "samples")))
    BATCH_INPUT_DIR = PROJ_ROOT / "data" / "batch_input"

    # ----- 上传限制与扩展名白名单 -----
    MAX_UPLOAD_MB = int(os.getenv("SMOKE_MAX_UPLOAD_MB", "500"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024  # Flask 请求体上限
    ALLOWED_VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"})
    ALLOWED_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})

    # ----- 本机绝对路径直读白名单（Q7，默认 * 允许任意本机路径）-----
    LOCAL_PATH_ALLOWED_ROOTS = _parse_local_roots(
        os.getenv("SMOKE_LOCAL_PATH_ROOTS", "*"), PROJ_ROOT
    )

    # ----- 模型 / 推理默认（M3 会话使用；先集中声明，保证口径单一）-----
    # 模型分阶段目录（引用模块级常量），model_catalog 据此扫描；目录内新增 .pt 后前端下拉自动同步
    MODELS_DIR = MODELS_DIR
    STAGE1_DIR = STAGE1_DIR
    FACE_DIR = FACE_DIR
    HEAD_DIR = HEAD_DIR
    STAGE2_DIR = STAGE2_DIR
    DEFAULT_STAGE1_CHOICE = DEFAULT_STAGE1_CHOICE
    DEFAULT_STAGE2_CHOICE = DEFAULT_STAGE2_CHOICE
    # 权重随 Web 工程内置在 models/（自包含）；可用 SMOKE_DEFAULT_WEIGHTS 指向训练基地新权重，免复制切换。
    # 注意（用户最终决定）：所有推理参数在“开始会话前”设定，会话运行中面板锁定、不做热更；
    # 要改参数先停止会话，修改后重新开始。
    DEFAULT_WEIGHTS = os.getenv(
        "SMOKE_DEFAULT_WEIGHTS",
        str(CIG_WEIGHTS),
    )
    DEFAULT_FACE_WEIGHTS = os.getenv("SMOKE_FACE_WEIGHTS", str(FACE_WEIGHTS))
    DEFAULT_FACE_CONF = float(os.getenv("SMOKE_FACE_CONF", "0.35"))
    # 第一阶段检测器：默认 face 保持兼容；切 head 可覆盖 SMOKE_DETECTOR_KIND=head
    DEFAULT_DETECTOR_KIND = os.getenv("SMOKE_DETECTOR_KIND", "face")
    DEFAULT_HEAD_WEIGHTS = os.getenv("SMOKE_HEAD_WEIGHTS", str(HEAD_WEIGHTS))
    DEFAULT_HEAD_CONF = float(os.getenv("SMOKE_HEAD_CONF", "0.35"))
    # 第一阶段 ROI 固定像素外扩（不随框大小变化，避免近距离过大、远距离过小），前端可调
    EXPAND_PAD_MIN = 0
    EXPAND_PAD_MAX = 200
    DEFAULT_EXPAND_PAD = int(os.getenv("SMOKE_EXPAND_PAD", "15"))
    # 报警红框保持帧数：报警后短暂漏检仍显示红框，避免逐帧闪烁；0=关闭，前端可调
    ALARM_HOLD_MIN = 0
    ALARM_HOLD_MAX = 120
    DEFAULT_ALARM_HOLD_FRAMES = int(os.getenv("SMOKE_ALARM_HOLD_FRAMES", "12"))
    DEFAULT_IMGSZ = int(os.getenv("SMOKE_DEFAULT_IMGSZ", "960"))
    DEFAULT_CONF = float(os.getenv("SMOKE_DEFAULT_CONF", "0.35"))
    DEFAULT_IOU = float(os.getenv("SMOKE_DEFAULT_IOU", "0.70"))
    DEFAULT_USE_VOTE = False
    DEFAULT_VOTE_WINDOW = int(os.getenv("SMOKE_VOTE_WINDOW", "1"))
    DEFAULT_VOTE_THRESHOLD = int(os.getenv("SMOKE_VOTE_THRESHOLD", "1"))
    # 推理设备：auto=有 CUDA 用 GPU、否则 CPU；也可显式 0 或 cpu（会话开始前固定）
    INFER_DEVICE = os.getenv("SMOKE_INFER_DEVICE", "auto")
    CAMERA_DEFAULT_INDEX = int(os.getenv("SMOKE_CAMERA_INDEX", "0"))

    # ----- 事件记录冷却（开始前可配，会话内固定；后端做范围校验）-----
    EVENT_COOLDOWN_SEC = float(os.getenv("SMOKE_EVENT_COOLDOWN_SEC", "10"))
    EVENT_COOLDOWN_MIN = 5.0
    EVENT_COOLDOWN_MAX = 300.0
    EVENT_HEARTBEAT_ENABLED = True
