"""Run on the existing Linux server after copying this folder to the shared drive."""
import os
from pathlib import Path
import datetime
import shutil
import subprocess

code=Path(os.environ.get('DCP_TERMINAL_CODE_DIR') or Path.home()/'dcp-terminal-code')
backup=Path(os.environ.get('DCP_BACKUP_ROOT') or Path.home()/'dcp-terminal-backups')/('infocenter-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
shutil.copy2(code/'app.py',backup/'app.py')
if (code/'desktop_api.py').exists():shutil.copy2(code/'desktop_api.py',backup/'desktop_api.py')
shutil.copy2(Path(__file__).parent/'desktop_api.py',code/'desktop_api.py')
source=(code/'app.py').read_text()
if 'mount_desktop' not in source:
    source+='\nfrom desktop_api import mount as mount_desktop\nmount_desktop(app)\n'
    (code/'app.py').write_text(source)
subprocess.run(['systemctl','--user','restart',os.environ.get('DCP_TERMINAL_SERVICE') or 'dcp-terminal.service'],check=True)
print('Backup:',backup)
