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


def _low_base_kwargs(**overrides) -> dict:
    """clamp 100 に当たらない低めのベース (trust=50, body=True, 情報ボーナス少)。"""
    kw = dict(
        source_trust_score=50,
        has_product_match=False,
        has_apply_start=False,
        has_apply_end=False,
        has_result_at=False,
        has_retailer=False,
        has_store=False,
        has_url=False,
        sales_type_known=True,
        body_extracted=True,
        title_only=False,
    )
    kw.update(overrides)
    return kw


def test_cross_source_single_other_source_adds_5():
    base = compute_confidence(**_low_base_kwargs(cross_source_count=0))
    with_one = compute_confidence(**_low_base_kwargs(cross_source_count=1))
    assert with_one - base == 5


def test_cross_source_two_or_more_adds_15():
    base = compute_confidence(**_low_base_kwargs(cross_source_count=0))
    with_two = compute_confidence(**_low_base_kwargs(cross_source_count=2))
    assert with_two - base == 15


def test_cross_source_three_same_as_two():
    # 閾値は 2+ 固定。3 でも加点は 15 のまま。
    with_two = compute_confidence(**_low_base_kwargs(cross_source_count=2))
    with_three = compute_confidence(**_low_base_kwargs(cross_source_count=3))
    assert with_two == with_three


def test_twitter_solo_stays_unconfirmed_but_with_corroboration_confirmed():
    """Twitter 単独 (trust=80) では confirmed 相当にならないが、
    2+ ソース corroboration があれば 90 以上になる。"""
    # Twitter 単独: trust=80, body_extracted=False, title_only=True, 最小情報
    solo = compute_confidence(
        source_trust_score=80,
        has_product_match=False, has_apply_start=False, has_apply_end=False,
        has_result_at=False, has_retailer=True, has_store=True,
        has_url=True, sales_type_known=True,
        body_extracted=False, title_only=True,
        cross_source_count=0,
    )
    # 80 + 2 + 2 + 2 + 5 - 20(title_only) = 71
    assert solo < 90
    # 2+ ソース corroboration で +15
    corr = compute_confidence(
        source_trust_score=80,
        has_product_match=False, has_apply_start=False, has_apply_end=False,
        has_result_at=False, has_retailer=True, has_store=True,
        has_url=True, sales_type_known=True,
        body_extracted=False, title_only=True,
        cross_source_count=2,
    )
    assert corr == solo + 15
