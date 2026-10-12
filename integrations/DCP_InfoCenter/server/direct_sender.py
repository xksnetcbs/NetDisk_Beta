"""Locate an exact visible recipient before sending, without a confirmation dialog."""
import base64
import contextlib
import csv
import io
import json
import re
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path
from PIL import Image

def normalized(text):
    return re.sub(r'\s+', '', text).casefold()

def lines(ui, window, state, box, *, snapshot=None, green=False, bounds=False, title=False):
    shot=state/'locate.png'
    if snapshot is None:
        subprocess.run(['scrot','--overwrite',str(shot)],check=True,capture_output=True,timeout=5)
    else:shot=Path(snapshot)
    x,y=int(window['x']),int(window['y'])
    with Image.open(shot) as image:
        left,top=max(0,x+box[0]),max(0,y+box[1])
        right,bottom=min(image.width,x+box[2]),min(image.height,y+box[3])
        if right<=left or bottom<=top:return []
        crop=image.crop((left,top,right,bottom)).convert('RGB')
        if title:
            mask=Image.new('L',crop.size,255)
            mask.putdata([0 if r<180 and max(r,g,b)-min(r,g,b)<10 else 255 for r,g,b in crop.getdata()])
            crop=mask
        if green:
            # Search matches are green; avatars and trailing info/bell icons are not names.
            mask=Image.new('L',crop.size,255)
            mask.putdata([0 if g-r>20 and g-b>20 and g-r>(b-r)*1.7 else 255 for r,g,b in crop.getdata()])
            # Tiny colored accents on the adjacent notification icon are not glyphs.
            pixels=mask.load()
            # Connected components, keeping small dot components aligned with a tall glyph.
            seen=set();components=[]
            for yy in range(mask.height):
                for xx in range(mask.width):
                    if pixels[xx,yy]!=0 or (xx,yy) in seen:continue
                    stack=[(xx,yy)];seen.add((xx,yy));points=[]
                    while stack:
                        px,py=stack.pop();points.append((px,py))
                        for nx,ny in ((px-1,py),(px+1,py),(px,py-1),(px,py+1),(px-1,py-1),(px+1,py+1),(px-1,py+1),(px+1,py-1)):
                            if 0<=nx<mask.width and 0<=ny<mask.height and pixels[nx,ny]==0 and (nx,ny) not in seen:
                                seen.add((nx,ny));stack.append((nx,ny))
                    components.append(points)
            tall=[(min(x for x,y in pts),max(x for x,y in pts),min(y for x,y in pts),max(y for x,y in pts)) for pts in components if max(y for x,y in pts)-min(y for x,y in pts)>=7]
            for pts in components:
                if max(y for x,y in pts)-min(y for x,y in pts)>=7:continue
                if any(l<=x<=r and t-6<=y<=b+6 for x,y in pts for l,r,t,b in tall):continue
                for px,py in pts:pixels[px,py]=255
            crop=mask
        crop.resize((crop.width*2,crop.height*2)).save(state/'ocr.png')
    proc=subprocess.run(['tesseract',str(state/'ocr.png'),'stdout','-l','chi_sim+eng','--psm','6','tsv'],capture_output=True,text=True,timeout=8,check=True)
    groups={}
    # Tesseract TSV text is literal, not CSV-quoted (a recognized quote must not swallow rows).
    for row in csv.DictReader(io.StringIO(proc.stdout),delimiter='\t',quoting=csv.QUOTE_NONE):
        if row.get('level')!='5' or not row.get('text','').strip():continue
        groups.setdefault((row['block_num'],row['par_num'],row['line_num']),[]).append(row)
    result=[]
    for rows in groups.values():
        left=min(int(r['left']) for r in rows);top=min(int(r['top']) for r in rows)
        right=max(int(r['left'])+int(r['width']) for r in rows);bottom=max(int(r['top'])+int(r['height']) for r in rows)
        value=(''.join(r['text'] for r in rows),max(box[0],-x)+(left+right)/4,max(box[1],-y)+(top+bottom)/4)
        result.append(value+(max(box[0],-x)+left/2,) if bounds else value)
    return result

def recipient_candidates(ui,window,state,name,snapshot,*,filehelper=False):
    width,height=int(window['width']),int(window['height'])
    # Local recipient names start after the avatar at x=135. Web suggestions
    # start at x=113; "find WeChat ID" starts much farther right. Search order varies.
    rows=lines(ui,window,state,(133,78,min(375,width//2),height-30),snapshot=snapshot,green=True,bounds=True)
    history_start=None
    if filehelper and normalized(name)==normalized('文件传输助手'):
        # The history shortcut can repeat the exact name well below its section
        # label. Restrict the built-in helper only using the same captured frame;
        # never choose an arbitrary first match among real contacts.
        sections=lines(ui,window,state,(80,62,min(375,width//2),height-30),snapshot=snapshot)
        history=[row[2] for row in sections if re.fullmatch(r'聊天记录(?:[（(]\d+[)）])?',normalized(row[0]))]
        if history:history_start=min(history)
    candidates=[]
    for row in rows:
        if not (134<=row[3]<=142 and normalized(row[0])==normalized(name)):continue
        if history_start is not None and row[2]>=history_start:continue
        # A history-search shortcut repeats the name but is not a recipient.
        labels=lines(ui,window,state,(80,max(62,int(row[2]-65)),230,int(row[2]-18)),snapshot=snapshot)
        if any('聊天记录' in text for text,_,_ in labels):continue
        candidates.append(row[:3])
    return candidates

def locate(ui,window,state,name,*,filehelper=False):
    ui.activate(window);ui.key('Escape');ui.click(window,*ui.chat_tab_point(window));time.sleep(.15)
    ui.click(window,*ui.search_box_point(window));ui.clear_focused_text();ui.paste_text(name);time.sleep(.9)
    width,height=int(window['width']),int(window['height'])
    shot=state/'locate.png'
    subprocess.run(['scrot','--overwrite',str(shot)],check=True,capture_output=True,timeout=5)
    candidates=recipient_candidates(ui,window,state,name,shot,filehelper=filehelper)
    if not candidates:raise ValueError('未能识别微信搜索结果中的目标会话，未发送，请稍后重试')
    if len(candidates)>1:raise ValueError('微信搜索结果中检测到多个同名会话，未发送')
    _,x,y=candidates[0];ui.click(window,int(x),int(y));time.sleep(.65)
    titles=lines(ui,window,state,(285,22,width-65,72),title=True)
    def title_name(text):return normalized(re.sub(r'[（(]\d+[)）]$','',text))
    if not any(title_name(row[0])==normalized(name) for row in titles):
        raise ValueError('微信聊天标题与收件人不一致，未发送')

def send(body,db,ui,state,root):
    uid=body.get('id')
    if not isinstance(uid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',uid):raise ValueError('缺少有效发送请求编号')
    text=body.get('text','');attachment=body.get('attachment');chat=body.get('chat');name=body.get('name')
    if not isinstance(text,str) or len(text)>4000 or '\x00' in text or (not text.strip() and not attachment):raise ValueError('请输入消息或选择附件')
    if not chat or not name or name.endswith('@chatroom'):raise ValueError('缺少可识别的收件人名称')
    previous=db.execute('SELECT status,chat,body FROM drafts WHERE id=?',(uid,)).fetchone()
    if previous:
        if previous['chat']!=chat or previous['body']!=text:raise ValueError('请求编号已用于其它消息')
        return dict(id=uid,status=previous['status'])
    path=None
    if attachment:
        data=base64.b64decode(attachment['data'],validate=True)
        if len(data)>20*1024*1024:raise ValueError('附件不能超过20MB')
        folder=state/'uploads'/secrets.token_hex(12);folder.mkdir(parents=True,mode=0o700)
        filename=Path(str(attachment.get('name','')).replace('\\','/')).name
        if filename in ('','.','..') or any(ord(c)<32 for c in filename):raise ValueError('附件名称无效')
        path=folder/filename
        if attachment.get('type','').startswith('image/'):
            path=folder/'image.png'
            with Image.open(io.BytesIO(data)) as image:image.convert('RGBA').save(path)
        else:path.write_bytes(data)
    window=ui.find_main_window();locate(ui,window,state,name,filehelper=chat=='filehelper' and normalized(name)==normalized('文件传输助手'))
    with contextlib.closing(sqlite3.connect((root/'runtime/memory/wechat_memory.sqlite').as_uri()+'?mode=ro',uri=True)) as memory:
        before=memory.execute('SELECT coalesce(max(rowid),0) FROM messages').fetchone()[0]
    # Persist before any send key; uncertain actions must never be replayed.
    db.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?,?)',(uid,chat,text,json.dumps(window),'',time.time(),'uncertain'))
    db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?)',(uid,before));db.commit()
    if path:
        ui.click(window,max(80,int(window['width']*.57)),max(120,window['height']-70));ui.clear_focused_text()
        if attachment.get('type','').startswith('image/'):ui.paste_image(str(path))
        else:
            subprocess.run(['xclip','-selection','clipboard','-target','text/uri-list'],input=path.as_uri()+'\r\n',text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=5)
            ui.key('ctrl+v');time.sleep(.8)
        ui.key('Return');time.sleep(.6)
    if text.strip():ui.paste_active(text,True,0)
    db.execute("UPDATE drafts SET status='submitted' WHERE id=?",(uid,));db.commit()
    return dict(id=uid,status='submitted',chat=chat)
