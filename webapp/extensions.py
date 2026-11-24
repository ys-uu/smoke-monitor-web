# -*- coding: utf-8 -*-
"""Flask 扩展单例（独立文件以避免应用工厂与模型之间的循环导入）。"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
