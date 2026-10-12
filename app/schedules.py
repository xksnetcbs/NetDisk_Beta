"""One account-scoped Terminal schedule feed for web, InfoCenter and Android."""
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from flask import abort, current_app, jsonify, make_response, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import or_

from .extensions import db
from .auth_sessions import as_utc, is_live_session
from .infocenter import MAX_JSON_BYTES, NoRedirect, open_upstream, upstream_configuration
from .models import AuthRefreshToken, CalendarEvent, Project, ProjectMember, ScheduleOverride, Task, User

SHANGHAI = ZoneInfo("Asia/Shanghai")


def milliseconds(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return int(value.timestamp() * 1000)


def event_schedule(e, uid):
    return {
        "id": f"netdisk:event:{e.id}", "source": "netdisk", "netdisk_kind": "event", "netdisk_id": int(e.id),
        "title": e.title, "start_at": milliseconds(e.start_at), "end_at": milliseconds(e.end_at),
        "location": e.location or "", "description": e.description_md or "", "status": "active",
        "all_day": bool(e.all_day), "user_id": int(uid), "project_id": e.project_id, "source_completed": False,
        "course": "项目日程" if e.scope == "project" else "个人日程", "url": "/calendar",
        "editable": e.scope == "personal" and int(e.owner_user_id or 0) == int(uid),
        "deletable": e.scope == "personal" and int(e.owner_user_id or 0) == int(uid),
    }


def own_schedules(user):
    uid = int(user.id)
    projects = db.session.query(ProjectMember.project_id).filter_by(user_id=uid).union(
        db.session.query(Project.id).filter_by(creator_id=uid))
    if user.role_system == "super_admin":
        projects = db.session.query(Project.id)
    events = CalendarEvent.query.filter(or_(
        (CalendarEvent.scope == "personal") & (CalendarEvent.owner_user_id == uid),
        (CalendarEvent.scope == "project") & (CalendarEvent.assignee_id == uid) & CalendarEvent.project_id.in_(projects),
    )).order_by(CalendarEvent.start_at).all()
    schedules = [event_schedule(e, uid) for e in events]
    tasks = Task.query.filter(Task.assignee_id == uid, Task.project_id.in_(projects),
                             or_(Task.start_at.isnot(None), Task.due_at.isnot(None))).all()
    for task in tasks:
        start = task.start_at or task.due_at
        end = task.due_at or start + dt.timedelta(minutes=30)
        if milliseconds(end) <= milliseconds(start):
            start = end - dt.timedelta(minutes=30)
        complete = bool(task.completed_at)
        schedules.append({
            "id": f"netdisk:task:{task.id}", "source": "netdisk", "netdisk_kind": "task", "netdisk_id": int(task.id),
            "title": task.title, "start_at": milliseconds(start), "end_at": milliseconds(end),
            "location": "", "description": task.description_md or "", "status": "completed" if complete else "active",
            "user_id": uid, "project_id": int(task.project_id), "task_status": task.status,
            "source_completed": complete, "course": "网盘任务", "url": f"/projects/{task.project_id}?task={task.id}",
            "editable": False, "deletable": False,
        })
    return schedules


def _calendar_bytes():
    url = current_app.config.get("TERMINAL_CALENDAR_URL", "")
    credential = current_app.config.get("TERMINAL_CALENDAR_BASIC", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not credential:
        raise ValueError("课表服务未配置")
    opener = urllib.request.build_opener(NoRedirect)
    remote = opener.open(urllib.request.Request(url, headers={"Authorization": "Basic " + credential, "Accept": "text/calendar"}),
                         timeout=current_app.config.get("INFOCENTER_TIMEOUT", 45))
    try:
        value = remote.read(MAX_JSON_BYTES + 1)
        if len(value) > MAX_JSON_BYTES or not value.lstrip().startswith(b"BEGIN:VCALENDAR"):
            raise ValueError("课表响应无效")
        return value.decode("utf-8-sig")
    finally:
        remote.close()


def _ics_text(value):
    return re.sub(r"\\([nN,;\\])", lambda match: "\n" if match[1].lower() == "n" else match[1], value)


def _ics_date(value, header):
    zone = dt.timezone.utc if value.endswith("Z") else SHANGHAI
    tz = re.search(r'(?:^|;)TZID=(?:"([^"]+)"|([^;]+))', header, re.I)
    if tz and not value.endswith("Z"):
        zone = ZoneInfo(tz[1] or tz[2])
    pattern = "%Y%m%d" if len(value) == 8 else "%Y%m%dT%H%M%SZ" if value.endswith("Z") else "%Y%m%dT%H%M%S"
    return dt.datetime.strptime(value, pattern).replace(tzinfo=zone)


def parse_calendar(text):
    """Parse the existing non-recurring Canvas feed without changing its content."""
    if "END:VCALENDAR" not in text:
        raise ValueError("日历内容不完整")
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    result, event, depth = {}, None, 0
    for line in lines:
        if line == "BEGIN:VEVENT":
            event, depth = {}, 0
            continue
        if event is None:
            continue
        if line == "END:VEVENT":
            uid, title = event.get("UID", ""), event.get("SUMMARY", "")
            if uid and title:
                end = event.get("X-CANVAS-DUE") or event.get("DTEND")
                start = event.get("DTSTART")
                duration = dt.timedelta(days=1) if event.get("all_day") else dt.timedelta(hours=1)
                if end is None and start:
                    end = start + duration
                elif start is None and end:
                    start = end - duration
                if start and end and end <= start:
                    start = end - duration
                complete = event.get("STATUS") == "COMPLETED" or event.get("X-CANVAS-COMPLETED", "").upper() == "TRUE" or title.startswith("[已完成]")
                result[uid] = {
                    "id": uid, "title": re.sub(r"^\[(?:已完成|!!!)\]\s*", "", title),
                    "start_at": milliseconds(start) if start else 0, "end_at": milliseconds(end) if end else 0,
                    "description": event.get("DESCRIPTION", ""), "location": event.get("LOCATION", ""),
                    "course": event.get("X-CANVAS-COURSE", "共享日历"), "url": event.get("URL", ""),
                    "source": "calendar", "source_completed": complete,
                    "status": "completed" if complete else "cancelled" if event.get("STATUS") == "CANCELLED" else "active",
                    "all_day": bool(event.get("all_day")), "editable": False,
                    "deletable": bool(re.fullmatch(r"phone-[A-Za-z0-9_-]{1,128}", uid)),
                }
            event = None
            continue
        if line.startswith("BEGIN:"):
            depth += 1
            continue
        if line.startswith("END:"):
            depth -= 1
            continue
        if depth or ":" not in line:
            continue
        header, value = line.split(":", 1)
        field = header.split(";", 1)[0].upper()
        if field in ("DTSTART", "DTEND", "X-CANVAS-DUE"):
            event[field] = _ics_date(value, header)
            if field == "DTSTART" or field == "DTEND" and "DTSTART" not in event:
                event["all_day"] = len(value) == 8
        else:
            event[field] = _ics_text(value)
    if event is not None:
        raise ValueError("日历内容不完整")
    return list(result.values())


def terminal_snapshot():
    base, token = upstream_configuration()
    remote = open_upstream(base + "/snapshot", token, method="GET")
    try:
        data = remote.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError("snapshot too large")
        result = json.loads(data.decode("utf-8").replace(token, "[redacted]"))
        if not isinstance(result, dict):
            raise ValueError("invalid snapshot")
        return result
    finally:
        remote.close()


def assemble_schedules(user, terminal=None):
    own = own_schedules(user)
    rows, flags = list(own), {}
    if user.role_system == "super_admin":
        if terminal is None:
            try:
                terminal = terminal_snapshot()
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                terminal, flags["upstream_unavailable"] = {}, True
        for item in terminal.get("schedules", []):
            if not str(item.get("id", "")).startswith(("netdisk:", "timetable:")) and item.get("source") != "timetable":
                row = dict(item)
                row.update(source=row.get("source", "terminal"), source_completed=row.get("status") == "completed",
                           editable=True, deletable=True, course="微信识别日程")
                rows.append(row)
        if current_app.config.get("TERMINAL_CALENDAR_URL"):
            try:
                rows.extend(item for item in parse_calendar(_calendar_bytes()) if not item["id"].startswith(("netdisk:", "timetable:")))
            except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError):
                flags["calendar_unavailable"] = True
    overrides = {row.schedule_uid: bool(row.forced_completed) for row in ScheduleOverride.query.filter_by(user_id=int(user.id)).all()}
    unique = {}
    for row in rows:
        uid = str(row.get("id", ""))
        if not uid or len(uid) > 512 or re.search(r"[\x00-\x1f]", uid):
            continue
        row["id"], row["user_id"] = uid, int(user.id)
        row["forced_completed"] = overrides.get(uid, False)
        row["completed"] = bool(row.get("source_completed")) or row["forced_completed"]
        row["status"] = "cancelled" if row.get("status") == "cancelled" else "completed" if row["completed"] else "active"
        unique[uid] = row
    return sorted(unique.values(), key=lambda item: (item.get("start_at", 0), item["id"])), flags, len(own)


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("请使用 JSON 对象")
    return data


def _event_values(data, old=None):
    value = {
        "title": old.title if old else "", "start_at": milliseconds(old.start_at) if old else None,
        "end_at": milliseconds(old.end_at) if old else None, "description": old.description_md or "" if old else "",
        "location": old.location or "" if old else "", "all_day": bool(old.all_day) if old else False,
    }
    for key in value:
        if key in data:
            value[key] = data[key]
    for key, maximum in (("title", 255), ("description", 20000), ("location", 255)):
        if not isinstance(value[key], str) or len(value[key]) > maximum:
            raise ValueError("标题、地点或描述无效")
    value["title"] = value["title"].strip()
    if not value["title"] or type(value["all_day"]) is not bool:
        raise ValueError("请输入标题和有效全天状态")
    for key in ("start_at", "end_at"):
        if type(value[key]) is not int or not 0 < value[key] < 32503680000000:
            raise ValueError("时间必须使用有效的毫秒时间戳")
    if value["end_at"] <= value["start_at"]:
        raise ValueError("结束时间必须晚于开始时间")
    return value


def _set_event(event, value):
    event.title, event.location, event.description_md = value["title"], value["location"], value["description"]
    event.start_at = dt.datetime.fromtimestamp(value["start_at"] / 1000, dt.timezone.utc)
    event.end_at = dt.datetime.fromtimestamp(value["end_at"] / 1000, dt.timezone.utc)
    event.all_day = value["all_day"]


def register_schedule_routes(bp):
    def actor():
        return db.session.get(User, int(get_jwt_identity()))

    def current_write_actor():
        # External calendar calls may last seconds. Drop the old repeatable-read
        # snapshot and recheck revocation/role before committing account data.
        db.session.rollback()
        verify_jwt_in_request()
        user = User.query.filter_by(id=int(get_jwt_identity())).populate_existing().with_for_update().first()
        claims = get_jwt()
        valid = bool(user and user.status == "active" and user.is_activated
                     and claims.get("exp", 0) > dt.datetime.now(dt.timezone.utc).timestamp())
        session_id = claims.get("auth_session")
        if session_id is not None:
            try:
                session = AuthRefreshToken.query.filter_by(id=int(session_id)).populate_existing().with_for_update().first()
                valid = valid and is_live_session(session) and int(session.user_id) == int(user.id)
            except (TypeError, ValueError):
                valid = False
        elif valid:
            revoked = AuthRefreshToken.query.filter(AuthRefreshToken.user_id == user.id, AuthRefreshToken.revoked_at.isnot(None)).order_by(AuthRefreshToken.revoked_at.desc()).populate_existing().with_for_update().first()
            valid = not revoked or claims["iat"] > as_utc(revoked.revoked_at).timestamp()
        if not valid:
            db.session.rollback()
            abort(make_response(jsonify(error="登录已失效，请重新登录"), 401))
        return user

    def lock_owned_row(user, row):
        kind = row.get("netdisk_kind")
        if kind not in ("event", "task"):
            return user.role_system == "super_admin", None
        model = CalendarEvent if kind == "event" else Task
        item = model.query.filter_by(id=row["netdisk_id"]).populate_existing().with_for_update().first()
        if not item:
            return False, None
        if kind == "event" and item.scope == "personal":
            return int(item.owner_user_id or 0) == int(user.id), item
        if int(item.assignee_id or 0) != int(user.id):
            return False, None
        project = Project.query.filter_by(id=item.project_id).populate_existing().with_for_update().first()
        if not project:
            return False, None
        member = ProjectMember.query.filter_by(project_id=project.id, user_id=user.id).populate_existing().with_for_update().first()
        return user.role_system == "super_admin" or int(project.creator_id) == int(user.id) or bool(member), item

    @bp.get("/schedules")
    def schedule_list():
        user = actor()
        rows, flags, _ = assemble_schedules(user)
        return jsonify(schedules=rows, netdisk_user_id=int(user.id), terminal_access=user.role_system == "super_admin", **flags), 200, {"Cache-Control": "no-store"}

    @bp.post("/schedules")
    def schedule_create():
        user = actor()
        try:
            data = _body()
            if set(data) - {"id", "title", "start_at", "end_at", "description", "location", "all_day"}:
                raise ValueError("个人日程不支持指定其他账号或项目")
            value = _event_values(data)
            key = data.get("id")
            if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key)):
                raise ValueError("创建请求编号无效")
        except (ValueError, TypeError, OverflowError) as error:
            return jsonify(error=str(error)), 400
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        # Lock the existing account before the current read; this also serializes
        # retries against MySQL's repeatable-read snapshots.
        user = current_write_actor()
        event = CalendarEvent.query.filter_by(created_by=user.id, client_request_id=key).populate_existing().with_for_update().first() if key else None
        if event and event.request_digest != digest:
            return jsonify(error="请求编号已用于其他日程"), 409
        if event and (event.scope != "personal" or int(event.owner_user_id or 0) != int(user.id)):
            return jsonify(error="原日程已分配给其他账号，无法重复创建"), 409
        if not event:
            event = CalendarEvent(scope="personal", owner_user_id=user.id, assignee_id=user.id, created_by=user.id,
                                  client_request_id=key, request_digest=digest)
            _set_event(event, value)
            db.session.add(event)
            db.session.flush()
        uid = f"netdisk:event:{event.id}"
        row = event_schedule(event, user.id)
        override = ScheduleOverride.query.filter_by(user_id=user.id, schedule_uid=uid).first()
        forced = bool(override and override.forced_completed)
        row.update(forced_completed=forced, completed=forced, status="completed" if forced else "active")
        db.session.commit()
        return jsonify(ok=True, schedule=row), 200, {"Cache-Control": "no-store"}

    @bp.route("/schedules/<path:uid>", methods=["PATCH", "POST", "DELETE"])
    def schedule_update(uid):
        user = actor()
        if not uid or len(uid) > 512 or re.search(r"[\x00-\x1f]", uid):
            return jsonify(error="日程编号无效"), 400
        rows, flags, _ = assemble_schedules(user)
        row = next((item for item in rows if item["id"] == uid), None)
        if not row:
            return jsonify(error="日程不存在或不属于当前账号"), 503 if flags else 404
        user = current_write_actor()
        permitted, owned_item = lock_owned_row(user, row)
        if not permitted:
            return jsonify(error="日程不存在或不属于当前账号"), 404
        if row.get("netdisk_kind") == "task":
            row["source_completed"] = bool(owned_item.completed_at)
        if request.method == "DELETE":
            if not row.get("deletable"):
                return jsonify(error="来源日程请在原系统管理"), 403
            if row.get("netdisk_kind") == "event":
                db.session.delete(owned_item)
            elif row.get("source") == "calendar":
                # Keep the existing explicit phone-calendar deletion boundary.
                from .mobile import calendar_delete
                response = calendar_delete(uid)
                if isinstance(response, tuple) and response[1] != 200:
                    return response
            else:
                base, token = upstream_configuration()
                try:
                    remote = open_upstream(base + "/schedules/" + urllib.parse.quote(uid, safe=""), token, b"{}", method="DELETE")
                    remote.close()
                except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                    return jsonify(error="日程删除未完成"), 502
            ScheduleOverride.query.filter_by(user_id=user.id, schedule_uid=uid).delete()
            db.session.commit()
            return jsonify(ok=True)
        try:
            data = _body()
            allowed = {"forced_completed", "title", "start_at", "end_at", "description", "location", "all_day"}
            if not data or set(data) - allowed:
                raise ValueError("日程修改内容无效")
            if "forced_completed" in data and type(data["forced_completed"]) is not bool:
                raise ValueError("强制完成必须为布尔值")
            edits = {key: value for key, value in data.items() if key != "forced_completed"}
            if edits and not row.get("editable"):
                return jsonify(error="来源日程请在原系统编辑"), 403
            if edits and row.get("netdisk_kind") == "event":
                event = owned_item
                value = _event_values(edits, event)
                _set_event(event, value)
                row.update(value)
            elif edits:
                base, token = upstream_configuration()
                remote = open_upstream(base + "/schedules/" + urllib.parse.quote(uid, safe=""), token,
                                       json.dumps(edits).encode(), method="POST")
                remote.close()
            if "forced_completed" in data:
                override = ScheduleOverride.query.filter_by(user_id=user.id, schedule_uid=uid).with_for_update().first()
                if override is None:
                    override = ScheduleOverride(user_id=user.id, schedule_uid=uid)
                    db.session.add(override)
                override.forced_completed = data["forced_completed"]
                row["forced_completed"] = data["forced_completed"]
                row["completed"] = bool(row.get("source_completed")) or data["forced_completed"]
                row["status"] = "cancelled" if row.get("status") == "cancelled" else "completed" if row["completed"] else "active"
            db.session.commit()
        except (ValueError, TypeError, OverflowError) as error:
            db.session.rollback()
            return jsonify(error=str(error)), 400
        except (urllib.error.URLError, OSError, TimeoutError):
            db.session.rollback()
            return jsonify(error="日程更新未完成"), 502
        return jsonify(ok=True, schedule=row), 200, {"Cache-Control": "no-store"}
