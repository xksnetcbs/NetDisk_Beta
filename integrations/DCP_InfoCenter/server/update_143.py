"""Update existing backend source, preserving a recoverable backup."""
import os
from pathlib import Path
import datetime
import shutil
import subprocess

stage=Path(__file__).parent
code=Path(os.environ.get('DCP_TERMINAL_CODE_DIR') or Path.home()/'dcp-terminal-code')
for name in ('terminal_backend','desktop_api'):
    if (code/(name+'.py')).read_bytes()!=(Path(os.environ.get('DCP_DEPLOY_BASELINE_DIR') or stage)/(name+'.current.py')).read_bytes():raise SystemExit(name+' changed after inspection')
backup=Path(os.environ.get('DCP_BACKUP_ROOT') or Path.home()/'dcp-terminal-backups')/('v143-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
for name in ('terminal_backend.py','desktop_api.py','timetable_api.py','send_api.py','wechat_sender.py'):
    if (code/name).exists():shutil.copy2(code/name,backup/name)
    shutil.copy2(stage/name,code/name)
subprocess.run(['systemctl','--user','restart',os.environ.get('DCP_TERMINAL_SERVICE') or 'dcp-terminal.service'],check=True)
print('Backend updated; backup:',backup)
