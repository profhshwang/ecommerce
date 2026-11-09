"""배송비 조건 규칙 기반 파서 (계획서 8절).

자연어 배송조건을 ShippingRule로 구조화한다. 복잡한 문장은 향후 AI 파서로
넘길 수 있도록 parse_shipping_text() 결과의 confidence를 함께 반환한다.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import ShippingRule

_NUM = r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만)?\s*원?"


def _to_int(num: str, man: Optional[str] = None) -> int:
    value = float(num.replace(",", ""))
    if man:
        value *= 10000
    return int(round(value))


def parse_shipping_text(text: Optional[str], default_fee: Optional[int] = None) -> tuple[ShippingRule, float]:
    """배송 조건 문자열을 구조화한다.

    반환: (ShippingRule, confidence 0~1)

    지원 예:
      "무료배송", "배송비 무료", "로켓배송"
      "배송비 3,000원", "3000원"
      "30,000원 이상 구매시 무료" / "3만원 이상 무료배송 (미만 2,500원)"
      "10개 이상 주문시 무료, 배송비 3,000원"
      "조건부 무료배송"  → 금액을 모르면 fee_known=False
    """
    raw = (text or "").strip()
    t = re.sub(r"\s+", " ", raw)

    if not t:
        if default_fee is not None:
            return ShippingRule(shipping_fee=default_fee, raw_text=raw), 0.9
        return ShippingRule(fee_known=False, raw_text=raw), 0.0

    rule = ShippingRule(raw_text=raw)
    confidence = 0.9

    # 1) 조건부 무료: 금액 기준
    m_amt = re.search(_NUM + r"\s*이상\s*(?:구매|주문|결제)?\s*(?:시|하면|시에)?\s*(?:배송비\s*)?무료", t)
    # 2) 조건부 무료: 수량 기준
    m_qty = re.search(r"([0-9]+)\s*(?:개|ea|EA|세트|박스)\s*이상\s*(?:구매|주문)?\s*(?:시|하면)?\s*(?:배송비\s*)?무료", t)
    # 3) 묶음 단위 부과: "10개마다", "10개당 배송비"
    m_per = re.search(r"([0-9]+)\s*개\s*(?:마다|당|단위)", t)

    if m_amt:
        rule.free_threshold_amount = _to_int(m_amt.group(1), m_amt.group(2))
    if m_qty:
        rule.free_threshold_quantity = int(m_qty.group(1))
    if m_per and not m_qty:
        rule.per_quantity = int(m_per.group(1))

    # 기본 배송비 금액 찾기: 임계값 숫자를 제거한 뒤 남은 금액
    t_rest = t
    for m in (m_amt, m_qty):
        if m:
            t_rest = t_rest.replace(m.group(0), " ")
    fee_candidates = [
        _to_int(m.group(1), m.group(2))
        for m in re.finditer(_NUM, t_rest)
        if not re.match(r"^[0-9]+$", m.group(1)) or int(m.group(1).replace(",", "")) >= 100
    ]

    is_free_word = bool(re.search(r"무료\s*배송|배송비\s*무료|^무료$|로켓\s*배송|로켓와우|free", t, re.I))
    conditional = bool(m_amt or m_qty or re.search(r"조건부", t))

    if conditional:
        if fee_candidates:
            rule.shipping_fee = fee_candidates[0]
        elif default_fee is not None:
            rule.shipping_fee = default_fee
        else:
            # 무료 조건은 알지만 기본 배송비를 모르면 확인 필요
            rule.fee_known = False
            confidence = 0.4
    elif is_free_word:
        rule.shipping_fee = 0
    elif fee_candidates:
        rule.shipping_fee = fee_candidates[0]
    elif default_fee is not None:
        rule.shipping_fee = default_fee
        confidence = 0.6
    else:
        rule.fee_known = False
        confidence = 0.0

    return rule, confidence
