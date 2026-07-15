"""
Tests for scoring.compute_ranking_score / compute_score_explanation - the
Phase 4 (2026-07-13) profit-first 85/15 ranking formula, which REPLACES the
old Phase 2 formula (50% deal quality + 50% weighted risk-component average)
tested by the previous version of this file.

New formula (see scoring.py's module docstring for the full spec):
  cost_basis   = final_judgment if set else opening_bid
  est_value    = avg of available (zillow_estimate, realtor_estimate,
                 redfin_estimate) else assessed_value (labeled fallback)
  known_costs  = (taxes_owed or 0) + (code_liens or 0) + (hoa_balance or 0)
  profit_gap   = (est_value - cost_basis - known_costs) / est_value
  profit_score = clamp(profit_gap, 0, 1) * 100
  location_score = 0-100 avg of whichever of {crime_grade, flood_zone,
                   market_conditions} have real data (missing ones excluded
                   from the average, not counted as neutral)
  ranking_score = 0.85 * profit_score + 0.15 * location_score, or
                  profit_score alone if there's no location data at all

Every scenario below is built so the expected value can be derived by hand
(comments show the arithmetic) rather than re-deriving the function under
test. `weights` (the old score_weights dict) is passed as `None` throughout
since the new formula no longer uses it.
"""
from types import SimpleNamespace

from scoring import compute_ranking_score, compute_score_explanation


def _make_property(**overrides):
    defaults = dict(
        final_judgment=None,
        opening_bid=None,
        assessed_value=None,
        zillow_estimate=None,
        realtor_estimate=None,
        redfin_estimate=None,
        taxes_owed=None,
        code_liens=None,
        hoa_balance=None,
        crime_grade=None,
        flood_zone=None,
        flood_zone_source=None,
        market_conditions=None,
        plaintiff_type=None,
        senior_lien_survives=False,
        bankruptcy_flag=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_no_estimate_falls_back_to_assessed_value():
    # No Zillow/Realtor/Redfin estimate -> falls back to county assessed
    # value, clearly labeled. cost_basis=150,000 (final_judgment),
    # est_value=200,000 (assessed_value fallback).
    # profit_gap = (200,000 - 150,000 - 0) / 200,000 = 0.25 -> profit_score = 25.0
    # No location data -> ranking_score falls back to profit-only = 25.0
    prop = _make_property(final_judgment=150_000, assessed_value=200_000)
    explanation = compute_score_explanation(prop)
    assert explanation["profit"]["used_assessed_fallback"] is True
    assert explanation["profit"]["value_sources"] == ["assessed_value"]
    assert explanation["profit"]["est_value"] == 200_000
    assert explanation["profit"]["profit_score"] == 25.0
    assert explanation["ranking_score"] == 25.0
    assert compute_ranking_score(prop) == 25.0


def test_negative_gap_clamped_to_zero():
    # Overpaying: cost_basis (300,000) exceeds est_value (200,000) ->
    # profit_gap = (200,000 - 300,000) / 200,000 = -0.5 -> clamped to 0.0
    # -> profit_score = 0.0, not a negative number.
    prop = _make_property(final_judgment=300_000, assessed_value=200_000)
    explanation = compute_score_explanation(prop)
    assert explanation["profit"]["profit_gap_pct"] == -0.5
    assert explanation["profit"]["profit_score"] == 0.0
    assert explanation["ranking_score"] == 0.0


def test_missing_cost_basis_is_unscored_null():
    # Neither final_judgment nor opening_bid on record -> ranking_score must
    # be null (never fabricated), with a reason naming the missing field.
    prop = _make_property(assessed_value=200_000)
    explanation = compute_score_explanation(prop)
    assert explanation["ranking_score"] is None
    assert "final judgment or opening bid" in explanation["unscored_reason"]
    assert compute_ranking_score(prop) is None


def test_missing_all_value_sources_is_unscored_null():
    # cost_basis exists but there's no estimate AND no assessed_value at
    # all - still null, with a different reason naming the missing value.
    prop = _make_property(final_judgment=100_000)
    explanation = compute_score_explanation(prop)
    assert explanation["ranking_score"] is None
    assert "estimated value" in explanation["unscored_reason"]


def test_location_partial_data_excluded_not_neutral():
    # Only crime_grade is populated (flood_zone/market_conditions missing).
    # location_score must equal the crime component alone (90.0), NOT be
    # diluted by averaging in a neutral 50 for the two missing components
    # (which would give (90+50+50)/3 = 63.33 instead).
    # crime "A" -> (0.8 + 1) * 50 = 90.0
    # profit: cost_basis=100,000, est_value=200,000 (zillow only) ->
    # gap = 100,000/200,000 = 0.5 -> profit_score = 50.0
    # ranking = 0.85*50 + 0.15*90 = 42.5 + 13.5 = 56.0
    prop = _make_property(
        final_judgment=100_000,
        zillow_estimate=200_000,
        crime_grade="A",
    )
    explanation = compute_score_explanation(prop)
    assert explanation["location"]["location_score"] == 90.0
    assert set(explanation["location"]["components"].keys()) == {"crime_grade"}
    assert explanation["ranking_score"] == 56.0


def test_full_location_combination_hand_computed():
    # All three location components present:
    #   crime "B"            -> (0.2 + 1) * 50 = 60.0
    #   flood "AE" (A-prefix, high risk) -> 15.0
    #   market "seller_market"           -> 0.0
    # location_score = (60 + 15 + 0) / 3 = 25.0
    # profit: cost_basis=100,000, est_value=200,000 -> gap=0.5 -> profit_score=50.0
    # ranking = 0.85*50 + 0.15*25 = 42.5 + 3.75 = 46.25
    prop = _make_property(
        final_judgment=100_000,
        zillow_estimate=200_000,
        crime_grade="B",
        flood_zone="AE",
        market_conditions="seller_market",
    )
    explanation = compute_score_explanation(prop)
    assert explanation["location"]["location_score"] == 25.0
    assert explanation["ranking_score"] == 46.25


def test_no_location_data_falls_back_to_profit_only():
    # No crime/flood/market data at all (typical before /enrich has ever
    # run) - ranking_score must equal profit_score exactly (100% weight),
    # NOT 0.85 * profit_score (which would silently punish every
    # not-yet-enriched property by discarding 15% of the score for free).
    prop = _make_property(final_judgment=100_000, zillow_estimate=200_000)
    explanation = compute_score_explanation(prop)
    assert explanation["location"]["location_score"] is None
    assert explanation["profit"]["profit_score"] == 50.0
    assert explanation["ranking_score"] == 50.0
    assert explanation["profit_weight"] == 1.0
    assert explanation["location_weight"] == 0.0


def test_opening_bid_used_when_final_judgment_missing():
    # cost_basis falls back to opening_bid when final_judgment is null.
    # gap = (100,000 - 80,000) / 100,000 = 0.2 -> profit_score = 20.0
    prop = _make_property(opening_bid=80_000, zillow_estimate=100_000)
    explanation = compute_score_explanation(prop)
    assert explanation["profit"]["cost_basis"] == 80_000
    assert explanation["profit"]["cost_basis_source"] == "opening_bid"
    assert explanation["ranking_score"] == 20.0


def test_known_costs_subtracted_from_profit():
    # taxes_owed + code_liens + hoa_balance = 20,000 known costs.
    # gap = (200,000 - 100,000 - 20,000) / 200,000 = 0.4 -> profit_score = 40.0
    prop = _make_property(
        final_judgment=100_000,
        zillow_estimate=200_000,
        taxes_owed=10_000,
        code_liens=5_000,
        hoa_balance=5_000,
    )
    explanation = compute_score_explanation(prop)
    assert explanation["profit"]["known_costs"] == 20_000
    assert explanation["ranking_score"] == 40.0


def test_lien_priority_and_bankruptcy_never_change_the_score():
    # Same profit/location inputs as test_no_estimate_falls_back_to_assessed_value
    # (ranking_score 25.0), but with every warning-triggering flag set -
    # the number must be IDENTICAL; only the warnings list should differ.
    clean = _make_property(final_judgment=150_000, assessed_value=200_000)
    flagged = _make_property(
        final_judgment=150_000,
        assessed_value=200_000,
        plaintiff_type="HOA-COA",
        senior_lien_survives=True,
        bankruptcy_flag=True,
    )
    clean_explanation = compute_score_explanation(clean)
    flagged_explanation = compute_score_explanation(flagged)

    assert clean_explanation["ranking_score"] == flagged_explanation["ranking_score"] == 25.0
    assert clean_explanation["warnings"] == []
    assert len(flagged_explanation["warnings"]) == 2
    assert any("LIEN PRIORITY" in w for w in flagged_explanation["warnings"])
    assert any("BANKRUPTCY" in w for w in flagged_explanation["warnings"])


def test_zero_or_negative_estimate_treated_as_missing():
    # A stray non-positive "estimate" must not be treated as real data - it
    # falls through to the assessed_value fallback (or null if that's also
    # missing), same as if no estimate had been scraped at all.
    prop = _make_property(final_judgment=100_000, zillow_estimate=0, assessed_value=150_000)
    explanation = compute_score_explanation(prop)
    assert explanation["profit"]["used_assessed_fallback"] is True
    assert explanation["profit"]["value_sources"] == ["assessed_value"]


def test_rank_always_within_0_100_bounds_or_null():
    # Sanity bound check across a spread of extreme property values - the
    # formula must never escape [0, 100], and must be null (never a
    # fabricated number) when there's truly nothing to compute from.
    scenarios = [
        _make_property(
            final_judgment=0, zillow_estimate=1, realtor_estimate=1, redfin_estimate=1,
            bankruptcy_flag=True, taxes_owed=1_000_000, code_liens=1_000_000,
            hoa_balance=1_000_000, senior_lien_survives=True, plaintiff_type="HOA-COA",
            crime_grade="F", flood_zone="VE", market_conditions="seller_market",
        ),
        _make_property(
            final_judgment=10_000_000, zillow_estimate=1, realtor_estimate=1, redfin_estimate=1,
            crime_grade="A+", flood_zone="X", market_conditions="buyer_market",
        ),
        _make_property(),  # nothing populated at all -> must be None, not a crash
    ]
    for prop in scenarios[:2]:
        score = compute_ranking_score(prop)
        assert 0.0 <= score <= 100.0
    assert compute_ranking_score(scenarios[2]) is None
