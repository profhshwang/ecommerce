"""쿠팡 connector — 쿠팡 파트너스 Open API (공식 제휴 API).

신청: https://partners.coupang.com → 추천인/파트너스 가입 → Open API 키 발급
     (최종 승인 및 일정 실적 조건이 있을 수 있음)
환경변수: COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY
제약: 검색 API는 1회 최대 10개, 시간당 호출 수 제한이 있다.
     반환 URL은 파트너스 추적 링크이다.

배송비: API는 isFreeShipping / isRocket 플래그만 제공한다.
       무료배송이 아니면 배송비 금액은 '정보 없음'(상품 페이지 확인)으로 둔다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx

from ..models import Product, SearchStatus, ShippingRule, SourceKind
from .base import ConnectorError, ShoppingConnector, to_int_price

DOMAIN = "https://api-gateway.coupang.com"
PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"


def _authorization(method: str, path: str, query: str, access_key: str, secret_key: str) -> str:
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + query
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={signed_date}, signature={signature}"
    )


class CoupangConnector(ShoppingConnector):
    id = "coupang"
    name = "쿠팡"
    kind = SourceKind.RETAIL
    required_env = ("COUPANG_ACCESS_KEY", "COUPANG_SECRET_KEY")
    note = "쿠팡 파트너스 Open API (공식). 1회 최대 10개, 배송비 금액 미제공."
    manual_search_url = "https://www.coupang.com/np/search?q={q}"
    max_results = 10

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        query_string = urlencode({"keyword": query, "limit": self.max_results})
        auth = _authorization(
            "GET", PATH, query_string, os.environ["COUPANG_ACCESS_KEY"], os.environ["COUPANG_SECRET_KEY"]
        )
        resp = await client.get(
            f"{DOMAIN}{PATH}?{query_string}",
            headers={"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"},
            timeout=self.timeout_sec,
        )
        self.raise_for_http(resp)
        try:
            body = resp.json()
        except ValueError as e:
            raise ConnectorError(SearchStatus.PARSER_ERROR, str(e)) from e
        if str(body.get("rCode", "0")) not in ("0", "200"):
            raise ConnectorError(SearchStatus.UNAVAILABLE, body.get("rMessage", "쿠팡 API 오류"))
        data = body.get("data") or {}
        items = data.get("productData", []) if isinstance(data, dict) else []
        return [p for p in (self._parse(it) for it in items) if p]

    def _parse(self, it: dict) -> Product | None:
        try:
            price = to_int_price(it.get("productPrice"))
        except ValueError:
            return None
        is_free = bool(it.get("isFreeShipping"))
        is_rocket = bool(it.get("isRocket"))
        if is_free:
            shipping = ShippingRule(shipping_fee=0, raw_text="무료배송" + (" (로켓배송)" if is_rocket else ""))
        else:
            shipping = ShippingRule(
                fee_known=False, raw_text="로켓배송 (와우회원 무료, 비회원 조건부)" if is_rocket else ""
            )
        return Product(
            source=self.id,
            source_name=self.name,
            kind=self.kind,
            external_id=str(it.get("productId", "")),
            name=it.get("productName", ""),
            category=it.get("categoryName", ""),
            seller="쿠팡 로켓배송" if is_rocket else "",
            url=it.get("productUrl", ""),
            image_url=it.get("productImage", ""),
            price=price,
            shipping=shipping,
            raw=it,
        )
