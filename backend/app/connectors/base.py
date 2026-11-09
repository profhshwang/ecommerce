"""사이트 connector 공통 인터페이스 (계획서 5.1절)."""
from __future__ import annotations

import os
from typing import ClassVar

import httpx

from ..models import Product, SearchStatus, SourceKind


class ConnectorError(Exception):
    """사이트 검색 실패. status는 계획서 40절의 오류 코드."""

    def __init__(self, status: SearchStatus, message: str = ""):
        super().__init__(message or status.value)
        self.status = status
        self.message = message


class ShoppingConnector:
    id: ClassVar[str]
    name: ClassVar[str]
    kind: ClassVar[SourceKind]
    #: 사용에 필요한 환경변수 (모두 설정되어야 활성화)
    required_env: ClassVar[tuple[str, ...]] = ()
    #: 사이트 설명 (설정 화면 표시용)
    note: ClassVar[str] = ""
    #: 한 번에 내부적으로 수집할 최대 개수 (계획서 10절: 사이트당 최대 100)
    max_results: int = 100
    timeout_sec: float = 15.0
    #: 확장 검색어 중 실제로 사용할 최대 개수 (요청량 제어)
    max_queries: int = 3
    #: 사용자가 직접 확인할 수 있는 검색 페이지 URL 템플릿 ({q}: URL 인코딩된 검색어)
    manual_search_url: ClassVar[str] = ""

    def manual_url(self, query: str) -> str:
        from urllib.parse import quote

        return self.manual_search_url.format(q=quote(query)) if self.manual_search_url else ""

    def is_configured(self) -> bool:
        return all(os.getenv(k) for k in self.required_env)

    def unavailable_reason(self) -> str:
        missing = [k for k in self.required_env if not os.getenv(k)]
        if missing:
            return "API 키가 설정되지 않았습니다: " + ", ".join(missing)
        return ""

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        raise NotImplementedError

    # ---- 공통 유틸 ----
    @staticmethod
    def raise_for_http(resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise ConnectorError(SearchStatus.AUTH_REQUIRED, f"HTTP {resp.status_code}: 인증 실패 또는 접근 거부")
        if resp.status_code == 429:
            raise ConnectorError(SearchStatus.API_LIMIT, "요청 한도 초과")
        if resp.status_code >= 400:
            raise ConnectorError(SearchStatus.UNAVAILABLE, f"HTTP {resp.status_code}")


def to_int_price(value) -> int:
    """'12,900원', 12900, '12900.0' 등을 정수 원으로."""
    if value is None:
        raise ValueError("price is None")
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
    if not digits:
        raise ValueError(f"invalid price: {value!r}")
    return int(float(digits))
