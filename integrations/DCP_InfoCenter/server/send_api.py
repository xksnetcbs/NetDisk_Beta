import json
from pathlib import Path
import subprocess
import base64
import tempfile
import os
import shutil
from flask import jsonify,request

def mount(api,store):
    @api.get('/send/capabilities')
    def capabilities():
        runtime = Path(os.environ.get('DCP_CAPTURE_ROOT') or Path.home()/'wechat-capture')
        python = Path(os.environ.get('DCP_CAPTURE_PYTHON') or runtime/'venv/bin/python')
        controller = runtime/'app/agent_console/wechat_controller.py'
        display = os.environ.get('DCP_WECHAT_DISPLAY') or os.environ.get('DISPLAY') or ':99'
        authority = Path(os.environ.get('XAUTHORITY') or runtime/'runtime/Xauthority')
        socket = Path('/tmp/.X11-unix')/('X'+display.rsplit(':',1)[-1].split('.')[0])
        available = all(path.is_file() for path in (python, controller, authority, runtime/'runtime/memory/wechat_memory.sqlite',
            Path(__file__).parent/'wechat_sender.py', Path(__file__).parent/'direct_sender.py', Path(__file__).parent/'sender_identity.py'))
        available = available and socket.exists() and all(shutil.which(name) for name in ('scrot','tesseract','xclip','xdotool'))
        if available:
            script = "import sys,json;sys.path.insert(0,sys.argv[1]);import wechat_controller as ui;print(json.dumps({'ok':bool(ui.find_main_window())}))"
            environment = dict(os.environ, DISPLAY=display, XAUTHORITY=str(authority))
            try:
                result = subprocess.run([str(python),'-c',script,str(controller.parent)],env=environment,text=True,capture_output=True,timeout=8)
                available = result.returncode == 0 and json.loads(result.stdout).get('ok') is True
            except (OSError, ValueError, subprocess.TimeoutExpired):
                available = False
        return jsonify(available=bool(available), targets=['filehelper'] if available else [])

    def call(body):
        try:
            proc=subprocess.run([str(Path(os.environ.get('DCP_CAPTURE_PYTHON') or Path(os.environ.get('DCP_CAPTURE_ROOT') or Path.home()/'wechat-capture')/'venv/bin/python')),str(Path(__file__).parent/'wechat_sender.py')],input=json.dumps(body),text=True,capture_output=True,timeout=35)
        except subprocess.TimeoutExpired:
            raise ValueError('操作超时，请检查发送状态；不要重复发送')
        try:result=json.loads(proc.stdout)
        except ValueError:raise ValueError('微信发送控制器不可用')
        if proc.returncode or 'error' in result:raise ValueError(result.get('error','发送操作失败'))
        return result

    @api.post('/send/prepare')
    def prepare():
        body=request.get_json(force=True);chat=body.get('chat')
        if isinstance(chat,str) and chat.startswith('netdisk:'):
            raise ValueError('站内会话只能通过 NetDisk 站内消息接口回复')
        store.refresh()
        if chat=='filehelper': name='文件传输助手'
        else:
            entry=store.directory.get(chat)
            if not entry:raise ValueError('请从已有联系人或群聊中选择收件人')
            name=entry.get('wx_remark') or entry.get('name')
            if not name:raise ValueError('没有可用于微信搜索的会话名称')
            if str(name).strip().lower() == str(chat).strip().lower() or str(name).strip().lower().endswith('@chatroom'):
                raise ValueError('该会话没有群名，无法安全定位，不允许发送')
            matches=[item for item in store.directory.values() if (item.get('wx_remark') or item.get('name') or '').strip()==str(name).strip()]
            if len(matches)>1:raise ValueError('存在同名联系人或群聊，请先在微信中设置唯一备注')
        attachment=body.get('attachment') or None
        if attachment:
            if not isinstance(attachment,dict) or not attachment.get('data') or len(attachment['data'])>28*1024*1024: raise ValueError('附件格式或大小不符合要求')
            try: base64.b64decode(attachment['data'],validate=True)
            except Exception: raise ValueError('附件编码无效')
        return jsonify(call(dict(action='send',id=body.get('id',''),chat=chat,name=name,text=body.get('text',''),attachment=attachment)))

    @api.post('/send/<action>')
    def send(action):
        if action not in ('select','submit','cancel','status'):raise ValueError('无效发送操作')
        body=request.get_json(force=True)
        return jsonify(call(dict(action=action,id=body.get('id',''),x=body.get('x'),y=body.get('y'))))
