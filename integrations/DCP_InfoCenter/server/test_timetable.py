import contextlib
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from flask import Flask,Blueprint
from timetable_api import mount

class Store:
    def __init__(self,path):self.path=path
    @contextlib.contextmanager
    def connect(self):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            db.row_factory=sqlite3.Row
            with db:yield db

class CloudTests(unittest.TestCase):
    def test_roundtrip_conflict_and_invalid_data(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Flask(__name__);api=Blueprint('test',__name__);mount(api,Store(Path(temp)/'state.sqlite'));app.register_blueprint(api)
            app.register_error_handler(ValueError,lambda e:({'error':str(e)},400))
            client=app.test_client()
            self.assertEqual(client.get('/timetable').json,{'revision':0,'data':None})
            data={'schema_version':1,'term':{'week1_monday':'2026-09-07','start_week':1,'end_week':20},'periods':[{'number':i+1,'start':f'{i+7:02}:00','end':f'{i+7:02}:45'} for i in range(11)],'courses':[{'id':'one','name':'数学','day':1,'weeks':[1,2],'periods':[1,2]}]}
            response=client.post('/timetable',json={'revision':0,'data':data})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['revision'],1)
            self.assertEqual(client.get('/timetable').json['data'],data)
            self.assertEqual(client.post('/timetable',json={'revision':0,'data':data}).status_code,409)
            bad=copy.deepcopy(data);bad['courses'][0]['day']=8
            self.assertEqual(client.post('/timetable',json={'revision':1,'data':bad}).status_code,400)
            self.assertEqual(client.get('/timetable').json['revision'],1)

if __name__=='__main__':unittest.main()
