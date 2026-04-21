from pokebot.lib.confidence import compute_confidence, classify_confirmation


def test_base_equals_trust_score():
    score = compute_confidence(
        source_trust_score=90,
        has_product_match=False, has_apply_start=False, has_apply_end=False,
        has_result_at=False, has_retailer=False, has_store=False,
        has_url=False, sales_type_known=False,
    )
    assert score == 90


def test_bonuses_add_up_capped():
    score = compute_confidence(
        source_trust_score=100,
        has_product_match=True, has_apply_start=True, has_apply_end=True,
        has_result_at=True, has_retailer=True, has_store=True,
        has_url=True, sales_type_known=True,
    )
    assert score == 100  # capped


def test_penalties_subtract():
    score = compute_confidence(
        source_trust_score=100,
        has_product_match=True, has_apply_start=False, has_apply_end=False,
        has_result_at=False, has_retailer=True, has_store=False,
        has_url=True, sales_type_known=False,
        product_name_ambiguous=True, date_missing=True,
    )
    # 100 + 5(product) + 2(retailer) + 2(url) = 109 → capped 100
    # -10(ambiguous) -10(date_missing) = 80
    assert score == 80


def test_classify_confirmation():
    assert classify_confirmation(confidence_score=95, source_trust_score=100) == "confirmed"
    assert classify_confirmation(confidence_score=80, source_trust_score=95) == "unconfirmed"
    assert classify_confirmation(confidence_score=50, source_trust_score=100) == "unconfirmed"
