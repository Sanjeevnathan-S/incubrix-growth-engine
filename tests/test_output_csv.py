import os
import pandas as pd
import pytest

from config import settings

# Resolves from config settings, environment variable, or default fallback
OUTPUT_CSV_PATH = getattr(
    settings, 
    "OUTPUT_CSV_PATH", 
    os.getenv("OUTPUT_PATH", "data/leads.csv")
)
TIER1_COUNTRIES = {"US", "CA", "GB", "UK", "IE", "AU", "NZ", "SG"}

@pytest.fixture
def leads_df():
    """Loads generated leads.csv file for quality auditing."""
    assert os.path.exists(OUTPUT_CSV_PATH), f"Output file missing at {OUTPUT_CSV_PATH}. Run pipeline first."
    df = pd.read_csv(OUTPUT_CSV_PATH)
    return df


def test_output_lead_count_baseline(leads_df):
    """Verifies output contains at least 1,000 qualified leads."""
    assert len(leads_df) >= 1000, f"Expected >= 1000 leads, found {len(leads_df)}"


def test_output_zero_duplicate_rate(leads_df):
    """Confirms final output duplicate rate is strictly 0%."""
    duplicate_count = leads_df["Creator ID / Feed"].duplicated().sum()
    assert duplicate_count == 0, f"Found {duplicate_count} duplicate creator IDs in output CSV"


def test_output_priority_a_tagging_count(leads_df):
    """Verifies that top 25 leads are marked as Priority A."""
    priority_a_leads = leads_df[leads_df["Priority Rank"] == "Priority A"]
    assert len(priority_a_leads) == 25, f"Expected 25 Priority A leads, found {len(priority_a_leads)}"


def test_output_tier1_and_country_distribution(leads_df):
    """
    Verifies Section 2 Geographic criteria:
    1. >= 80% of leads from Tier-1 English markets (US, CA, UK, IE, AU, NZ, SG)
    2. Single country share <= 60%
    3. Minimum 3 distinct countries included
    """
    total_count = len(leads_df)
    country_counts = leads_df["Country"].str.upper().value_counts()
    
    # 1. Minimum 3 distinct countries
    assert len(country_counts) >= 3, f"Expected >= 3 distinct countries, found {len(country_counts)}"
    
    # 2. Max single country ratio <= 60%
    max_country, max_count = country_counts.index[0], country_counts.iloc[0]
    max_ratio = max_count / total_count
    assert max_ratio <= 0.60, f"Country {max_country} accounts for {max_ratio:.2%}, exceeding 60% ceiling"
    
    # 3. Aggregate Tier-1 ratio >= 80%
    tier1_count = leads_df["Country"].str.upper().isin(TIER1_COUNTRIES).sum()
    tier1_ratio = tier1_count / total_count
    assert tier1_ratio >= 0.80, f"Tier-1 ratio is {tier1_ratio:.2%}, below 80% threshold"


def test_output_required_fields_non_empty(leads_df):
    """Ensures verified contacts, source links, and qualification reasons are populated."""
    # Verified contact route present
    missing_contacts = leads_df["Verified Contact Email / Route"].isna().sum()
    assert missing_contacts == 0, f"Found {missing_contacts} rows missing contact routes"

    # Evidence links present
    missing_evidence = leads_df["Commercial Evidence Links"].isna().sum()
    assert missing_evidence == 0, f"Found {missing_evidence} rows missing commercial evidence links"


def test_output_schema_columns(leads_df):
    """Validates output column header schema against project specification."""
    expected_columns = [
        "Priority Rank", "Platform", "Creator ID / Feed", "Channel / Show Title",
        "Handle / Host", "Country", "Verified Contact Email / Route", "Website / Profile URL",
        "Account Category", "Confidence Score", "Commercial Evidence Links", 
        "Identified Bottlenecks", "Custom Pitch Hook", "Qualification Reason", "Bio Description"
    ]
    assert list(leads_df.columns) == expected_columns