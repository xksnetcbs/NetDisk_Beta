"""Read-only desktop client API over the existing Linux WeChat capture store.

No WeChat login, sending, GUI automation, CDN requests, or LLM calls.
"""
import contextlib
import hashlib
import hmac
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from flask import Blueprint, jsonify, request, send_file
from netdisk_meta import metadata as netdisk_metadata, sender_details as netdisk_sender_details


def clean_body(value):
    return re.sub(r'^[\w@.-]+:\r?\n', '', str(value or ''), count=1).strip()


def parse_content(row):
    body = clean_body(row['message_content'])
    kind = int(row['base_type'] or 0)
    result = {'kind': 'text', 'text': body}
    if kind == 1:
        return result
    xml = html.unescape(body) if body.startswith('&lt;') else body
    root = None
    if len(xml) < 1024 * 1024 and '<!DOCTYPE' not in xml.upper() and '<!ENTITY' not in xml.upper():
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            pass
    if kind == 49 and root is not None:
        app = root.find('.//appmsg')
        if app is None and root.tag == 'appmsg': app = root
        if app is not None:
            subtype = app.findtext('type', '')
            title = app.findtext('title', '')
            description = app.findtext('des', '')
            if subtype == '6':
                size = app.findtext('appattach/totallen', '0')
                result.update(kind='file', text=title, attachment={
                    'name': title or '未命名文件', 'size': int(size) if size.isdigit() else 0,
                    'extension': app.findtext('appattach/fileext', '') or Path(title).suffix.lstrip('.'),
                    'md5': app.findtext('md5', '') or app.findtext('appattach/md5', ''),
                })
            elif subtype == '57':
                quote = app.find('refermsg')
                result.update(kind='quote', text=title)
                if quote is not None:
                    result['quote'] = (quote.findtext('displayname', '') + '：' + clean_body(quote.findtext('content', '')))[:4000]
            else:
                result.update(kind='link', text=title + ('\n' + description if description else ''))
                url = app.findtext('url', '')
                parsed = urlparse(url)
                if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username:
                    result['url'] = url
                if subtype == '19': result.update(kind='forward', text=title or '合并转发记录')
            return result
    labels = {3: ('image', '图片'), 34: ('voice', '语音消息'), 42: ('contact', '联系人名片'),
              43: ('video', '视频'), 47: ('sticker', '表情'), 48: ('location', '位置'),
              50: ('call', '通话记录'), 10000: ('system', '系统消息')}
    label, fallback = labels.get(kind, ('other', row['type_label'] or '暂不支持的消息'))
    result.update(kind=label, text=(html.unescape(re.sub('<[^>]+>', '', body)) if label == 'system' else fallback))
    if label == 'voice' and root is not None:
        voice = root.find('.//voicemsg')
        if voice is not None:
            duration = voice.get('voicelength', '0')
            if duration.isdigit(): result['duration'] = round(int(duration) / 1000, 1)
    return result


class DesktopStore:
    def __init__(self, home=None, memory=None, account=None, identity=None):
        self.home = Path(home or os.environ.get('DCP_TERMINAL_HOME') or Path.home() / 'dcp-terminal')
        self.memory = Path(memory or os.environ.get('DCP_CAPTURE_DB') or Path(os.environ.get('DCP_CAPTURE_ROOT') or Path.home() / 'wechat-capture') / 'runtime/memory/wechat_memory.sqlite')
        capture = self.memory.parent.parent / 'wechat-decrypt'
        self.account = Path(account) if account else Path(json.loads((capture / 'config.json').read_text())['db_dir']).parent
        self.file_root = (self.account / 'msg/file').resolve()
        self.media_root = (self.memory.parent.parent / 'media').resolve()
        if identity is None:
            from sender_identity import SenderIdentity
            identity = SenderIdentity(self.memory)
        self.identity = identity
        self.lock = threading.RLock()
        self.updated = 0
        self.files = []
        self.digests = {}
        self.directory = {}

    @contextlib.contextmanager
    def source(self):
        with contextlib.closing(sqlite3.connect(self.memory.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            yield db

    def refresh(self, force=False):
        with self.lock:
            if not force and time.monotonic() - self.updated < 8: return
            with self.source() as db:
                paths = [r[0] for r in db.execute('SELECT DISTINCT source_message_db FROM messages') if r[0]]
            self.identity.refresh(paths)
            terminal = self.home / 'terminal.sqlite'
            if terminal.exists():
                with contextlib.closing(sqlite3.connect(terminal.as_uri() + '?mode=ro', uri=True)) as db:
                    db.row_factory = sqlite3.Row
                    self.directory = {r['username']: dict(r) for r in db.execute('SELECT * FROM directory')}
            self.files = [p for p in self.file_root.glob('**/*') if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(self.file_root)]
            self.updated = time.monotonic()

    def name(self, username, fallback=''):
        entry = self.directory.get(username, {})
        return entry.get('note') or entry.get('wx_remark') or self.identity.names.get(username) or entry.get('name') or fallback or username

    def attachment_path(self, metadata):
        name, size, expected = metadata['name'], metadata['size'], metadata.get('md5', '').lower()
        if expected and not re.fullmatch('[0-9a-f]{32}', expected): return None, False
        with self.lock:
            candidates = []
            for path in self.files:
                try:
                    if not path.resolve().is_relative_to(self.file_root): continue
                    stat = path.stat()
                    if size and stat.st_size != size: continue
                    if not expected and path.name != name: continue
                    if expected:
                        key = (str(path), stat.st_size, stat.st_mtime_ns)
                        digest = self.digests.get(key)
                        if digest is None:
                            md5 = hashlib.md5()
                            with path.open('rb') as f:
                                for chunk in iter(lambda: f.read(1024 * 1024), b''): md5.update(chunk)
                            digest = md5.hexdigest()
                            self.digests[key] = digest
                        if digest != expected: continue
                    candidates.append(path)
                except OSError:
                    continue
            if expected and candidates: return candidates[0], True
            return (candidates[0], False) if len(candidates) == 1 and size else (None, False)

    def media_path(self, uid):
        with self.source() as db:
            has_table = db.execute("SELECT 1 FROM sqlite_master WHERE name='message_media'").fetchone()
            row = db.execute('SELECT media_path,mime_type FROM message_media WHERE message_uid=?', (uid,)).fetchone() if has_table else None
        if row and row['media_path']:
            path = Path(row['media_path'])
            if not path.is_absolute(): path = self.media_root.parent / path
            path = path.resolve()
            mime = row['mime_type'] or mimetypes.guess_type(path.name)[0] or ''
            allowed = {'image/jpeg','image/png','image/gif','image/webp','audio/mpeg','audio/wav','audio/ogg','video/mp4'}
            if path.is_relative_to(self.media_root) and path.is_file() and mime in allowed:
                return path, mime
        return None, None

    def present(self, row):
        with self.source() as db:
            bridge = netdisk_metadata(db, row['message_uid'])
        if bridge:
            details = netdisk_sender_details(bridge)
            return dict(
                id=row['rowid'], uid=row['message_uid'], source='netdisk',
                chat_id=bridge['chat_id'], chat_name=bridge['chat_name'],
                sender_id=details['sender_id'], sender=details['sender_name'],
                outgoing=False, time=row['create_time'] or 0,
                kind='text', text=bridge.get('content') or '',
                payload=bridge, link_url=bridge.get('link_url'),
            )
        result = parse_content(row)
        sender = self.identity.sender(row)
        result.update(id=row['rowid'], uid=row['message_uid'], chat_id=row['chat_username'],
                      chat_name=self.name(row['chat_username'], row['chat_display_name']),
                      sender_id=sender, sender='微信系统' if result['kind']=='system' else self.name(sender, '未知发送者'),
                      outgoing=self.identity.outgoing(row), time=row['create_time'] or 0)
        result['source'] = 'wechat'
        if 'attachment' in result:
            path, verified = self.attachment_path(result['attachment'])
            result['attachment'].update(available=bool(path), verified=verified)
            result['attachment'].pop('md5', None)
        if result['kind'] in ('image','sticker','video','voice'):
            path, _ = self.media_path(row['message_uid'])
            result['media_available'] = bool(path)
            with self.source() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='message_media'").fetchone()
                state = db.execute('SELECT status FROM message_media WHERE message_uid=?', (row['message_uid'],)).fetchone() if exists else None
            result['media_status'] = 'ready' if path else state['status'] if state else 'pending'
        return result


def mount(app, store=None):
    store = store or DesktopStore()
    api = Blueprint('desktop', __name__, url_prefix='/api/terminal/desktop')

    @api.before_request
    def authorize():
        config = json.loads((store.home / 'config.json').read_text())
        if not hmac.compare_digest(request.headers.get('Authorization',''), 'Bearer ' + config['token']):
            return jsonify(error='未授权的连接'), 401

    @api.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @api.errorhandler(ValueError)
    def invalid(error): return jsonify(error=str(error)), 400

    @api.get('/status')
    def status():
        store.refresh()
        with store.source() as db:
            row = db.execute('SELECT count(*) AS n,count(DISTINCT chat_username) AS chats,max(create_time) AS latest,max(ingested_at) AS captured,max(rowid) AS cursor FROM messages').fetchone()
            files = db.execute('SELECT rowid,* FROM messages WHERE base_type=49 AND app_subtype=6').fetchall()
        available = sum(bool(store.attachment_path(parse_content(r)['attachment'])[0]) for r in files if 'attachment' in parse_content(r))
        return jsonify(version='0.1.0', messages=row['n'], conversations=row['chats'], latest_at=row['latest'] or 0,
                       captured_at=row['captured'], cursor=row['cursor'] or 0, file_messages=len(files), available_files=available,
                       self_name=store.name(store.identity.username))

    @api.get('/conversations')
    def conversations():
        store.refresh()
        with store.source() as db:
            rows = db.execute('''WITH ranked AS (SELECT rowid AS rid,*,
                row_number() OVER (PARTITION BY chat_username ORDER BY create_time DESC,rowid DESC) AS rank,
                count(*) OVER (PARTITION BY chat_username) AS total,
                sum(CASE WHEN base_type=49 AND app_subtype=6 THEN 1 ELSE 0 END) OVER (PARTITION BY chat_username) AS files
                FROM messages) SELECT rid AS rowid,* FROM ranked WHERE rank=1 ORDER BY create_time DESC,rid DESC''').fetchall()
            cursor = db.execute('SELECT coalesce(max(rowid),0) FROM messages').fetchone()[0]
        return jsonify(cursor=cursor, items=[dict(id=r['chat_username'], name=store.name(r['chat_username'],r['chat_display_name']),
            nickname=store.directory.get(r['chat_username'],{}).get('name') or r['chat_display_name'],
            is_group=r['chat_username'].endswith('@chatroom'), muted=store.directory.get(r['chat_username'],{}).get('muted')==1,
            count=r['total'], file_count=r['files'], last=store.present(r)) for r in rows])

    @api.get('/messages')
    def messages():
        store.refresh()
        limit = min(100, max(1, int(request.args.get('limit',80))))
        conditions, values = [], []
        for key, column in [('chat','chat_username')]:
            if request.args.get(key): conditions.append(column+'=?'); values.append(request.args[key])
        if request.args.get('q'):
            conditions.append('instr(lower(message_content),lower(?))>0'); values.append(request.args['q'][:300])
        if request.args.get('kind')=='file': conditions.append('base_type=49 AND app_subtype=6')
        if request.args.get('kind')=='media': conditions.append('base_type IN (3,34)')
        if request.args.get('ids'):
            ids = [int(value) for value in request.args['ids'].split(',')][:100]
            conditions.append('rowid IN ('+','.join('?' for _ in ids)+')'); values.extend(ids)
        if request.args.get('before'):
            timestamp, rid = map(int, request.args['before'].split(':'))
            conditions.append('(create_time<? OR (create_time=? AND rowid<?))'); values.extend([timestamp,timestamp,rid])
        after = request.args.get('after')
        if after is not None: conditions.append('rowid>?'); values.append(int(after))
        with store.source() as db:
            db.execute('BEGIN')
            maximum = db.execute('SELECT coalesce(max(rowid),0) FROM messages').fetchone()[0]
            conditions.append('rowid<=?'); values.append(maximum)
            order = 'rowid ASC' if after is not None else 'create_time DESC,rowid DESC'
            rows = db.execute('SELECT rowid,* FROM messages WHERE '+' AND '.join(conditions)+' ORDER BY '+order+' LIMIT ?',values+[limit+1]).fetchall()
        more=len(rows)>limit
        rows=rows[:limit]
        items=[store.present(r) for r in rows]
        if after is None: items.reverse()
        return jsonify(items=items, more=more, cursor=rows[-1]['rowid'] if after is not None and more else maximum,
                       before=f"{rows[-1]['create_time']}:{rows[-1]['rowid']}" if rows and after is None else None)

    def lookup(message_id):
        store.refresh(force=True)
        with store.source() as db:
            return db.execute('SELECT rowid,* FROM messages WHERE rowid=?',(message_id,)).fetchone()

    @api.get('/messages/<int:message_id>/file')
    def download(message_id):
        row=lookup(message_id)
        metadata=parse_content(row).get('attachment') if row else None
        if not metadata: return jsonify(error='文件消息不存在'),404
        path, verified=store.attachment_path(metadata)
        if not path: return jsonify(error='Linux 微信尚未下载此附件，或文件校验不匹配'),404
        filename=Path(metadata['name'].replace('\\','/')).name.replace('\r','').replace('\n','') or path.name
        return send_file(path,as_attachment=True,download_name=filename,mimetype='application/octet-stream',conditional=True)

    @api.get('/messages/<int:message_id>/media')
    def media(message_id):
        row=lookup(message_id)
        path,mime=store.media_path(row['message_uid']) if row else (None,None)
        if not path: return jsonify(error='没有可播放的本地媒体'),404
        return send_file(path,mimetype=mime,conditional=True,as_attachment=request.args.get('download')=='1')

    from send_api import mount as mount_send
    mount_send(api,store)
    app.register_blueprint(api)
    return store
