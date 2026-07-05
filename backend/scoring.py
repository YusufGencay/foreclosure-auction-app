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


def _score_crime_rate(prop) -> Dict[str, Any]:
    zip_code = None
    if prop.address:
        parts = prop.address.strip().split()
        if parts and parts[-1].isdigit() and len(parts[-1]) == 5:
            zip_code = parts[-1]

    crime_rate = get_crime_rate(zip_code)
    if crime_rate is None:
        return {"raw_value": None, "normalized_score": 0.0, "status": "unavailable"}
    return {"raw_value": crime_rate, "normalized_score": 0.0, "status": "available"}


def _score_lien_priority(prop, warnings: List[str]) -> Dict[str, Any]:
    penalty_triggered = False
    reasons = []

    if (prop.plaintiff_type or "").strip() in ("HOA-COA", "HOA", "COA"):
        penalty_triggered = True
        reasons.append("plaintiff is an HOA/COA (junior lienholder; senior liens likely survive the sale)")

    if prop.senior_lien_survives:
        penalty_triggered = True
        reasons.append("senior_lien_survives is True (a superior lien will remain on title after sale)")

    if penalty_triggered:
        warnings.append(
            "LIEN PRIORITY RISK: " + "; ".join(reasons) +
            ". This can mean the buyer inherits a mortgage or other senior "
            "obligation not extinguished by this sale - verify title carefully."
        )
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


def _score_flood_zone(prop) -> Dict[str, Any]:
    existing = (prop.flood_zone or "").strip()
    if existing and existing.lower() not in ("unknown", ""):
        # High-risk zones per FEMA convention start with A or V.
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
    if prop.bankruptcy_flag:
        warnings.append(
            "BANKRUPTCY FLAG: an active or recent bankruptcy filing is "
            "associated with this property/owner. An automatic stay may "
            "delay or void this sale - verify case status before bidding."
        )
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
# Phase 2: 0-100 ranking formula.
#
# rank = (deal_quality * 0.5) + (risk_score * 0.5), each sub-score already
# normalized to 0-100 before combining. This is a separate, investor-facing
# 0-100 figure from composite_score above (which stays an unbounded,
# signed weighted sum used for the raw component breakdown/UI warnings) -
# ranking_score is what drives the dashboard's default sort.
# ---------------------------------------------------------------------------

# Risk-side components pulled from the existing scoring engine's component
# breakdown. Deliberately excludes equity_spread (deal quality is computed
# separately below, from real third-party estimates rather than the
# assessed-value-based market_value field) and absorption_rate (an honest
# placeholder with no data source, not a risk signal).
RISK_COMPONENT_KEYS = (
    "lien_priority",
    "bankruptcy",
    "taxes_owed",
    "code_liens",
    "flood_zone",
    "crime_rate",
)


def _compute_deal_quality_subscore(prop) -> Optional[float]:
    """
    gap = (avg_of_available_estimates - final_judgment) / avg_of_available_estimates
    A bigger gap (final judgment far below what the property is actually
    worth) means more built-in equity at the auction price - a better
    deal - so it's normalized to a HIGHER 0-100 score.

    Uses whichever of zillow_estimate/realtor_estimate/redfin_estimate are
    actually populated (never fabricates a missing one). Returns None if
    there isn't at least one real estimate and a final_judgment to compare
    it against - the caller falls back to risk-score-only in that case,
    per spec, rather than guessing a deal-quality figure.
    """
    estimates = [
        e for e in (prop.zillow_estimate, prop.realtor_estimate, prop.redfin_estimate)
        if e is not None and e > 0
    ]
    if not estimates:
        return None

    final_judgment = getattr(prop, "final_judgment", None)
    if final_judgment is None:
        return None

    avg_estimate = sum(estimates) / len(estimates)
    if avg_estimate <= 0:
        return None

    gap = (avg_estimate - final_judgment) / avg_estimate
    clamped = max(-1.0, min(1.0, gap))
    return (clamped + 1.0) * 50.0


def _compute_risk_subscore(component_breakdown: Dict[str, Any]) -> float:
    """
    Weighted-average the existing scoring engine's risk-related component
    scores (each already normalized to [-1, 1]) into a single [-1, 1]
    composite, then rescale to 0-100 where HIGHER = LOWER risk (so it
    combines intuitively with deal quality - bigger number is always
    better for both halves of the ranking formula).

    If every risk weight is configured to 0 (an investor could zero them
    all out via PUT /api/weights), there's no risk signal to weight by, so
    this returns a neutral 50.0 rather than dividing by zero or guessing.
    """
    weighted_sum = 0.0
    total_weight = 0.0
    for key in RISK_COMPONENT_KEYS:
        comp = component_breakdown.get(key)
        if not comp:
            continue
        weight = comp.get("weight", 0.0)
        if not weight:
            continue
        weighted_sum += comp.get("normalized_score", 0.0) * weight
        total_weight += abs(weight)

    if total_weight == 0:
        composite = 0.0
    else:
        composite = weighted_sum / total_weight

    composite = max(-1.0, min(1.0, composite))
    return (composite + 1.0) * 50.0


def compute_ranking_score(property_row, weights: Dict[str, float]) -> float:
    """
    property_row: a Property ORM instance (or any object with the same
                  attribute names).
    weights: dict of component_key -> weight (float), the same
             score_weights-backed dict passed to compute_score().

    Returns a 0-100 float: 50% deal quality (real third-party estimates vs.
    final judgment) + 50% risk (existing lien/bankruptcy/tax/code-lien/
    flood/crime scoring engine, rescaled). If no third-party estimates are
    available yet (enrich hasn't run / all three scrapers came back None),
    the deal-quality half is dropped and the rank is the risk score alone,
    per spec - never a fabricated deal-quality figure.
    """
    score_result = compute_score(property_row, weights)
    risk_score = _compute_risk_subscore(score_result["component_breakdown"])
    deal_score = _compute_deal_quality_subscore(property_row)

    if deal_score is None:
        return round(risk_score, 2)

    return round(deal_score * 0.5 + risk_score * 0.5, 2)
