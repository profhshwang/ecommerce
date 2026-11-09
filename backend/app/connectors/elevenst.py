"""11번가 connector — 11번가 Open API (공식, ProductSearch).

신청: 11번가 Open API 센터 (openapi.11st.co.kr)에서 API Key 발급
환경변수: ELEVENST_API_KEY
주의: 응답은 XML(EUC-KR)이며, API 정책/필드는 PoC 단계에서 실제 키로 확인 필요.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import httpx

from ..models import Product, SearchStatus, SourceKind
from ..shipping import parse_shipping_text
from .base import ConnectorError, ShoppingConnector, to_int_price

API_URL = "http://openapi.11st.co.kr/openapi/OpenApiService.tmall"


def _text(el: ET.Element, *tags: str) -> str:
    for tag in tags:
        found = el.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ""


class ElevenstConnector(ShoppingConnector):
    id = "11st"
    name = "11번가"
    kind = SourceKind.RETAIL
    required_env = ("ELEVENST_API_KEY",)
    note = "11번가 Open API (공식 ProductSearch)."
    manual_search_url = "https://search.11st.co.kr/Search.tmall?kwd={q}"

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        params = {
            "key": os.environ["ELEVENST_API_KEY"],
            "apiCode": "ProductSearch",
            "keyword": query,
            "pageSize": min(self.max_results, 200),
            "sortCd": "A",  # 정확도순
        }
        resp = await client.get(API_URL, params=params, timeout=self.timeout_sec)
        self.raise_for_http(resp)
        try:
            text = resp.content.decode("euc-kr", errors="replace")
            text = text.replace('encoding="EUC-KR"', "").replace("encoding='EUC-KR'", "")
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise ConnectorError(SearchStatus.PARSER_ERROR, str(e)) from e
        products = []
        for el in root.iter("Product"):
            p = self._parse(el)
            if p:
                products.append(p)
        return products

    def _parse(self, el: ET.Element) -> Product | None:
        try:
            price = to_int_price(_text(el, "SalePrice", "ProductPrice"))
        except ValueError:
            return None
        delivery = _text(el, "Delivery")
        shipping, _conf = parse_shipping_text(delivery)
        return Product(
            source=self.id,
            source_name=self.name,
            kind=self.kind,
            external_id=_text(el, "ProductCode"),
            name=_text(el, "ProductName"),
            seller=_text(el, "SellerNick", "Seller"),
            url=_text(el, "DetailPageUrl"),
            image_url=_text(el, "ProductImage300", "ProductImage"),
            price=price,
            shipping=shipping,
            raw={c.tag: (c.text or "") for c in el},
        )
