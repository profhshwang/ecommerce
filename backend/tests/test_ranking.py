"""최저가 정렬 / 매칭 테스트 (TC-03, TC-04, TC-07)."""
from app.matching import expand_query, rule_match_score
from app.models import Product, ShippingRule, SourceKind
from app.ranking import dedupe, market_stats, score_and_rank


def mk(name, price, fee=0, known=True, source="naver", ext=""):
    return Product(
        source=source, source_name=source, kind=SourceKind.RETAIL, external_id=ext or f"{name}-{price}",
        name=name, url=f"https://x/{ext or name}{price}", price=price,
        shipping=ShippingRule(shipping_fee=fee, fee_known=known),
    )


def test_lowest_effective_price_includes_shipping():
    q = "삼성 USB-C 케이블"
    items = [mk("삼성 USB-C 케이블", 9000, 3000), mk("삼성 USB-C 케이블 1m", 10500, 0), mk("삼성 USB-C 케이블 정품", 11000, 2500)]
    top, _ = score_and_rank(q, items, top_n=20)
    assert [p.effective_price for p in top] == [10500, 12000, 13500]
    assert top[0].rank == 1 and top[0].shipping_fee == 0


def test_top_n_limit():
    items = [mk("갤럭시 버즈3", 100000 + i * 10, ext=str(i)) for i in range(50)]
    top, allm = score_and_rank("갤럭시 버즈3", items, top_n=20)
    assert len(top) == 20 and len(allm) == 50


def test_irrelevant_accessory_filtered():
    items = [mk("아이폰 15 케이스", 5000), mk("아이폰 15 128GB", 1100000)]
    top, _ = score_and_rank("아이폰 15 128GB", items, min_match_score=60)
    assert [p.name for p in top] == ["아이폰 15 128GB"]


def test_model_number_match_and_mismatch():
    assert rule_match_score("소니 WH-1000XM5", "SONY 소니 WH1000XM5 블랙") >= 90
    assert rule_match_score("소니 WH-1000XM5", "소니 WH-1000XM4 헤드폰") < 70


def test_unknown_shipping_sorted_after_known_at_same_price():
    top, _ = score_and_rank("물병", [mk("물병", 1000, known=False, ext="a"), mk("물병", 1000, 0, ext="b")])
    assert top[0].shipping.fee_known and top[0].price_confidence > top[1].price_confidence


def test_dedupe_and_stats():
    a = mk("물병", 1000, ext="1")
    items = dedupe([a, a.model_copy(), mk("물병", 2000, ext="2"), mk("물병", 3000, ext="3")])
    assert len(items) == 3
    for p in items:
        p.finalize()
    s = market_stats(items)
    assert (s.min_price, s.max_price, s.median_price, s.count) == (1000, 3000, 2000.0, 3)


def test_expand_query_capped():
    qs = expand_query("아이폰 15 케이스")
    assert qs[0] == "아이폰 15 케이스" and "아이폰15 케이스" in qs and len(qs) <= 3
