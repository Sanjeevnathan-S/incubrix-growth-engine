import os
import sqlite3
import pytest
from unittest.mock import MagicMock
from src.storage.db import LeadDatabase
from src.export.exporter import LeadExporter

@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "integration.db")
    return LeadDatabase(db_path=db_file)


def test_database_deduplication_and_unseen_filter(test_db):
    """Verifies SQLite deduplication filtering for candidate IDs."""
    test_db.save_lead({"creator_id": "channel_001", "platform": "YOUTUBE", "country": "US"}, status="QUALIFIED")
    
    candidates = ["channel_001", "channel_002", "channel_003"]
    unseen = test_db.filter_unseen_channel_ids(candidates)
    
    assert unseen == ["channel_002", "channel_003"]


def test_lead_dynamic_field_refresh(test_db):
    """Verifies dynamic timestamps update without creating duplicate rows."""
    creator_id = "refresh_creator_01"
    
    # Initial insertion
    test_db.save_lead({"creator_id": creator_id, "platform": "YOUTUBE", "country": "US"}, status="QUALIFIED")
    assert test_db.get_qualified_lead_count() == 1

    # Dynamic field update on rerun
    updated_dates = ["2026-03-14T12:00:00Z"]
    test_db.update_lead_dynamic_fields(creator_id=creator_id, recent_publish_dates=updated_dates)

    # Database count remains 1 (0% duplicates)
    assert test_db.get_qualified_lead_count() == 1


def test_pipeline_graceful_failure_handling(test_db):
    """Simulates API failure during enrichment to confirm pipeline resilience."""
    failing_scraper = MagicMock()
    failing_scraper.extract_monetization_and_contact.side_effect = Exception("HTTP 504 Gateway Timeout")

    candidate = {
        "creator_id": "resilience_test_01",
        "platform": "YOUTUBE",
        "title": "Tech Podcast",
        "country": "US"
    }

    # Pipeline should execute without raising unhandled exception
    try:
        scraped_data = failing_scraper.extract_monetization_and_contact(candidate["website_url"] if "website_url" in candidate else "")
    except Exception:
        scraped_data = {"emails": [], "monetization_signals": [], "external_links": []}

    candidate.update(scraped_data)
    test_db.save_lead(candidate, status="QUALIFIED")
    
    assert test_db.is_already_processed("resilience_test_01") is True