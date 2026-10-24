"""LORE — Living Organizational Record Engine."""

import os
from pathlib import Path

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _key, _sep, _value = _line.partition("=")
        if _sep and not _line.lstrip().startswith("#") and _value.strip():
            os.environ.setdefault(_key.strip(), _value.strip())
