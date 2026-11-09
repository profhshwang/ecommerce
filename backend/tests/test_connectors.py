"""connector 파싱 테스트 — 공식 API 응답 형식을 흉내낸 MockTransport 사용."""
import httpx
import pytest

from app.connectors.coupang import CoupangConnector
from app.connectors.domeggook import DomeggookConnector
from app.connectors.elevenst import ElevenstConnector
from app.connectors.naver import NaverShoppingConnector

NAVER_JSON = {"items": [
    {"title": "<b>삼성</b> 25W 충전기", "link": "https://smartstore.naver.com/a/1", "image": "", "lprice": "15900",
     "hprice": "", "mallName": "A몰", "productId": "111", "productType": "2", "brand": "삼성", "maker": "",
     "category1": "디지털/가전", "category2": "휴대폰액세서리", "category3": "", "category4": ""},
]}
COUPANG_JSON = {"rCode": "0", "rMessage": "", "data": {"landingUrl": "", "productData": [
    {"productId": 1, "productName": "삼성 25W 충전기", "productPrice": 14900, "productImage": "",
     "productUrl": "https://link.coupang.com/a/x", "isRocket": True, "isFreeShipping": True, "categoryName": "충전기"},
    {"productId": 2, "productName": "삼성 25W 충전기 정품", "productPrice": 13900, "productImage": "",
     "productUrl": "https://link.coupang.com/a/y", "isRocket": False, "isFreeShipping": False},
]}}
ELEVENST_XML = """<?xml version="1.0" encoding="EUC-KR"?>
<ProductSearchResponse><Products><Product><ProductCode>9</ProductCode><ProductName>삼성 25W 충전기</ProductName>
<ProductPrice>17000</ProductPrice><SalePrice>16000</SalePrice><Delivery>2,500원</Delivery><SellerNick>B샵</SellerNick>
<DetailPageUrl>https://www.11st.co.kr/products/9</DetailPageUrl></Product></Products></ProductSearchResponse>""".encode("euc-kr")
DOME_JSON = {"domeggook": {"header": {}, "list": {"item": [
    {"no": "123", "title": "삼성 25W 충전기 벌크", "price": "8,500", "id": "seller1", "thumb": "",
     "deli": {"fee": "3000", "text": "10개 이상 주문시 무료"}, "unitQty": "5"},
]}}}


def client_for(body, content_type="application/json"):
    def handler(request):
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, headers={"content-type": content_type})
        return httpx.Response(200, json=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "COUPANG_ACCESS_KEY", "COUPANG_SECRET_KEY",
              "ELEVENST_API_KEY", "DOMEGGOOK_API_KEY"):
        monkeypatch.setenv(k, "test")


async def test_naver():
    async with client_for(NAVER_JSON) as c:
        ps = await NaverShoppingConnector().search("삼성 충전기", c)
    assert len(ps) == 1 and ps[0].name == "삼성 25W 충전기" and ps[0].price == 15900
    assert not ps[0].shipping.fee_known  # API가 배송비를 주지 않음


async def test_coupang():
    async with client_for(COUPANG_JSON) as c:
        ps = await CoupangConnector().search("삼성 충전기", c)
    assert [p.price for p in ps] == [14900, 13900]
    assert ps[0].shipping.fee_known and ps[0].shipping.shipping_fee == 0
    assert not ps[1].shipping.fee_known


async def test_elevenst():
    async with client_for(ELEVENST_XML, "text/xml") as c:
        ps = await ElevenstConnector().search("삼성 충전기", c)
    assert ps[0].price == 16000 and ps[0].shipping.shipping_fee == 2500


async def test_domeggook_moq_and_shipping():
    async with client_for(DOME_JSON) as c:
        ps = await DomeggookConnector().search("삼성 충전기", c)
    p = ps[0].finalize(1)
    assert p.min_order_quantity == 5 and p.price == 8500
    assert p.shipping.free_threshold_quantity == 10
    assert p.effective_price == 8500 * 5 + 3000  # MOQ 기준 원가 (TC-06)
