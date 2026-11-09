"""스크래핑 connector 공통 기능.

원칙 (계획서 5.2, 38절):
- 공개 검색 페이지를 일반 브라우저와 같은 방식으로 1회 요청한다.
- 요청 간격 제한(사이트별 최소 간격)과 캐시로 요청량을 줄인다.
- 차단·캡차·로그인 요구가 감지되면 우회하지 않고 BLOCKED/AUTH_REQUIRED 로 표시한다.
  (IP 우회, 캡차 풀이, 봇 탐지 회피 기능은 넣지 않는다)

추출 전략 (사이트 구조 변경에 덜 민감하도록 여러 단계를 차례로 시도):
1) 사이트별 CSS 선택자 (extract_html)
2) 페이지에 포함된 JSON (__NEXT_DATA__, JSON-LD, 기타 script JSON)을 재귀 탐색하여
   '상품명 + 가격 + URL' 형태의 객체를 찾는다 (extract_embedded_json)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, ClassVar, Iterable, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..models import Product, SearchStatus, ShippingRule
from ..shipping import parse_shipping_text
from .base import ConnectorError, ShoppingConnector, to_int_price

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.6",
}

_BLOCK_PATTERNS = [
    r"Access Denied",
    r"captcha",
    r"보안\s*문자",
    r"비정상적인\s*(접근|요청)",
    r"자동입력\s*방지",
    r"robot",
    r"Request blocked",
    r"Pardon Our Interruption",
]
_LOGIN_PATTERNS = [r"로그인\s*후\s*(이용|확인)", r"회원만\s*(이용|확인)"]

_last_request: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def _min_interval() -> float:
    return float(os.getenv("SCRAPE_MIN_INTERVAL_SEC", "3"))


class ScrapeConnector(ShoppingConnector):
    """공개 검색 페이지 스크래핑 connector 기반 클래스."""

    #: 검색 페이지 URL 템플릿. {q} 는 URL 인코딩된 검색어
    search_url: ClassVar[str] = ""
    #: 상품 링크의 상대경로를 절대경로로 만들 기준 URL
    base_url: ClassVar[str] = ""
    #: 검색 페이지 하나에서 얻는 최대 개수 (페이지 1장만 요청)
    max_results = 100
    #: 스크래핑은 사이트 부담을 줄이기 위해 기본적으로 원 검색어 1개만 요청
    max_queries = int(os.getenv("SCRAPE_MAX_QUERIES", "1"))

    def is_configured(self) -> bool:
        return os.getenv(f"DISABLE_{self.id.upper()}", "") not in ("1", "true")

    def unavailable_reason(self) -> str:
        return "" if self.is_configured() else "관리자 설정으로 비활성화됨"

    # ---- 요청 ----
    async def fetch(self, url: str, client: httpx.AsyncClient, *, referer: str | None = None) -> str:
        lock = _locks.setdefault(self.id, asyncio.Lock())
        async with lock:  # 같은 사이트에 동시에 여러 요청을 보내지 않는다
            wait = _min_interval() - (time.monotonic() - _last_request.get(self.id, 0))
            if wait > 0:
                await asyncio.sleep(wait)
            headers = dict(BROWSER_HEADERS)
            if referer:
                headers["Referer"] = referer
            try:
                resp = await client.get(url, headers=headers, timeout=self.timeout_sec, follow_redirects=True)
            finally:
                _last_request[self.id] = time.monotonic()
        if resp.status_code in (403, 418, 429, 503):
            raise ConnectorError(
                SearchStatus.API_LIMIT if resp.status_code == 429 else SearchStatus.BLOCKED,
                f"HTTP {resp.status_code}: 사이트가 자동 요청을 제한했습니다.",
            )
        self.raise_for_http(resp)
        text = resp.text
        self._save_probe(url, text)
        self.check_blocked(text)
        return text

    def check_blocked(self, text: str) -> None:
        head = text[:20000]
        if len(text) < 30000:  # 정상 검색결과 페이지는 대개 훨씬 크다
            for pat in _BLOCK_PATTERNS:
                if re.search(pat, head, re.I):
                    raise ConnectorError(SearchStatus.BLOCKED, "차단 또는 캡차 페이지가 반환되었습니다.")
        for pat in _LOGIN_PATTERNS:
            if re.search(pat, head):
                raise ConnectorError(SearchStatus.AUTH_REQUIRED, "로그인이 필요한 페이지입니다.")

    def _save_probe(self, url: str, text: str) -> None:
        """PROBE_DIR 이 설정되면 받은 HTML을 저장한다 (파서 보정용)."""
        d = os.getenv("PROBE_DIR")
        if not d:
            return
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{self.id}.html").write_text(f"<!-- {url} -->\n" + text, encoding="utf-8")

    # ---- 검색 ----
    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        from urllib.parse import quote

        url = self.search_url.format(q=quote(query))
        html = await self.fetch(url, client)
        products = self.parse(html)
        if not products:
            raise ConnectorError(
                SearchStatus.PARSER_ERROR,
                "검색 페이지에서 상품을 찾지 못했습니다 (사이트 구조 변경 가능성).",
            )
        return products[: self.max_results]

    def parse(self, html: str) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        products = self.extract_html(soup)
        if not products:
            products = self.extract_embedded_json(soup)
        return dedupe_by_url(products)

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        """사이트별 선택자 기반 추출. 하위 클래스에서 구현."""
        return []

    # ---- 임베디드 JSON 일반 추출 ----
    NAME_KEYS: ClassVar[tuple[str, ...]] = (
        "productTitle", "productName", "prdNm", "itemName", "title", "name", "goodsName",
    )
    PRICE_KEYS: ClassVar[tuple[str, ...]] = (
        "lowPrice", "price", "salePrice", "finalPrc", "finalPrice", "sellPrice", "selPrc", "discountedPrice",
    )
    URL_KEYS: ClassVar[tuple[str, ...]] = (
        "mallProductUrl", "crUrl", "productUrl", "linkUrl", "url", "link", "prdUrl", "detailUrl", "adcrUrl",
    )
    SHIP_KEYS: ClassVar[tuple[str, ...]] = (
        "deliveryFeeContent", "deliveryFee", "dlvFee", "deliveryPrice", "shippingFee", "deliveryInfo", "dlvCst",
    )
    SELLER_KEYS: ClassVar[tuple[str, ...]] = ("mallName", "sellerName", "sellerNm", "storeName", "seller")
    IMAGE_KEYS: ClassVar[tuple[str, ...]] = ("imageUrl", "image", "imgUrl", "productImage", "thumbnail")
    ID_KEYS: ClassVar[tuple[str, ...]] = ("id", "productId", "nvMid", "prdNo", "itemId", "goodsNo")

    def extract_embedded_json(self, soup: BeautifulSoup) -> list[Product]:
        blobs: list[Any] = []
        for s in soup.find_all("script"):
            txt = s.string or s.get_text() or ""
            if not txt or len(txt) < 50:
                continue
            if s.get("type") in ("application/json", "application/ld+json") or s.get("id") == "__NEXT_DATA__":
                try:
                    blobs.append(json.loads(txt))
                    continue
                except ValueError:
                    pass
            # window.__STATE__ = {...}; 형태
            for m in re.finditer(r"=\s*(\{.*\})\s*;?\s*$", txt, re.S):
                try:
                    blobs.append(json.loads(m.group(1)))
                except ValueError:
                    pass
        out: list[Product] = []
        for blob in blobs:
            for obj in walk_dicts(blob):
                p = self._product_from_obj(obj)
                if p:
                    out.append(p)
        return out

    def _product_from_obj(self, obj: dict) -> Optional[Product]:
        name = first_value(obj, self.NAME_KEYS)
        url = first_value(obj, self.URL_KEYS)
        price_raw = first_value(obj, self.PRICE_KEYS)
        if isinstance(obj.get("offers"), dict):  # JSON-LD Product
            price_raw = price_raw or obj["offers"].get("price") or obj["offers"].get("lowPrice")
            url = url or obj["offers"].get("url")
        if not (isinstance(name, str) and isinstance(url, str) and price_raw not in (None, "")):
            return None
        if not url.startswith(("http", "/")):
            return None
        try:
            price = to_int_price(price_raw)
        except (ValueError, TypeError):
            return None
        if price < 10 or price > 100_000_000:
            return None
        ship_raw = first_value(obj, self.SHIP_KEYS)
        shipping = shipping_from_value(ship_raw)
        img = first_value(obj, self.IMAGE_KEYS)
        return self.make_product(
            name=strip_tags(name),
            url=url,
            price=price,
            shipping=shipping,
            seller=str(first_value(obj, self.SELLER_KEYS) or ""),
            image_url=img if isinstance(img, str) else "",
            external_id=str(first_value(obj, self.ID_KEYS) or ""),
            raw={k: v for k, v in obj.items() if isinstance(v, (str, int, float, bool))},
        )

    def make_product(self, *, name: str, url: str, price: int, shipping: ShippingRule, **kw) -> Product:
        return Product(
            source=self.id,
            source_name=self.name,
            kind=self.kind,
            name=name.strip(),
            url=urljoin(self.base_url, url),
            price=price,
            shipping=shipping,
            **kw,
        )


# ---- 유틸 ----
def walk_dicts(obj: Any, depth: int = 0) -> Iterable[dict]:
    if depth > 40:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v, depth + 1)


def first_value(obj: dict, keys: Iterable[str]):
    for k in keys:
        v = obj.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def strip_tags(s: str) -> str:
    import html as _html

    return _html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def shipping_from_value(v) -> ShippingRule:
    if v is None:
        return ShippingRule(fee_known=False)
    if isinstance(v, (int, float)):
        return ShippingRule(shipping_fee=int(v), raw_text=str(v))
    if isinstance(v, dict):
        text = " ".join(str(x) for x in v.values() if isinstance(x, (str, int, float)))
        return parse_shipping_text(text)[0]
    return parse_shipping_text(str(v))[0]


def text_of(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el is not None else ""


def price_in(text: str) -> Optional[int]:
    m = re.search(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})\s*원?", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def dedupe_by_url(products: list[Product]) -> list[Product]:
    seen, out = set(), []
    for p in products:
        key = p.url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def select_any(el, selectors: Iterable[str]):
    for sel in selectors:
        found = el.select_one(sel)
        if found is not None:
            return found
    return None


__all__ = [
    "ScrapeConnector",
    "text_of",
    "price_in",
    "select_any",
    "shipping_from_value",
    "parse_shipping_text",
    "to_int_price",
]
