"""Directory metadata and deterministic attention policy. Never sends WeChat messages."""
import contextlib
import copy
import json
import sqlite3
import time
from pathlib import Path
from flask import jsonify, request

KINDS = ['工作消息', '工作日程', '科研任务', '闲聊消息', '工作询问', '一般消息', '重要']
MODES = ['正常', 'WORKING', '免打扰', 'STUDY']
DEFAULT = {
    'categories': {'group': ['闲聊','工作','科研','学习','家庭','其它'], 'contact': ['老师','教授','同学','亲人','其它']},
    'rules': [], 'muted_action': 'inherit',
    'matrix': dict(zip(MODES, [dict(zip(KINDS, row)) for row in [
        ['notify','notify','notify','quiet','notify','notify','notify'],
        ['notify','notify','notify','quiet','notify','reply','notify'],
        ['reply','reply','notify','notify','reply','reply','notify'],
        ['reply','reply','notify','quiet','quiet','quiet','notify']]])),
    'important_words': ['紧急','急事','尽快回复'],
    'schedule_categories': [], 'schedule_muted': True, 'schedule_all': None,
}

class Attention:
    def __init__(self, store):
        self.store = store
        self.last_scan = 0
        self.contacts = store.wechat.parent.parent / 'wechat-decrypt/decrypted/contact/contact.db'
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS directory(
              username TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
              wx_remark TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '其它',
              note TEXT NOT NULL DEFAULT '', muted INTEGER, notify_raw INTEGER,
              action TEXT NOT NULL DEFAULT 'inherit', message_kind TEXT NOT NULL DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS attention_events(
              message_id INTEGER PRIMARY KEY, chat TEXT, created_at INTEGER, action TEXT, kind TEXT);''')
            if not store.meta(db, 'attention_state'):
                store.set_meta(db, 'attention_state', {'mode':'正常','since':self.now(),'summary_until':0,'summary':{},'away_since':0})
            if 'categories' not in {r[1] for r in db.execute('PRAGMA table_info(directory)')}:
                db.execute("ALTER TABLE directory ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'")
                for row in db.execute('SELECT username,category FROM directory').fetchall():
                    db.execute('UPDATE directory SET categories=? WHERE username=?',(json.dumps([row['category']]),row['username']))
        self.refresh_entries()

    def refresh_entries(self):
        with self.store.connect() as db:
            self.entries = {r['username']:dict(r) for r in db.execute('SELECT * FROM directory')}

    @staticmethod
    def tags(entity):
        if not entity: return ['其它']
        return json.loads(entity['categories'])

    def display(self, username, fallback=''):
        row=self.entries.get(username)
        if not row: return fallback or username
        name=row['name'] or username
        remark=row['note'].strip() or row['wx_remark'].strip()
        return f'{remark}（{name}）' if remark and remark!=name else remark or name

    @staticmethod
    def now(): return int(time.time()*1000)

    def settings(self, db):
        result = copy.deepcopy(DEFAULT)
        result.update(self.store.meta(db, 'attention_settings', {}))
        return result

    def sync_directory(self):
        if time.monotonic()-self.last_scan < 30 or not self.contacts.exists(): return
        with contextlib.closing(sqlite3.connect(f'file:{self.contacts}?mode=ro',uri=True)) as source:
            rows = source.execute("SELECT username,nick_name,remark,chat_room_notify FROM contact WHERE username LIKE '%@chatroom' OR local_type=1").fetchall()
        with self.store.connect() as db:
            db.execute('UPDATE directory SET active=0')
            for username,name,remark,raw in rows:
                if not username: continue
                kind = 'group' if username.endswith('@chatroom') else 'contact'
                db.execute('''INSERT INTO directory(username,kind,name,wx_remark,muted,notify_raw,updated_at)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET name=excluded.name,
                  wx_remark=excluded.wx_remark,muted=excluded.muted,notify_raw=excluded.notify_raw,
                  active=1,updated_at=excluded.updated_at''',
                  (username,kind,name or remark or username,remark or '',int(raw==0) if kind=='group' and raw in (0,1) else None,raw,self.now()))
            self.store.set_meta(db,'directory_checked_at',self.now())
        self.last_scan = time.monotonic()
        self.refresh_entries()

    def route(self, db, source, payload, body):
        cfg = self.settings(db)
        state = self.store.meta(db,'attention_state')
        entity = db.execute('SELECT * FROM directory WHERE username=?',(payload.get('chat_id',''),)).fetchone()
        categories = self.tags(entity)
        category = categories[0] if categories else '其它'
        kind = entity['message_kind'] if entity else ''
        if source == 'canvas' or source == 'schedule': kind = '工作日程'
        if not kind:
            inferred={'工作':'工作消息','科研':'科研任务','学习':'工作日程','闲聊':'闲聊消息'}
            kind = next((inferred[c] for c in categories if c in inferred),'一般消息')
        if any(word and word in body for word in cfg['important_words']): kind = '重要'
        action = entity['action'] if entity else 'inherit'
        entity_kind = entity['kind'] if entity else 'contact'
        if action == 'inherit':
            for rule in cfg['rules']:
                if rule['kind'] in ('all',entity_kind) and rule['category'] in categories:
                    action = rule['action']; break
        if action == 'inherit' and entity and entity['muted']==1: action = cfg['muted_action']
        if action == 'inherit': action = cfg['matrix'][state['mode']][kind]
        all_categories = cfg['schedule_all'] if cfg['schedule_all'] is not None else not cfg['schedule_categories']
        allow_llm = (all_categories or bool(set(categories)&set(cfg['schedule_categories']))) and (cfg['schedule_muted'] or not entity or entity['muted']!=1)
        return action,kind,category,allow_llm

    def state(self):
        with self.store.connect() as db:
            state = self.store.meta(db,'attention_state')
            return dict(state, settings=self.settings(db), directory_checked_at=self.store.meta(db,'directory_checked_at',0))

    def set_mode(self, mode):
        if mode not in MODES: raise ValueError('无效工作状态')
        with self.store.connect() as db:
            state = self.store.meta(db,'attention_state')
            if state['mode']==mode: return state
            now = self.now()
            if state['mode']=='正常': state['away_since']=now
            if mode=='正常':
                rows = db.execute("SELECT chat,kind,count(*) AS n FROM attention_events WHERE created_at>=? AND action IN ('quiet','reply') GROUP BY chat,kind",(state.get('away_since',state['since']),)).fetchall()
                state['summary']={'total':sum(r['n'] for r in rows),'chats':len(set(r['chat'] for r in rows)),'items':[dict(r) for r in rows]}
                state['summary_until']=now+300000
            else: state['summary_until']=0
            state.update(mode=mode,since=now)
            self.store.set_meta(db,'attention_state',state)
        return state

    def save_settings(self, patch):
        with self.store.connect() as db:
            cfg=self.settings(db)
            for key in DEFAULT:
                if key in patch: cfg[key]=patch[key]
            for kind in ('group','contact'):
                values=cfg['categories'].get(kind)
                if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() for v in values): raise ValueError('分类不能为空')
                if len(values)!=len(set(values)): raise ValueError('分类不能重复')
            actions=('inherit','notify','quiet','ignore','reply')
            if cfg['muted_action'] not in actions: raise ValueError('无效免打扰规则')
            for row in cfg['rules']:
                if row.get('kind') not in ('group','contact','all') or row.get('action') not in actions or not isinstance(row.get('category'),str): raise ValueError('无效分类规则')
            for mode in MODES:
                for kind in KINDS:
                    if cfg['matrix'][mode][kind] not in ('notify','quiet','reply'): raise ValueError('无效状态规则')
            if not isinstance(cfg['schedule_muted'],bool): raise ValueError('无效日程范围')
            for key in ('important_words','schedule_categories'):
                if not isinstance(cfg[key],list) or any(not isinstance(v,str) for v in cfg[key]): raise ValueError('无效列表')
            self.store.set_meta(db,'attention_settings',cfg)
        return cfg

    def mount(self, api):
        @api.get('/directory')
        def directory():
            with self.store.connect() as db:
                rows=[dict(r) for r in db.execute("SELECT * FROM directory WHERE active=1 OR note!='' OR category NOT IN ('其它','') OR json_array_length(categories)>1 ORDER BY kind,COALESCE(NULLIF(note,''),NULLIF(wx_remark,''),name)")]
                for row in rows: row['categories']=json.loads(row['categories'])
                return jsonify(items=rows,settings=self.settings(db))

        @api.post('/directory/<path:username>')
        def edit(username):
            patch=request.get_json(force=True)
            with self.store.connect() as db:
                row=db.execute('SELECT * FROM directory WHERE username=?',(username,)).fetchone()
                if not row: return jsonify(error='联系人不存在'),404
                categories=patch.get('categories',[patch['category']] if 'category' in patch else self.tags(row))
                action=patch.get('action',row['action'])
                kind=patch.get('message_kind',row['message_kind'])
                note=patch.get('note',row['note'])
                if not isinstance(categories,list) or any(not isinstance(c,str) for c in categories): raise ValueError('分类必须是列表')
                if any(c not in self.settings(db)['categories'][row['kind']] and c not in self.tags(row) for c in categories): raise ValueError('请先添加分类')
                categories=list(dict.fromkeys(categories))
                if action not in ('inherit','notify','quiet','ignore') or kind not in ['']+KINDS: raise ValueError('无效消息规则')
                if not isinstance(note,str): raise ValueError('备注必须是文本')
                db.execute('UPDATE directory SET category=?,categories=?,note=?,action=?,message_kind=? WHERE username=?',(categories[0] if categories else '',json.dumps(categories),note.strip(),action,kind,username))
            self.refresh_entries()
            return jsonify(ok=True)

        @api.route('/attention',methods=['GET','POST'])
        def attention():
            if request.method=='POST':
                patch=request.get_json(force=True)
                if 'mode' in patch: self.set_mode(patch['mode'])
                if 'settings' in patch: self.save_settings(patch['settings'])
            return jsonify(self.state())

        @api.post('/attention/opened')
        def opened():
            with self.store.connect() as db:
                state=self.store.meta(db,'attention_state')
                # Only acknowledge the summary actually displayed by this client.
                if (request.get_json(silent=True) or {}).get('summary_until')==state.get('summary_until'):
                    state['summary_until']=0
                    self.store.set_meta(db,'attention_state',state)
            return jsonify(ok=True)

        @api.post('/auto-reply')
        def reply():
            return jsonify(enabled=False,sent=False,status='reserved',message='自动回复仅预留接口，不发送微信消息')
