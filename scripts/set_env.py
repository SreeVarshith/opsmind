"""Set one variable in .env without touching the others.

Usage:  python scripts/set_env.py API_MODEL openai/gpt-oss-120b
"""
import re
import sys
from pathlib import Path

key, value = sys.argv[1], sys.argv[2]
path = Path(".env")
text = path.read_text(encoding="utf-8")
pattern = rf"(?m)^{re.escape(key)}=.*$"
text = re.sub(pattern, f"{key}={value}", text) if re.search(pattern, text) else text.rstrip("\n") + f"\n{key}={value}\n"
path.write_text(text, encoding="utf-8")
print(f"{key} updated in .env")
