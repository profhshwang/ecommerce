"""정규화 · 중복 제거 · 최저가 정렬 · 시장가격 통계 (계획서 10, 15, 16절)."""
from __future__ import annotations

import statistics
from typing import Iterable

from .matching import normalize, price_confidence, rule_match_score
from .models import MarketStats, Product


def dedupe(products: Iterable[Product]) -> list[Product]:
    """같은 사이트의 같은 상품(ID 또는 URL)과, 같은 판매자·이름·가격 중복 제거."""
    seen: set[tuple] = set()
    out = []
    for p in products:
        keys = [
            (p.source, "id", p.external_id) if p.external_id else None,
            (p.source, "url", p.url) if p.url else None,
            (p.source, "nsp", normalize(p.name), p.seller, p.price),
        ]
        keys = [k for k in keys if k]
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        out.append(p)
    return out


def score_and_rank(
    query: str,
    products: list[Product],
    *,
    quantity: int = 1,
    min_match_score: int = 40,
    top_n: int = 20,
) -> tuple[list[Product], list[Product]]:
    """매칭 점수·실질가격 계산 후 (상위 top_n, 매칭 통과 전체) 반환.

    정렬 기준: 실질가격(상품가격 + 배송비) 오름차순 (TC-07).
    배송비 정보가 없는 상품은 상품가격만으로 정렬하되 같은 가격이면 뒤로 보낸다.
    """
    for p in products:
        p.finalize(quantity)
        p.match_score = rule_match_score(query, p.name)
        p.price_confidence = price_confidence(p)
    matched = [p for p in products if p.match_score >= min_match_score]
    matched.sort(key=lambda p: (p.effective_price, not p.shipping.fee_known, -p.match_score))
    top = matched[:top_n]
    for i, p in enumerate(top, 1):
        p.rank = i
    return top, matched


def market_stats(products: list[Product]) -> MarketStats:
    prices = [p.effective_price for p in products]
    if not prices:
        return MarketStats()
    q = statistics.quantiles(prices, n=4) if len(prices) >= 2 else [prices[0]] * 3
    return MarketStats(
        count=len(prices),
        seller_count=len({(p.source, p.seller) for p in products if p.seller}) or len(prices),
        min_price=min(prices),
        max_price=max(prices),
        mean_price=round(statistics.fmean(prices), 1),
        median_price=float(statistics.median(prices)),
        std_price=round(statistics.pstdev(prices), 1),
        p25_price=round(q[0], 1),
        p75_price=round(q[2], 1),
    )
