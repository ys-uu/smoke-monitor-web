# -*- coding: utf-8 -*-
"""webapp.services 包：M2 起按能力拆分（infer_engine / M3 session_manager / M4 event_recorder）。

不在包级 import 任何具体服务：避免导入轻量模块时也加载 torch/ultralytics。
"""
