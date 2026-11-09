"""도매꾹 / 도매매 connector — 도매꾹 Open API (공식).

신청: 도매꾹 Open API (domeggook.com → 고객센터 → Open API) 에서 API Key(aid) 발급
환경변수: DOMEGGOOK_API_KEY
도매꾹(market=dome)과 도매매(market=supply)는 같은 API를 사용한다.

주의: 응답 필드 구조는 API 버전에 따라 다를 수 있어 방어적으로 파싱한다.
      PoC 단계에서 실제 키로 필드명을 확인하고 _parse()를 보정할 것.
"""
from __future__ import annotations

import os

import httpx

from ..models import Product, SearchStatus, ShippingRule, SourceKind, StockStatus
from ..shipping import parse_shipping_text
from .base import ConnectorError, ShoppingConnector, to_int_price

API_URL = "https://domeggook.com/ssl/api/"


def _get(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


class DomeggookConnector(ShoppingConnector):
    id = "domeggook"
    name = "도매꾹"
    kind = SourceKind.WHOLESALE
    required_env = ("DOMEGGOOK_API_KEY",)
    note = "도매꾹 Open API (공식)."
    market = "dome"
    manual_search_url = "https://domeggook.com/main/item/itemList.php?sw={q}"
    base_item_url = "https://domeggook.com/"

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        params = {
            "ver": "4.1",
            "mode": "getItemList",
            "aid": os.environ["DOMEGGOOK_API_KEY"],
            "market": self.market,
            "om": "json",
            "kw": query,
            "sz": min(self.max_results, 200),
            "so": "rd",  # 정확도(랭킹)순
        }
        resp = await client.get(API_URL, params=params, timeout=self.timeout_sec)
        self.raise_for_http(resp)
        try:
            body = resp.json()
        except ValueError as e:
            raise ConnectorError(SearchStatus.PARSER_ERROR, str(e)) from e
        root = body.get("domeggook", body)
        if "errors" in root:
            raise ConnectorError(SearchStatus.UNAVAILABLE, str(root["errors"]))
        items = _get(_get(root, "list", default={}) or {}, "item", default=[]) or []
        if isinstance(items, dict):
            items = [items]
        return [p for p in (self._parse(it) for it in items) if p]

    def _parse(self, it: dict) -> Product | None:
        try:
            price = to_int_price(_get(it, "price", "amt"))
        except ValueError:
            return None
        no = str(_get(it, "no", "itemNo", default=""))
        deli = _get(it, "deli", default={}) or {}
        if isinstance(deli, dict):
            fee_raw = _get(deli, "fee", "dlvFee")
            text = _get(deli, "text", "tx", default="") or ""
            free_amt = _get(deli, "freeAmt", "free")
            parts = [str(text)]
            if free_amt:
                parts.append(f"{free_amt}원 이상 무료")
            default_fee = None
            try:
                default_fee = to_int_price(fee_raw) if fee_raw not in (None, "") else None
            except ValueError:
                pass
            shipping, _ = parse_shipping_text(" ".join(p for p in parts if p), default_fee=default_fee)
        elif isinstance(deli, str):
            shipping, _ = parse_shipping_text(deli)
        else:
            shipping = ShippingRule(fee_known=False)
        moq = _get(it, "minQty", "unitQty", "qty", default=1)
        try:
            moq = max(1, int(str(moq).replace(",", "")))
        except ValueError:
            moq = 1
        url = _get(it, "url", default="") or (f"{self.base_item_url}{no}" if no else self.base_item_url)
        return Product(
            source=self.id,
            source_name=self.name,
            kind=self.kind,
            external_id=no,
            name=str(_get(it, "title", "name", default="")),
            seller=str(_get(it, "id", "seller", "comp", default="")),
            url=url,
            image_url=str(_get(it, "thumb", "image", default="")),
            price=price,
            shipping=shipping,
            min_order_quantity=moq,
            stock_status=StockStatus.UNKNOWN,
            raw=it,
        )


class DomemaeConnector(DomeggookConnector):
    id = "domemae"
    name = "도매매"
    note = "도매꾹 Open API (market=supply, 공식)."
    market = "supply"
    manual_search_url = "https://domeme.domeggook.com/s/main/item/itemList.php?sw={q}"
    base_item_url = "https://domeme.domeggook.com/s/"
