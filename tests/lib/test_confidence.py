from pokebot.lib.confidence import classify_confirmation, compute_confidence


def test_base_equals_trust_score_minus_unknown_penalty():
    # title_only(default True) + no body + no sales_type_known
    # → 90 - 25(unknown) - 20(title_only) = 45
    score = compute_confidence(
        source_trust_score=90,
        has_product_match=False, has_apply_start=False, has_apply_end=False,
        has_result_at=False, has_retailer=False, has_store=False,
        has_url=False, sales_type_known=False,
    )
    assert score == 45


def test_body_extracted_with_all_bonuses_caps_100():
    score = compute_confidence(
        source_trust_score=100,
        has_product_match=True, has_apply_start=True, has_apply_end=True,
        has_result_at=True, has_retailer=True, has_store=True,
        has_url=True, sales_type_known=True,
        body_extracted=True, title_only=False,
    )
    assert score == 100


def test_title_only_penalty_applied():
    # body 無しだと title_only -20 が効く
    # base(80) + 5+5+5+2+2+5 = 104 - 20(title_only) = 84 → clamp 84
    score = compute_confidence(
        source_trust_score=80,
        has_product_match=True, has_apply_start=True, has_apply_end=True,
        has_result_at=False, has_retailer=True, has_store=False,
        has_url=True, sales_type_known=True,
        body_extracted=False, title_only=True,
    )
    assert score == 84


def test_unknown_sales_type_is_heavily_penalized():
    # base(50) + 5(body) + 5+5+5+2+2 - 25(unknown) = 49
    score = compute_confidence(
        source_trust_score=50,
        has_product_match=True, has_apply_start=True, has_apply_end=True,
        has_result_at=False, has_retailer=True, has_store=False,
        has_url=True, sales_type_known=False,
        body_extracted=True, title_only=False,
    )
    assert score == 49


def test_classify_confirmation():
    assert classify_confirmation(confidence_score=95, source_trust_score=100) == "confirmed"
    assert classify_confirmation(confidence_score=80, source_trust_score=95) == "unconfirmed"
    assert classify_confirmation(confidence_score=50, source_trust_score=100) == "unconfirmed"
