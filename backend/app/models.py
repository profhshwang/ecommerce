"""공통 데이터 모델 (계획서 7, 13, 15, 34절)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    WHOLESALE = "wholesale"
    RETAIL = "retail"


class SearchStatus(str, Enum):
    """사이트별 검색 상태 (계획서 40절)."""

    PENDING = "PENDING"
    SEARCH_SUCCESS = "SEARCH_SUCCESS"
    SEARCH_TIMEOUT = "SEARCH_TIMEOUT"
    API_LIMIT = "API_LIMIT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    BLOCKED = "BLOCKED"
    PARSER_ERROR = "PARSER_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class StockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    DISCONTINUED = "DISCONTINUED"
    UNKNOWN = "UNKNOWN"


class ShippingRule(BaseModel):
    """구조화된 배송 조건 (계획서 8절).

    fee_known=False 이면 사이트가 배송비를 제공하지 않아 확인이 필요한 상태.
    """

    shipping_fee: int = 0
    fee_known: bool = True
    free_threshold_amount: Optional[int] = None  # 예: 30000원 이상 무료
    free_threshold_quantity: Optional[int] = None  # 예: 10개 이상 무료
    per_quantity: Optional[int] = None  # 예: 10개마다 배송비 1회 부과(묶음 단위)
    raw_text: str = ""

    def fee_for(self, unit_price: int, quantity: int = 1) -> int:
        """수량/주문금액에 따른 실제 배송비 계산."""
        if not self.fee_known:
            return 0
        amount = unit_price * quantity
        if self.free_threshold_amount is not None and amount >= self.free_threshold_amount:
            return 0
        if self.free_threshold_quantity is not None and quantity >= self.free_threshold_quantity:
            return 0
        if self.per_quantity:
            bundles = -(-quantity // self.per_quantity)  # 올림
            return self.shipping_fee * bundles
        return self.shipping_fee

    def describe(self) -> str:
        if not self.fee_known:
            return "배송비 정보 없음 (상품 페이지 확인 필요)"
        parts: list[str] = []
        if self.shipping_fee == 0:
            parts.append("무료배송")
        else:
            parts.append(f"배송비 {self.shipping_fee:,}원")
            if self.free_threshold_amount is not None:
                parts.append(f"{self.free_threshold_amount:,}원 이상 주문 시 무료")
            if self.free_threshold_quantity is not None:
                parts.append(f"{self.free_threshold_quantity}개 이상 주문 시 무료")
            if self.per_quantity:
                parts.append(f"{self.per_quantity}개마다 부과")
        return " · ".join(parts)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Product(BaseModel):
    source: str  # connector id (예: "coupang")
    source_name: str  # 화면 표시명 (예: "쿠팡")
    kind: SourceKind
    external_id: str = ""
    name: str
    brand: str = ""
    model_number: str = ""
    category: str = ""
    seller: str = ""
    url: str
    image_url: str = ""
    price: int  # 일반 판매가격 (모든 구매자 접근 가능 가격)
    discount_price: Optional[int] = None  # 쿠폰/회원 할인가 (참고용)
    shipping: ShippingRule = Field(default_factory=ShippingRule)
    min_order_quantity: int = 1
    stock_status: StockStatus = StockStatus.UNKNOWN
    checked_at: datetime = Field(default_factory=now_utc)
    is_demo: bool = False
    raw: Optional[dict] = None  # 원본 데이터 보존 (원칙 2)

    # 후처리로 채워지는 값
    shipping_fee: int = 0
    effective_price: int = 0
    shipping_condition: str = ""
    match_score: int = 0
    price_confidence: int = 0
    rank: Optional[int] = None

    def finalize(self, quantity: int = 1) -> "Product":
        qty = max(quantity, self.min_order_quantity if self.kind == SourceKind.WHOLESALE else 1)
        self.shipping_fee = self.shipping.fee_for(self.price, qty)
        self.effective_price = self.price * qty + self.shipping_fee
        self.shipping_condition = self.shipping.describe()
        return self


class SiteResult(BaseModel):
    source: str
    source_name: str
    kind: SourceKind
    status: SearchStatus
    message: str = ""
    elapsed_sec: float = 0.0
    count: int = 0
    from_cache: bool = False
    manual_url: str = ""  # 사용자가 직접 확인할 수 있는 검색 URL (계획서 38절)


class MarketStats(BaseModel):
    count: int = 0
    seller_count: int = 0
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    mean_price: Optional[float] = None
    median_price: Optional[float] = None
    std_price: Optional[float] = None
    p25_price: Optional[float] = None
    p75_price: Optional[float] = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    sources: Optional[list[str]] = None
    top_n: int = Field(default=20, ge=1, le=100)
    quantity: int = Field(default=1, ge=1, le=10000)
    expand: bool = True
    min_match_score: int = Field(default=40, ge=0, le=100)


class SearchResponse(BaseModel):
    query: str
    expanded_queries: list[str]
    sites: list[SiteResult]
    retail_top: list[Product]
    wholesale_top: list[Product]
    retail_stats: MarketStats
    wholesale_stats: MarketStats
    started_at: datetime
    completed_at: datetime
