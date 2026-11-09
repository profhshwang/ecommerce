"""공식 검색 API가 확인되지 않은 사이트 (계획서 5.2, 38절).

접근 제한을 우회하지 않는다는 원칙에 따라 UNAVAILABLE 로 표시하고,
사용자가 직접 확인할 수 있는 검색 URL만 제공한다.
공식 API/제휴 접근이 확보되면 이 클래스를 실제 connector로 교체한다.
"""
from __future__ import annotations

import httpx

from ..models import Product, SearchStatus, SourceKind
from .base import ConnectorError, ShoppingConnector


class _ManualOnlyConnector(ShoppingConnector):
    def is_configured(self) -> bool:
        return False

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        raise ConnectorError(SearchStatus.UNAVAILABLE, self.note)


class GmarketConnector(_ManualOnlyConnector):
    id = "gmarket"
    name = "G마켓"
    kind = SourceKind.RETAIL
    note = "공개 검색 API 없음 (ESM 판매자 API는 상품 검색 미지원). 수동 확인 링크 제공."
    manual_search_url = "https://browse.gmarket.co.kr/search?keyword={q}"


class OwnerclanConnector(_ManualOnlyConnector):
    id = "ownerclan"
    name = "오너클랜"
    kind = SourceKind.WHOLESALE
    note = "오너클랜 API는 판매회원 계정 인증(GraphQL) 필요. 계정 확보 후 구현 예정."
    manual_search_url = "https://www.ownerclan.com/V2/product/search.php?topSearchKeyword={q}"
