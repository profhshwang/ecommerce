"""데모 connector — API 키 없이 UI·계산 로직을 확인하기 위한 가상 데이터.

DEMO_MODE=1 일 때 모든 사이트를 이 connector로 대체한다.
생성된 상품은 is_demo=True 로 표시되며 실제 가격이 아니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from urllib.parse import quote

import httpx

from ..models import Product, SourceKind
from ..shipping import parse_shipping_text
from .base import ShoppingConnector

_RETAIL_SHIPPING = [
    "무료배송",
    "배송비 3,000원",
    "배송비 2,500원 (30,000원 이상 구매시 무료)",
    "19,800원 이상 무료배송, 미만 3,000원",
    "배송비 3,500원",
    "로켓배송 무료배송",
]
_WHOLESALE_SHIPPING = [
    "배송비 3,000원 (10개 이상 주문시 무료)",
    "배송비 4,000원 (50,000원 이상 구매시 무료)",
    "배송비 3,500원",
    "20개마다 배송비 3,000원",
    "무료배송",
]
_SUFFIX = ["", " 정품", " 1+1", " 2개입", " 블랙", " 화이트", " 고속", " 리뉴얼", " 벌크"]


class DemoConnector(ShoppingConnector):
    def __init__(self, base: type[ShoppingConnector]):
        self.id = base.id  # type: ignore[misc]
        self.name = base.name  # type: ignore[misc]
        self.kind = base.kind  # type: ignore[misc]
        self.note = "데모 데이터 (실제 가격 아님)"  # type: ignore[misc]
        self.manual_search_url = base.manual_search_url  # type: ignore[misc]

    def is_configured(self) -> bool:
        return True

    async def search(self, query: str, client: httpx.AsyncClient) -> list[Product]:
        seed = int(hashlib.md5(f"{self.id}:{query}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        await asyncio.sleep(rng.uniform(0.3, 2.5))  # 사이트별 응답 지연 흉내
        base_price = 5000 + (int(hashlib.md5(query.encode()).hexdigest()[:6], 16) % 40) * 1000
        n = rng.randint(15, 40)
        out = []
        wholesale = self.kind == SourceKind.WHOLESALE
        for i in range(n):
            factor = rng.uniform(0.35, 0.65) if wholesale else rng.uniform(0.85, 1.6)
            price = int(round(base_price * factor, -1))
            ship_text = rng.choice(_WHOLESALE_SHIPPING if wholesale else _RETAIL_SHIPPING)
            shipping, _ = parse_shipping_text(ship_text)
            name = f"{query}{rng.choice(_SUFFIX)}"
            if rng.random() < 0.12:  # 관련성 낮은 상품(액세서리 등) 섞기
                name = f"{query.split()[0]} 호환 액세서리 거치대"
            out.append(
                Product(
                    source=self.id,
                    source_name=self.name,
                    kind=self.kind,
                    external_id=f"demo-{self.id}-{i}",
                    name=name,
                    seller=f"{self.name} 판매자{rng.randint(1, 25)}",
                    url=f"https://example.com/{self.id}/item/{i}?q={quote(query)}",
                    price=price,
                    shipping=shipping,
                    min_order_quantity=rng.choice([1, 1, 5, 10]) if wholesale else 1,
                    is_demo=True,
                )
            )
        return out
