"""Audit compiled APK strings against upstream defaults without displaying secrets."""

import argparse
import base64
import re
from pathlib import Path
from zipfile import ZipFile

parser = argparse.ArgumentParser()
parser.add_argument("apk", type=Path)
parser.add_argument("--legacy-source", type=Path, required=True)
args = parser.parse_args()
source = args.legacy_source / "app/src/main/java/top/dcpstudios/calendarwidget"
defaults = (source / "TerminalDefaults.java").read_text(encoding="utf-8-sig")
legacy = (source / "LegacyConnection.java").read_text(encoding="utf-8-sig")
token = re.search(r'\bTOKEN\s*=\s*"([^"]+)"', defaults)
encoded = re.search(r'Base64\.decode\("([^"]+)"', legacy)
needles = []
if token:
    needles.append(token.group(1).encode())
if encoded:
    needles.append(encoded.group(1).encode())
    pair = base64.b64decode(encoded.group(1))
    needles.extend([pair, pair.split(b":", 1)[1]])
if not needles:
    raise SystemExit("Upstream credential patterns were not found; audit could not be performed")
with ZipFile(args.apk) as apk:
    dex = [apk.read(name) for name in apk.namelist() if name.endswith(".dex")]
found = sum(any(needle in content for content in dex) for needle in needles)
if found:
    raise SystemExit(f"FAIL: {found} upstream credential patterns found in compiled APK")
print(f"PASS: {len(needles)} upstream credential patterns absent from compiled APK")
