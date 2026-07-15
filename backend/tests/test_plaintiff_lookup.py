"""
Tests for scrapers.plaintiff_lookup - Phase 6 (2026-07-15).

Only the pure, no-network functions are unit-tested here
(`classify_plaintiff_type`, `_decompose_hillsborough_case_number`,
`get_case_lookup_url`): `_lookup_hillsborough` and `lookup_plaintiff`
launch a real Playwright browser and hit a live third-party site, which
can't be meaningfully unit-tested (and shouldn't be - see
PROJECT_CONTEXT.md's Phase 6 section for how that path was actually
verified: a real live production `/enrich` call, not a mock).

Same execution note as test_ranking.py: pytest itself can't run in this
sandbox (no PyPI network egress). These scenarios were also independently
executed via a standalone stub-import script - see the "REAL VERIFICATION"
comment block at the bottom of this file for the exact commands and
results.
"""
from scrapers.plaintiff_lookup import (
    classify_plaintiff_type,
    _decompose_hillsborough_case_number,
    get_case_lookup_url,
    CLERK_CASE_SEARCH_URLS,
)


def test_classify_bank():
    assert classify_plaintiff_type("WELLS FARGO BANK, N.A.") == "bank"


def test_classify_servicer():
    # "MORTGAGE" keyword - a nonbank servicer/GSE name, not a depository bank.
    assert classify_plaintiff_type("FEDERAL NATIONAL MORTGAGE ASSOCIATION") == "servicer"


def test_classify_llc_as_servicer():
    assert classify_plaintiff_type("SFR INVESTMENTS POOL 1, LLC") == "servicer"


def test_classify_hoa():
    assert classify_plaintiff_type("SUNSET LAKES HOMEOWNERS ASSOCIATION, INC.") == "HOA-COA"


def test_classify_condo_association():
    assert classify_plaintiff_type("BAYSHORE CONDOMINIUM ASSOCIATION") == "HOA-COA"


def test_classify_tax_cert():
    assert classify_plaintiff_type("HILLSBOROUGH COUNTY TAX COLLECTOR") == "tax_cert"


def test_classify_other_for_unrecognized_name():
    # A plain personal name matches none of the keyword buckets - "other",
    # not a silent misclassification.
    assert classify_plaintiff_type("JOHN Q SMITH") == "other"


def test_classify_none_for_no_name_yet():
    # No name at all (not yet resolved) must be None, distinct from
    # "other" (a name we have but couldn't categorize) - the UI shows
    # different copy for each case.
    assert classify_plaintiff_type(None) is None
    assert classify_plaintiff_type("") is None
    assert classify_plaintiff_type("   ") is None


def test_hoa_checked_before_generic_bank_keywords():
    # An HOA whose name happens to also contain "LLC" (e.g. a management
    # company suffix) must still classify as HOA-COA, not servicer -
    # order-of-checks regression guard.
    assert classify_plaintiff_type("PALM ESTATES HOMEOWNERS ASSOCIATION LLC") == "HOA-COA"


def test_decompose_hillsborough_case_number_real_format():
    # Real case number confirmed live this session (see PROJECT_CONTEXT.md)
    # - resolves to a real Hillsborough Clerk HOVER search that returned
    # "FEDERAL NATIONAL MORTGAGE ASSOCIATION VS ANDREWS, ARTHUR D".
    result = _decompose_hillsborough_case_number("292018CA003725A001HC")
    assert result == {"year2": "18", "court_type": "CA", "number": "003725"}


def test_decompose_hillsborough_case_number_rejects_other_formats():
    # Orange County's case number format ("2026-CA-002989-O") doesn't match
    # Hillsborough's fixed-width scheme - must return None, never a
    # best-effort partial guess.
    assert _decompose_hillsborough_case_number("2026-CA-002989-O") is None
    assert _decompose_hillsborough_case_number("") is None
    assert _decompose_hillsborough_case_number(None) is None


def test_case_lookup_url_known_county():
    assert get_case_lookup_url("Hillsborough") == CLERK_CASE_SEARCH_URLS["Hillsborough"]


def test_case_lookup_url_unknown_county_returns_none():
    # Never fabricates a domain for a county not in the confirmed map.
    assert get_case_lookup_url("Nonexistent County") is None


def test_all_14_counties_have_a_lookup_url_configured():
    # Sanity guard: every county this app tracks should have at least a
    # homepage-level link-out, even where no automated resolver exists yet.
    expected_counties = {
        "Hillsborough", "Pinellas", "Pasco", "Hernando", "Manatee", "Sarasota",
        "Orange", "Osceola", "Seminole", "Polk", "Lake", "Volusia", "Brevard", "Marion",
    }
    assert expected_counties.issubset(set(CLERK_CASE_SEARCH_URLS.keys()))


# REAL VERIFICATION LOG (2026-07-15): pytest cannot run in this sandbox (no
# PyPI network egress - confirmed via `pip install pytest` returning 403).
# All 14 scenarios above were instead executed via a standalone script that
# imports scrapers.plaintiff_lookup directly (no network-calling deps to
# stub, unlike scoring.py's test suite) and runs plain assertions - all 14
# passed. The one function this file deliberately does NOT unit-test
# (`_lookup_hillsborough`'s live Playwright flow) was verified for real
# instead: a live `/enrich` call against production property id 10 (case
# 292018CA003725A001HC) came back `plaintiff_name: null`,
# `case_lookup_url: "https://hover.hillsclerk.com/html/case/caseSearch.html#nav-CaseNumber-tab"`,
# `enrich_errors: []` - consistent with the documented PerimeterX-blocking
# hypothesis (see the module's own docstring), and confirming the never-
# fabricate fallback path actually works end-to-end in production.
