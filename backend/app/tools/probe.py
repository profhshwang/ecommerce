"""사이트별 스크래핑 진단 도구.

사용법 (backend 폴더에서):
    python -m app.tools.probe "삼성 USB-C 케이블"

각 사이트 검색 페이지를 1회씩 요청해 상태·추출 건수·첫 상품을 출력하고,
받은 HTML을 backend/probe/<사이트>.html 로 저장한다.
파싱이 실패한 사이트는 이 HTML 파일을 보고 선택자를 보정한다.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

os.environ.setdefault("PROBE_DIR", str(Path(__file__).resolve().parents[2] / "probe"))
os.environ.setdefault("SCRAPE_MIN_INTERVAL_SEC", "1")

from .. import config  # noqa: E402,F401
from ..connectors import CONNECTOR_CLASSES, ConnectorError  # noqa: E402


async def main(query: str) -> None:
    async with httpx.AsyncClient() as client:
        for cls in CONNECTOR_CLASSES:
            c = cls()
            try:
                items = await c.search(query, client)
                first = items[0]
                print(f"[OK]   {c.name:6s} {len(items):3d}건 | {first.name[:40]} | {first.price:,}원 | {first.shipping.describe()}")
            except ConnectorError as e:
                print(f"[FAIL] {c.name:6s} {e.status.value} | {e.message}")
            except Exception as e:  # noqa: BLE001
                print(f"[ERR]  {c.name:6s} {type(e).__name__}: {e}")
    print(f"\nHTML 저장 위치: {os.environ['PROBE_DIR']}")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "삼성 USB-C 케이블"))
