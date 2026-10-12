"""Install a packaged frontend with deployment settings supplied by environment."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from urllib.parse import urlparse

parser=argparse.ArgumentParser()
parser.add_argument('--origin',default=os.environ.get('DCP_PUBLIC_ORIGIN') or 'http://127.0.0.1:5525')
args=parser.parse_args()
origin=urlparse(args.origin)
local=origin.hostname in ('localhost','127.0.0.1','::1')
if origin.scheme not in ('http','https') or origin.scheme!='https' and not local:
    raise SystemExit('Public origin must use HTTPS or localhost')
if not origin.netloc or origin.username or origin.password or origin.path not in ('','/') or origin.query or origin.fragment:
    raise SystemExit('Use an origin without credentials, query parameters or a path')
# Resolve credentials before creating or replacing any deployment files.
token=os.environ.get('DCP_API_TOKEN')
if not token or '\n' in token or '\r' in token:
    raise SystemExit('Set DCP_API_TOKEN in the environment')
api_base=os.environ.get('DCP_API_BASE') or 'http://127.0.0.1:8766/api/terminal'
upstream=urlparse(api_base)
if upstream.username or upstream.password or upstream.query or upstream.fragment or upstream.scheme not in ('http','https'):
    raise SystemExit('Use a plain HTTP(S) DCP_API_BASE without credentials')
if upstream.scheme!='https' and upstream.hostname not in ('localhost','127.0.0.1','::1'):
    raise SystemExit('Remote API requires HTTPS')
home=Path.home()
target=Path(os.environ.get('DCP_FRONTEND_DEPLOY_ROOT') or home/'dcp-infocenter')
state=Path(os.environ.get('DCP_FRONTEND_STATE_DIR') or home/'dcp-infocenter-state')
state.mkdir(mode=0o700,parents=True,exist_ok=True)
if (target/'server').exists():
    backup=Path(os.environ.get('DCP_BACKUP_ROOT') or home/'dcp-terminal-backups')/('frontend-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copytree(target,backup)
    print('Existing deployment backed up.')
archive=Path(os.environ.get('DCP_FRONTEND_ARCHIVE') or Path(__file__).parent/'DCP-InfoCenter-device-verified.zip')
with tempfile.TemporaryDirectory(prefix='dcp-frontend-') as directory:
    temp=Path(directory)
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            if not (temp/item.filename).resolve().is_relative_to(temp.resolve()):
                raise SystemExit('Invalid package path')
        package.extractall(temp)
    shutil.copytree(temp/'DCP-InfoCenter-device-verified',target,dirs_exist_ok=True)
environment=Path(os.environ.get('DCP_FRONTEND_ENV_FILE') or home/'.config/dcp-infocenter.env')
environment.parent.mkdir(parents=True,exist_ok=True)
values={'PORT':str(origin.port or (443 if origin.scheme=='https' else 80)),
        'DCP_PUBLIC_ORIGIN':args.origin.rstrip('/'),'DCP_API_BASE':api_base,
        'DCP_API_TOKEN':token,'DCP_DEVICE_STORE':str(state/'devices.json')}
# The local listener can use a separate port when a reverse proxy terminates HTTPS.
values['PORT']=os.environ.get('DCP_FRONTEND_PORT') or '5525'
environment.write_text('\n'.join(key+'='+json.dumps(value) for key,value in values.items())+'\n')
os.chmod(environment,0o600)
node=shutil.which('node')
if not node: raise SystemExit('Node.js missing')
unit=home/'.config/systemd/user/dcp-infocenter.service'
unit.parent.mkdir(parents=True,exist_ok=True)
unit.write_text(f'''[Unit]
Description=DCP InfoCenter device-verified frontend
After=network-online.target

[Service]
Type=simple
WorkingDirectory={target}
EnvironmentFile={environment}
ExecStart={node} {target}/server/gateway.mjs
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
''')
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','dcp-infocenter.service'],check=True)
subprocess.run(['systemctl','--user','restart','dcp-infocenter.service'],check=True)
print('Frontend installed using the supplied deployment configuration.')
