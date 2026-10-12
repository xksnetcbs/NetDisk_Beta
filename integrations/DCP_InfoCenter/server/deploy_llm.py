"""Deploy the reviewed request-only change without overwriting intervening edits."""
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

stage=Path(__file__).parent
target=Path(os.environ.get('DCP_TERMINAL_CODE_DIR') or Path.home()/'dcp-terminal-code')/'terminal_backend.py'
if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256((Path(os.environ.get('DCP_DEPLOY_BASELINE_DIR') or stage)/'terminal_backend.live.py').read_bytes()).digest():
    raise SystemExit('Backend changed since inspection; deployment stopped')
backup=Path(os.environ.get('DCP_BACKUP_ROOT') or Path.home()/'dcp-terminal-backups')/('no-thinking-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
shutil.copy2(target,backup/target.name)
shutil.copy2(stage/'terminal_backend.py',target)
subprocess.run(['systemctl','--user','restart',os.environ.get('DCP_TERMINAL_SERVICE') or 'dcp-terminal.service'],check=True)
print('Deployed no-thinking request policy. Backup:',backup)
