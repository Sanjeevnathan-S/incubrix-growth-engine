import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from config.settings import DATABASE_PATH, TARGET_LEADS_COUNT

logger = logging.getLogger(__name__)

class LeadDatabase:
    TIER1_COUNTRIES = {"US", "CA", "GB", "UK", "IE", "AU", "NZ", "SG"}

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    creator_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    title TEXT,
                    handle_or_artist TEXT,
                    country TEXT,
                    owner_email TEXT,
                    website_url TEXT,
                    bio TEXT,
                    account_category TEXT,
                    confidence_score REAL,
                    qualification_reason TEXT,
                    bottlenecks TEXT,
                    pitch_hook TEXT,
                    monetization_signals TEXT,
                    external_links TEXT,
                    recent_publish_dates TEXT,
                    recent_videos TEXT,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    search_key TEXT PRIMARY KEY,
                    scraped_count INTEGER DEFAULT 0,
                    last_scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            try:
                cursor.execute("ALTER TABLE leads ADD COLUMN recent_videos TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.commit()

    def clear_stale_disqualifications(self, stale_days: int = 90) -> int:
        """Deletes non-QUALIFIED leads older than stale_days (default 90)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM leads
                WHERE status != 'QUALIFIED'
                  AND created_at <= datetime('now', '-' || ? || ' days')
            """, (stale_days,))
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Purged {deleted_count} non-QUALIFIED leads older than {stale_days} days.")
            return deleted_count

    def should_scrape_query(self, query: str, country: str, ttl_days: int = 30) -> bool:
        """Returns True if the query+country has not been searched within the TTL window."""
        search_key = f"{query.lower().strip()}:{country.upper().strip()}"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT last_scraped_at 
                FROM search_history 
                WHERE search_key = ? 
                  AND last_scraped_at >= datetime('now', '-' || ? || ' days')
            """, (search_key, ttl_days))
            return cursor.fetchone() is None

    def record_search(self, query: str, country: str, scraped_count: int) -> None:
        """Logs or refreshes the search timestamp and scraped count."""
        search_key = f"{query.lower().strip()}:{country.upper().strip()}"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO search_history (search_key, scraped_count, last_scraped_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (search_key, scraped_count))
            conn.commit()

    def filter_unseen_channel_ids(self, candidate_ids: List[str]) -> List[str]:
        """Filters candidate channel IDs against SQLite, after clearing non-QUALIFIED leads > 90 days."""
        if not candidate_ids:
            return []

        self.clear_stale_disqualifications(stale_days=90)

        placeholders = ",".join(["?"] * len(candidate_ids))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT creator_id FROM leads WHERE creator_id IN ({placeholders})",
                candidate_ids
            )
            existing_ids = {row[0] for row in cursor.fetchall()}

        return [cid for cid in candidate_ids if cid not in existing_ids]

    def is_already_processed(self, creator_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM leads WHERE creator_id = ?", (creator_id,))
            return cursor.fetchone() is not None

    def update_lead_dynamic_fields(
        self, 
        creator_id: str, 
        recent_publish_dates: Optional[List[str]] = None,
        recent_videos: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """Updates dynamic timestamps and structured video items when a channel is re-encountered."""
        dates_json = json.dumps(recent_publish_dates) if recent_publish_dates else None
        videos_json = json.dumps(recent_videos) if recent_videos else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE leads
                SET recent_publish_dates = COALESCE(?, recent_publish_dates),
                    recent_videos = COALESCE(?, recent_videos)
                WHERE creator_id = ?
            """, (dates_json, videos_json, creator_id))
            conn.commit()

    def save_lead(self, lead: Dict[str, Any], status: str = "QUALIFIED") -> None:
        structured_videos = (
            lead.get("recent_videos") 
            or lead.get("recent_episodes") 
            or lead.get("recent_content") 
            or []
        )
        
        confidence = lead.get("confidence_score") if lead.get("confidence_score") is not None else lead.get("confidence", 0.0)
        reason = lead.get("qualification_reason") or lead.get("reason")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO leads (
                    creator_id, platform, title, handle_or_artist, country,
                    owner_email, website_url, bio, account_category, confidence_score,
                    qualification_reason, bottlenecks, pitch_hook, monetization_signals,
                    external_links, recent_publish_dates, recent_videos, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lead.get("creator_id"),
                lead.get("platform"),
                lead.get("title"),
                lead.get("handle_or_artist"),
                lead.get("country"),
                lead.get("owner_email"),
                lead.get("website_url"),
                lead.get("bio"),
                lead.get("account_category"),
                confidence,
                reason,
                json.dumps(lead.get("bottlenecks", [])),
                lead.get("pitch_hook"),
                json.dumps(lead.get("monetization_signals", [])),
                json.dumps(lead.get("external_links", [])),
                json.dumps(lead.get("recent_publish_dates", [])),
                json.dumps(structured_videos),
                status
            ))
            conn.commit()

    def get_qualified_lead_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'QUALIFIED'")
            return cursor.fetchone()[0]

    def export_all_qualified(
        self, 
        target_limit: int = TARGET_LEADS_COUNT, 
        max_country_ratio: float = 0.60,
        min_tier1_ratio: float = 0.80
    ) -> List[Dict[str, Any]]:
        """
        Retrieves qualified leads while enforcing assessment constraints:
        1. Single country share <= 60%
        2. Tier-1 English market aggregate share >= 80%
        3. Minimum of 3 distinct countries included
        """
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM leads 
                WHERE status = 'QUALIFIED' 
                ORDER BY confidence_score DESC, created_at ASC
            """)
            raw_rows = [dict(row) for row in cursor.fetchall()]

        if not raw_rows:
            return []

        selected_leads = []
        country_counts = {}
        tier1_count = 0

        max_single_country_count = int(target_limit * max_country_ratio)

        for lead in raw_rows:
            if len(selected_leads) >= target_limit:
                break

            country = (lead.get("country") or "UNK").upper()
            is_tier1 = country in self.TIER1_COUNTRIES
            current_count = len(selected_leads)

            # Check single country limit (<= 60%)
            if country_counts.get(country, 0) >= max_single_country_count:
                continue

            # Check Tier-1 minimum requirement (>= 80% after warming up initial batch)
            new_total = current_count + 1
            new_tier1 = tier1_count + (1 if is_tier1 else 0)

            if current_count >= 10 and not is_tier1:
                if (new_tier1 / new_total) < min_tier1_ratio:
                    continue  # Skip non-Tier-1 to preserve >= 80% ratio requirement

            selected_leads.append(lead)
            country_counts[country] = country_counts.get(country, 0) + 1
            if is_tier1:
                tier1_count += 1

        distinct_countries = len(country_counts)
        logger.info(
            f"Export selection complete: {len(selected_leads)} leads across {distinct_countries} countries. "
            f"Tier-1 Ratio: {(tier1_count / len(selected_leads) * 100) if selected_leads else 0:.1f}%"
        )

        return selected_leads
    
    def truncate_search_history(self) -> int:
        """Clears all records from the search_history table and returns the number of deleted rows."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM search_history")
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Truncated search_history table. Cleared {deleted_count} records.")
            return deleted_count