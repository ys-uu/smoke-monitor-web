from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..api import ApiError
from .event_recorder import EventRecorder
from .source_resolver import VideoSource, fps_or_default

ACTIVE_STATES = ("starting", "running", "stopping")


@dataclass
class MonitorSession:
    source: VideoSource
    settings: dict
    data: dict
    stop: threading.Event = field(default_factory=threading.Event)
    jpeg: bytes | None = None
    sequence: int = 0


class SessionManager:
    def __init__(self, app):
        self.app = app
        self.changed = threading.Condition()
        self.session: MonitorSession | None = None
        self.worker: threading.Thread | None = None
        self.next_id = 0

    def status(self):
        with self.changed:
            if self.session is None:
                return {"state": "idle", "running": False, "alarm": False, "has_frame": False}
            data = self.session.data.copy()
            data["running"] = data["state"] in ACTIVE_STATES
            data["has_frame"] = self.session.jpeg is not None
            return data

    def start(self, source, settings):
        with self.changed:
            if self.session is not None and self.session.data["state"] in ACTIVE_STATES:
                raise ApiError("已有监控会话，请先停止", 409)
            self.next_id += 1
            session = MonitorSession(source, settings, {
                "session_id": self.next_id, "state": "starting", "source_type": source.kind,
                "source_display": source.name, "source_id": source.key,
                "alarm": False, "alarm_count": 0, "alarm_persons": 0, "last_event_at": None,
                "last_error": "", "record_error": "", **settings,
            })
            self.session = session
            self.worker = threading.Thread(target=self._run, args=(session,), name="smoke-monitor", daemon=True)
            try:
                self.worker.start()
            except RuntimeError:
                session.data.update(state="error", last_error="无法启动监控线程")
                raise ApiError("无法启动监控线程", 500)
            return session.data["session_id"]

    def stop(self, wait=2.0):
        with self.changed:
            session = self.session
            if session is None:
                return
            if session.data["state"] not in ACTIVE_STATES:
                session.data.update(state="idle", alarm=False, alarm_persons=0, last_error="", record_error="")
                session.jpeg = None
                self.changed.notify_all()
                return
            session.stop.set()
            session.data.update(state="stopping", alarm=False, alarm_persons=0)
            self.changed.notify_all()
            worker = self.worker
        if worker is not None:
            worker.join(wait)

    def stream(self, session_id):
        with self.changed:
            session = self.session
            if session is None or (session_id is not None and session_id != session.data["session_id"]):
                raise ApiError("监控会话不存在", 409)
            if session.data["state"] == "idle" or (session.data["state"] == "error" and session.jpeg is None):
                raise ApiError("当前没有可播放的画面", 409)
        return self._stream(session)

    def _stream(self, session):
        seen = 0
        while True:
            with self.changed:
                self.changed.wait_for(lambda: session.sequence != seen or session.data["state"] not in ACTIVE_STATES)
                frame = session.jpeg if session.sequence != seen else None
                seen = session.sequence
                done = session.data["state"] not in ACTIVE_STATES
            if frame is not None:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n")
            if done:
                yield b"--frame--\r\n"
                return

    def _run(self, session):
        capture = None
        finish_state = "ended"
        error = ""
        try:
            import cv2
            from .engine_holder import get_engine
            from .infer_engine import InferParams

            source, settings = session.source, session.settings
            config = self.app.config
            weights = Path(config["DEFAULT_WEIGHTS"]).expanduser()
            params = InferParams(
                weights_path=str(weights), device=config["INFER_DEVICE"],
                face_weights_path=config["DEFAULT_FACE_WEIGHTS"], face_conf=config["DEFAULT_FACE_CONF"],
                **{key: settings[key] for key in ("conf", "iou", "imgsz", "use_vote", "vote_window", "vote_threshold")},
            )
            capture = cv2.VideoCapture(source.capture_input)
            if not capture.isOpened():
                raise RuntimeError("无法打开摄像头，请检查设备编号和占用情况" if source.kind == "camera"
                                   else "无法打开视频，请检查文件格式或编码")
            if session.stop.is_set():
                return
            engine = get_engine(params)
            fps = fps_or_default(capture.get(cv2.CAP_PROP_FPS))
            file_source = source.kind != "camera"
            recorder = EventRecorder(source, settings["cooldown"], settings["heartbeat"], settings["save_snapshot"])
            with self.app.app_context():
                self._read_frames(session, capture, engine, params, recorder, fps, file_source)
        except Exception as exc:
            finish_state = "error"
            error = str(exc) or "推理会话异常"
            self.app.logger.exception("监控会话退出")
        finally:
            try:
                if capture is not None:
                    capture.release()
            finally:
                with self.changed:
                    if session.stop.is_set():
                        session.jpeg = None
                        finish_state, error = "idle", ""
                    session.data.update(state=finish_state, alarm=False, alarm_persons=0, last_error=error)
                    self.changed.notify_all()

    def _read_frames(self, session, capture, engine, params, recorder, fps, file_source):
        import cv2
        from .infer_engine import new_vote_state

        vote_state = new_vote_state(params)
        while not session.stop.is_set():
            frame_start = time.monotonic()
            ok, frame = capture.read()
            if not ok:
                if not file_source or vote_state.frame_index == 1:
                    raise RuntimeError("无法读取视频画面")
                if not session.settings["loop"]:
                    return
                if not capture.set(cv2.CAP_PROP_POS_FRAMES, 0):
                    raise RuntimeError("无法将视频重新定位到开头")
                vote_state = new_vote_state(params)
                recorder.recorded_in_alarm = False
                with self.changed:
                    session.data.update(alarm=False, alarm_persons=0)
                continue

            jpeg, info = engine.process_frame(frame, vote_state)
            if session.stop.is_set():
                return
            video_time = round((info["frame_index"] - 1) / fps, 3) if file_source else None
            alarm = info["is_alarm"]
            with self.changed:
                if session.stop.is_set():
                    return
                session.jpeg = jpeg
                session.sequence += 1
                if alarm and not session.data["alarm"]:
                    session.data["alarm_count"] += 1
                session.data.update(state="running", frame_idx=info["frame_index"], video_time=video_time,
                                    fps=info["fps_ema"], infer_ms=info["infer_ms"], n_faces=info["face_count"],
                                    n_boxes=info["cig_count"], face_model_name=engine.face_model_name,
                                    alarm_persons=info["alarm_persons"],
                                    vote_sum=info["vote_sum"], alarm=alarm, model_name=engine.model_name,
                                    device=info["device"])
                self.changed.notify_all()

            try:
                saved_at = recorder.observe(jpeg, info, engine.model_name, video_time)
            except Exception:
                self.app.logger.exception("报警记录保存失败")
                with self.changed:
                    session.data["record_error"] = "保存报警记录失败，请检查数据库和快照目录"
            else:
                if saved_at:
                    with self.changed:
                        session.data.update(last_event_at=saved_at, record_error="")

            if file_source:
                session.stop.wait(max(0, frame_start + 1 / fps - time.monotonic()))
