"""User-scoped mobile schedules and Terminal proxy tests with mocked upstream."""

import datetime as dt
import io
import json
import unittest
from unittest.mock import patch
import urllib.error

from flask import Flask
from flask_jwt_extended import create_access_token
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles

from app.api import api_bp
from app.auth_sessions import register_auth_callbacks
from app.extensions import db, jwt
from app.mobile import mobile_bp
from app.models import AuthRefreshToken, CalendarEvent, Project, ProjectMember, Task, User, utcnow


@compiles(BigInteger,"sqlite")
def sqlite_integer(_type,_compiler,**_kwargs):
    return "INTEGER"


class Remote(io.BytesIO):
    def __init__(self,body,content_type="application/json",status=200):
        super().__init__(body)
        self.status=status
        self.headers={"Content-Type":content_type}


class ChangingRemote(Remote):
    def __init__(self, change):
        super().__init__(b'data: {"body":"authorized-first-event"}\n'
                         b'data: {"body":"private-event-after-access-loss"}\n',
                         content_type="text/event-stream")
        self.change=change
        self.line_count=0

    def readline(self, *args):
        self.line_count+=1
        if self.line_count==2:
            self.change()
        return super().readline(*args)


class MobileTerminalTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.secret="private-mobile-upstream-fixture-credential"
        self.app.config.update(
            TESTING=True,SQLALCHEMY_DATABASE_URI="sqlite://",SQLALCHEMY_TRACK_MODIFICATIONS=False,
            JWT_SECRET_KEY="disposable-mobile-jwt-secret-at-least-32-characters",
            INFOCENTER_API_BASE="http://127.0.0.1:8767/api/terminal",INFOCENTER_API_TOKEN=self.secret,
            MESSAGE_BRIDGE_ENABLED=False,READABLE_STORAGE_ENABLED=False,
        )
        db.init_app(self.app)
        jwt.init_app(self.app)
        register_auth_callbacks(jwt)
        self.app.register_blueprint(api_bp,url_prefix="/api")
        self.app.register_blueprint(mobile_bp,url_prefix="/api/mobile/terminal")
        self.context=self.app.app_context();self.context.push()
        db.create_all()
        for user_id,role,active in ((1,"super_admin",True),(2,"user",True),(3,"user",True),(4,"super_admin",False)):
            db.session.add(User(id=user_id,username=f"mobile-{user_id}",display_name=f"User {user_id}",password_hash="unused",role_system=role,status="active",is_activated=active))
        for project_id,creator in ((10,1),(20,2),(30,3)):
            db.session.add(Project(id=project_id,name=f"Project {project_id}",key=f"MOBILE_{project_id}",creator_id=creator))
        db.session.add(ProjectMember(project_id=10,user_id=2,role_project="user"))
        self.start=dt.datetime(2026,10,12,9,tzinfo=dt.timezone.utc)
        for event_id,scope,owner,project,assignee in (
            (201,"personal",2,None,None),(202,"personal",3,None,2),
            (203,"project",None,10,2),(204,"project",None,10,3),
            (205,"project",None,10,None),(206,"project",None,30,2),
            (207,"project",None,20,2),(208,"personal",1,None,1),
            (209,"project",None,10,1),
        ):
            db.session.add(CalendarEvent(id=event_id,scope=scope,owner_user_id=owner,project_id=project,assignee_id=assignee,title=f"Event {event_id}",start_at=self.start,end_at=self.start+dt.timedelta(hours=1),created_by=1))
        for task_id,project,assignee,dated,completed in (
            (101,10,2,True,False),(102,10,3,True,False),(103,30,2,True,False),
            (104,10,2,False,False),(105,20,2,True,True),(106,10,1,True,False),
        ):
            db.session.add(Task(id=task_id,project_id=project,assignee_id=assignee,title=f"Task {task_id}",reporter_id=1,status="done" if completed else "todo",start_at=self.start if dated else None,due_at=self.start if dated else None,completed_at=self.start if completed else None))
        db.session.commit()
        self.tokens={user_id:create_access_token(identity=str(user_id)) for user_id in (1,2,3,4)}
        self.client=self.app.test_client()
        self.mock=patch("app.mobile.open_upstream")
        self.upstream=self.mock.start()
        self.addCleanup(self.mock.stop)
        self.upstream.side_effect=lambda *_args:Remote(b'{"messages":[],"schedules":[],"revision":1}')

    def tearDown(self):
        db.session.remove();db.drop_all();self.context.pop()

    def headers(self,user_id=2,token=None):
        return {"Authorization":"Bearer "+(token or self.tokens[user_id])}

    def get(self,path="snapshot",user_id=2,token=None):
        return self.client.get("/api/mobile/terminal/"+path,headers=self.headers(user_id,token))

    def test_ordinary_snapshot_contains_only_owner_events_and_current_assigned_project_work(self):
        response=self.get()
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json["terminal_access"])
        self.assertEqual(response.json["messages"],[])
        self.assertEqual({row["id"] for row in response.json["schedules"]},{"netdisk:event:201","netdisk:event:203","netdisk:event:207","netdisk:task:101","netdisk:task:105"})
        self.assertTrue(all(row["user_id"]==2 and row["source"]=="netdisk" for row in response.json["schedules"]))
        tasks=[row for row in response.json["schedules"] if row["netdisk_kind"]=="task"]
        self.assertTrue(all(row["end_at"]>row["start_at"] for row in tasks))
        self.assertEqual(next(row for row in tasks if row["netdisk_id"]==105)["status"],"completed")
        self.upstream.assert_not_called()

    def test_leaving_project_removes_assigned_event_and_task_without_stale_cache(self):
        self.assertEqual(self.get().status_code,200)
        db.session.delete(ProjectMember.query.filter_by(project_id=10,user_id=2).first());db.session.commit()
        response=self.get()
        self.assertEqual({row["id"] for row in response.json["schedules"]},{"netdisk:event:201","netdisk:event:207","netdisk:task:105"})
        self.upstream.assert_not_called()

    def test_other_user_token_cannot_select_a_different_users_schedule_feed(self):
        response=self.get("snapshot?user_id=2&owner_user_id=2",user_id=3)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["netdisk_user_id"],3)
        self.assertEqual({row["id"] for row in response.json["schedules"]},{"netdisk:event:202"})
        self.assertTrue(all(row["user_id"]==3 for row in response.json["schedules"]))
        self.upstream.assert_not_called()

    def test_super_admin_merges_upstream_and_own_namespaced_schedules_without_duplicates(self):
        upstream={"messages":[{"uid":"wechat-real-1","source":"wechat"}],"schedules":[
            {"id":"201","source":"canvas","title":"Canvas"},
            {"id":"netdisk:event:208","source":"netdisk","title":"stale upstream copy"},
        ],"revision":42}
        self.upstream.side_effect=lambda *_args:Remote(json.dumps(upstream).encode())
        response=self.get(user_id=1)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json["terminal_access"])
        self.assertEqual(response.json["messages"],upstream["messages"])
        self.assertEqual({row["id"] for row in response.json["schedules"]},{"201","netdisk:event:208","netdisk:event:209","netdisk:task:106"})
        self.assertEqual(len(response.json["schedules"]),4)
        self.assertEqual(next(row for row in response.json["schedules"] if row["id"]=="netdisk:event:208")["title"],"Event 208")
        self.upstream.assert_called_once_with("http://127.0.0.1:8767/api/terminal/snapshot",self.secret)
        self.assertNotIn(self.secret.encode(),response.data)

    def test_non_admin_cannot_proxy_any_shared_terminal_route(self):
        for path in ("messages","stream","health","llm","../snapshot"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code,403)
        response=self.client.post("/api/mobile/terminal/messages/1/read",json={"is_read":True},headers=self.headers())
        self.assertEqual(response.status_code,403)
        self.upstream.assert_not_called()

    def test_expired_revoked_and_unactivated_tokens_are_rejected_before_upstream(self):
        expired=create_access_token(identity="1",expires_delta=dt.timedelta(seconds=-1))
        self.assertEqual(self.get(user_id=1,token=expired).status_code,401)
        session=AuthRefreshToken(user_id=1,token_hash="unused",expires_at=utcnow()+dt.timedelta(days=1),revoked_at=None)
        db.session.add(session);db.session.commit()
        token=create_access_token(identity="1",additional_claims={"auth_session":str(session.id)})
        session.revoked_at=utcnow();db.session.commit()
        self.assertEqual(self.get(user_id=1,token=token).status_code,401)
        self.assertEqual(self.get(user_id=4).status_code,401)
        self.assertEqual(self.client.get("/api/mobile/terminal/snapshot").status_code,401)
        self.upstream.assert_not_called()

    def test_upstream_json_and_event_stream_never_expose_server_credentials(self):
        self.upstream.side_effect=lambda *_args:Remote(json.dumps({"echo":self.secret}).encode())
        response=self.get("health",user_id=1)
        self.assertEqual(response.status_code,200)
        self.assertNotIn(self.secret.encode(),response.data)
        self.upstream.side_effect=lambda *_args:Remote((f'data: {{"body":"{self.secret}"}}\n\n').encode(),content_type="text/event-stream")
        response=self.get("stream",user_id=1)
        self.assertEqual(response.status_code,200)
        self.assertNotIn(self.secret.encode(),response.data)
        response.close()

    def test_active_event_stream_stops_before_data_after_super_admin_demotion(self):
        def demote():
            db.session.get(User,1).role_system="user"
            db.session.commit()
        remote=ChangingRemote(demote)
        self.upstream.side_effect=lambda *_args:remote
        response=self.get("stream",user_id=1)
        self.assertEqual(response.status_code,200)
        data=response.data
        self.assertIn(b"authorized-first-event",data)
        self.assertNotIn(b"private-event-after-access-loss",data)
        self.assertEqual(remote.line_count,2)
        self.assertTrue(remote.closed)
        response.close()

    def test_active_event_stream_stops_before_data_after_device_session_revocation(self):
        session=AuthRefreshToken(user_id=1,token_hash="offline-stream-session",
                                 expires_at=utcnow()+dt.timedelta(days=1),revoked_at=None)
        db.session.add(session);db.session.commit()
        session_id=int(session.id)
        token=create_access_token(identity="1",additional_claims={"auth_session":str(session_id)})
        def revoke():
            db.session.get(AuthRefreshToken,session_id).revoked_at=utcnow()
            db.session.commit()
        remote=ChangingRemote(revoke)
        self.upstream.side_effect=lambda *_args:remote
        response=self.get("stream",user_id=1,token=token)
        self.assertEqual(response.status_code,200)
        data=response.data
        self.assertIn(b"authorized-first-event",data)
        self.assertNotIn(b"private-event-after-access-loss",data)
        self.assertEqual(remote.line_count,2)
        self.assertTrue(remote.closed)
        response.close()

    def test_calendar_feed_uses_private_basic_auth_and_validates_ics(self):
        credential="offline-calendar-basic-fixture"
        self.app.config.update(TERMINAL_CALENDAR_URL="https://calendar.invalid/private/events",TERMINAL_CALENDAR_BASIC=credential)
        calendar=b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:phone-offline\r\nDTSTART:20261012T090000Z\r\nDTEND:20261012T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        with patch("app.mobile.urllib.request.build_opener") as build:
            remote=Remote(calendar,content_type="text/calendar")
            build.return_value.open.return_value=remote
            response=self.get("calendar",user_id=1)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.data,calendar)
            self.assertIn("text/calendar",response.content_type)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertNotIn(credential.encode(),response.data)
            request=build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,"https://calendar.invalid/private/events")
            self.assertEqual(request.get_header("Authorization"),"Basic "+credential)
            self.assertEqual(request.get_header("Accept"),"text/calendar")
            self.assertTrue(remote.closed)
            build.reset_mock()
            self.assertEqual(self.get("calendar").status_code,403)
            build.assert_not_called()
            for bad in (b"<html>login required</html>",b"BEGIN:VCALENDAR"+b"x"*300):
                with self.subTest(body=bad[:20]),patch("app.mobile.MAX_JSON_BYTES",256):
                    remote=Remote(bad)
                    build.return_value.open.return_value=remote
                    self.assertEqual(self.get("calendar",user_id=1).status_code,502)
                    self.assertTrue(remote.closed)
            build.return_value.open.side_effect=urllib.error.URLError("offline fixture")
            self.assertEqual(self.get("calendar",user_id=1).status_code,502)
        self.upstream.assert_not_called()

    def test_calendar_config_rejects_unsafe_urls_without_opening_a_connection(self):
        for url,credential in (
            ("http://calendar.invalid/events","fixture"),
            ("https://user:password@calendar.invalid/events","fixture"),
            ("https://calendar.invalid/events?token=fixture","fixture"),
            ("https://calendar.invalid/events#private","fixture"),
            ("https://calendar.invalid/events",""),
        ):
            with self.subTest(url=url),patch("app.mobile.urllib.request.build_opener") as build:
                self.app.config.update(TERMINAL_CALENDAR_URL=url,TERMINAL_CALENDAR_BASIC=credential)
                self.assertEqual(self.get("calendar",user_id=1).status_code,503)
                build.assert_not_called()

    def test_calendar_delete_is_restricted_to_phone_uids_and_super_admin(self):
        self.app.config.update(TERMINAL_CALENDAR_URL="https://calendar.invalid/events",TERMINAL_CALENDAR_BASIC="offline-basic")
        with patch("app.mobile.urllib.request.build_opener") as build:
            response=self.client.delete("/api/mobile/terminal/calendar/phone-offline_1",headers=self.headers(2))
            self.assertEqual(response.status_code,403)
            build.assert_not_called()
            for uid in ("canvas-event-1","phone-","phone-a.b"):
                response=self.client.delete("/api/mobile/terminal/calendar/"+uid,headers=self.headers(1))
                self.assertEqual(response.status_code,400)
            build.assert_not_called()
            remote=Remote(b"")
            build.return_value.open.return_value=remote
            response=self.client.delete("/api/mobile/terminal/calendar/phone-offline_1",headers=self.headers(1))
            self.assertEqual(response.status_code,200)
            request=build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(),"DELETE")
            self.assertEqual(request.full_url,"https://calendar.invalid/events/phone-offline_1.ics")
            self.assertTrue(remote.closed)

    def test_new_terminal_whitelist_forwards_supported_methods_and_rejects_others(self):
        for method,path in (
            ("GET","unread"),("GET","attention"),
            ("POST","conversations/read"),("POST","conversations/summary"),
            ("POST","messages/12/process"),("POST","messages/read-all"),
            ("PATCH","directory/netdisk-user-2"),
            ("PATCH","attention/netdisk:instance:thread:2"),("POST","attention/summary"),
            ("POST","llm/test"),("POST","llm/process"),("POST","summarize"),
            ("POST","test-notification"),
        ):
            with self.subTest(method=method,path=path):
                self.upstream.reset_mock()
                body={"chat_id":"netdisk:fixture:thread:2","through_uid":"netdisk:fixture:inbox:1"}
                response=self.client.open("/api/mobile/terminal/"+path,method=method,
                                          json=body if method!="GET" else None,headers=self.headers(1))
                self.assertEqual(response.status_code,200)
                args=self.upstream.call_args.args
                self.assertEqual(args[:2],("http://127.0.0.1:8767/api/terminal/"+path,self.secret))
                self.assertEqual(None if args[2] is None else json.loads(args[2]),None if method=="GET" else body)
        for path in ("../snapshot","messages/1/delete","directory/user/private"):
            with self.subTest(path=path):
                self.upstream.reset_mock()
                response=self.client.post("/api/mobile/terminal/"+path,json={},headers=self.headers(1))
                self.assertEqual(response.status_code,404)
                self.upstream.assert_not_called()
        for path in ("unread?token=private","unread?access_token=private"):
            self.upstream.reset_mock()
            self.assertEqual(self.get(path,user_id=1).status_code,400)
            self.upstream.assert_not_called()
        self.upstream.reset_mock()
        response=self.client.post("/api/mobile/terminal/conversations/read",data="not JSON",headers=self.headers(1))
        self.assertEqual(response.status_code,415)
        self.upstream.assert_not_called()
        response=self.client.post("/api/mobile/terminal/conversations/read",json=[],headers=self.headers(1))
        self.assertEqual(response.status_code,400)
        self.upstream.assert_not_called()

    def calendar_request(self,method,path="",user_id=2,body=None):
        return self.client.open("/api/calendar/events"+path,method=method,json=body,headers=self.headers(user_id))

    def mine_ids(self,user_id):
        response=self.calendar_request("GET","?scope=mine",user_id=user_id)
        self.assertEqual(response.status_code,200)
        return {row["id"] for row in response.json["data"]["items"]}

    def test_personal_assignee_create_mine_timezone_patch_reassign_and_delete_isolation(self):
        body={"scope":"personal","assignee_id":2,"title":"Assigned personal event",
              "start_at":"2026-10-12T17:00:00+08:00","end_at":"2026-10-12T18:00:00+08:00"}
        created=self.calendar_request("POST",user_id=1,body=body)
        self.assertEqual(created.status_code,200)
        event_id=created.json["data"]["event"]["id"]
        self.assertIn(event_id,self.mine_ids(2));self.assertNotIn(event_id,self.mine_ids(1))
        event=db.session.get(CalendarEvent,event_id)
        self.assertEqual((event.owner_user_id,event.assignee_id),(2,2))
        self.assertEqual(event.start_at.replace(tzinfo=dt.timezone.utc),self.start)
        self.assertEqual(self.calendar_request("PATCH",f"/{event_id}",user_id=3,body={"title":"forbidden"}).status_code,403)
        self.assertEqual(self.calendar_request("DELETE",f"/{event_id}",user_id=3).status_code,403)
        updated=self.calendar_request("PATCH",f"/{event_id}",user_id=2,body={"start_at":"2026-10-12T17:30:00+08:00"})
        self.assertEqual(updated.status_code,200)
        self.assertEqual(db.session.get(CalendarEvent,event_id).start_at.replace(tzinfo=dt.timezone.utc),self.start+dt.timedelta(minutes=30))
        self.assertEqual(self.calendar_request("PATCH",f"/{event_id}",user_id=2,body={"assignee_id":3}).status_code,403)
        db.session.rollback()
        self.assertEqual(self.calendar_request("PATCH",f"/{event_id}",user_id=1,body={"assignee_id":3}).status_code,200)
        self.assertNotIn(event_id,self.mine_ids(2));self.assertIn(event_id,self.mine_ids(3))
        self.assertEqual(self.calendar_request("DELETE",f"/{event_id}",user_id=2).status_code,403)
        self.assertEqual(self.calendar_request("DELETE",f"/{event_id}",user_id=3).status_code,200)
        self.assertNotIn(event_id,self.mine_ids(3))
        self.assertIsNone(db.session.get(CalendarEvent,event_id))
        self.upstream.assert_not_called()

    def test_project_assignee_create_mine_timezone_patch_departure_and_delete_isolation(self):
        body={"scope":"project","project_id":10,"assignee_id":2,"title":"Assigned project event",
              "start_at":"2026-10-12T17:00:00+08:00","end_at":"2026-10-12T18:00:00+08:00"}
        invalid=self.calendar_request("POST",user_id=1,body={**body,"assignee_id":3})
        self.assertEqual(invalid.status_code,400)
        created=self.calendar_request("POST",user_id=1,body=body)
        self.assertEqual(created.status_code,200)
        event_id=created.json["data"]["event"]["id"]
        self.assertIn(event_id,self.mine_ids(2));self.assertNotIn(event_id,self.mine_ids(1));self.assertNotIn(event_id,self.mine_ids(3))
        self.assertIn(f"netdisk:event:{event_id}",{row["id"] for row in self.get().json["schedules"]})
        self.assertEqual(self.calendar_request("PATCH",f"/{event_id}",body={"start_at":"2026-10-12T04:30:00-05:00"}).status_code,200)
        self.assertEqual(db.session.get(CalendarEvent,event_id).start_at.replace(tzinfo=dt.timezone.utc),self.start+dt.timedelta(minutes=30))
        self.assertEqual(self.calendar_request("PATCH",f"/{event_id}",body={"start_at":"2026-10-12T19:00:00+08:00"}).status_code,400)
        db.session.rollback()
        self.assertEqual(self.calendar_request("DELETE",f"/{event_id}",user_id=3).status_code,403)
        db.session.delete(ProjectMember.query.filter_by(project_id=10,user_id=2).first());db.session.commit()
        self.assertNotIn(event_id,self.mine_ids(2))
        self.assertNotIn(f"netdisk:event:{event_id}",{row["id"] for row in self.get().json["schedules"]})
        self.assertEqual(self.calendar_request("PATCH",f"/{event_id}",body={"title":"forbidden after departure"}).status_code,403)
        self.assertEqual(self.calendar_request("DELETE",f"/{event_id}").status_code,403)
        self.assertEqual(self.calendar_request("DELETE",f"/{event_id}",user_id=1).status_code,200)
        self.assertIsNone(db.session.get(CalendarEvent,event_id))
        self.upstream.assert_not_called()


if __name__=="__main__":
    unittest.main()
