"""Private sender receipt tests with temporary capture data and no desktop UI."""
import importlib.util
import contextlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SERVER = Path(__file__).resolve().parents[1] / "integrations/DCP_InfoCenter/server"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SERVER / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateReplySenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "dcp-terminal").mkdir()
        runtime = self.home / "wechat-capture/runtime"
        (runtime / "memory").mkdir(parents=True)
        self.memory = runtime / "memory/wechat_memory.sqlite"
        with contextlib.closing(sqlite3.connect(self.memory)) as db:
            db.execute("CREATE TABLE messages(chat_username TEXT,message_content TEXT,source_message_db TEXT,outgoing INTEGER)")
            db.execute("INSERT INTO messages VALUES('filehelper','test reply','fixture',1)")
            db.commit()
        self.ui = types.SimpleNamespace(key=Mock())
        identity = types.SimpleNamespace(SenderIdentity=lambda _memory: types.SimpleNamespace(
            refresh=lambda _paths: None, outgoing=lambda row: row["outgoing"] == 1))
        fake_fcntl = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *_args: None)
        self.patches = [patch.object(Path, "home", return_value=self.home), patch.dict(os.environ),
            patch.object(sys, "path", list(sys.path)), patch.dict(sys.modules,
                {"wechat_controller": self.ui, "sender_identity": identity, "fcntl": fake_fcntl,
                 "PIL": types.SimpleNamespace(Image=Mock())})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.sender = load("receipt_fixture", "wechat_sender.py")

    def receipt(self, status, after=0):
        with contextlib.closing(sqlite3.connect(self.sender.state / "receipts.sqlite")) as db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,chat TEXT,body TEXT,window TEXT,header TEXT,created REAL,status TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY,after_row INTEGER)")
            db.execute("INSERT OR REPLACE INTO drafts VALUES('receipt-123456789','filehelper','test reply','{}','',0,?)", (status,))
            db.execute("INSERT OR REPLACE INTO checkpoints VALUES('receipt-123456789',?)", (after,))
            db.commit()

    def test_submitted_and_uncertain_confirm_only_after_real_outgoing_capture(self):
        for status in ("submitted", "uncertain"):
            self.receipt(status)
            result = self.sender.invoke({"action": "status", "id": "receipt-123456789"})
            self.assertEqual(result["status"], "confirmed")
        self.ui.key.assert_not_called()

    def test_wrong_target_wrong_text_incoming_or_precheckpoint_never_confirm(self):
        for chat, text, outgoing, after in (("another-person", "test reply", 1, 0),
            ("filehelper", "wrong text", 1, 0), ("filehelper", "test reply", 0, 0), ("filehelper", "test reply", 1, 99)):
            with contextlib.closing(sqlite3.connect(self.memory)) as db:
                db.execute("DELETE FROM messages")
                db.execute("INSERT INTO messages VALUES(?,?,?,?)", (chat, text, "fixture", outgoing))
                db.commit()
            self.receipt("uncertain", after)
            self.assertEqual(self.sender.invoke({"action": "status", "id": "receipt-123456789"})["status"], "uncertain")
        self.ui.key.assert_not_called()

    def test_private_same_request_returns_receipt_without_any_send_key(self):
        direct = load("direct_sender_fixture", "direct_sender.py")
        self.receipt("uncertain")
        with contextlib.closing(sqlite3.connect(self.sender.state / "receipts.sqlite")) as db:
            db.row_factory = sqlite3.Row
            ui = Mock()
            value = direct.send({"id": "receipt-123456789", "chat": "filehelper", "name": "文件传输助手", "text": "test reply"}, db, ui, self.sender.state, self.home)
            self.assertEqual(value["status"], "uncertain")
            self.assertEqual(ui.mock_calls, [])
            with self.assertRaises(ValueError):
                direct.send({"id": "receipt-123456789", "chat": "filehelper", "name": "文件传输助手", "text": "changed reply"}, db, ui, self.sender.state, self.home)
            self.assertEqual(ui.mock_calls, [])

    def candidates(self, direct, sections, rows=None, filehelper=True, name="文件传输助手"):
        rows = rows or [(name, 179.25, 129.25, 136.5), (name, 180.25, 284.25, 136.5)]
        def ocr(_ui, _window, _state, box, **options):
            if options.get("green"): return rows
            if box == (80,62,375,742): return sections
            return []
        with patch.object(direct, "lines", side_effect=ocr):
            return direct.recipient_candidates(None,{"width":1280,"height":772},self.sender.state,name,"same-frame.png",filehelper=filehelper)

    def test_filehelper_history_shortcut_is_excluded_using_full_section_boundary(self):
        direct = load("direct_sender_fixture", "direct_sender.py")
        result = self.candidates(direct, [("聊天记录", 114.5, 179.5)])
        self.assertEqual(result, [("文件传输助手",179.25,129.25)])

    def test_ordinary_contacts_and_missing_boundary_keep_duplicate_protection(self):
        direct = load("direct_sender_fixture", "direct_sender.py")
        self.assertEqual(len(self.candidates(direct, [("聊天记录",114.5,179.5)],filehelper=False)),2)
        self.assertEqual(len(self.candidates(direct, [])),2)
        self.assertEqual(len(self.candidates(direct, [("文件传输助手聊天记录",114.5,179.5)])),2)

    def test_two_real_filehelpers_before_history_remain_ambiguous(self):
        direct = load("direct_sender_fixture", "direct_sender.py")
        rows=[("文件传输助手",179.25,129.25,136.5),("文件传输助手",180.25,154.25,136.5),("文件传输助手",180.25,284.25,136.5)]
        self.assertEqual(len(self.candidates(direct,[("聊天记录",114.5,179.5)],rows)),2)

    def test_selecting_filehelper_still_requires_exact_chat_title(self):
        direct = load("direct_sender_fixture", "direct_sender.py")
        ui = Mock();ui.search_box_point.return_value=(100,70);ui.chat_tab_point.return_value=(30,70)
        window={"width":1280,"height":772}
        with patch.object(direct,"recipient_candidates",return_value=[("文件传输助手",179.25,129.25)]),patch.object(direct,"lines",return_value=[("Wrong title",400,40)]),patch.object(direct.subprocess,"run"),patch.object(direct.time,"sleep"):
            with self.assertRaises(ValueError): direct.locate(ui,window,self.sender.state,"文件传输助手",filehelper=True)
        self.assertNotIn(unittest.mock.call.key("Return"),ui.mock_calls)
