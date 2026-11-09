"""환경변수 파일 로더. 다른 모듈보다 먼저 import 된다."""
from __future__ import annotations

import os
from pathlib import Path


def _load_env_file() -> None:
    """backend/.env.local 또는 .env 를 읽어 환경변수로 설정 (의존성 없이)."""
    base = Path(__file__).resolve().parent.parent
    for name in (".env.local", ".env"):
        f = base / name
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()
