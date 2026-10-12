"""Versioned cloud timetable using the existing authenticated terminal blueprint."""
import datetime
import json
import re
from flask import jsonify, request


def validate(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1: raise ValueError('课表格式版本错误')
    term=data.get('term',{})
    start,end=term.get('start_week'),term.get('end_week')
    if type(start)!=int or type(end)!=int or not 1<=start<=end<=60: raise ValueError('周次范围错误')
    if datetime.date.fromisoformat(term.get('week1_monday','')).weekday()!=0: raise ValueError('第一周起始日必须是周一')
    periods=data.get('periods',[])
    if len(periods)!=11: raise ValueError('需要十一节课的时间')
    previous=-1
    for index,row in enumerate(periods):
        if row.get('number')!=index+1: raise ValueError('节次顺序错误')
        values=[]
        for field in ('start','end'):
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(row.get(field,''))): raise ValueError('时间格式错误')
            hour,minute=map(int,row[field].split(':'));values.append(hour*60+minute)
        if not previous<=values[0]<values[1]: raise ValueError('节次重叠或倒置')
        previous=values[1]
    courses=data.get('courses')
    if not isinstance(courses,list) or len(courses)>500: raise ValueError('课程数量错误')
    ids=set()
    for row in courses:
        uid=row.get('id');name=row.get('name')
        if not isinstance(uid,str) or not uid or uid in ids or not isinstance(name,str) or not name.strip(): raise ValueError('课程名称或编号错误')
        ids.add(uid)
        if type(row.get('day'))!=int or not 1<=row['day']<=7: raise ValueError('星期错误')
        for field,lo,hi in [('weeks',start,end),('periods',1,11)]:
            values=row.get(field)
            if not isinstance(values,list) or not values or any(type(n)!=int or not lo<=n<=hi for n in values): raise ValueError('课程周次或节次错误')
    if len(json.dumps(data))>1024*1024: raise ValueError('课表过大')
    return data


def mount(api,store):
    @api.route('/timetable',methods=['GET','POST'])
    def timetable():
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cloud_timetable (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL)')
            if request.method=='POST': db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision,data FROM cloud_timetable WHERE id=1').fetchone()
            current={'revision':row['revision'],'data':json.loads(row['data'])} if row else {'revision':0,'data':None}
            if request.method=='GET': return jsonify(current)
            body=request.get_json(force=True)
            data=validate(body.get('data'))
            if body.get('revision')!=current['revision']:
                return jsonify(error='云端课表已有更新，本地编辑已保留，请选择要使用的版本',conflict=True,**current),409
            revision=current['revision']+1
            db.execute('INSERT INTO cloud_timetable VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,data=excluded.data',(revision,json.dumps(data,ensure_ascii=False)))
        return jsonify(revision=revision,data=data)
