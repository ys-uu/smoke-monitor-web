# -*- coding: utf-8 -*-
"""违规事件 ORM 模型。

本期仅一张事件表；列类型保持通用（Integer/Float/String/Text/DateTime），
不使用 MySQL 专有 JSON 类型，以便应急情况下用 SQLite 连接串直接建表启动。
图片以 JPG 文件存磁盘（data/web_events/日期/uuid.jpg），数据库只存相对路径。
"""
from __future__ import annotations

import json
from datetime import datetime

from .extensions import db


class DetectionEvent(db.Model):
    __tablename__ = "detection_event"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # 事件墙钟时间（本地时间，页面与 CSV 直接可读）
    event_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    # 来源标识与展示信息：sample:<文件> / local:<hash> / upload:<id> / camera:0
    source_id = db.Column(db.String(64), nullable=False, default="")
    source_type = db.Column(db.String(16), nullable=False, default="sample")
    source_name = db.Column(db.String(255), nullable=False, default="")
    # 文件源定位信息（实时流可为空）
    frame_index = db.Column(db.Integer, nullable=True)
    video_time_sec = db.Column(db.Float, nullable=True)
    # 该事件帧的检测/投票快照
    max_conf = db.Column(db.Float, nullable=True)
    vote_sum = db.Column(db.Integer, nullable=True)
    vote_window = db.Column(db.Integer, nullable=True)
    model_name = db.Column(db.String(128), nullable=False, default="")
    # 快照相对 data/web_events 的路径；bbox_json 存该帧烟框列表文本
    snapshot_relpath = db.Column(db.String(512), nullable=False, default="")
    bbox_json = db.Column(db.Text, nullable=False, default="[]")
    # 人工处置状态：open / confirmed / false_alarm；记录原因：alarm_start / heartbeat
    status = db.Column(db.String(16), nullable=False, default="open")
    reason = db.Column(db.String(16), nullable=False, default="alarm_start")
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        db.Index("idx_event_time", "event_time"),
        db.Index("idx_source_time", "source_id", "event_time"),
        db.Index("idx_status", "status"),
    )

    def to_dict(self, with_boxes: bool = True) -> dict:
        """序列化为前端/CSV 友好的字典；bbox_json 解析为 boxes 列表。"""
        data = {
            "id": self.id,
            "event_time": self.event_time.strftime("%Y-%m-%d %H:%M:%S") if self.event_time else None,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "frame_index": self.frame_index,
            "video_time_sec": round(self.video_time_sec, 3) if self.video_time_sec is not None else None,
            "max_conf": round(self.max_conf, 4) if self.max_conf is not None else None,
            "vote_sum": self.vote_sum,
            "vote_window": self.vote_window,
            "model_name": self.model_name,
            "snapshot_url": f"/api/events/{self.id}/snapshot" if self.snapshot_relpath else "",
            "status": self.status,
            "reason": self.reason,
            "note": self.note,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
        if with_boxes:
            try:
                data["boxes"] = json.loads(self.bbox_json or "[]")
            except (ValueError, TypeError):
                data["boxes"] = []
        return data
