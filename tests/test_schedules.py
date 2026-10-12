"""Cross-device account schedules, external calendars, and completion authority."""
import datetime as dt
import json
import unittest
from unittest.mock import patch
from urllib.parse import quote

from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import AuthRefreshToken, CalendarEvent, ProjectMember, ScheduleOverride, User, utcnow
from app.schedules import milliseconds, parse_calendar
from tests import test_mobile as fixtures


class UnifiedScheduleTests(unittest.TestCase):
    headers = fixtures.MobileTerminalTests.headers
    get = fixtures.MobileTerminalTests.get
    tearDown = fixtures.MobileTerminalTests.tearDown

    def setUp(self):
        fixtures.MobileTerminalTests.setUp(self)
        self.schedule_upstream = patch("app.schedules.open_upstream", self.upstream)
        self.schedule_upstream.start()
        self.addCleanup(self.schedule_upstream.stop)

    def change(self, uid, body=None, method="PATCH", user_id=2):
        return self.client.open("/api/mobile/terminal/schedules/" + quote(uid, safe=""), method=method,
                                json=body, headers=self.headers(user_id))

    def create(self, body=None, user_id=2):
        value = {"id": "schedule-idempotent-test-0001", "title": "Personal appointment", "start_at": milliseconds(self.start),
                 "end_at": milliseconds(self.start + dt.timedelta(hours=1)), "location": "Office", "description": "Notes"}
        return self.client.post("/api/mobile/terminal/schedules", json=value if body is None else body, headers=self.headers(user_id))

    def test_create_is_owned_idempotent_across_devices_and_visible_in_both_feeds(self):
        first = self.create()
        self.assertEqual(first.status_code, 200)
        uid = first.json["schedule"]["id"]
        second = self.create()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["schedule"]["id"], uid)
        self.assertEqual(CalendarEvent.query.filter_by(client_request_id="schedule-idempotent-test-0001").count(), 1)
        for path in ("snapshot", "schedules"):
            rows = self.get(path).json["schedules"]
            self.assertIn(uid, {row["id"] for row in rows})
            self.assertNotIn(uid, {row["id"] for row in self.get(path, user_id=3).json["schedules"]})
        other = self.create(user_id=3)
        self.assertEqual(other.status_code, 200)
        self.assertNotEqual(other.json["schedule"]["id"], uid)
        duplicate = self.create().json["schedule"]
        altered = {"id": "schedule-idempotent-test-0001", "title": "Changed retry", "start_at": duplicate["start_at"], "end_at": duplicate["end_at"]}
        self.assertEqual(self.create(altered).status_code, 409)
        self.upstream.assert_not_called()

    def test_creation_rejects_other_owners_bad_types_and_invalid_ranges(self):
        for body in ({"owner_user_id": 3}, {"user_id": 1}, {"project_id": 10}, {"scope": "project"},
                     {"title": "x", "start_at": True, "end_at": 1},
                     {"title": "x", "start_at": 1000, "end_at": 1000},
                     {"title": "", "start_at": 1000, "end_at": 2000},
                     {"id": "invalid", "title": "x", "start_at": 1000, "end_at": 2000}):
            with self.subTest(body=body):
                self.assertEqual(self.create(body).status_code, 400)
        self.assertEqual(CalendarEvent.query.count(), 9)

    def test_idempotent_create_after_admin_reassignment_is_a_conflict_without_leak(self):
        response = self.create()
        event_id = response.json["schedule"]["netdisk_id"]
        event = db.session.get(CalendarEvent, event_id)
        event.owner_user_id = event.assignee_id = 3
        db.session.commit()
        retry = self.create()
        self.assertEqual(retry.status_code, 409)
        self.assertNotIn("schedule", retry.json)
        self.assertEqual(CalendarEvent.query.filter_by(client_request_id="schedule-idempotent-test-0001").count(), 1)

    def test_create_response_is_built_before_commit_releases_ownership_lock(self):
        original = db.session.commit
        def commit_then_reassign():
            original()
            event = CalendarEvent.query.filter_by(client_request_id="schedule-idempotent-test-0001").one()
            event.owner_user_id = event.assignee_id = 3
            original()
        with patch.object(db.session, "commit", commit_then_reassign):
            response = self.create()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["schedule"]["user_id"], 2)
        self.assertNotIn(response.json["schedule"]["id"], {row["id"] for row in self.get().json["schedules"]})

    def test_account_disabled_while_waiting_for_write_lock_is_rechecked(self):
        from sqlalchemy.orm import Query
        original = Query.first
        changed = False
        def wait_then_first(query):
            nonlocal changed
            if query._for_update_arg is not None and query.column_descriptions[0]["entity"] is User and not changed:
                changed = True
                db.session.execute(User.__table__.update().where(User.id == 2).values(status="disabled"))
                db.session.commit()
            return original(query)
        with patch.object(Query, "first", wait_then_first):
            response = self.create()
        self.assertTrue(changed)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(CalendarEvent.query.count(), 9)

    def test_device_revoked_while_waiting_for_write_lock_is_current_read_checked(self):
        from sqlalchemy.orm import Query
        session = AuthRefreshToken(user_id=2, token_hash="lock-revoke", expires_at=utcnow()+dt.timedelta(days=1))
        db.session.add(session); db.session.commit()
        self.tokens[2] = create_access_token(identity="2", additional_claims={"auth_session": str(session.id)})
        original = Query.first
        changed = False
        def wait_then_first(query):
            nonlocal changed
            if query._for_update_arg is not None and query.column_descriptions[0]["entity"] is User and not changed:
                changed = True
                db.session.execute(AuthRefreshToken.__table__.update().where(AuthRefreshToken.id == session.id).values(revoked_at=utcnow()))
                db.session.commit()
            return original(query)
        with patch.object(Query, "first", wait_then_first):
            response = self.change("netdisk:event:201", {"forced_completed": True})
        self.assertTrue(changed)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(ScheduleOverride.query.count(), 0)

    def test_force_completion_persists_on_server_and_restores_for_new_device_token(self):
        uid = "netdisk:event:201"
        response = self.change(uid, {"forced_completed": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["schedule"]["forced_completed"])
        self.assertFalse(response.json["schedule"]["source_completed"])
        self.assertTrue(ScheduleOverride.query.filter_by(user_id=2, schedule_uid=uid).one().forced_completed)
        second_device = create_access_token(identity="2")
        for path in ("snapshot", "schedules"):
            row = next(row for row in self.get(path, token=second_device).json["schedules"] if row["id"] == uid)
            self.assertTrue(row["completed"])
            self.assertEqual(row["status"], "completed")
        self.assertEqual(self.change(uid, {"forced_completed": False}).status_code, 200)
        row = next(row for row in self.get().json["schedules"] if row["id"] == uid)
        self.assertFalse(row["completed"])
        self.assertFalse(row["forced_completed"])
        self.assertEqual(ScheduleOverride.query.count(), 1)
        self.upstream.assert_not_called()

    def test_cancel_force_preserves_naturally_completed_task_and_does_not_mutate_task(self):
        uid = "netdisk:task:105"
        self.assertEqual(self.change(uid, {"forced_completed": True}).status_code, 200)
        response = self.change(uid, {"forced_completed": False})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["schedule"]["source_completed"])
        self.assertTrue(response.json["schedule"]["completed"])
        self.assertFalse(response.json["schedule"]["forced_completed"])

    def test_task_and_canvas_deadline_only_or_equal_start_keep_real_deadline(self):
        from app.models import Task
        task = db.session.get(Task, 101)
        for start in (None, self.start):
            task.start_at, task.due_at = start, self.start
            db.session.commit()
            row = next(row for row in self.get().json["schedules"] if row["id"] == "netdisk:task:101")
            self.assertEqual(row["end_at"], milliseconds(self.start))
            self.assertLess(row["start_at"], row["end_at"])
        for source in ("X-CANVAS-DUE:20261012T090000Z", "DTSTART:20261012T090000Z\nDTEND:20261012T090000Z"):
            text = f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:deadline\nSUMMARY:Task\n{source}\nEND:VEVENT\nEND:VCALENDAR"
            row = parse_calendar(text)[0]
            self.assertEqual(row["end_at"], milliseconds(self.start))
            self.assertLess(row["start_at"], row["end_at"])
        undated = parse_calendar("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:undated\nSUMMARY:Undated task\nEND:VEVENT\nEND:VCALENDAR")[0]
        self.assertEqual((undated["start_at"], undated["end_at"]), (0, 0))
        all_day = parse_calendar("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:date-only\nSUMMARY:All day\nDTSTART;VALUE=DATE:20261012\nEND:VEVENT\nEND:VCALENDAR")[0]
        self.assertTrue(all_day["all_day"])
        self.assertEqual(all_day["end_at"] - all_day["start_at"], 86400000)

    def test_forbidden_uid_and_departed_project_never_create_completion_records(self):
        for uid in ("netdisk:event:202", "netdisk:task:102", "canvas-other-person", "llm-1"):
            with self.subTest(uid=uid):
                self.assertEqual(self.change(uid, {"forced_completed": True}).status_code, 404)
        db.session.delete(ProjectMember.query.filter_by(project_id=10, user_id=2).one())
        db.session.commit()
        self.assertEqual(self.change("netdisk:event:203", {"forced_completed": True}).status_code, 404)
        self.assertEqual(self.change("netdisk:task:101", {"forced_completed": True}).status_code, 404)
        self.assertEqual(ScheduleOverride.query.count(), 0)
        self.upstream.assert_not_called()

    def test_completion_requires_boolean_and_rejects_status_or_other_owner_fields(self):
        for body in ({"forced_completed": "false"}, {"forced_completed": 1}, {"status": "completed"},
                     {"forced_completed": True, "user_id": 1}, {}):
            with self.subTest(body=body):
                self.assertEqual(self.change("netdisk:event:201", body).status_code, 400)
        self.assertEqual(ScheduleOverride.query.count(), 0)

    def test_edit_and_delete_personal_event_and_completion_use_same_authority(self):
        uid = self.create().json["schedule"]["id"]
        self.assertEqual(self.change(uid, {"title": "Cross-device edit", "forced_completed": True}).status_code, 200)
        row = next(row for row in self.get().json["schedules"] if row["id"] == uid)
        self.assertEqual(row["title"], "Cross-device edit")
        self.assertTrue(row["completed"])
        self.assertEqual(self.change(uid, method="DELETE", user_id=3).status_code, 404)
        self.assertEqual(self.change("netdisk:task:101", method="DELETE").status_code, 403)
        self.assertEqual(self.change(uid, method="DELETE").status_code, 200)
        self.assertNotIn(uid, {row["id"] for row in self.get().json["schedules"]})
        self.assertEqual(ScheduleOverride.query.count(), 0)

    def external(self):
        self.app.config.update(TERMINAL_CALENDAR_URL="https://calendar.invalid/events", TERMINAL_CALENDAR_BASIC="private-ics-fixture")
        calendar = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:canvas-assignment-1\r\nSUMMARY:[已完成] Read chapter\r\nDTSTART;TZID=Asia/Shanghai:20261012T170000\r\nDTEND;TZID=Asia/Shanghai:20261012T180000\r\nX-CANVAS-COURSE:Biology\r\nX-CANVAS-COMPLETED:TRUE\r\nDESCRIPTION:First line\\nSecond\r\n line\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        self.upstream.side_effect = lambda *_args, **_kwargs: fixtures.Remote(json.dumps({"messages": [], "schedules": [{"id": "llm-1", "title": "Meeting", "start_at": milliseconds(self.start), "end_at": milliseconds(self.start + dt.timedelta(hours=1)), "status": "active"}], "timetable": {"revision": 1, "data": {"term": {"week1_monday": "2026-10-12"}, "periods": [{"number": 1, "start": "08:00", "end": "08:45"}], "courses": [{"id": "course-1", "name": "Linear algebra", "day": 2, "weeks": [1, 2], "periods": [1], "location": "A101"}]}}}).encode())
        return patch("app.schedules._calendar_bytes", return_value=calendar)

    def test_super_feed_includes_ics_canvas_llm_and_own_but_keeps_timetable_separate(self):
        with self.external():
            for path in ("schedules", "snapshot"):
                response = self.get(path, user_id=1)
                self.assertEqual(response.status_code, 200)
                rows = {row["id"]: row for row in response.json["schedules"]}
                self.assertTrue({"canvas-assignment-1", "llm-1", "netdisk:event:208", "netdisk:task:106"} <= set(rows))
                self.assertFalse(any(row.get("source") == "timetable" or row["id"].startswith("timetable:") for row in rows.values()))
                canvas = rows["canvas-assignment-1"]
                self.assertEqual(canvas["start_at"], milliseconds(self.start))
                self.assertEqual(canvas["description"], "First line\nSecondline")
                self.assertTrue(canvas["source_completed"])
                self.assertEqual(canvas["course"], "Biology")
                self.assertFalse(canvas["editable"])
                if path == "snapshot":
                    self.assertEqual(response.json["timetable"]["data"]["courses"][0]["id"], "course-1")
                    self.assertEqual(response.json["timetable"]["revision"], 1)

    def test_legacy_timetable_schedule_copies_are_excluded_and_cannot_be_forced(self):
        with self.external():
            original = self.upstream.side_effect
            def snapshot_with_legacy_copy(*args, **kwargs):
                with original(*args, **kwargs) as remote:
                    data = json.loads(remote.read())
                data["schedules"].extend([
                    {"id": "timetable:course-1:1", "source": "terminal", "title": "Stale course by UID"},
                    {"id": "old-course-copy", "source": "timetable", "title": "Stale course by source"},
                ])
                return fixtures.Remote(json.dumps(data).encode())
            self.upstream.side_effect = snapshot_with_legacy_copy
            for path in ("schedules", "snapshot"):
                response = self.get(path, user_id=1)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(any(row.get("source") == "timetable" or row["id"].startswith("timetable:") for row in response.json["schedules"]))
                self.assertNotIn("old-course-copy", {row["id"] for row in response.json["schedules"]})
            self.assertEqual(self.change("timetable:course-1:1", {"forced_completed": True}, user_id=1).status_code, 404)
            self.assertEqual(self.change("old-course-copy", {"forced_completed": True}, user_id=1).status_code, 404)
            self.assertEqual(ScheduleOverride.query.count(), 0)

    def test_external_force_is_server_persisted_account_private_and_keeps_source_complete(self):
        with self.external():
            self.assertEqual(self.change("canvas-assignment-1", {"forced_completed": True}, user_id=1).status_code, 200)
            changed = self.change("canvas-assignment-1", {"forced_completed": False}, user_id=1)
            self.assertEqual(changed.status_code, 200)
            self.assertTrue(changed.json["schedule"]["source_completed"])
            self.assertTrue(changed.json["schedule"]["completed"])
            self.assertFalse(changed.json["schedule"]["forced_completed"])
            self.assertEqual(self.change("llm-1", {"forced_completed": True}, user_id=1).status_code, 200)
            self.assertEqual(self.change("timetable:course-1:1", {"forced_completed": True}, user_id=1).status_code, 404)
            self.assertEqual(self.change("canvas-assignment-1", {"forced_completed": True}, user_id=2).status_code, 404)
            self.assertEqual(self.change("timetable:course-1:1", {"title": "Foreign edit"}, user_id=1).status_code, 404)
            rows = {row["id"]: row for row in self.get(user_id=1).json["schedules"]}
            self.assertTrue(rows["llm-1"]["forced_completed"])
            self.assertNotIn("timetable:course-1:1", rows)
            self.assertTrue(all(row.user_id == 1 for row in ScheduleOverride.query.all()))
            self.assertTrue(all(call.kwargs.get("method") == "GET" for call in self.upstream.call_args_list if call.args[0].endswith("snapshot") and call.kwargs))

    def test_external_failure_is_reported_without_hiding_owned_schedules(self):
        with self.external(), patch("app.schedules._calendar_bytes", side_effect=ValueError("private-ics-fixture")):
            response = self.get("schedules", user_id=1)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["calendar_unavailable"])
            self.assertIn("netdisk:event:208", {row["id"] for row in response.json["schedules"]})
            self.assertNotIn("private-ics-fixture", response.get_data(as_text=True))
            self.assertEqual(self.change("nonexistent-external", {"forced_completed": True}, user_id=1).status_code, 503)

    def test_ics_parser_validates_complete_calendar_and_ignores_nested_alarms(self):
        with self.assertRaises(ValueError):
            parse_calendar("BEGIN:VCALENDAR\n")
        value = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:event-a\nSUMMARY:Event\\, one\nDTSTART;VALUE=DATE:20261012\nDTEND;VALUE=DATE:20261013\nBEGIN:VALARM\nDESCRIPTION:Alarm\nEND:VALARM\nDESCRIPTION:Event notes\nEND:VEVENT\nEND:VCALENDAR"
        row = parse_calendar(value)[0]
        self.assertTrue(row["all_day"])
        self.assertEqual(row["title"], "Event, one")
        self.assertEqual(row["description"], "Event notes")


if __name__ == "__main__":
    unittest.main()
