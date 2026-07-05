"""
sample_data.py - ONE clearly-labeled SAMPLE/DEMO dataset used ONLY to let the
API/UI be demoed while real scraping is blocked or JS-rendered (see
realforeclose.py / grantstreet.py for why live scraping is not currently
functional against the real portals).

Every record produced here:
  - has is_demo_data = True
  - has raw_scraped_json containing {"data_source": "SAMPLE_DEMO_DATA_NOT_REAL"}
  - has notes prefixed "[DEMO DATA - NOT REAL]"
  - uses a fictional Hillsborough county, FL setting

This data must NEVER be presented to a user as real auction data. It exists
purely so the ranking/scoring UI has something realistic-looking to render.
"""
from datetime import datetime, timedelta

DEMO_MARKER = "SAMPLE_DEMO_DATA_NOT_REAL"
NOTES_PREFIX = "[DEMO DATA - NOT REAL] "


def _demo_properties():
    base_date = datetime.utcnow() + timedelta(days=14)
    return [
        dict(
            case_number="2026-CA-000123",
            county="Hillsborough",
            sale_date=base_date,
            owner_name="Jane A. Sample",
            address="1234 Demo Oak St, Tampa, FL 33602",
            parcel_id="U-19-29-18-1ZZ-000001-00001.0",
            legal_description="LOT 1 BLOCK 1 DEMO SUBDIVISION",
            property_type="Single Family",
            beds=3, baths=2.0, sqft=1650, year_built=1998,
            final_judgment=185000.00, opening_bid=185000.00,
            assessed_value=245000.00, market_value=310000.00,
            plaintiff_name="Demo Bank N.A.", plaintiff_type="bank",
            occupancy_status="occupied", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=2100.00, code_liens=0.0, flood_zone="X",
            insurance_estimate=1800.00, bankruptcy_flag=False,
            hoa_balance=0.0, redemption_notes="",
        ),
        dict(
            case_number="2026-CA-000456",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=1),
            owner_name="Marcus T. Fictional",
            address="5678 Placeholder Ave, Brandon, FL 33511",
            parcel_id="U-07-30-20-2ZZ-000002-00002.0",
            legal_description="LOT 2 BLOCK 2 DEMO SUBDIVISION",
            property_type="Townhouse",
            beds=2, baths=2.5, sqft=1300, year_built=2005,
            final_judgment=95000.00, opening_bid=95000.00,
            assessed_value=175000.00, market_value=220000.00,
            plaintiff_name="Sunshine HOA Collections", plaintiff_type="HOA-COA",
            occupancy_status="vacant", lien_priority_status="junior_position",
            senior_lien_survives=True,
            taxes_owed=1400.00, code_liens=500.0, flood_zone="AE",
            insurance_estimate=2400.00, bankruptcy_flag=False,
            hoa_balance=8200.00, redemption_notes="Owner may have redemption rights until sale certification.",
        ),
        dict(
            case_number="2026-CA-000789",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=2),
            owner_name="Estate of Fictitious Person",
            address="900 Notreal Blvd, Tampa, FL 33610",
            parcel_id="U-23-28-19-3ZZ-000003-00003.0",
            legal_description="LOT 3 BLOCK 3 DEMO SUBDIVISION",
            property_type="Single Family",
            beds=4, baths=3.0, sqft=2400, year_built=1985,
            final_judgment=210000.00, opening_bid=210000.00,
            assessed_value=380000.00, market_value=460000.00,
            plaintiff_name="Placeholder Mortgage Servicing LLC", plaintiff_type="servicer",
            occupancy_status="unknown", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=3200.00, code_liens=0.0, flood_zone="X",
            insurance_estimate=2200.00, bankruptcy_flag=False,
            hoa_balance=0.0, redemption_notes="",
        ),
        dict(
            case_number="2026-CA-001012",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=3),
            owner_name="Fake Investments Trust",
            address="42 Simulation Way, Riverview, FL 33578",
            parcel_id="U-01-30-19-4ZZ-000004-00004.0",
            legal_description="LOT 4 BLOCK 4 DEMO SUBDIVISION",
            property_type="Single Family",
            beds=3, baths=2.0, sqft=1800, year_built=2012,
            final_judgment=145000.00, opening_bid=145000.00,
            assessed_value=210000.00, market_value=255000.00,
            plaintiff_name="Coastal Tax Certificates LLC", plaintiff_type="tax_cert",
            occupancy_status="occupied", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=6800.00, code_liens=0.0, flood_zone="AE",
            insurance_estimate=2600.00, bankruptcy_flag=True,
            hoa_balance=0.0, redemption_notes="Active bankruptcy case - automatic stay may apply.",
        ),
        dict(
            case_number="2026-CA-001345",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=4),
            owner_name="No Such Person",
            address="17 Imaginary Ct, Plant City, FL 33563",
            parcel_id="U-11-27-21-5ZZ-000005-00005.0",
            legal_description="LOT 5 BLOCK 5 DEMO SUBDIVISION",
            property_type="Manufactured Home",
            beds=3, baths=2.0, sqft=1450, year_built=1992,
            final_judgment=60000.00, opening_bid=60000.00,
            assessed_value=95000.00, market_value=110000.00,
            plaintiff_name="Demo Bank N.A.", plaintiff_type="bank",
            occupancy_status="vacant", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=900.00, code_liens=1200.0, flood_zone="X",
            insurance_estimate=1200.00, bankruptcy_flag=False,
            hoa_balance=0.0, redemption_notes="",
        ),
        dict(
            case_number="2026-CA-001678",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=5),
            owner_name="Sample & Sample Holdings",
            address="303 Testcase Terrace, Tampa, FL 33629",
            parcel_id="U-05-29-18-6ZZ-000006-00006.0",
            legal_description="LOT 6 BLOCK 6 DEMO SUBDIVISION",
            property_type="Condominium",
            beds=2, baths=2.0, sqft=1100, year_built=2001,
            final_judgment=130000.00, opening_bid=130000.00,
            assessed_value=190000.00, market_value=340000.00,
            plaintiff_name="Bayshore Condo Association", plaintiff_type="HOA-COA",
            occupancy_status="occupied", lien_priority_status="junior_position",
            senior_lien_survives=True,
            taxes_owed=1750.00, code_liens=0.0, flood_zone="AE",
            insurance_estimate=3100.00, bankruptcy_flag=False,
            hoa_balance=14500.00, redemption_notes="",
        ),
        dict(
            case_number="2026-CA-001901",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=6),
            owner_name="Demo Family Revocable Trust",
            address="88 Prototype Pl, Tampa, FL 33615",
            parcel_id="U-14-28-17-7ZZ-000007-00007.0",
            legal_description="LOT 7 BLOCK 7 DEMO SUBDIVISION",
            property_type="Single Family",
            beds=4, baths=2.5, sqft=2100, year_built=2015,
            final_judgment=250000.00, opening_bid=250000.00,
            assessed_value=410000.00, market_value=520000.00,
            plaintiff_name="Placeholder Mortgage Servicing LLC", plaintiff_type="servicer",
            occupancy_status="occupied", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=4100.00, code_liens=0.0, flood_zone="X",
            insurance_estimate=2900.00, bankruptcy_flag=False,
            hoa_balance=0.0, redemption_notes="",
        ),
        dict(
            case_number="2026-CA-002234",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=7),
            owner_name="Ghost Ownership LLC",
            address="215 Dummy Dr, Seffner, FL 33584",
            parcel_id="U-29-27-20-8ZZ-000008-00008.0",
            legal_description="LOT 8 BLOCK 8 DEMO SUBDIVISION",
            property_type="Single Family",
            beds=3, baths=2.0, sqft=1550, year_built=1978,
            final_judgment=88000.00, opening_bid=88000.00,
            assessed_value=150000.00, market_value=175000.00,
            plaintiff_name="Private Lender Capital Group", plaintiff_type="private_lender",
            occupancy_status="unknown", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=2600.00, code_liens=800.0, flood_zone="X",
            insurance_estimate=1900.00, bankruptcy_flag=False,
            hoa_balance=0.0, redemption_notes="",
        ),
        dict(
            case_number="2026-CA-002567",
            county="Hillsborough",
            sale_date=base_date + timedelta(days=8),
            owner_name="Illustrative Owner II",
            address="76 Fictional Fields Ln, Lutz, FL 33549",
            parcel_id="U-33-26-19-9ZZ-000009-00009.0",
            legal_description="LOT 9 BLOCK 9 DEMO SUBDIVISION",
            property_type="Single Family",
            beds=5, baths=4.0, sqft=3200, year_built=2018,
            final_judgment=380000.00, opening_bid=380000.00,
            assessed_value=520000.00, market_value=650000.00,
            plaintiff_name="Demo Bank N.A.", plaintiff_type="bank",
            occupancy_status="occupied", lien_priority_status="first_position",
            senior_lien_survives=False,
            taxes_owed=5200.00, code_liens=0.0, flood_zone="X",
            insurance_estimate=3400.00, bankruptcy_flag=False,
            hoa_balance=0.0, redemption_notes="",
        ),
    ]


def seed_sample_data(db_session):
    """
    Insert the fictional demo dataset into the properties table if it is
    empty. Safe to call at startup - no-ops if properties already exist.
    """
    from models import Property  # local import avoids circular import

    existing_count = db_session.query(Property).count()
    if existing_count > 0:
        return 0

    inserted = 0
    for rec in _demo_properties():
        market_value = rec.get("market_value") or 0
        final_judgment = rec.get("final_judgment") or 0
        equity_spread = market_value - final_judgment

        prop = Property(
            case_number=rec["case_number"],
            county=rec["county"],
            sale_date=rec["sale_date"],
            owner_name=rec["owner_name"],
            address=rec["address"],
            parcel_id=rec["parcel_id"],
            legal_description=rec["legal_description"],
            property_type=rec["property_type"],
            beds=rec["beds"],
            baths=rec["baths"],
            sqft=rec["sqft"],
            year_built=rec["year_built"],
            final_judgment=final_judgment,
            opening_bid=rec["opening_bid"],
            assessed_value=rec["assessed_value"],
            market_value=market_value,
            plaintiff_name=rec["plaintiff_name"],
            plaintiff_type=rec["plaintiff_type"],
            occupancy_status=rec["occupancy_status"],
            lien_priority_status=rec["lien_priority_status"],
            senior_lien_survives=rec["senior_lien_survives"],
            taxes_owed=rec["taxes_owed"],
            code_liens=rec["code_liens"],
            flood_zone=rec["flood_zone"],
            insurance_estimate=rec["insurance_estimate"],
            comps_json=None,
            bankruptcy_flag=rec["bankruptcy_flag"],
            redemption_notes=rec["redemption_notes"],
            hoa_balance=rec["hoa_balance"],
            rehab_estimate_user_input=None,
            notes=NOTES_PREFIX + "Fictional record generated for UI/API demo purposes only.",
            flag_status="none",
            source_url="https://hillsborough.realforeclose.com (NOT ACTUALLY SCRAPED)",
            raw_scraped_json={"data_source": DEMO_MARKER},
            is_demo_data=True,
            last_scraped_at=datetime.utcnow(),
            equity_spread=equity_spread,
            composite_score=None,
        )
        db_session.add(prop)
        inserted += 1

    db_session.commit()
    return inserted
