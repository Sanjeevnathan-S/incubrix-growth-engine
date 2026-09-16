import pytest
from datetime import datetime, timezone, timedelta
from src.filtering.activity_filter import ActivityFilter
from src.filtering.geo_filter import GeographicFilter
from src.export.exporter import LeadExporter

# ==============================================================================
# Unit Test Suite: Activity Filter Criteria
# ==============================================================================

def test_activity_filter_rule_a_30_day_volume():
    """Validates Rule A: Creator passes with >= 8 content items published within 30 days."""
    filter_obj = ActivityFilter(min_total_30_days=8)
    now = datetime.now(timezone.utc)
    
    # 9 posts published over the last 9 days
    dates = [(now - timedelta(days=i)).isoformat() for i in range(9)]
    candidate = {"recent_publish_dates": dates}
    
    assert filter_obj.is_active_creator(candidate) is True


def test_activity_filter_rule_b_60_day_longform():
    """Validates Rule B: Creator passes with >= 2 long-form items (>600s or podcast) in 60 days."""
    filter_obj = ActivityFilter(min_longform_60_days=2, longform_min_duration_seconds=600)
    now = datetime.now(timezone.utc)
    
    recent_videos = [
        {"published_at": (now - timedelta(days=10)).isoformat(), "duration_seconds": 900},
        {"published_at": (now - timedelta(days=40)).isoformat(), "duration_seconds": 1200}
    ]
    candidate = {"recent_videos": recent_videos}
    
    assert filter_obj.is_active_creator(candidate) is True


def test_activity_filter_disqualify_inactive():
    """Validates rejection when creator fails both 30-day and 60-day volume rules."""
    filter_obj = ActivityFilter(min_total_30_days=8, min_longform_60_days=2)
    now = datetime.now(timezone.utc)
    
    # Only 1 video published 45 days ago with short duration
    recent_videos = [
        {"published_at": (now - timedelta(days=45)).isoformat(), "duration_seconds": 180}
    ]
    candidate = {"recent_videos": recent_videos}
    
    assert filter_obj.is_active_creator(candidate) is False


# ==============================================================================
# Unit Test Suite: Exporter Helper Logic
# ==============================================================================

def test_exporter_parse_json_list():
    """Validates transformation of stringified JSON arrays into clean comma-separated text."""
    parse = LeadExporter._parse_json_list

    assert parse('["editing", "captions"]') == "editing, captions"
    assert parse(["editing", "repurposing"]) == "editing, repurposing"
    assert parse("Direct Text") == "Direct Text"
    assert parse(None) == ""


def test_exporter_priority_tagging(tmp_path):
    """Verifies that top 25 leads receive 'Priority A' tag and remaining receive 'Standard'."""
    csv_file = str(tmp_path / "test_export.csv")
    
    # Create 30 test candidates with varying confidence scores
    leads = []
    for i in range(30):
        leads.append({
            "creator_id": f"id_{i}",
            "platform": "YOUTUBE",
            "title": f"Creator {i}",
            "confidence_score": i * 0.03,
            "country": "US",
            "owner_email": f"user{i}@test.com"
        })

    LeadExporter.export_to_csv_and_excel(leads, csv_path=csv_file)
    
    import pandas as pd
    df = pd.read_csv(csv_file)
    
    # Highest confidence score lead must be indexed first
    assert df.iloc[0]["Priority Rank"] == "Priority A"
    assert df.iloc[24]["Priority Rank"] == "Priority A"
    assert df.iloc[25]["Priority Rank"] == "Standard"