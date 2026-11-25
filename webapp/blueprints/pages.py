# -*- coding: utf-8 -*-
"""页面路由与系统级接口（首页、健康检查）。"""
from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, render_template
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("pages", __name__)


def _db_driver() -> str:
    """从连接串 scheme 解析当前数据库驱动（mysql / sqlite / 其他）。"""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    scheme = urlparse(uri).scheme.lower()
    if scheme.startswith("mysql"):
        return "mysql"
    if scheme.startswith("sqlite"):
        return "sqlite"
    return scheme or "unknown"


@bp.get("/")
def index():
    return render_template("index.html", version=current_app.config.get("VERSION", ""))


@bp.get("/api/health")
def health():
    """实时检查数据库并读取两阶段模型的缓存状态。"""
    from ..services.engine_holder import model_brief

    driver = _db_driver()
    db_ok = False
    db_error = ""
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = f"{type(exc).__name__}: {exc}"
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass

    init_error = current_app.extensions.get("smoke_db_init_error", "")
    if not db_ok and init_error and init_error not in db_error:
        db_error = f"{db_error} | 初始化异常: {init_error}".strip(" |")

    brief = model_brief()
    body = {
        "code": 0 if db_ok else 503,
        "msg": "ok" if db_ok else "database unavailable",
        "data": {
            "status": "ok" if db_ok else "degraded",
            "db_driver": driver,
            "db_ok": db_ok,
            "db_error": db_error,
            "model_loaded": brief["loaded"],
            "model_name": brief["name"],
            "face_model_name": brief["face_name"],
            "model_device": brief["device"],
            "web_host": current_app.config.get("WEB_HOST"),
            "web_port": current_app.config.get("WEB_PORT"),
            "version": current_app.config.get("VERSION"),
        },
    }
    return jsonify(body), (200 if db_ok else 503)


@bp.post("/api/engine/selftest")
def engine_selftest():
    """自检默认人脸和香烟模型，返回设备、耗时和推理参数。"""
    from ..services.engine_holder import selftest

    try:
        data = selftest(current_app)
        return jsonify({"code": 0, "msg": "ok", "data": data})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"code": 500, "msg": f"模型自检失败：{type(exc).__name__}: {exc}", "data": {"ok": False}}), 500
