"""스크래핑 파서 테스트 — 사이트 구조를 흉내낸 HTML 고정 샘플 사용.

실제 사이트 구조와 다를 수 있으므로, app.tools.probe 로 받은 실제 HTML을
tests/fixtures/ 에 넣어 테스트를 추가하는 것을 권장한다.
"""
import json

import httpx
import pytest

from app.connectors.base import ConnectorError
from app.connectors.scrapers import (
    CoupangScraper, DomeggookScraper, ElevenstScraper, GmarketScraper, NaverShoppingScraper,
)
from app.models import SearchStatus

PAD = "<!--" + "x" * 31000 + "-->"  # 정상 페이지 크기 흉내

COUPANG_HTML = f"""<html><body>{PAD}<ul id="productList">
<li class="search-product" data-product-id="11"><a class="search-product-link" href="/vp/products/11?itemId=1">
<div class="name">삼성 25W 충전기</div><strong class="price-value">14,900</strong>
<span class="badge rocket">로켓배송</span><div class="delivery">무료배송</div></a></li>
<li class="search-product" data-product-id="12"><a href="/vp/products/12">
<div class="name">삼성 25W 충전기 호환</div><strong class="price-value">9,900</strong>
<div class="delivery">배송비 3,000원</div></a></li></ul></body></html>"""

NEXT_DATA = {"props": {"pageProps": {"initialState": {"products": {"list": [
    {"item": {"id": "1", "productTitle": "<b>삼성</b> 25W 충전기", "price": "15900", "lowPrice": "15900",
              "mallName": "A몰", "mallProductUrl": "https://smartstore.naver.com/a/products/1",
              "deliveryFeeContent": "3,000", "imageUrl": "https://img/1.jpg"}},
    {"item": {"id": "2", "productTitle": "삼성 25W 충전기 정품", "price": "17000", "lowPrice": "16500",
              "mallName": "", "crUrl": "https://cr.shopping.naver.com/2", "deliveryFeeContent": "무료",
              "productType": 1}},
]}}}}}
NAVER_HTML = f"""<html><body>{PAD}<script id="__NEXT_DATA__" type="application/json">{json.dumps(NEXT_DATA, ensure_ascii=False)}</script></body></html>"""

GMARKET_HTML = f"""<html><body>{PAD}<div class="box__component box__component-itemcard">
<div class="box__item-title"><a class="link__item" href="https://item.gmarket.co.kr/Item?goodscode=1">
<span class="text__item">삼성 25W 충전기</span></a></div>
<div class="box__price-seller"><strong class="text__value">13,500</strong>원</div>
<ul class="list__tag"><li>배송비 2,500원</li><li>30,000원 이상 구매시 무료</li></ul></div></body></html>"""

ELEVEN_HTML = f"""<html><body>{PAD}<ul><li class="c-search-list__item"><div class="c-card-item">
<div class="c-card-item__name"><a href="https://www.11st.co.kr/products/9">삼성 25W 충전기</a></div>
<dd class="price"><span class="value">16,000</span>원</dd><div class="c-card-item__delivery">무료배송</div>
</div></li></ul></body></html>"""

DOME_HTML = f"""<html><body>{PAD}<ol class="lItemList"><li>
<a class="title" href="/123">삼성 25W 충전기 벌크</a><div class="amt"><b>8,500</b>원</div>
<div class="deli">배송비 3,000원 10개 이상 구매시 무료</div><div class="nick">공급사A</div>
<span>최소구매 5개</span></li></ol></body></html>"""

BLOCK_HTML = "<html><head><title>Access Denied</title></head><body>You don't have permission</body></html>"


def client_for(html, status=200):
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=html)))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("SCRAPE_MIN_INTERVAL_SEC", "0")


async def test_coupang():
    async with client_for(COUPANG_HTML) as c:
        ps = await CoupangScraper().search("삼성 충전기", c)
    assert [(p.price, p.shipping.shipping_fee) for p in ps] == [(14900, 0), (9900, 3000)]
    assert ps[0].url == "https://www.coupang.com/vp/products/11?itemId=1"


async def test_naver_next_data():
    async with client_for(NAVER_HTML) as c:
        ps = await NaverShoppingScraper().search("삼성 충전기", c)
    assert ps[0].name == "삼성 25W 충전기" and ps[0].price == 15900 and ps[0].shipping.shipping_fee == 3000
    assert ps[1].price == 16500 and ps[1].shipping.shipping_fee == 0  # lowPrice 우선
    assert ps[0].seller == "A몰"


async def test_gmarket():
    async with client_for(GMARKET_HTML) as c:
        ps = await GmarketScraper().search("삼성 충전기", c)
    p = ps[0]
    assert p.price == 13500 and p.shipping.shipping_fee == 2500 and p.shipping.free_threshold_amount == 30000


async def test_elevenst():
    async with client_for(ELEVEN_HTML) as c:
        ps = await ElevenstScraper().search("삼성 충전기", c)
    assert ps[0].price == 16000 and ps[0].shipping.shipping_fee == 0


async def test_domeggook_moq():
    async with client_for(DOME_HTML) as c:
        ps = await DomeggookScraper().search("삼성 충전기", c)
    p = ps[0]
    assert p.price == 8500 and p.min_order_quantity == 5 and p.shipping.free_threshold_quantity == 10
    assert p.url == "https://domeggook.com/123" and p.seller == "공급사A"


@pytest.mark.parametrize("html,status,expected", [
    (BLOCK_HTML, 200, SearchStatus.BLOCKED),
    ("blocked", 403, SearchStatus.BLOCKED),
    ("slow down", 429, SearchStatus.API_LIMIT),
    (f"<html>{PAD}<body>상품 없음</body></html>", 200, SearchStatus.PARSER_ERROR),
])
async def test_block_and_empty_are_reported_not_bypassed(html, status, expected):
    async with client_for(html, status) as c:
        with pytest.raises(ConnectorError) as ei:
            await CoupangScraper().search("x", c)
    assert ei.value.status == expected
