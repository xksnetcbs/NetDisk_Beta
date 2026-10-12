"""Resolve sender IDs within their own WeChat database shard."""
import contextlib
import json
from pathlib import Path
import re
import sqlite3

class SenderIdentity:
    def __init__(self, memory):
        self.root = memory.parent.parent / 'wechat-decrypt'
        self.username = ''
        self.maps = {}
        self.names = {}

    def refresh(self, paths):
        config = self.root / 'config.json'
        if not config.exists(): return
        account = Path(json.loads(config.read_text())['db_dir']).parent.name
        candidates = [re.sub(r'_[0-9a-fA-F]{4,}$', '', account), account]
        contact = self.root / 'decrypted/contact/contact.db'
        with contextlib.closing(sqlite3.connect(f'file:{contact}?mode=ro',uri=True)) as db:
            self.username = next((name for name in candidates if db.execute('SELECT 1 FROM contact WHERE username=?',(name,)).fetchone()), '')
            self.names = {u:remark or nick or u for u,nick,remark in db.execute('SELECT username,nick_name,remark FROM contact')}
        if not self.username: raise ValueError('无法确认当前微信账号，暂缓新消息采集')
        for path in paths:
            with contextlib.closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True)) as db:
                self.maps[path] = dict(db.execute('SELECT rowid,user_name FROM Name2Id'))

    def sender(self, row):
        return self.maps.get(row['source_message_db'],{}).get(row['real_sender_id'],'')

    def outgoing(self, row):
        return bool(self.username and self.sender(row)==self.username)

    def details(self,row):
        username=self.sender(row)
        return {'sender_id':username,'sender_name':self.names.get(username,username or '未知发送者'),'direction':'outgoing' if self.outgoing(row) else 'incoming'}
