"""Process received image caches and SILK voice blobs; never send messages."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import wave

ROOT = Path(os.environ.get('DCP_CAPTURE_ROOT') or Path.home() / 'wechat-capture')
sys.path.insert(0, str(ROOT / 'app'))
from memory import media_sync as media
import pilk


def run():
    runtime = ROOT / 'runtime'
    config = runtime / 'wechat-decrypt/config.json'
    cfg = media.load_config(config)
    args = SimpleNamespace(runtime_dir=runtime, media_dir=runtime / 'media',
        wechat_base_dir=Path(cfg['db_dir']).parent, prefer_thumbnails=False)
    resource = media.load_resource_map(runtime / 'wechat-decrypt/decrypted/message/message_resource.db')
    memory = runtime / 'memory/wechat_memory.sqlite'
    voices = {}
    for path in (runtime / 'wechat-decrypt/decrypted/message').glob('media_*.db'):
        with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            for chat, server, local, stamp, blob in db.execute('SELECT n.user_name,v.svr_id,v.local_id,v.create_time,v.voice_data FROM VoiceInfo v JOIN Name2Id n ON n.rowid=v.chat_name_id'):
                voices[(chat, server, local, stamp)] = blob
    with contextlib.closing(sqlite3.connect(memory, timeout=15)) as db:
        db.row_factory = sqlite3.Row
        media.ensure_media_schema(db)
        rows = db.execute('SELECT m.* FROM messages m LEFT JOIN message_media mm USING(message_uid) WHERE m.base_type IN (3,34) AND (mm.status IS NULL OR mm.status != \'ready\') ORDER BY m.create_time DESC').fetchall()
        counts = {}
        for row in rows:
            item = dict(message_uid=row['message_uid'], chat_username=row['chat_username'], local_id=row['local_id'], media_type='image' if row['base_type']==3 else 'voice')
            try:
                if row['base_type'] == 3:
                    item = media.sync_image(row, args, resource, cfg)
                    # A thumbnail may use an older codec even when the full image needs a key.
                    if item['status'] == 'decode_failed':
                        args.prefer_thumbnails = True
                        item = media.sync_image(row, args, resource, cfg)
                        args.prefer_thumbnails = False
                    if item['status'] == 'decode_failed' and not cfg.get('image_aes_key'):
                        item.update(status='missing_key',error='V2 image key is not configured')
                else:
                    blob = voices.get((row['chat_username'],row['server_id'],row['local_id'],row['create_time']))
                    if blob is None:
                        blob = next((v for (c,s,l,t),v in voices.items() if c==row['chat_username'] and s and s==row['server_id']), None)
                    if not blob:
                        item.update(status='missing_file')
                    else:
                        base = args.media_dir / 'voice' / hashlib.sha256(row['message_uid'].encode()).hexdigest()
                        base.parent.mkdir(parents=True, exist_ok=True)
                        silk, pcm, target = base.with_suffix('.silk'), base.with_suffix('.pcm'), base.with_suffix('.wav')
                        try:
                            silk.write_bytes(blob)
                            pilk.decode(str(silk), str(pcm), pcm_rate=24000)
                            with wave.open(str(target), 'wb') as output:
                                output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                                output.writeframes(pcm.read_bytes())
                            item.update(status='ready',media_path=str(target),mime_type='audio/wav')
                        finally:
                            silk.unlink(missing_ok=True); pcm.unlink(missing_ok=True)
            except Exception as exc:
                item.update(status='decode_failed',error=type(exc).__name__)
            media.upsert_media(db,item,runtime)
            db.commit()
            counts[item['status']] = counts.get(item['status'],0)+1
        print(json.dumps(counts), flush=True)


if __name__ == '__main__':
    run()
