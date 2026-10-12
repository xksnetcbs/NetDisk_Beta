import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from flask import Flask
from desktop_api import DesktopStore, mount, parse_content

class Identity:
    username='self'
    names={'self':'我','peer':'同学'}
    def refresh(self,paths): pass
    def sender(self,row): return 'self' if row['real_sender_id']==1 else 'peer'
    def outgoing(self,row): return self.sender(row)==self.username

class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.memory=self.root/'memory.sqlite';self.account=self.root/'account';self.files=self.account/'msg/file/2026-09';self.files.mkdir(parents=True)
        (self.root/'config.json').write_text(json.dumps({'token':'test-token'}))
        self.data=b'test attachment content'
        (self.files/'test.pdf').write_bytes(self.data)
        self.md5=hashlib.md5(self.data).hexdigest()
        with contextlib.closing(sqlite3.connect(self.memory)) as db, db:
            db.execute('CREATE TABLE messages(message_uid TEXT,chat_username TEXT,chat_display_name TEXT,source_message_db TEXT,real_sender_id INTEGER,create_time INTEGER,base_type INTEGER,app_subtype INTEGER,type_label TEXT,message_content TEXT,ingested_at TEXT)')
            for i in range(1,5):
                body='hello '+str(i);kind=1;sub=0
                if i==3:body=self.xml('test.pdf',self.md5);kind=49;sub=6
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?)',(str(i),'group@chatroom','测试群','shard',1 if i==2 else 2,100+i,kind,sub,'text',body,'2026-09-17T00:00:00+00:00'))
        self.store=DesktopStore(self.root,self.memory,self.account,Identity())
        app=Flask(__name__);app.testing=True;mount(app,self.store);self.client=app.test_client();self.headers={'Authorization':'Bearer test-token'}
    def tearDown(self):self.tmp.cleanup()
    def xml(self,name,md5):return f'<msg><appmsg><type>6</type><title>{name}</title><md5>{md5}</md5><appattach><totallen>{len(self.data)}</totallen><fileext>pdf</fileext></appattach></appmsg></msg>'
    def get(self,path):return self.client.get('/api/terminal/desktop'+path,headers=self.headers)
    def test_pagination_directions_and_download(self):
        self.assertEqual(self.client.get('/api/terminal/desktop/status').status_code,401)
        status=self.get('/status').json;self.assertEqual(status['available_files'],1)
        latest=self.get('/messages?chat=group@chatroom&limit=2').json
        self.assertEqual([r['id'] for r in latest['items']],[3,4]);self.assertTrue(latest['more'])
        history=self.get('/messages?chat=group@chatroom&before='+latest['before']).json
        self.assertEqual([r['id'] for r in history['items']],[1,2]);self.assertTrue(history['items'][1]['outgoing'])
        incoming=self.get('/messages?chat=group@chatroom&after=2').json
        self.assertEqual([r['id'] for r in incoming['items']],[3,4])
        response=self.get('/messages/3/file');self.assertEqual(response.data,self.data);self.assertIn('attachment;',response.headers['Content-Disposition']);response.close()
        self.assertEqual(self.get('/messages/1/file').status_code,404)
    def test_integrity_and_path_boundary(self):
        self.store.refresh()
        wrong={'name':'test.pdf','size':len(self.data),'md5':'0'*32}
        self.assertIsNone(self.store.attachment_path(wrong)[0])
        secret=self.root/'secret.pdf';secret.write_bytes(self.data)
        self.store.files=[secret]
        self.assertIsNone(self.store.attachment_path({'name':'secret.pdf','size':len(self.data),'md5':self.md5})[0])
    def test_links_and_no_raw_secrets(self):
        body='<msg><appmsg><type>5</type><title>标题</title><url>javascript:alert(1)</url><aeskey>PRIVATE</aeskey></appmsg></msg>'
        result=parse_content({'message_content':body,'base_type':49,'type_label':'app'})
        self.assertNotIn('url',result);self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('attachment',parse_content({'message_content':'invalid','base_type':49,'type_label':'app'}))

    def test_relative_media_path_and_escape(self):
        self.store.media_root=self.root/'runtime/media'
        self.store.media_root.mkdir(parents=True)
        voice=self.store.media_root/'voice.wav';voice.write_bytes(b'RIFFtest')
        with contextlib.closing(sqlite3.connect(self.memory)) as db, db:
            db.execute('CREATE TABLE message_media(message_uid TEXT,media_path TEXT,mime_type TEXT,status TEXT)')
            db.execute('INSERT INTO message_media VALUES(?,?,?,?)',('1','media/voice.wav','audio/wav','ready'))
        self.assertEqual(self.store.media_path('1'),(voice,'audio/wav'))
        with contextlib.closing(sqlite3.connect(self.memory)) as db, db:
            db.execute("UPDATE message_media SET media_path='../config.json'")
        self.assertEqual(self.store.media_path('1'),(None,None))

if __name__=='__main__':unittest.main()
