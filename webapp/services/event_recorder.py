from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import current_app

from ..extensions import db
from ..models import DetectionEvent


def snapshot_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not relative or not path.is_relative_to(root.resolve()) or path.suffix.lower() != ".jpg":
        raise ValueError("快照路径无效")
    return path


class EventRecorder:
    def __init__(self, source, cooldown, heartbeat, save_snapshot):
        self.source = source
        self.cooldown = cooldown
        self.heartbeat = heartbeat
        self.save_snapshot = save_snapshot
        self.recorded_in_alarm = False
        self.last_saved = float("-inf")
        self.retry_at = float("-inf")

    def observe(self, jpeg, info, model_name, video_time):
        if not info["is_alarm"]:
            self.recorded_in_alarm = False
            return None
        if not info["boxes"]:
            return None

        now = time.monotonic()
        if now < self.retry_at or now - self.last_saved < self.cooldown:
            return None
        if self.recorded_in_alarm and not self.heartbeat:
            return None

        timestamp = datetime.now()
        relative = f"{timestamp:%Y-%m-%d}/{uuid4().hex}.jpg" if self.save_snapshot else ""
        path = None
        reason = "heartbeat" if self.recorded_in_alarm else "alarm_start"
        try:
            if relative:
                path = snapshot_path(current_app.config["SNAPSHOT_DIR"], relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(jpeg)
            db.session.add(DetectionEvent(
                event_time=timestamp, source_id=self.source.key, source_type=self.source.kind,
                source_name=self.source.name, frame_index=info["frame_index"], video_time_sec=video_time,
                max_conf=info["max_conf"], vote_sum=info["vote_sum"], vote_window=info["vote_window"],
                model_name=model_name, snapshot_relpath=relative, bbox_json=json.dumps(info["boxes"]),
                reason=reason,
            ))
            db.session.commit()
        except Exception:
            self.retry_at = now + min(self.cooldown, 5.0)
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    current_app.logger.exception("清理未入库的快照失败")
            db.session.rollback()
            raise

        self.recorded_in_alarm = True
        self.last_saved = now
        return timestamp.strftime("%Y-%m-%d %H:%M:%S")
