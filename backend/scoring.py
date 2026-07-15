"""
scoring.py - Composite scoring engine for foreclosure auction properties.

compute_score(property_row, weights) -> dict with:
  - composite_score: float
  - component_breakdown: dict of component_key -> {raw_value, normalized_score, weight, contribution}
  - warnings: list[str]

Weights are read from the score_weights DB table (re-weightable via
GET/PUT /api/weights) rather than hardcoded, so users can tune the model.
"""
import os
from typing import Any, Dict, List, Optional

import requests

from config import CRIME_DATA_API_KEY, FEMA_API_BASE_URL

# --- Component score bounds: all normalized components are clamped to [-1, 1]
# before weighting, so warnings-driven penalties can meaningfully offset
# positive equity_spread scores regardless of absolute dollar magnitudes. ---

EQUITY_SPREAD_STRONG_THRESHOLD = 200_000.0
LIEN_PRIORITY_PENALTY = -1.0  # large negative, offsets most positive equity score
BANKRUPTCY_PENALTY = -0.6


def _score_equity_spread(prop) -> Dict[str, Any]:
    market_value = prop.market_value or 0.0
    final_judgment = prop.final_judgment or 0.0
    spread = market_value - final_judgment  # raw dollar value, always shown

    if spread >= EQUITY_SPREAD_STRONG_THRESHOLD:
        normalized = 1.0
    elif spread <= 0:
        normalized = -1.0
    else:
        # Linear scale between 0 and the strong threshold.
        normalized = (spread / EQUITY_SPREAD_STRONG_THRESHOLD) * 2 - 1
        normalized = max(-1.0, min(1.0, normalized))

    return {"raw_value": spread, "normalized_score": normalized}


def _score_absorption_rate(prop) -> Dict[str, Any]:
    """
    PLACEHOLDER: No free/public data source currently exists for
    neighborhood absorption rate (months-of-inventory) that this tool
    integrates with. Left as null with a neutral (0) score component so it
    does not silently bias the composite score. A future integration could
    pull from a paid MLS/market-data feed.
    """
    return {"raw_value": None, "normalized_score": 0.0, "placeholder": True}


def get_crime_rate(zip_code: Optional[str]) -> Optional[float]:
    """
    Attempts a real call to the FBI Crime Data API (Crime Data Explorer,
    https://api.usa.gov/crime/fbi/cde/) for the given ZIP code's
    surrounding agency/area. Requires an api.data.gov key
    (CRIME_DATA_API_KEY). The FBI CDE API is organized by ORI (agency) or
    state/city, not directly by ZIP, so a production implementation would
    need a ZIP->ORI or ZIP->county mapping step; that mapping is not
    implemented here.

    Returns a numeric crime rate if a real API call succeeds, otherwise
    None (never fabricated).
    """
    if not CRIME_DATA_API_KEY or not zip_code:
        return None
    try:
        # Example endpoint shape (state/agency summary); real usage requires
        # resolving zip_code -> ORI/state first, which is out of scope here.
        url = "https://api.usa.gov/crime/fbi/cde/summarized/state/FL/violent-crime"
        resp = requests.get(
            url,
            params={"API_KEY": CRIME_DATA_API_KEY, "type": "counts"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Real parsing would extract a specific figure; without a confirmed
        # ZIP->ORI mapping we cannot honestly attribute a number to this
        # specific property, so we return None rather than guess.
        if not data:
            return None
        return None
    except Exception:
        return None


# Letter-grade -> normalized [-1, 1] score, worst (F) to best (A+).
# crimegrade.org's convention (Phase C.1, 2026-07-13): A+ is safest.
CRIME_GRADE_SCORES = {
    "A+": 1.0, "A": 0.8, "A-": 0.6,
    "B+": 0.4, "B": 0.2, "B-": 0.0,
    "C+": -0.2, "C": -0.4, "C-": -0.6,
    "D+": -0.7, "D": -0.8, "D-": -0.9,
    "F": -1.0,
}


def _score_crime_rate(prop) -> Dict[str, Any]:
    # Prefer the real crimegrade.org letter grade fetched via
    # GET /api/properties/{id}/enrich (Phase C.1, 2026-07-13) - replaces
    # the never-provisioned FBI Crime Data API key path below, which stays
    # only as a fallback for records that haven't been enriched yet.
    grade = (getattr(prop, "crime_grade", None) or "").strip().upper()
    if grade and grade in CRIME_GRADE_SCORES:
        return {
            "raw_value": grade,
            "normalized_score": CRIME_GRADE_SCORES[grade],
            "status": "available",
            "source": "crimegrade.org",
        }

    zip_code = None
    if prop.address:
        parts = prop.address.strip().split()
        if parts and parts[-1].isdigit() and len(parts[-1]) == 5:
            zip_code = parts[-1]

    crime_rate = get_crime_rate(zip_code)
    if crime_rate is None:
        return {"raw_value": None, "normalized_score": 0.0, "status": "unavailable"}
    return {"raw_value": crime_rate, "normalized_score": 0.0, "status": "available"}


def _lien_priority_warning_text(prop) -> Optional[str]:
    """
    Pure warning-text derivation, no scoring side effects - shared by the
    legacy compute_score() component below (Phase 4 keeps composite_score/
    component_breakdown around for the existing detail-view score block)
    and the new Phase 4 profit-first compute_score_explanation(), which
    treats lien priority as a warning-only signal that never touches the
    number (per spec, 2026-07-13 - the investor explicitly chose loud
    warning badges over score-capping for this).
    """
    reasons = []
    if (getattr(prop, "plaintiff_type", None) or "").strip() in ("HOA-COA", "HOA", "COA"):
        reasons.append("plaintiff is an HOA/COA (junior lienholder; senior liens likely survive the sale)")
    if getattr(prop, "senior_lien_survives", False):
        reasons.append("senior_lien_survives is True (a superior lien will remain on title after sale)")
    if not reasons:
        return None
    return (
        "LIEN PRIORITY RISK: " + "; ".join(reasons) +
        ". This can mean the buyer inherits a mortgage or other senior "
        "obligation not extinguished by this sale - verify title carefully."
    )


def _bankruptcy_warning_text(prop) -> Optional[str]:
    """Pure warning-text derivation, no scoring side effects - see
    _lien_priority_warning_text's docstring for why this is split out."""
    if getattr(prop, "bankruptcy_flag", False):
        return (
            "BANKRUPTCY FLAG: an active or recent bankruptcy filing is "
            "associated with this property/owner. An automatic stay may "
            "delay or void this sale - verify case status before bidding."
        )
    return None


def _score_lien_priority(prop, warnings: List[str]) -> Dict[str, Any]:
    text = _lien_priority_warning_text(prop)
    if text:
        warnings.append(text)
        return {"raw_value": True, "normalized_score": LIEN_PRIORITY_PENALTY}
    return {"raw_value": False, "normalized_score": 0.2}


def get_flood_zone_info(address: Optional[str], lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    """
    Attempts to query FEMA's public OpenFEMA / National Flood Hazard Layer
    (NFHL) data. Documented public API base: FEMA_API_BASE_URL (default
    https://www.fema.gov/api/open/v2), e.g. the NfhlSpatialData /
    disaster-related datasets. A precise flood-zone-by-address lookup
    generally requires the NFHL ArcGIS REST map service
    (https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer)
    with lat/long, which needs a geocoding step this build does not
    implement. We attempt a best-effort call; if lat/long is not available
    or the call fails, we mark the field as a placeholder rather than
    guessing a flood zone.
    """
    if lat is None or lng is None:
        return {"flood_zone": "unknown / verify manually", "source": "not attempted (no lat/long)"}
    try:
        url = f"{FEMA_API_BASE_URL}/DisasterDeclarationsSummaries"
        resp = requests.get(url, params={"$top": 1}, timeout=10)
        if resp.status_code == 200:
            return {"flood_zone": "unknown / verify manually", "source": url, "note": "endpoint reachable but NFHL zone-by-point lookup not implemented"}
    except Exception:
        pass
    return {"flood_zone": "unknown / verify manually", "source": "attempt failed"}


FLOOD_ZONE_PLACEHOLDER_VALUES = ("unknown", "unknown / verify manually", "")


def _score_flood_zone(prop) -> Dict[str, Any]:
    existing = (prop.flood_zone or "").strip()
    if existing and existing.lower() not in FLOOD_ZONE_PLACEHOLDER_VALUES:
        # High-risk zones per FEMA convention start with A or V (e.g. "AE",
        # "VE", "A1-30"); "X" and similar are minimal-risk. A real value
        # here now normally comes from the live FEMA NFHL lookup in
        # scrapers/flood_zone.py (Phase C.2, 2026-07-13), triggered via
        # GET /api/properties/{id}/enrich, rather than only ever being
        # placeholder text.
        high_risk = existing.upper().startswith(("A", "V"))
        return {
            "raw_value": existing,
            "normalized_score": -0.3 if high_risk else 0.1,
        }
    info = get_flood_zone_info(prop.address)
    return {"raw_value": info["flood_zone"], "normalized_score": 0.0, "placeholder": True}


def _score_taxes_owed(prop) -> Dict[str, Any]:
    taxes = prop.taxes_owed or 0.0
    # Proportional penalty: scaled against a $10k reference point.
    normalized = max(-1.0, -(taxes / 10_000.0))
    return {"raw_value": taxes, "normalized_score": normalized}


def _score_code_liens(prop) -> Dict[str, Any]:
    liens = prop.code_liens or 0.0
    normalized = max(-1.0, -(liens / 10_000.0))
    return {"raw_value": liens, "normalized_score": normalized}


def _score_bankruptcy(prop, warnings: List[str]) -> Dict[str, Any]:
    text = _bankruptcy_warning_text(prop)
    if text:
        warnings.append(text)
        return {"raw_value": True, "normalized_score": BANKRUPTCY_PENALTY}
    return {"raw_value": False, "normalized_score": 0.0}


def _score_hoa_balance(prop) -> Dict[str, Any]:
    balance = prop.hoa_balance or 0.0
    normalized = max(-1.0, -(balance / 15_000.0))
    return {"raw_value": balance, "normalized_score": normalized}


COMPONENT_FUNCS = {
    "equity_spread": lambda prop, warnings: _score_equity_spread(prop),
    "absorption_rate": lambda prop, warnings: _score_absorption_rate(prop),
    "crime_rate": lambda prop, warnings: _score_crime_rate(prop),
    "lien_priority": lambda prop, warnings: _score_lien_priority(prop, warnings),
    "taxes_owed": lambda prop, warnings: _score_taxes_owed(prop),
    "code_liens": lambda prop, warnings: _score_code_liens(prop),
    "flood_zone": lambda prop, warnings: _score_flood_zone(prop),
    "bankruptcy": lambda prop, warnings: _score_bankruptcy(prop, warnings),
    "hoa_balance": lambda prop, warnings: _score_hoa_balance(prop),
}


def compute_score(property_row, weights: Dict[str, float]) -> Dict[str, Any]:
    """
    property_row: a Property ORM instance (or any object with the same
                  attribute names).
    weights: dict of component_key -> weight (float), typically loaded from
             the score_weights DB table.
    """
    warnings: List[str] = []
    breakdown: Dict[str, Any] = {}
    composite = 0.0

    for key, func in COMPONENT_FUNCS.items():
        weight = weights.get(key, 0.0)
        result = func(property_row, warnings)
        normalized = result.get("normalized_score", 0.0)
        contribution = normalized * weight
        composite += contribution
        breakdown[key] = {
            **result,
            "weight": weight,
            "contribution": contribution,
        }

    return {
        "composite_score": round(composite, 4),
        "component_breakdown": breakdown,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Phase 4 (2026-07-13): profit-first 85/15 ranking formula, REPLACING the old
# Phase 2 formula (50% deal quality vs. real estimates + 50% weighted risk
# component average). This is a separate, investor-facing 0-100 figure from
# composite_score above (which stays around unbounded/signed for the legacy
# component-breakdown detail view) - ranking_score is what drives the
# dashboard's default sort.
#
# Explicit spec from the investor (2026-07-13): the score should heavily
# prioritize money to be made - final judgment (or opening bid) vs.
# estimated value, bigger gap = better, 100 = best. Location/schools/crime/
# flood etc. affect AT MOST 15% of the total. Lien-priority and bankruptcy
# do NOT affect the number at all anymore - they're warning-only (loud UI
# badges), a deliberate choice the investor made over score-capping so a
# single flag can't silently bury an otherwise-great deal in the sort order.
#
#   cost_basis   = final_judgment if set else opening_bid
#   est_value    = avg of available (zillow_estimate, realtor_estimate,
#                  redfin_estimate) else assessed_value (fallback, labeled)
#   known_costs  = (taxes_owed or 0) + (code_liens or 0) + (hoa_balance or 0)
#   profit_gap   = (est_value - cost_basis - known_costs) / est_value
#   profit_score = clamp(profit_gap, 0, 1) * 100
#   location_score = 0-100 avg of whichever of {crime_grade, flood_zone,
#                    market_conditions} have real data - missing components
#                    are EXCLUDED from the average, not counted as neutral
#   ranking_score = 0.85 * profit_score + 0.15 * location_score
#
# If neither final_judgment nor opening_bid exists, or no est_value source
# exists at all (no estimates AND no assessed_value), ranking_score is None
# ("unscored") rather than a fabricated number - the API/UI show "unscored -
# missing value data" and sort these last. If profit_score is computable but
# location_score has zero data (typical before /enrich has ever run for a
# property), the score falls back to profit-only (100% weight on profit)
# rather than guessing a location figure or leaving 15% of the score blank -
# this is the same "drop the sub-score, don't guess" pattern the old Phase 2
# formula used for missing deal-quality data.
# ---------------------------------------------------------------------------

PROFIT_WEIGHT = 0.85
LOCATION_WEIGHT = 0.15


def _get_cost_basis(prop) -> "tuple[Optional[float], Optional[str]]":
    final_judgment = getattr(prop, "final_judgment", None)
    if final_judgment is not None:
        return final_judgment, "final_judgment"
    opening_bid = getattr(prop, "opening_bid", None)
    if opening_bid is not None:
        return opening_bid, "opening_bid"
    return None, None


def _get_estimated_value(prop) -> Dict[str, Any]:
    """
    Averages whichever of zillow_estimate/realtor_estimate/redfin_estimate
    are actually populated and positive (never fabricates a missing one).
    Falls back to the county assessed_value (clearly labeled) only if none
    of the three third-party estimates are available - per spec, so a
    property never goes unscored purely because /enrich hasn't run yet.
    """
    sources = []
    values = []
    for label, val in (
        ("zillow", getattr(prop, "zillow_estimate", None)),
        ("realtor", getattr(prop, "realtor_estimate", None)),
        ("redfin", getattr(prop, "redfin_estimate", None)),
    ):
        if val is not None and val > 0:
            sources.append(label)
            values.append(val)

    if values:
        return {
            "est_value": sum(values) / len(values),
            "value_sources": sources,
            "used_assessed_fallback": False,
        }

    assessed = getattr(prop, "assessed_value", None)
    if assessed is not None and assessed > 0:
        return {
            "est_value": assessed,
            "value_sources": ["assessed_value"],
            "used_assessed_fallback": True,
        }

    return {"est_value": None, "value_sources": [], "used_assessed_fallback": False}


def _compute_profit_gap(prop) -> Dict[str, Any]:
    cost_basis, cost_basis_source = _get_cost_basis(prop)
    value_info = _get_estimated_value(prop)
    est_value = value_info["est_value"]
    known_costs = (
        (getattr(prop, "taxes_owed", None) or 0.0)
        + (getattr(prop, "code_liens", None) or 0.0)
        + (getattr(prop, "hoa_balance", None) or 0.0)
    )

    result: Dict[str, Any] = {
        "cost_basis": cost_basis,
        "cost_basis_source": cost_basis_source,
        "est_value": est_value,
        "value_sources": value_info["value_sources"],
        "used_assessed_fallback": value_info["used_assessed_fallback"],
        "known_costs": known_costs,
        "profit_gap_dollars": None,
        "profit_gap_pct": None,
        "profit_score": None,
    }

    if cost_basis is None or est_value is None or est_value <= 0:
        return result

    profit_gap_dollars = est_value - cost_basis - known_costs
    profit_gap_pct = profit_gap_dollars / est_value  # can exceed 1.0 or go negative
    clamped = max(0.0, min(1.0, profit_gap_pct))  # negative gap -> 0, per spec

    result["profit_gap_dollars"] = profit_gap_dollars
    result["profit_gap_pct"] = profit_gap_pct
    result["profit_score"] = clamped * 100.0
    return result


def _compute_location_subscore(prop) -> Dict[str, Any]:
    """
    0-100 average of whichever of {crime_grade, flood_zone,
    market_conditions} actually have real (non-placeholder) data. A
    component with no data is excluded from the average entirely - it is
    NOT counted as a neutral/50 value, per spec, since that would silently
    reward properties with no location data the same as ones confirmed
    safe.
    """
    components: Dict[str, Any] = {}

    grade = (getattr(prop, "crime_grade", None) or "").strip().upper()
    if grade and grade in CRIME_GRADE_SCORES:
        components["crime_grade"] = {
            "raw_value": grade,
            "score_0_100": (CRIME_GRADE_SCORES[grade] + 1.0) * 50.0,
            "source": "crimegrade.org",
        }

    flood = (getattr(prop, "flood_zone", None) or "").strip()
    if flood and flood.lower() not in FLOOD_ZONE_PLACEHOLDER_VALUES:
        high_risk = flood.upper().startswith(("A", "V"))
        components["flood_zone"] = {
            "raw_value": flood,
            "score_0_100": 15.0 if high_risk else 85.0,
            "source": getattr(prop, "flood_zone_source", None) or "FEMA National Flood Hazard Layer (NFHL)",
        }

    market_conditions = (getattr(prop, "market_conditions", None) or "").strip().lower()
    if market_conditions in ("buyer_market", "seller_market"):
        # A buyer's market favors the investor (more negotiating room, softer
        # comps) - scored favorably; a seller's market is the opposite.
        components["market_conditions"] = {
            "raw_value": market_conditions,
            "score_0_100": 100.0 if market_conditions == "buyer_market" else 0.0,
            "source": "Redfin (zip-level market classification)",
        }

    if not components:
        return {"location_score": None, "components": components}

    avg = sum(c["score_0_100"] for c in components.values()) / len(components)
    return {"location_score": round(avg, 2), "components": components}


def compute_score_explanation(property_row, weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Phase 4/5 (2026-07-13): the full structured breakdown behind
    ranking_score, computed once server-side so Phase 5's
    ScoreExplainer.jsx can show the investor the EXACT numbers the formula
    used (which estimate sources were available, whether the
    assessed-value fallback kicked in, which location components had real
    data, and the lien-priority/bankruptcy warnings that do NOT affect the
    number) without ever duplicating the formula in JS.

    `weights` is accepted only so this shares a call signature with the
    legacy compute_score() below (used to harvest lien/bankruptcy warning
    text without triggering that function's other, network-calling
    components) - it has no effect on the 85/15 split, which is fixed per
    spec, not user-adjustable.
    """
    warnings: List[str] = []
    lien_text = _lien_priority_warning_text(property_row)
    if lien_text:
        warnings.append(lien_text)
    bankruptcy_text = _bankruptcy_warning_text(property_row)
    if bankruptcy_text:
        warnings.append(bankruptcy_text)

    profit = _compute_profit_gap(property_row)
    location = _compute_location_subscore(property_row)

    if profit["profit_score"] is None:
        if profit["cost_basis"] is None:
            reason = "unscored - missing value data (no final judgment or opening bid on record)"
        else:
            reason = (
                "unscored - no estimated value available (Zillow/Realtor/Redfin "
                "estimates and the county assessed value are all missing)"
            )
        return {
            "ranking_score": None,
            "unscored_reason": reason,
            "profit": profit,
            "location": location,
            "warnings": warnings,
            "profit_weight": PROFIT_WEIGHT,
            "location_weight": LOCATION_WEIGHT,
        }

    profit_score = profit["profit_score"]
    if location["location_score"] is None:
        # No location data at all yet (typical pre-/enrich) - fall back to a
        # profit-only score rather than guessing the missing 15%, same
        # "drop the sub-score, don't fabricate" pattern the old formula used.
        ranking_score = profit_score
        location = dict(location, note=(
            "no location data yet (crime grade / flood zone / market "
            "conditions all missing) - score is profit-only until /enrich runs"
        ))
        profit_weight_applied, location_weight_applied = 1.0, 0.0
    else:
        ranking_score = PROFIT_WEIGHT * profit_score + LOCATION_WEIGHT * location["location_score"]
        profit_weight_applied, location_weight_applied = PROFIT_WEIGHT, LOCATION_WEIGHT

    ranking_score = max(0.0, min(100.0, ranking_score))

    return {
        "ranking_score": round(ranking_score, 2),
        "unscored_reason": None,
        "profit": profit,
        "location": location,
        "warnings": warnings,
        "profit_weight": profit_weight_applied,
        "location_weight": location_weight_applied,
    }


def compute_ranking_score(property_row, weights: Optional[Dict[str, float]] = None) -> Optional[float]:
    """
    Phase 4 rewrite (2026-07-13): now the profit-first 85/15 formula (see
    compute_score_explanation() above for the full breakdown and rationale).
    Returns just the ranking_score float, or None if unscored (missing both
    a cost basis and any estimated value) - callers that need the full
    breakdown (e.g. the /enrich endpoint's score_explanation field) should
    call compute_score_explanation() directly instead of recomputing.

    `weights` is accepted only for backward compatibility with existing call
    sites (main.py's _rescore_all, the /enrich endpoint) - it is no longer
    used. The old per-component score_weights table still drives the legacy
    compute_score()/composite_score above, but the 85/15 profit/location
    split is fixed per spec, not adjustable via that table (see
    WeightsPanel.jsx, updated to show this as read-only).
    """
    return compute_score_explanation(property_row, weights)["ranking_score"]
