"""검색어 확장 · 상품 정규화 · 규칙 기반 매칭 · 가격 신뢰도 (계획서 2.3, 11, 14절).

MVP-1 은 규칙 기반으로만 동작한다. AI 매칭(MVP-2)은 rule_match_score 로
후보를 줄인 뒤 AIProvider 를 호출하도록 확장한다 (원칙: 계산과 AI 분리).
"""
from __future__ import annotations

import re
import unicodedata

from .models import Product

MAX_EXPANDED_QUERIES = 3  # 요청량 통제를 위한 상한 (계획서 2.3)

# 매칭 점수를 떨어뜨리는 '부속품' 신호어: 검색어에 없는데 상품명에 있으면 감점
_ACCESSORY_WORDS = {"케이스", "필름", "거치대", "호환", "액세서리", "커버", "파우치", "스트랩", "교체용", "리필"}
_MODEL_RE = re.compile(r"\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{3,}\b")
_QTY_RE = re.compile(r"(\d+)\s*(개입|개|팩|매|롤|ea|EA|세트|P\b|입)")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[\[\]\(\)\{\}/,·|+_]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split(" ") if w}


def model_numbers(text: str) -> set[str]:
    return {m.group(0).upper().replace("-", "") for m in _MODEL_RE.finditer(unicodedata.normalize("NFKC", text))}


def pack_quantity(text: str) -> int | None:
    m = _QTY_RE.search(text)
    return int(m.group(1)) if m else None


def expand_query(query: str) -> list[str]:
    """규칙 기반 검색어 확장. (AI 확장은 AIProvider 연결 후 추가)

    - 원 검색어
    - 한글-숫자/영문-숫자 사이 공백 제거/추가 변형 (예: '아이폰 15' ↔ '아이폰15')
    """
    q = re.sub(r"\s+", " ", query).strip()
    variants = [q]
    joined = re.sub(r"(?<=[가-힣A-Za-z])\s+(?=\d)", "", q)
    spaced = re.sub(r"(?<=[가-힣])(?=\d)|(?<=\d)(?=[가-힣])", " ", q)
    for v in (joined, spaced):
        if v and v not in variants:
            variants.append(v)
    return variants[:MAX_EXPANDED_QUERIES]


def rule_match_score(query: str, product_name: str) -> int:
    """검색어와 상품명의 동일상품 가능성 (0~100, 규칙 기반)."""
    q_tokens = tokens(query)
    if not q_tokens:
        return 0
    name_norm = normalize(product_name)
    name_compact = name_norm.replace(" ", "")
    hit = sum(1 for t in q_tokens if t in name_norm or t in name_compact)
    score = 100.0 * hit / len(q_tokens)

    q_models = model_numbers(query)
    if q_models:
        p_models = model_numbers(product_name)
        if q_models & p_models:
            score = max(score, 90)
        elif p_models:
            score *= 0.5  # 다른 모델번호 → 유사상품일 가능성 (TC-04)

    accessory = {w for w in _ACCESSORY_WORDS if w in name_norm and w not in normalize(query)}
    if accessory:
        score *= 0.5

    q_qty, p_qty = pack_quantity(query), pack_quantity(product_name)
    if q_qty and p_qty and q_qty != p_qty:
        score *= 0.7
    return int(round(min(score, 100)))


def price_confidence(p: Product) -> int:
    """가격 신뢰도 (0~100, 계획서 14절)."""
    score = 100
    if not p.shipping.fee_known:
        score -= 30  # 배송비 불명확
    if p.discount_price is not None and p.discount_price < p.price:
        score -= 5  # 쿠폰/회원가 존재
    if p.match_score < 70:
        score -= int((70 - p.match_score) * 0.5)
    if p.is_demo:
        score = min(score, 10)
    return max(0, min(100, score))
