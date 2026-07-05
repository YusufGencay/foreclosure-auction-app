"""
Seed logic:
  - counties: upserted from config/counties.yaml every startup (cache table).
  - properties: 2-3 SAMPLE (is_sample_data=True) rows per county, inserted
    ONLY if the properties table is currently empty. This gives the UI
    content to render before any real scraping has happened. These rows are
    clearly fake and MUST NOT be confused with live data anywhere downstream.
  - score_weights: sane defaults, upserted (won't clobber user edits because
    we only insert missing keys).
"""
import random
from datetime import datetime, timedelta

import yaml

from backend.config import COUNTIES_YAML_PATH
from backend.models import County, Property, ScoreWeight

PLAINTIFF_TYPES = ["bank", "servicer", "HOA-COA", "tax_cert", "private_lender", "other"]
OCCUPANCY = ["owner_occupied", "vacant", "tenant_occupied", "unknown"]
PROPERTY_TYPES = ["single_family", "condo", "townhouse", "multi_family", "vacant_land"]
LIEN_STATUSES = ["first_position", "junior_lien", "unknown"]
FLOOD_ZONES = [None, "AE", "X", "VE"]

DEFAULT_WEIGHTS = [
    ("equity_spread_bonus", 50.0, "Bonus applied when market_value - final_judgment >= $200,000."),
    ("senior_lien_penalty", -80.0, "Large penalty when senior_lien_survives is True; buyer inherits a surviving senior lien, largely negating apparent equity spread."),
    ("taxes_owed_weight", -0.001, "Per-dollar penalty for outstanding taxes_owed."),
    ("code_liens_weight", -0.002, "Per-dollar penalty for outstanding code_liens."),
    ("hoa_balance_weight", -0.0005, "Per-dollar penalty for outstanding hoa_balance."),
    ("flood_zone_penalty", -20.0, "Flat penalty applied when flood_zone is a hazardous zone (e.g. AE/VE)."),
    ("bankruptcy_penalty", -30.0, "Flat penalty applied when bankruptcy_flag is True."),
]


def load_counties_yaml():
    with open(COUNTIES_YAML_PATH, "r") as f:
        data = yaml.safe_load(f)
    return data.get("counties", [])


def seed_counties(db):
    counties = load_counties_yaml()
    for c in counties:
        existing = db.query(County).filter(County.name == c["name"]).first()
        if existing:
            existing.region = c.get("region")
            existing.platform = c.get("platform")
            existing.portal_url = c.get("portal_url")
            existing.confirmed = c.get("confirmed", False)
            existing.notes = c.get("notes")
        else:
            db.add(
                County(
                    name=c["name"],
                    region=c.get("region"),
                    platform=c.get("platform"),
                    portal_url=c.get("portal_url"),
                    confirmed=c.get("confirmed", False),
                    notes=c.get("notes"),
                )
            )
    db.commit()
    return counties


def seed_weights(db):
    for key, weight, desc in DEFAULT_WEIGHTS:
        existing = db.query(ScoreWeight).filter(ScoreWeight.key == key).first()
        if not existing:
            db.add(ScoreWeight(key=key, weight=weight, description=desc))
    db.commit()


def _fake_case_number(county, i):
        yr = random.choice([2023, 2024, 2025])
        return f"{yr}-CA-{random.randint(1000, 9999):04d}-{county[:2].upper()}{i}"


def seed_sample_properties(db, counties):
    if db.query(Property).count() > 0:
        return 0  # already have data, don't duplicate

    rng = random.Random(42)  # deterministic sample data
    inserted = 0
    for c in counties:
        county_name = c["name"]
        n = rng.choice([2, 3])
        for i in range(n):
            plaintiff_type = PLAINTIFF_TYPES[(inserted + i) % len(PLAINTIFF_TYPES)]
            occupancy = OCCUPANCY[(inserted + i) % len(OCCUPANCY)]
            senior_survives = bool((inserted + i) % 3 == 0)
            bankruptcy = bool((inserted + i) % 5 == 0)
            lien_status = LIEN_STATUSES[(inserted + i) % len(LIEN_STATUSES)]
            flood = FLOOD_ZONES[(inserted + i) % len(FLOOD_ZONES)]

            final_judgment = rng.uniform(80_000, 350_000)
            market_value = final_judgment + rng.uniform(-40_000, 260_000)
            assessed_value = market_value * rng.uniform(0.7, 0.95)
            opening_bid = final_judgment * rng.uniform(0.6, 1.0)

            sale_date = datetime.utcnow() + timedelta(days=rng.randint(3, 45))

            prop = Property(
                case_number=_fake_case_number(county_name, i),
                county=county_name,
                sale_date=sale_date,
                owner_name=f"SAMPLE Owner {county_name} {i+1}",
                address=f"{100 + inserted} SAMPLE St, {county_name}, FL",
                parcel_id=f"SAMPLE-PARCEL-{county_name[:3].upper()}-{i+1}",
                legal_description="SAMPLE DATA - not live scraped. Placeholder legal description.",
                property_type=PROPERTY_TYPES[(inserted + i) % len(PROPERTY_TYPES)],
                beds=rng.choice([2, 3, 4, None]),
                baths=rng.choice([1.0, 1.5, 2.0, 2.5, None]),
                sqft=rng.choice([1100, 1450, 1800, 2200, None]),
                year_built=rng.choice([1975, 1988, 1999, 2005, 2015, None]),
                final_judgment=round(final_judgment, 2),
                opening_bid=round(opening_bid, 2),
                assessed_value=round(assessed_value, 2),
                market_value=round(market_value, 2),
                plaintiff_name=f"SAMPLE Plaintiff {plaintiff_type}",
                plaintiff_type=plaintiff_type,
                occupancy_status=occupancy,
                lien_priority_status=lien_status,
                senior_lien_survives=senior_survives,
                taxes_owed=round(rng.uniform(0, 15_000), 2),
                code_liens=round(rng.uniform(0, 8_000), 2),
                flood_zone=flood,
                insurance_estimate=round(rng.uniform(800, 4500), 2),
                comps_json=None,
                bankruptcy_flag=bankruptcy,
                redemption_notes="SAMPLE DATA - not live scraped.",
                hoa_balance=round(rng.uniform(0, 6000), 2) if plaintiff_type == "HOA-COA" else round(rng.uniform(0, 1500), 2),
                rehab_estimate_user_input=None,
                notes="SAMPLE DATA - not live scraped. Seeded for UI/testing purposes only.",
                flag_status="none",
                source_url=c.get("portal_url"),
                raw_scraped_json=None,
                last_scraped_at=None,
                is_sample_data=True,
            )
            db.add(prop)
            inserted += 1
    db.commit()
    return inserted


def run_seed(db):
    counties = seed_counties(db)
    seed_weights(db)
    n = seed_sample_properties(db, counties)
    return {"counties_loaded": len(counties), "sample_properties_inserted": n}
