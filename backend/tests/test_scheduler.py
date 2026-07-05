"""
test_scheduler.py - scheduler registration + job execution tests for
Phase 2's twice-daily (06:00 / 18:00) auto-scrape.

Registration tests exercise main._register_scheduler_jobs() directly
against the module-level `main.scheduler` (a BackgroundScheduler that is
never .start()'d here - these tests only add/inspect jobs, they never let
APScheduler actually run one on a background thread, so nothing here can
accidentally hit a real network).

Job-execution tests call main.scrape_all_counties() directly (bypassing
the scheduler entirely, same as APScheduler would eventually do) against
an isolated in-memory SQLite session, with main._scrape_one_county mocked
out so no real scraper/Playwright code runs - this is purely testing that
scrape_all_counties() iterates every county and isolates per-county
failures, per the Phase 2 spec.
"""
import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from db import Base
from models import County


@pytest.fixture(autouse=True)
def _clean_scheduler_jobs():
    """Make sure no job leaks between tests (and that nothing here is ever
    left registered against the real scheduler after the test module
    finishes)."""
    main.scheduler.remove_all_jobs()
    yield
    main.scheduler.remove_all_jobs()


def _cron_field(trigger, name):
    for field in trigger.fields:
        if field.name == name:
            return str(field)
    return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def test_register_scheduler_jobs_adds_both_daily_jobs():
    main._register_scheduler_jobs()
    jobs = {job.id: job for job in main.scheduler.get_jobs()}

    assert set(jobs.keys()) == {"scrape_all_6am", "scrape_all_6pm"}


def test_register_scheduler_jobs_uses_correct_cron_times():
    main._register_scheduler_jobs()
    jobs = {job.id: job for job in main.scheduler.get_jobs()}

    assert _cron_field(jobs["scrape_all_6am"].trigger, "hour") == "6"
    assert _cron_field(jobs["scrape_all_6am"].trigger, "minute") == "0"
    assert _cron_field(jobs["scrape_all_6pm"].trigger, "hour") == "18"
    assert _cron_field(jobs["scrape_all_6pm"].trigger, "minute") == "0"


def test_register_scheduler_jobs_points_at_scrape_all_counties():
    main._register_scheduler_jobs()
    jobs = {job.id: job for job in main.scheduler.get_jobs()}

    assert jobs["scrape_all_6am"].func is main.scrape_all_counties
    assert jobs["scrape_all_6pm"].func is main.scrape_all_counties


def test_register_scheduler_jobs_is_idempotent(monkeypatch):
    # replace_existing=True should prevent duplicate jobs across repeated
    # registration (e.g. app restart). APScheduler only actually dedupes by
    # job id once the scheduler has started (pre-start, add_job() just
    # queues into an internal pending list without checking existing ids),
    # so this test swaps in its own scheduler instance and starts it
    # paused - jobs get registered for real, but nothing can ever fire.
    test_scheduler = BackgroundScheduler()
    monkeypatch.setattr(main, "scheduler", test_scheduler)
    test_scheduler.start(paused=True)
    try:
        main._register_scheduler_jobs()
        main._register_scheduler_jobs()
        assert len(test_scheduler.get_jobs()) == 2
    finally:
        test_scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------
def _isolated_session_factory():
    """A fresh in-memory SQLite DB, isolated from whatever real
    data/foreclosure.db this sandbox falls back to for other tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_scrape_all_counties_calls_scrape_one_county_per_county(monkeypatch):
    SessionFactory = _isolated_session_factory()
    db = SessionFactory()
    db.add(County(name="Hillsborough", platform="realforeclose", portal_url="https://hillsborough.realforeclose.com"))
    db.add(County(name="Pinellas", platform="realforeclose", portal_url="https://pinellas.realforeclose.com"))
    db.commit()
    db.close()

    monkeypatch.setattr(main, "SessionLocal", SessionFactory)

    calls = []

    def fake_scrape_one_county(db, county_row):
        calls.append(county_row.name)
        return main.ScrapeResult(success=True, records=[])

    monkeypatch.setattr(main, "_scrape_one_county", fake_scrape_one_county)

    main.scrape_all_counties()

    assert sorted(calls) == ["Hillsborough", "Pinellas"]


def test_scrape_all_counties_isolates_one_county_failure(monkeypatch):
    SessionFactory = _isolated_session_factory()
    db = SessionFactory()
    db.add(County(name="Hillsborough", platform="realforeclose", portal_url="https://hillsborough.realforeclose.com"))
    db.add(County(name="BrokenCounty", platform="realforeclose", portal_url="https://broken.realforeclose.com"))
    db.add(County(name="Pinellas", platform="realforeclose", portal_url="https://pinellas.realforeclose.com"))
    db.commit()
    db.close()

    monkeypatch.setattr(main, "SessionLocal", SessionFactory)

    calls = []

    def fake_scrape_one_county(db, county_row):
        calls.append(county_row.name)
        if county_row.name == "BrokenCounty":
            raise RuntimeError("simulated scraper crash")
        return main.ScrapeResult(success=True, records=[])

    monkeypatch.setattr(main, "_scrape_one_county", fake_scrape_one_county)

    # Must not raise, despite BrokenCounty's exception - and every other
    # county must still get its turn.
    main.scrape_all_counties()

    assert sorted(calls) == ["BrokenCounty", "Hillsborough", "Pinellas"]


def test_scrape_all_counties_handles_zero_counties_gracefully(monkeypatch):
    SessionFactory = _isolated_session_factory()
    monkeypatch.setattr(main, "SessionLocal", SessionFactory)

    calls = []
    monkeypatch.setattr(main, "_scrape_one_county", lambda db, c: calls.append(c.name))

    main.scrape_all_counties()  # no counties in DB - should just no-op

    assert calls == []
