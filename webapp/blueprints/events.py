import csv
import io
from datetime import date, datetime, time
from uuid import uuid4

from flask import Blueprint, Response, current_app, request, send_file
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..api import ApiError, api_error, api_ok, json_object
from ..extensions import db
from ..models import DetectionEvent
from ..services.event_recorder import snapshot_path

bp = Blueprint("events", __name__, url_prefix="/api/events")
STATUS_LABELS = {"open": "未处理", "confirmed": "确认抽烟", "false_alarm": "误报"}


@bp.errorhandler(SQLAlchemyError)
def database_error(error):
    db.session.rollback()
    current_app.logger.error("违规记录数据库操作失败", exc_info=error)
    return api_error(ApiError("违规记录数据库暂不可用", 503))


def _event(event_id):
    event = db.session.get(DetectionEvent, event_id)
    if event is None:
        raise ApiError("该违规记录不存在", 404)
    return event


def _date(arg):
    value = request.args.get(arg, "")
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise ApiError("日期必须使用 YYYY-MM-DD 格式") from exc


def _filtered_events():
    start = _date("date_from")
    end = _date("date_to")
    if start and end and start > end:
        raise ApiError("结束日期必须等于或晚于开始日期")
    stmt = select(DetectionEvent)
    if start:
        stmt = stmt.where(DetectionEvent.event_time >= datetime.combine(start, time.min))
    if end:
        stmt = stmt.where(DetectionEvent.event_time <= datetime.combine(end, time.max))
    if source := request.args.get("source"):
        stmt = stmt.where(DetectionEvent.source_id == source)
    if status := request.args.get("status"):
        if status not in STATUS_LABELS:
            raise ApiError("处理状态无效")
        stmt = stmt.where(DetectionEvent.status == status)
    return stmt.order_by(DetectionEvent.event_time.desc(), DetectionEvent.id.desc())


@bp.get("")
def index():
    page = request.args.get("page", "1")
    size = request.args.get("size", "12")
    try:
        page, size = int(page), int(size)
        if not 1 <= page <= 1000000 or not 1 <= size <= 100:
            raise ValueError
    except ValueError as exc:
        raise ApiError("页码或每页条数无效") from exc
    result = db.paginate(_filtered_events(), page=page, per_page=size, error_out=False)
    sources = db.session.execute(select(DetectionEvent.source_id, DetectionEvent.source_name)
                                 .distinct().order_by(DetectionEvent.source_name, DetectionEvent.source_id))
    return api_ok({"total": result.total, "page": page, "size": size,
                   "items": [event.to_dict(with_boxes=False) for event in result.items],
                   "sources": [{"id": key, "name": name} for key, name in sources]})


@bp.get("/<int:event_id>")
def detail(event_id):
    return api_ok(_event(event_id).to_dict())


@bp.get("/<int:event_id>/snapshot")
def snapshot(event_id):
    event = _event(event_id)
    try:
        path = snapshot_path(current_app.config["SNAPSHOT_DIR"], event.snapshot_relpath)
        if not path.is_file():
            raise FileNotFoundError
    except (OSError, ValueError) as exc:
        raise ApiError("该记录没有可用快照", 404) from exc
    return send_file(path, mimetype="image/jpeg", max_age=0)


@bp.post("/<int:event_id>/label")
def label(event_id):
    body = json_object()
    status = body.get("status")
    note = body.get("note")
    if not isinstance(status, str) or status not in STATUS_LABELS:
        raise ApiError("处理状态无效")
    if note is not None and (not isinstance(note, str) or len(note) > 255):
        raise ApiError("备注最多 255 个字符")
    event = _event(event_id)
    event.status = status
    if "note" in body:
        event.note = (note or "").strip() or None
    db.session.commit()
    return api_ok(event.to_dict())


@bp.delete("/<int:event_id>")
def delete(event_id):
    with current_app.extensions["smoke_event_delete_lock"]:
        event = _event(event_id)
        path = staged = None
        if event.snapshot_relpath:
            try:
                path = snapshot_path(current_app.config["SNAPSHOT_DIR"], event.snapshot_relpath)
            except (ValueError, RuntimeError):
                current_app.logger.warning("违规记录 %s 的快照路径无效", event_id)
            else:
                try:
                    staged = path.rename(path.with_name(f".{uuid4().hex}.tmp"))
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    raise ApiError("暂时无法删除快照，请稍后重试", 500) from exc
        try:
            db.session.delete(event)
            db.session.commit()
        except Exception:
            if staged is not None:
                staged.replace(path)
            raise
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                current_app.logger.exception("清理已删除记录的快照失败")
    return api_ok({"id": event_id})


def _csv_text(value):
    if value and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


@bp.get("/export.csv")
def export():
    stmt = _filtered_events()
    buffer = io.StringIO(newline="")
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(["编号", "报警时间", "来源", "来源类型", "帧号", "视频时间 (秒)", "置信度",
                     "投票", "模型", "状态", "记录原因", "备注"])
    for event in db.session.scalars(stmt.execution_options(yield_per=100)):
        votes = f"{event.vote_sum}/{event.vote_window}" if event.vote_sum is not None else ""
        writer.writerow([event.id, event.event_time, _csv_text(event.source_name), event.source_type,
                         event.frame_index, event.video_time_sec, event.max_conf, votes,
                         _csv_text(event.model_name), STATUS_LABELS.get(event.status, event.status),
                         "持续报警" if event.reason == "heartbeat" else "首次报警", _csv_text(event.note)])

    return Response(buffer.getvalue(), content_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="smoke-events.csv"',
                             "Cache-Control": "no-store"})
