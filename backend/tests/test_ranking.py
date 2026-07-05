"""
Tests for scoring.compute_ranking_score (Phase 2's 0-100 investor-facing
ranking formula: 50% deal quality + 50% risk, or risk-only if no
third-party estimates are available yet).

Rather than assert against numbers computed by re-running the function
under test, each scenario is built so the expected value can be derived by
hand:
  - "isolated risk" scenarios zero out every score_weights key except one,
    so the risk sub-score reduces to a single, known component.
  - "isolated deal quality" scenarios zero out every risk weight, which
    (per _compute_risk_subscore's zero-total-weight guard) forces a
    neutral risk_score of exactly 50.0, isolating the deal-quality half.
"""
from types import SimpleNamespace

from scoring import compute_ranking_score


# Every score_weights key zeroed out except where a scenario overrides one.
ZERO_WEIGHTS = {
    "equity_spread": 0.0,
    "absorption_rate": 0.0,
    "crime_rate": 0.0,
    "lien_priority": 0.0,
    "taxes_owed": 0.0,
    "code_liens": 0.0,
    "flood_zone": 0.0,
    "bankruptcy": 0.0,
    "hoa_balance": 0.0,
}


def _make_property(**overrides):
    defaults = dict(
        market_value=None,
        final_judgment=None,
        plaintiff_type=None,
        senior_lien_survives=False,
        address=None,
        taxes_owed=None,
        code_liens=None,
        flood_zone=None,
        bankruptcy_flag=False,
        hoa_balance=None,
        zillow_estimate=None,
        realtor_estimate=None,
        redfin_estimate=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_missing_estimates_falls_back_to_risk_only_high_risk():
    # Only bankruptcy carries any weight; bankruptcy_flag=True -> normalized
    # -0.6 (BANKRUPTCY_PENALTY), weight 1.0 -> composite = -0.6 exactly ->
    # risk_score = (-0.6 + 1) * 50 = 20.0. No estimates -> rank == risk_score.
    weights = dict(ZERO_WEIGHTS, bankruptcy=1.0)
    prop = _make_property(bankruptcy_flag=True, final_judgment=150_000)
    assert compute_ranking_score(prop, weights) == 20.0


def test_missing_estimates_falls_back_to_risk_only_low_risk():
    # Same isolated weighting, but no bankruptcy -> normalized 0.0 ->
    # composite = 0.0 -> risk_score = 50.0 -> rank == 50.0 exactly.
    weights = dict(ZERO_WEIGHTS, bankruptcy=1.0)
    prop = _make_property(bankruptcy_flag=False, final_judgment=150_000)
    assert compute_ranking_score(prop, weights) == 50.0


def test_high_deal_quality_zero_risk_weight():
    # All risk weights zeroed -> risk_score is neutral 50.0 regardless of
    # actual risk flags. final_judgment far below the estimate average ->
    # gap = (250,000 - 50,000) / 250,000 = 0.8 -> deal = (0.8+1)*50 = 90.0.
    # rank = 0.5*90 + 0.5*50 = 70.0.
    prop = _make_property(
        final_judgment=50_000,
        zillow_estimate=240_000,
        realtor_estimate=250_000,
        redfin_estimate=260_000,  # avg = 250,000
        bankruptcy_flag=True,  # irrelevant - risk weights are all zero
    )
    assert compute_ranking_score(prop, ZERO_WEIGHTS) == 70.0


def test_low_deal_quality_overpaying_zero_risk_weight():
    # final_judgment ABOVE the estimate average -> negative gap, clamped to
    # -1.0 -> deal = (-1+1)*50 = 0.0. rank = 0.5*0 + 0.5*50 = 25.0.
    prop = _make_property(
        final_judgment=400_000,
        zillow_estimate=200_000,
        realtor_estimate=200_000,
        redfin_estimate=200_000,
    )
    assert compute_ranking_score(prop, ZERO_WEIGHTS) == 25.0


def test_deal_quality_gap_clamped_for_extreme_overpay():
    # Wildly overpaying (final_judgment 10x the estimate) must clamp deal
    # quality to the same floor (0.0) as a merely-bad deal, not go negative
    # or blow up the scale. rank = 0.5*0 (clamped deal) + 0.5*50 (neutral
    # risk) = 25.0 - same as the merely-bad-deal scenario above.
    prop = _make_property(
        final_judgment=1_000_000,
        zillow_estimate=100_000,
        realtor_estimate=100_000,
        redfin_estimate=100_000,
    )
    assert compute_ranking_score(prop, ZERO_WEIGHTS) == 25.0


def test_neutral_deal_quality_when_judgment_equals_estimate():
    # gap = 0 -> deal = 50.0 exactly. Combined with neutral risk (50.0),
    # rank should be exactly 50.0.
    prop = _make_property(
        final_judgment=200_000,
        zillow_estimate=200_000,
        realtor_estimate=200_000,
        redfin_estimate=200_000,
    )
    assert compute_ranking_score(prop, ZERO_WEIGHTS) == 50.0


def test_partial_estimates_uses_only_available_data():
    # Only one of the three estimates is populated (enrich partially
    # succeeded) - deal quality must still be computed from what's
    # available rather than treated as fully missing.
    # gap = (250,000 - 125,000) / 250,000 = 0.5 -> deal = 75.0.
    # rank = 0.5*75 + 0.5*50(neutral risk) = 62.5.
    prop = _make_property(
        final_judgment=125_000,
        zillow_estimate=250_000,
        realtor_estimate=None,
        redfin_estimate=None,
    )
    assert compute_ranking_score(prop, ZERO_WEIGHTS) == 62.5


def test_mixed_moderate_deal_and_moderate_risk():
    # Isolated bankruptcy risk weight (risk_score = 20.0, per the first
    # test above) combined with a real, moderate deal-quality gap.
    # gap = (300,000 - 150,000) / 300,000 = 0.5 -> deal = 75.0.
    # rank = 0.5*75 + 0.5*20 = 47.5.
    weights = dict(ZERO_WEIGHTS, bankruptcy=1.0)
    prop = _make_property(
        bankruptcy_flag=True,
        final_judgment=150_000,
        zillow_estimate=300_000,
        realtor_estimate=300_000,
        redfin_estimate=300_000,
    )
    assert compute_ranking_score(prop, weights) == 47.5


def test_zero_or_negative_estimate_treated_as_missing():
    # A stray non-positive "estimate" (should never happen given the
    # scrapers' own sanity floors, but defensively) must not be treated as
    # real data - it's excluded, and if that leaves nothing usable, deal
    # quality falls back to None (risk-only), same as no estimates at all.
    weights = dict(ZERO_WEIGHTS, bankruptcy=1.0)
    prop = _make_property(
        bankruptcy_flag=False,
        final_judgment=100_000,
        zillow_estimate=0,
        realtor_estimate=None,
        redfin_estimate=None,
    )
    assert compute_ranking_score(prop, weights) == 50.0


def test_rank_always_within_0_100_bounds():
    # Sanity bound check across a spread of weight configs and extreme
    # property values - the formula must never escape [0, 100].
    scenarios = [
        _make_property(final_judgment=0, zillow_estimate=1, realtor_estimate=1, redfin_estimate=1,
                       bankruptcy_flag=True, taxes_owed=1_000_000, code_liens=1_000_000,
                       hoa_balance=1_000_000, senior_lien_survives=True, plaintiff_type="HOA-COA"),
        _make_property(final_judgment=10_000_000, zillow_estimate=1, realtor_estimate=1, redfin_estimate=1),
        _make_property(),  # nothing populated at all
    ]
    full_weights = {
        "equity_spread": 1.0, "absorption_rate": 0.0, "crime_rate": 0.3,
        "lien_priority": 1.0, "taxes_owed": 0.5, "code_liens": 0.4,
        "flood_zone": 0.3, "bankruptcy": 0.8, "hoa_balance": 0.5,
    }
    for prop in scenarios:
        score = compute_ranking_score(prop, full_weights)
        assert 0.0 <= score <= 100.0
