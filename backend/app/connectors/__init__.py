"""Connector 레지스트리.

CONNECTOR_MODE (환경변수)
  scrape (기본) : 공개 검색 페이지 스크래핑
  api           : 공식 API (키 필요, 없는 사이트는 사용 불가 표시)
  auto          : 공식 API 키가 있으면 API, 없으면 스크래핑
DEMO_MODE=1 이면 모든 사이트를 가상 데이터로 대체한다.
"""
from __future__ import annotations

import os

from .base import ConnectorError, ShoppingConnector
from .coupang import CoupangConnector
from .demo import DemoConnector
from .domeggook import DomeggookConnector, DomemaeConnector
from .elevenst import ElevenstConnector
from .naver import NaverShoppingConnector
from .scrapers import (
    CoupangScraper,
    DomeggookScraper,
    DomemaeScraper,
    ElevenstScraper,
    GmarketScraper,
    NaverShoppingScraper,
    OwnerclanScraper,
)
from .unavailable import GmarketConnector, OwnerclanConnector

# (스크래핑 connector, 공식 API connector) — 화면 표시 순서
SITES: list[tuple[type[ShoppingConnector], type[ShoppingConnector]]] = [
    (DomeggookScraper, DomeggookConnector),
    (DomemaeScraper, DomemaeConnector),
    (OwnerclanScraper, OwnerclanConnector),
    (CoupangScraper, CoupangConnector),
    (NaverShoppingScraper, NaverShoppingConnector),
    (GmarketScraper, GmarketConnector),
    (ElevenstScraper, ElevenstConnector),
]
CONNECTOR_CLASSES = [s for s, _ in SITES]


def demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes", "on")


def connector_mode() -> str:
    return os.getenv("CONNECTOR_MODE", "scrape").lower()


def build_connectors() -> dict[str, ShoppingConnector]:
    if demo_mode():
        return {s.id: DemoConnector(s) for s, _ in SITES}
    mode = connector_mode()
    out: dict[str, ShoppingConnector] = {}
    for scraper, api in SITES:
        if mode == "api":
            c = api()
        elif mode == "auto":
            c = api() if api().is_configured() else scraper()
        else:
            c = scraper()
        out[c.id] = c
    return out


__all__ = ["ConnectorError", "ShoppingConnector", "CONNECTOR_CLASSES", "build_connectors", "demo_mode", "connector_mode"]
