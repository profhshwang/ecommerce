"""사이트별 스크래핑 connector.

⚠ 쇼핑몰 화면 구조는 자주 바뀐다. 각 선택자는 2025~2026년 기준 추정이며,
  실제 페이지로 확인(tools/probe.py)한 뒤 보정해야 한다.
⚠ 쿠팡·네이버쇼핑은 자동 요청을 강하게 제한한다. 특히 클라우드 서버(데이터센터 IP)에서는
  대부분 차단되며, 이 경우 '접근 제한'으로 표시하고 우회하지 않는다.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Product, ShippingRule, SourceKind
from ..shipping import parse_shipping_text
from .scrape_base import ScrapeConnector, price_in, select_any, text_of


def _ship_from_text(text: str) -> ShippingRule:
    """카드 전체 텍스트에서 배송 관련 부분만 골라 파싱."""
    parts = re.findall(
        r"(무료\s*배송|로켓[가-힣]*|배송비\s*[0-9,]+\s*원?|[0-9,]+\s*원?\s*이상[^,·|]*무료[^,·|]*|"
        r"[0-9]+\s*개\s*이상[^,·|]*무료|조건부\s*무료)",
        text,
    )
    return parse_shipping_text(" ".join(parts))[0] if parts else ShippingRule(fee_known=False)


# ─────────────────────────────── 소매 ───────────────────────────────
class CoupangScraper(ScrapeConnector):
    id = "coupang"
    name = "쿠팡"
    kind = SourceKind.RETAIL
    note = "쿠팡 검색 페이지 스크래핑. 자동 요청 차단이 강해 실패할 수 있음."
    search_url = "https://www.coupang.com/np/search?q={q}&channel=user&listSize=72"
    base_url = "https://www.coupang.com"
    manual_search_url = "https://www.coupang.com/np/search?q={q}"

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        out = []
        cards = soup.select("li.search-product") or soup.select("#product-list > li, ul[id*=product-list] > li")
        for li in cards:
            a = li.select_one("a[href*='/vp/products/']") or li.find("a", href=True)
            name_el = select_any(li, ["div.name", "[class*=productName]", "[class*=ProductName]"])
            price_el = select_any(li, ["strong.price-value", "[class*=priceValue]", "[class*=Price_price]", "[class*=price]"])
            if not (a and name_el and price_el):
                continue
            price = price_in(text_of(price_el))
            if not price:
                continue
            card_text = text_of(li)
            shipping = _ship_from_text(card_text)
            if not shipping.fee_known and re.search(r"로켓|무료배송", card_text):
                shipping = ShippingRule(shipping_fee=0, raw_text="무료배송")
            img = li.find("img")
            out.append(
                self.make_product(
                    name=text_of(name_el),
                    url=a["href"],
                    price=price,
                    shipping=shipping,
                    seller="로켓배송" if "로켓" in card_text else "",
                    image_url=(img.get("src") or img.get("data-img-src") or "") if img else "",
                    external_id=(li.get("data-product-id") or li.get("id") or ""),
                )
            )
        return out


class NaverShoppingScraper(ScrapeConnector):
    id = "naver"
    name = "네이버쇼핑"
    kind = SourceKind.RETAIL
    note = "네이버쇼핑 검색 페이지 스크래핑 (__NEXT_DATA__). 자동 요청 제한이 강함."
    search_url = "https://search.shopping.naver.com/search/all?query={q}&sort=rel&pagingSize=80"
    base_url = "https://search.shopping.naver.com"
    manual_search_url = "https://search.shopping.naver.com/search/all?query={q}"

    def parse(self, html: str) -> list[Product]:
        # 네이버는 HTML 카드보다 __NEXT_DATA__ JSON이 안정적이다
        soup = BeautifulSoup(html, "html.parser")
        products = self.extract_embedded_json(soup) or self.extract_html(soup)
        # 가격비교 묶음(카탈로그)은 lowPrice 를 사용하므로 판매처 표시 보정
        for p in products:
            if not p.seller and p.raw and p.raw.get("productType") in (1, "1"):
                p.seller = "가격비교(최저가)"
        from .scrape_base import dedupe_by_url

        return dedupe_by_url(products)

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        out = []
        for card in soup.select("div[class*=product_item], div[class*=adProduct_item]"):
            a = select_any(card, ["a[class*=product_link]", "a[class*=title]", "a[href]"])
            price_el = select_any(card, ["span[class*=price_num]", "strong[class*=price]", "[class*=price]"])
            if not (a and price_el):
                continue
            price = price_in(text_of(price_el))
            if not price:
                continue
            seller = text_of(select_any(card, ["a[class*=mall_title]", "[class*=mall_name]"]))
            out.append(
                self.make_product(
                    name=text_of(a), url=a["href"], price=price,
                    shipping=_ship_from_text(text_of(card)), seller=seller,
                )
            )
        return out


class GmarketScraper(ScrapeConnector):
    id = "gmarket"
    name = "G마켓"
    kind = SourceKind.RETAIL
    note = "G마켓 검색 페이지 스크래핑."
    search_url = "https://browse.gmarket.co.kr/search?keyword={q}"
    base_url = "https://browse.gmarket.co.kr"
    manual_search_url = "https://browse.gmarket.co.kr/search?keyword={q}"

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        out = []
        for card in soup.select("div.box__component-itemcard, div[class*=box__item-container]"):
            a = select_any(card, ["a.link__item", "div.box__item-title a", "a[href*='item?goodscode']", "a[href]"])
            name_el = select_any(card, ["span.text__item", "[class*=text__item-title]", "div.box__item-title"])
            price_el = select_any(
                card, ["div.box__price-seller strong.text__value", "strong.text__value", "[class*=price] strong"]
            )
            if not (a and name_el and price_el):
                continue
            price = price_in(text_of(price_el))
            if not price:
                continue
            ship_el = select_any(card, ["[class*=delivery]", "[class*=shipping]", "ul.list__tag"])
            shipping = _ship_from_text(text_of(ship_el) or text_of(card))
            seller = text_of(select_any(card, ["span.text__seller", "[class*=seller] a", "[class*=seller]"]))
            img = card.find("img")
            out.append(
                self.make_product(
                    name=text_of(name_el), url=a["href"], price=price, shipping=shipping,
                    seller=seller, image_url=(img.get("src") or "") if img else "",
                )
            )
        return out


class ElevenstScraper(ScrapeConnector):
    id = "11st"
    name = "11번가"
    kind = SourceKind.RETAIL
    note = "11번가 검색 페이지 스크래핑."
    search_url = "https://search.11st.co.kr/Search.tmall?kwd={q}"
    base_url = "https://www.11st.co.kr"
    manual_search_url = "https://search.11st.co.kr/Search.tmall?kwd={q}"

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        out = []
        for card in soup.select("li[class*=c-search-list__item], div.c-card-item, li[data-log-actionid-area]"):
            a = select_any(card, ["div.c-card-item__name a", "a.c-card-item__anchor", "a[href*='/products/']"])
            name_el = select_any(card, ["div.c-card-item__name", "[class*=name]"]) or a
            price_el = select_any(card, ["dd.price span.value", "[class*=price] .value", "[class*=price]"])
            if not (a and price_el):
                continue
            price = price_in(text_of(price_el))
            if not price:
                continue
            ship_el = select_any(card, ["[class*=delivery]", "[class*=c-card-item__delivery]"])
            out.append(
                self.make_product(
                    name=text_of(name_el), url=a["href"], price=price,
                    shipping=_ship_from_text(text_of(ship_el) or text_of(card)),
                    seller=text_of(select_any(card, ["[class*=seller]", "[class*=store]"])),
                )
            )
        return out


# ─────────────────────────────── 도매 ───────────────────────────────
class DomeggookScraper(ScrapeConnector):
    id = "domeggook"
    name = "도매꾹"
    kind = SourceKind.WHOLESALE
    note = "도매꾹 검색 페이지 스크래핑. 일부 가격은 회원 전용일 수 있음."
    search_url = "https://domeggook.com/main/item/itemList.php?sw={q}&sz=100"
    base_url = "https://domeggook.com"
    manual_search_url = "https://domeggook.com/main/item/itemList.php?sw={q}"

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        out = []
        for li in soup.select("ol.lItemList > li, ul.lItemList > li, li[class*=itemList], div.item_box"):
            a = select_any(li, ["a.title", "a[href*='/main/item/']", "a[href*='domeggook.com/']", "a[href]"])
            price_el = select_any(li, ["div.amt b", "div.amt", "[class*=price]", "[class*=amt]"])
            if not (a and price_el):
                continue
            price = price_in(text_of(price_el))
            if not price:
                continue
            text = text_of(li)
            moq = 1
            m = re.search(r"(?:최소|최소구매|최소수량)\s*[:：]?\s*([0-9,]+)\s*개", text) or re.search(r"([0-9,]+)\s*개\s*이상\s*구매", text)
            if m:
                moq = max(1, int(m.group(1).replace(",", "")))
            ship_el = select_any(li, ["div.deli", "[class*=deli]", "[class*=ship]"])
            img = li.find("img")
            out.append(
                self.make_product(
                    name=text_of(a) or text_of(select_any(li, ["[class*=title]"])),
                    url=a["href"], price=price,
                    shipping=_ship_from_text(text_of(ship_el) or text),
                    seller=text_of(select_any(li, ["div.nick", "[class*=seller]", "[class*=nick]"])),
                    min_order_quantity=moq,
                    image_url=(img.get("src") or "") if img else "",
                )
            )
        return out


class DomemaeScraper(DomeggookScraper):
    id = "domemae"
    name = "도매매"
    note = "도매매 검색 페이지 스크래핑. 가격이 회원 전용이면 '로그인 필요'로 표시."
    search_url = "https://domeme.domeggook.com/s/main/item/itemList.php?sw={q}&sz=100"
    base_url = "https://domeme.domeggook.com"
    manual_search_url = "https://domeme.domeggook.com/s/main/item/itemList.php?sw={q}"


class OwnerclanScraper(ScrapeConnector):
    id = "ownerclan"
    name = "오너클랜"
    kind = SourceKind.WHOLESALE
    note = "오너클랜 검색 페이지 스크래핑. 공급가가 회원 전용이면 '로그인 필요'로 표시."
    search_url = "https://www.ownerclan.com/V2/product/search.php?topSearchKeyword={q}"
    base_url = "https://www.ownerclan.com"
    manual_search_url = "https://www.ownerclan.com/V2/product/search.php?topSearchKeyword={q}"

    def extract_html(self, soup: BeautifulSoup) -> list[Product]:
        out = []
        for card in soup.select("li[class*=prd], div[class*=prd_item], div[class*=goods], li[class*=goods]"):
            a = select_any(card, ["a[href*='view.php']", "a[href*='product']", "a[href]"])
            price_el = select_any(card, ["[class*=price]", "[class*=cost]"])
            if not (a and price_el):
                continue
            price = price_in(text_of(price_el))
            if not price:
                continue
            out.append(
                self.make_product(
                    name=text_of(select_any(card, ["[class*=name]", "[class*=tit]"])) or text_of(a),
                    url=a["href"], price=price, shipping=_ship_from_text(text_of(card)),
                )
            )
        return out
