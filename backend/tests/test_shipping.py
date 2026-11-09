"""배송비 파서/계산 테스트 (TC-05)."""
import pytest

from app.shipping import parse_shipping_text


@pytest.mark.parametrize(
    "text,fee,amt,qty,known",
    [
        ("무료배송", 0, None, None, True),
        ("배송비 3,000원", 3000, None, None, True),
        ("배송비 2,500원 (30,000원 이상 구매시 무료)", 2500, 30000, None, True),
        ("3만원 이상 무료배송 (미만 2,500원)", 2500, 30000, None, True),
        ("19,800원 이상 무료배송, 미만 3,000원", 3000, 19800, None, True),
        ("10개 이상 주문시 무료, 배송비 3,000원", 3000, None, 10, True),
        ("조건부 무료배송", 0, None, None, False),
        ("", 0, None, None, False),
        ("로켓배송 무료배송", 0, None, None, True),
    ],
)
def test_parse(text, fee, amt, qty, known):
    rule, _ = parse_shipping_text(text)
    assert rule.fee_known is known
    if known:
        assert rule.shipping_fee == fee
    assert rule.free_threshold_amount == amt
    assert rule.free_threshold_quantity == qty


def test_amount_threshold_recalculates_by_quantity():
    rule, _ = parse_shipping_text("배송비 3,000원 (30,000원 이상 구매시 무료)")
    assert rule.fee_for(12000, 1) == 3000
    assert rule.fee_for(12000, 2) == 3000
    assert rule.fee_for(12000, 3) == 0  # 36,000원 ≥ 30,000원


def test_quantity_threshold():
    rule, _ = parse_shipping_text("배송비 3,000원 (10개 이상 주문시 무료)")
    assert rule.fee_for(1000, 9) == 3000
    assert rule.fee_for(1000, 10) == 0


def test_per_quantity_bundles():
    rule, _ = parse_shipping_text("20개마다 배송비 3,000원")
    assert rule.per_quantity == 20
    assert rule.fee_for(500, 20) == 3000
    assert rule.fee_for(500, 21) == 6000


def test_default_fee_used_when_text_has_no_amount():
    rule, _ = parse_shipping_text("택배", default_fee=2500)
    assert rule.shipping_fee == 2500 and rule.fee_known
