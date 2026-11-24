# -*- coding: utf-8 -*-
"""抽烟检测监控 Web 系统 · 一键启动入口（课设本机开发 / 答辩演示）。

用法（工程根、dl-gpu 环境）：
    python run_web.py
然后浏览器访问终端提示的地址（默认 http://127.0.0.1:8010 ，端口见 deploy/mysql/.env 的 WEB_PORT）。

注意：
- debug=False、use_reloader=False，避免 Werkzeug reloader 起双进程重复加载 YOLO 模型；
- 仅绑定 127.0.0.1，不对局域网暴露；
- 环境变量统一从 deploy/mysql/.env 加载（docker compose 也使用同一份文件）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows 控制台 / 输出重定向时尽量使用 UTF-8，避免中文日志按 gbk 编码报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

PROJ_ROOT = Path(__file__).resolve().parent
# 单一环境变量文件：优先 deploy/mysql/.env（与 compose 共用）；不存在时回退工程根 .env
_ENV_FILE = PROJ_ROOT / "deploy" / "mysql" / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)
else:
    load_dotenv(PROJ_ROOT / ".env", override=False)

import os  # noqa: E402

from webapp import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8010"))
    print("=" * 70)
    print("  抽烟检测监控 Web 系统启动中 ...")
    print(f"  访问地址：http://{host}:{port}")
    print("  首次启动会连接 MySQL 并自动创建 detection_event 表；")
    print("  若数据库未就绪，Web 仍会启动，可访问 /api/health 查看原因。")
    print("=" * 70)
    # threaded=True：MJPEG 长连接与 JSON 请求可并发；关闭 debug/reloader
    app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)
