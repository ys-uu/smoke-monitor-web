# -*- coding: utf-8 -*-
"""Flask 应用工厂：加载配置、初始化 ORM、注册蓝图、启动时自动建表。"""
from __future__ import annotations

from flask import Flask

from .config import Config
from .extensions import db


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object)

    db.init_app(app)

    # 导入模型，确保表结构注册到 SQLAlchemy.metadata（必须在 db.create_all 之前）
    from . import models  # noqa: F401
    from .blueprints.pages import bp as pages_bp

    app.register_blueprint(pages_bp)

    # 启动时尝试连接并建表；失败不阻止 Web 进程启动：
    # /api/health 会实时上报 db_ok=false 与中文可排查错误，便于按部署文档处理
    # 或手动切换应急 SQLite 连接串（系统不做自动降级，避免数据写到错误位置）。
    app.extensions["smoke_db_init_error"] = ""
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("数据库表检查/创建完成：%s", app.config.get("SQLALCHEMY_DATABASE_URI"))
        except Exception as exc:  # noqa: BLE001
            app.extensions["smoke_db_init_error"] = f"{type(exc).__name__}: {exc}"
            app.logger.error("数据库初始化失败（Web 仍会启动，详见 /api/health）：%s", exc)

    return app
