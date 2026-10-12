"""Serialized UI sending with explicit preview and durable, non-replayed receipts."""
import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time
from PIL import Image

root=Path(os.environ.get('DCP_CAPTURE_ROOT') or Path.home()/'wechat-capture')
os.environ['DISPLAY']=os.environ.get('DCP_WECHAT_DISPLAY') or os.environ.get('DISPLAY') or ':99'
os.environ['XAUTHORITY']=os.environ.get('XAUTHORITY') or str(root/'runtime/Xauthority')
sys.path.insert(0,str(root/'app/agent_console'))
import wechat_controller as ui
state=Path(os.environ.get('DCP_SEND_STATE_DIR') or Path(os.environ.get('DCP_TERMINAL_HOME') or Path.home()/'dcp-terminal')/'send-state')
state.mkdir(mode=0o700,exist_ok=True)

def picture(window):
    path=state/'preview.png'
    subprocess.run(['scrot','--overwrite',str(path)],env=os.environ,check=True,capture_output=True,timeout=8)
    with Image.open(path) as shot:
        x,y,w,h=(int(window[k]) for k in ('x','y','width','height'))
        crop=shot.crop((x,y,x+w,y+h)).convert('RGB')
    header=crop.crop((min(340,w//2),0,w-50,85))
    digest=hashlib.sha256(header.tobytes()).hexdigest()
    output=io.BytesIO();crop.save(output,format='PNG')
    return digest,base64.b64encode(output.getvalue()).decode()

def invoke(body):
    with (root/'runtime/send.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with contextlib.closing(sqlite3.connect(state/'receipts.sqlite')) as db:
            db.row_factory=sqlite3.Row
            db.execute('CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, chat TEXT, body TEXT, window TEXT, header TEXT, created REAL, status TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY, after_row INTEGER)')
            action=body['action']
            if action=='send':
                from direct_sender import send
                return send(body,db,ui,state,root)
            if action=='prepare':
                if db.execute("SELECT 1 FROM drafts WHERE status IN ('prepared','searching') AND created>?",(time.time()-180,)).fetchone():
                    raise ValueError('另一个草稿等待确认，请取消或等待三分钟')
                text=body.get('text','');chat=body.get('chat','');name=body.get('name','')
                if not isinstance(text,str) or not text.strip() or len(text)>4000 or '\x00' in text: raise ValueError('消息长度应为 1—4000 字符')
                if not chat or not name: raise ValueError('缺少收件人')
                window=ui.find_main_window();ui.activate(window)
                ui.key('Escape');ui.click(window,*ui.search_box_point(window))
                ui.clear_focused_text();ui.paste_text(name);time.sleep(1)
                header,preview=picture(window)
                uid=secrets.token_urlsafe(24)
                db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?)',(uid,chat,text,json.dumps(window),header,time.time(),'searching'));db.commit()
                return dict(id=uid,preview='data:image/png;base64,'+preview,recipient=name,status='searching')
            uid=body.get('id','')
            row=db.execute('SELECT * FROM drafts WHERE id=?',(uid,)).fetchone()
            if not row: raise ValueError('草稿不存在')
            if action=='status':
                if row['status'] in ('submitted','uncertain'):
                    checkpoint=db.execute('SELECT after_row FROM checkpoints WHERE id=?',(uid,)).fetchone()
                    if checkpoint:
                        from sender_identity import SenderIdentity
                        memory=root/'runtime/memory/wechat_memory.sqlite'
                        with contextlib.closing(sqlite3.connect(memory.as_uri()+'?mode=ro',uri=True)) as source:
                            source.row_factory=sqlite3.Row
                            matches=source.execute('SELECT rowid,* FROM messages WHERE rowid>? AND chat_username=? AND message_content=?',(checkpoint[0],row['chat'],row['body'])).fetchall()
                        identity=SenderIdentity(memory)
                        identity.refresh([r['source_message_db'] for r in matches if r['source_message_db']])
                        if any(identity.outgoing(r) for r in matches):
                            db.execute("UPDATE drafts SET status='confirmed' WHERE id=?",(uid,));db.commit()
                            return dict(id=uid,status='confirmed')
                return dict(id=uid,status=row['status'])
            if action=='cancel':
                if row['status'] in ('prepared','searching'):db.execute("UPDATE drafts SET status='cancelled' WHERE id=?",(uid,));db.commit()
                return dict(status='cancelled' if row['status'] in ('prepared','searching') else row['status'])
            if action=='select':
                if row['status']!='searching' or time.time()-row['created']>180:raise ValueError('收件人选择已过期，请取消后重试')
                window=json.loads(row['window']);actual=ui.find_main_window()
                if any(actual[k]!=window[k] for k in ('window_id','x','y','width','height')):raise ValueError('微信窗口发生变化，请取消后重试')
                x=int(float(body.get('x',-1))*window['width']);y=int(float(body.get('y',-1))*window['height'])
                if not (70<x<min(420,window['width']*.5) and 70<y<window['height']-20):raise ValueError('请点选左侧搜索结果中的联系人')
                ui.activate(window);ui.click(window,x,y);time.sleep(1)
                ui.paste_active(row['body'],False,0)
                header,preview=picture(window)
                db.execute("UPDATE drafts SET status='prepared',header=?,created=? WHERE id=?",(header,time.time(),uid));db.commit()
                return dict(id=uid,preview='data:image/png;base64,'+preview,status='prepared')
            if action!='submit':raise ValueError('无效发送操作')
            if row['status']!='prepared':return dict(id=uid,status=row['status'])
            if time.time()-row['created']>180:raise ValueError('预览已过期，请重新准备草稿')
            window=json.loads(row['window']);actual=ui.find_main_window()
            if any(actual[k]!=window[k] for k in ('window_id','x','y','width','height')):raise ValueError('微信窗口发生变化，请重新准备')
            ui.activate(window)
            header,_=picture(window)
            if header!=row['header']:raise ValueError('当前聊天标题已变化，已阻止发送')
            # Focus only the same input area and verify the unchanged draft.
            ui.click(window,max(80,int(window['width']*.57)),max(120,window['height']-70))
            if not ui.verify_focused_text(row['body'])['ok']:raise ValueError('输入框草稿已变化，已阻止发送')
            with contextlib.closing(sqlite3.connect((root/'runtime/memory/wechat_memory.sqlite').as_uri()+'?mode=ro',uri=True)) as source:
                before=source.execute('SELECT coalesce(max(rowid),0) FROM messages').fetchone()[0]
            # Commit the receipt before the UI action. An uncertain result is never replayed.
            db.execute("UPDATE drafts SET status='submitted' WHERE id=?",(uid,));db.commit()
            db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?)',(uid,before));db.commit()
            ui.key('Return')
            return dict(id=uid,status='submitted',after=before,chat=row['chat'])

if __name__=='__main__':
    try: print(json.dumps(invoke(json.load(sys.stdin)),ensure_ascii=False))
    except Exception as exc: print(json.dumps({'error':str(exc)},ensure_ascii=False));sys.exit(1)
