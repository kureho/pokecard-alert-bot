from pokebot.lib.confidence import (
    ConfidenceLevel,
    EvidenceFields,
    build_evidence_summary,
    classify_confirmation,
    compute_confidence,
    evaluate_evidence,
    map_to_legacy_status,
)


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


# ===== evaluate_evidence (Dispatch1) =====


def _fields(**kw) -> EvidenceFields:
    base = dict(
        has_apply_start=True,
        has_apply_end=True,
        has_result_at=False,
        has_purchase_window=False,
        has_retailer=True,
        has_store=False,
        has_product_match=False,
        has_url=True,
        sales_type_known=True,
        cross_source_count=0,
        title_only=False,
        product_name_ambiguous=False,
        conflicting_existing=False,
    )
    base.update(kw)
    return EvidenceFields(**base)


def test_evaluate_evidence_entry_page_strong():
    """entry_page + 応募期間あり → confirmed_strong (base 90 + 加点)。"""
    level, score = evaluate_evidence(
        evidence_type="entry_page", fields=_fields()
    )
    assert level == ConfidenceLevel.CONFIRMED_STRONG
    # base 90 + 10(apply_start) + 5(apply_end) + 5(retailer) + 2(url) + 5(sales_type_known) = 117 → clamp 100
    assert score == 100


def test_evaluate_evidence_official_notice_reaches_strong_threshold():
    """official_notice + 主要情報揃い → confirmed_strong (ちょうど 85)。"""
    level, score = evaluate_evidence(
        evidence_type="official_notice", fields=_fields()
    )
    # base 60 + 10 + 5 + 5 + 2 + 5 = 87 → confirmed_strong
    assert score == 87
    assert level == ConfidenceLevel.CONFIRMED_STRONG


def test_evaluate_evidence_rss_item_is_candidate():
    """rss_item base=15 は全加点を得ても medium 閾値にも届かない。"""
    level, score = evaluate_evidence(
        evidence_type="rss_item", fields=_fields()
    )
    # 15 + 10 + 5 + 5 + 2 + 5 = 42
    assert score == 42
    assert level == ConfidenceLevel.CANDIDATE


def test_evaluate_evidence_social_post_is_candidate():
    level, score = evaluate_evidence(
        evidence_type="social_post", fields=_fields()
    )
    # 10 + 10 + 5 + 5 + 2 + 5 = 37
    assert level == ConfidenceLevel.CANDIDATE
    assert score == 37


def test_evaluate_evidence_unknown_type_is_low_candidate():
    """evidence_type='unknown' は base=5 の最弱扱い。"""
    level, score = evaluate_evidence(
        evidence_type="unknown", fields=_fields()
    )
    assert level == ConfidenceLevel.CANDIDATE
    assert score < 60


def test_evaluate_evidence_sales_type_unknown_heavy_penalty():
    """sales_type_known=False で -20 ペナルティ。"""
    level, score = evaluate_evidence(
        evidence_type="official_notice",
        fields=_fields(sales_type_known=False),
    )
    # 60 + 10 + 5 + 5 + 2 - 20 = 62 → medium
    assert score == 62
    assert level == ConfidenceLevel.CONFIRMED_MEDIUM


def test_evaluate_evidence_title_only_penalty():
    level, score = evaluate_evidence(
        evidence_type="official_notice",
        fields=_fields(title_only=True),
    )
    # 60 + 10 + 5 + 5 + 2 + 5 - 20 = 67 → medium
    assert score == 67
    assert level == ConfidenceLevel.CONFIRMED_MEDIUM


def test_evaluate_evidence_no_dates_penalty():
    """apply_start_at も apply_end_at も無ければ -15。"""
    level, score = evaluate_evidence(
        evidence_type="official_notice",
        fields=_fields(has_apply_start=False, has_apply_end=False),
    )
    # 60 + 5 + 2 + 5 - 15 = 57 → candidate
    assert score == 57
    assert level == ConfidenceLevel.CANDIDATE


def test_evaluate_evidence_conflicting_always_conflicting():
    """conflicting_existing=True なら score に関係なく CONFLICTING。"""
    level, _ = evaluate_evidence(
        evidence_type="entry_page", fields=_fields(conflicting_existing=True)
    )
    assert level == ConfidenceLevel.CONFLICTING


def test_evaluate_evidence_cross_source_boost():
    """cross_source_count >= 2 で +10。"""
    level, score = evaluate_evidence(
        evidence_type="official_notice",
        fields=_fields(cross_source_count=2),
    )
    # 60 + 10 + 5 + 5 + 2 + 5 + 10 = 97
    assert score == 97
    assert level == ConfidenceLevel.CONFIRMED_STRONG


def test_map_to_legacy_status():
    assert map_to_legacy_status(ConfidenceLevel.CONFIRMED_STRONG) == "confirmed"
    assert map_to_legacy_status(ConfidenceLevel.CONFIRMED_MEDIUM) == "unconfirmed"
    assert map_to_legacy_status(ConfidenceLevel.CANDIDATE) == "unconfirmed"
    assert map_to_legacy_status(ConfidenceLevel.CONFLICTING) == "conflicting"


def test_build_evidence_summary_includes_label():
    s = build_evidence_summary(
        evidence_type="entry_page",
        has_apply_period=True,
        has_result=True,
        sales_type="lottery",
    )
    assert "抽選受付ページ" in s
    assert "応募期間明記" in s
    assert "結果発表あり" in s
    assert "種別:lottery" in s


def test_build_evidence_summary_skips_unknown_sales_type():
    s = build_evidence_summary(
        evidence_type="rss_item",
        has_apply_period=False,
        has_result=False,
        sales_type="unknown",
    )
    assert "RSS" in s
    assert "種別" not in s


def test_confidence_level_values_are_stable_strings():
    """DB 保存時に使う string 値が壊れないことを明示的に固定。"""
    assert ConfidenceLevel.CONFIRMED_STRONG.value == "confirmed_strong"
    assert ConfidenceLevel.CONFIRMED_MEDIUM.value == "confirmed_medium"
    assert ConfidenceLevel.CANDIDATE.value == "candidate"
    assert ConfidenceLevel.CONFLICTING.value == "conflicting"
