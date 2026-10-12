"""Explicit filehelper smoke test; connection and message settings come from environment."""
import base64
import json
import os
from pathlib import Path
import sys
import urllib.request
from urllib.parse import urlparse

root=Path(os.environ.get('DCP_SEND_STATE_DIR') or Path(os.environ.get('DCP_TERMINAL_HOME') or Path.home()/'dcp-terminal')/'send-state')
root.mkdir(parents=True,mode=0o700,exist_ok=True)
state=root/'smoke-test.json'
preview=root/'smoke-test-preview.png'
token=os.environ.get('DCP_API_TOKEN')
base=(os.environ.get('DCP_API_BASE') or 'http://127.0.0.1:8766/api/terminal').rstrip('/')
url=urlparse(base)
if not token or '\n' in token or '\r' in token:raise SystemExit('Set DCP_API_TOKEN in the environment')
if url.username or url.password or url.query or url.fragment or url.scheme not in ('http','https'):raise SystemExit('Use a plain HTTP(S) DCP_API_BASE')
if url.scheme!='https' and url.hostname not in ('localhost','127.0.0.1','::1'):raise SystemExit('Remote API requires HTTPS')
def request(action,body):
    req=urllib.request.Request(base+'/desktop/send/'+action,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=45) as response:return json.load(response)
def save_preview(result):
    image=result.pop('preview',None)
    if image:preview.write_bytes(base64.b64decode(image.split(',')[1]));os.chmod(preview,0o600)
if len(sys.argv)<2:raise SystemExit('Choose prepare, select, submit, status or cancel explicitly')
action=sys.argv[1]
if action not in ('prepare','select','submit','status','cancel'):raise SystemExit('Unknown send action')
if action=='prepare':
    result=request(action,{'chat':'filehelper','text':os.environ.get('DCP_SEND_TEST_TEXT') or 'InfoCenter file helper delivery smoke test'})
    save_preview(result)
    state.write_text(json.dumps(result));os.chmod(state,0o600)
else:
    result=request(action,dict(id=json.loads(state.read_text())['id'],**({'x':float(sys.argv[2]),'y':float(sys.argv[3])} if action=='select' else {})))
    save_preview(result)
print(json.dumps(result,ensure_ascii=False))
