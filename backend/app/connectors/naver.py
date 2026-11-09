"""네이버쇼핑 connector — 네이버 검색 Open API (공식).

신청: https://developers.naver.com → 애플리케이션 등록 → '검색' API 선택
환경변수: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
한도: 하루 25,000회 (2026년 기준, 변경될 수 있음)

주의: 검색 API는 배송비를 제공하지 않는다. 따라서 배송비는 '정보 없음'으로
표시하고 가격 신뢰도를 낮춘다. (상품 페이지에서 확인 필요)
"""
from __future__ import annotations

import html
import os
import re

import httpx

from ..models import Product, ShippingRule, SourceKind
from .base import ConnectorError, ShoppingConnector, to_int_price
from ..models import SearchStatus

API_URL = "https://openapi.naver.com/v1/search/shop.json"
_TAG = re.compile(r"<[^>]+>")


class NaverShoppingConnector(ShoppingConnector):
    id = "naver"
    name = "네이버쇼핑"
    kind = SourceKind.RETAIL
    required_env = ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
    note = "네이버 검색 Open API (공식). 배송비는 API에서 제공되지 않음."
    manual_search_url = "https://search.shopping.naver.com/search/all?query={q}"

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        headers = {
            "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
        }
        products: dict[str, Product] = {}
        # 정확도순 100개 + 가격낮은순 100개를 합쳐 후보를 넓힌다.
        for sort in ("sim", "asc"):
            params = {
                "query": query,
                "display": min(self.max_results, 100),
                "start": 1,
                "sort": sort,
                "exclude": "used:rental:cbshop",  # 중고·렌탈·해외직구 제외
            }
            resp = await client.get(API_URL, params=params, headers=headers, timeout=self.timeout_sec)
            self.raise_for_http(resp)
            try:
                items = resp.json().get("items", [])
            except ValueError as e:
                raise ConnectorError(SearchStatus.PARSER_ERROR, str(e)) from e
            for it in items:
                p = self._parse(it)
                if p:
                    products.setdefault(p.external_id or p.url, p)
        return list(products.values())

    def _parse(self, it: dict) -> Product | None:
        try:
            price = to_int_price(it.get("lprice"))
        except ValueError:
            return None
        if price <= 0:
            return None
        return Product(
            source=self.id,
            source_name=self.name,
            kind=self.kind,
            external_id=str(it.get("productId", "")),
            name=html.unescape(_TAG.sub("", it.get("title", ""))),
            brand=it.get("brand") or it.get("maker") or "",
            category=" > ".join(c for c in (it.get(f"category{i}") for i in range(1, 5)) if c),
            seller=it.get("mallName", ""),
            url=it.get("link", ""),
            image_url=it.get("image", ""),
            price=price,
            shipping=ShippingRule(fee_known=False, raw_text="네이버 API 미제공"),
            raw=it,
        )
