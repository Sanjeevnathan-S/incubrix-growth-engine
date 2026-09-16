import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import dateutil.parser

from config import settings

logger = logging.getLogger(__name__)


class ActivityFilter:
    """
    Evaluates creator activity density using existing settings:
    - Rule A: >= 2 posts for podcasts (or MIN_POSTS_LAST_30_DAYS for YouTube) in the last 30 days
    OR
    - Rule B: >= MIN_LONGFORM_LAST_60_DAYS long-form items in the last 60 days
    """

    def __init__(
        self,
        min_total_30_days: Optional[int] = None,
        min_podcast_30_days: Optional[int] = None,
        min_longform_60_days: Optional[int] = None,
        longform_min_duration_seconds: Optional[int] = None,
    ):
        self.min_total_30_days = (
            min_total_30_days
            if min_total_30_days is not None
            else getattr(settings, "MIN_POSTS_LAST_30_DAYS", 8)
        )
        # Default directly to 2 for podcasts without querying settings/env
        self.min_podcast_30_days = (
            min_podcast_30_days if min_podcast_30_days is not None else 2
        )
        self.min_longform_60_days = (
            min_longform_60_days
            if min_longform_60_days is not None
            else getattr(settings, "MIN_LONGFORM_LAST_60_DAYS", 2)
        )
        # Default long-form duration threshold set to 600s (10 mins) per assessment standards
        self.longform_min_duration_seconds = (
            longform_min_duration_seconds
            if longform_min_duration_seconds is not None
            else getattr(settings, "LONGFORM_MIN_DURATION_SECONDS", 600)
        )

    def is_active_creator(self, candidate: Dict[str, Any]) -> bool:
        """
        Determines whether candidate meets Rule A (30-day activity volume)
        or Rule B (60-day long-form volume).
        """
        now = datetime.now(timezone.utc)
        cutoff_30_days = now - timedelta(days=30)
        cutoff_60_days = now - timedelta(days=60)

        total_items_30_days = 0
        longform_items_60_days = 0

        # Primary inspection: Structured item lists containing video/episode metadata
        content_items: List[Dict[str, Any]] = (
            candidate.get("recent_videos")
            or candidate.get("recent_episodes")
            or candidate.get("recent_content")
            or []
        )

        if content_items:
            for item in content_items:
                pub_date = self._parse_datetime(
                    item.get("publish_date") or item.get("published_at")
                )
                if not pub_date:
                    continue

                duration = item.get("duration_seconds", 0)
                is_long_form = item.get("is_long_form")
                if is_long_form is None:
                    is_long_form = (
                        duration >= self.longform_min_duration_seconds 
                        or candidate.get("platform") == "podcast"
                    )

                # Rule A increment: Total content items within 30 days
                if pub_date >= cutoff_30_days:
                    total_items_30_days += 1

                # Rule B increment: Long-form items within 60 days
                if pub_date >= cutoff_60_days and is_long_form:
                    longform_items_60_days += 1

        # Fallback inspection: Flat ISO/RSS date strings (Only satisfies Rule A)
        elif candidate.get("recent_publish_dates"):
            for date_str in candidate.get("recent_publish_dates", []):
                pub_date = self._parse_datetime(date_str)
                if pub_date and pub_date >= cutoff_30_days:
                    total_items_30_days += 1

        # Enforce dynamic 30-day threshold based on platform type
        target_30d_min = (
            self.min_podcast_30_days
            if candidate.get("platform") == "podcast"
            else self.min_total_30_days
        )

        passes_30d_rule = total_items_30_days >= target_30d_min
        passes_60d_longform_rule = longform_items_60_days >= self.min_longform_60_days

        return passes_30d_rule or passes_60d_longform_rule

    def _parse_datetime(self, date_val: Any) -> Optional[datetime]:
        """Utility to safely parse mixed datetime types and enforce UTC tzinfo."""
        if isinstance(date_val, datetime):
            return date_val if date_val.tzinfo else date_val.replace(tzinfo=timezone.utc)

        if isinstance(date_val, str) and date_val.strip():
            try:
                dt = dateutil.parser.parse(date_val)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, OverflowError):
                return None

        return None