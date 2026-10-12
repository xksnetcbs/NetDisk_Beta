"""One-shot, read-only scan of this user's WeChat process for a cache-validated image key."""
import collections
import json
import os
from pathlib import Path
import re
import sys
import time
from Crypto.Cipher import AES

root = Path(os.environ.get('DCP_CAPTURE_ROOT') or Path.home() / 'wechat-capture')
config_path = root / 'runtime/wechat-decrypt/config.json'
config = json.loads(config_path.read_text())
account = Path(config['db_dir']).parent
samples = []
tails = collections.Counter()
for path in sorted((account/'msg/attach').glob('*/*/Img/*_t.dat'), key=lambda p:p.stat().st_mtime, reverse=True)[:80]:
    data = path.read_bytes()
    if data[:6] == b'\x07\x08V2\x08\x07' and len(data)>31:
        if data[15:31] not in samples: samples.append(data[15:31])
        if data[-2]^0xff == data[-1]^0xd9: tails[data[-1]^0xd9]+=1
samples = samples[:8]
if not samples:
    print('No V2 samples'); sys.exit(0)
pattern = re.compile(rb'(?<![a-zA-Z0-9])(?:[a-zA-Z0-9]{32}|[a-zA-Z0-9]{16})(?![a-zA-Z0-9])')
seen = set()
deadline = time.monotonic()+60
found = None
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit(): continue
    try:
        if proc.stat().st_uid != account.stat().st_uid: continue
        if 'wechat' not in (proc/'comm').read_text().lower() and 'weixin' not in (proc/'comm').read_text().lower(): continue
        with (proc/'mem').open('rb',buffering=0) as memory:
            for line in (proc/'maps').read_text().splitlines():
                parts = line.split()
                if not parts[1].startswith('rw'): continue
                start,end = (int(x,16) for x in parts[0].split('-'))
                for offset in range(start,end,4*1024*1024):
                    if time.monotonic()>deadline: break
                    try:
                        memory.seek(offset)
                        data = memory.read(min(4*1024*1024+32,end-offset))
                    except OSError: continue
                    for match in pattern.finditer(data):
                        key = match.group()[:16]
                        if key in seen: continue
                        seen.add(key)
                        cipher=AES.new(key,AES.MODE_ECB)
                        if any(cipher.decrypt(block).startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n',b'GIF89a',b'GIF87a',b'wxgf')) for block in samples):
                            found=key; break
                    if found: break
                if found or time.monotonic()>deadline: break
    except (OSError,PermissionError): continue
    if found or time.monotonic()>deadline: break
if found:
    # Update only the two media fields; do not print secrets or process memory.
    config=json.loads(config_path.read_text())
    config['image_aes_key']=found.decode('ascii')
    if tails: config['image_xor_key']=tails.most_common(1)[0][0]
    config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2))
print(json.dumps({'found':bool(found),'candidates_checked':len(seen)}))
