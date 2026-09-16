import logging
import re
import socket
from typing import List, Dict, Any, Tuple, Union, Callable
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from config.settings import YOUTUBE_API_KEY, ALLOWED_COUNTRIES
from src.discovery.scrapetube_client import YouTubeScraperClient
from src.storage.db import LeadDatabase

logger = logging.getLogger(__name__)


class YouTubeDiscoveryClient:
    """
    Scraper-First YouTube discovery client.
    Uses scrapetube for initial search (0 quota), filters unseen IDs via SQLite,
    and uses official API keys in 50-item batches for enriched details and exact video durations.
    """

    def __init__(self, api_key: Union[str, List[str]] = None):
        self.api_keys = self._parse_api_keys(api_key)
        self.current_key_idx = 0
        self.youtube = None
        self.quota_exhausted = False
        self.scraper_client = YouTubeScraperClient()

        if self.api_keys:
            self._init_current_client()
        else:
            logger.warning("YOUTUBE_API_KEY missing from configuration. Operating in pure scraper mode.")
            self.quota_exhausted = True

    def _parse_api_keys(self, api_key: Union[str, List[str]] = None) -> List[str]:
        raw_keys = api_key or YOUTUBE_API_KEY
        if not raw_keys:
            return []

        if isinstance(raw_keys, str):
            return [k.strip() for k in raw_keys.split(",") if k.strip()]
        elif isinstance(raw_keys, list):
            return [str(k).strip() for k in raw_keys if str(k).strip()]
        return []

    def _init_current_client(self) -> bool:
        if self.current_key_idx >= len(self.api_keys):
            self.quota_exhausted = True
            self.youtube = None
            return False

        current_key = self.api_keys[self.current_key_idx]
        masked_key = f"{current_key[:6]}...{current_key[-4:]}" if len(current_key) > 10 else "***"

        try:
            self.youtube = build("youtube", "v3", developerKey=current_key)
            logger.info(f"Initialized YouTube API Client with Key #{self.current_key_idx + 1}/{len(self.api_keys)} ({masked_key})")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize YouTube API client key #{self.current_key_idx + 1}: {e}")
            return self._rotate_to_next_key()

    def _rotate_to_next_key(self) -> bool:
        self.current_key_idx += 1
        if self.current_key_idx < len(self.api_keys):
            logger.warning(f"Quota reached on Key #{self.current_key_idx}. Rotating to Key #{self.current_key_idx + 1}/{len(self.api_keys)}...")
            return self._init_current_client()
        else:
            logger.warning("All YouTube API keys exhausted! Fallback mode active.")
            self.quota_exhausted = True
            self.youtube = None
            return False

    def _execute_api_call(self, api_func: Callable) -> Any:
        prev_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(10.0)
        try:
            while not self.quota_exhausted and self.youtube:
                try:
                    return api_func().execute()
                except HttpError as e:
                    status_code = getattr(e.resp, "status", None) if hasattr(e, "resp") else None
                    if status_code in (429, 403) or "quotaExceeded" in str(e):
                        logger.warning(f"YouTube API Key #{self.current_key_idx + 1} quota limit reached.")
                        rotated = self._rotate_to_next_key()
                        if not rotated:
                            raise e
                    else:
                        raise e

            raise RuntimeError("All YouTube API keys exhausted or client unavailable.")
        finally:
            socket.setdefaulttimeout(prev_timeout)

    def _fallback_enrich_via_rss(self, candidates: List[Dict[str, Any]], unseen_ids: List[str]) -> List[Dict[str, Any]]:
        """Helper method for RSS fallback enrichment using parallel thread pool."""
        unseen_set = set(unseen_ids)
        fallback_candidates = [c for c in candidates if c.get("creator_id") in unseen_set]
        return self.scraper_client.enrich_creators_via_rss_parallel(fallback_candidates, max_workers=10)

    def search_creators(
        self,
        query: str,
        db: LeadDatabase,
        countries: List[str] = None,
        max_results_per_country: int = 50,
        ttl_days: int = 30,
    ) -> List[Dict[str, Any]]:

        target_countries = countries or ALLOWED_COUNTRIES
        aggregated_creators = []

        for country in target_countries:
            if not db.should_scrape_query(query, country, ttl_days=ttl_days):
                logger.info(f"Skipping search for '{query}' [{country}] — processed within {ttl_days} days.")
                continue

            # 1. Scrapetube Discovery (0 Quota)
            scraped_results = self.scraper_client.search_creators(
                query=query,
                countries=[country],
                max_results_per_country=max_results_per_country,
            )

            if not scraped_results:
                continue

            # 2. SQLite Deduplication BEFORE heavy network calls
            scraped_ids = [c["creator_id"] for c in scraped_results if c.get("creator_id")]
            unseen_ids = db.filter_unseen_channel_ids(scraped_ids)

            logger.info(f"Query '{query}' [{country}]: Discovered {len(scraped_ids)} candidates, {len(unseen_ids)} NEW.")

            if not unseen_ids:
                continue

            # 3. Batch API Enrichment with Parallel RSS Fallback
            if not self.quota_exhausted and self.youtube:
                enriched_data, processed_ids = self.get_channel_details(unseen_ids, country)
                aggregated_creators.extend(enriched_data)

                missed_ids = list(set(unseen_ids) - set(processed_ids))
                if missed_ids:
                    logger.info(f"Falling back to parallel RSS enrichment for {len(missed_ids)} unfulfilled channels.")
                    aggregated_creators.extend(self._fallback_enrich_via_rss(scraped_results, missed_ids))
            else:
                aggregated_creators.extend(self._fallback_enrich_via_rss(scraped_results, unseen_ids))

        return aggregated_creators

    def get_channel_details(self, channel_ids: List[str], fallback_country: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        if not channel_ids or self.quota_exhausted:
            return [], []

        creators = []
        processed_ids = []

        for i in range(0, len(channel_ids), 50):
            batch_ids = channel_ids[i : i + 50]
            try:
                channels_call = lambda: self.youtube.channels().list(
                    id=",".join(batch_ids),
                    part="snippet,statistics,contentDetails,topicDetails",
                    maxResults=50,
                )
                channels_response = self._execute_api_call(channels_call)

                for item in channels_response.get("items", []):
                    c_id = item.get("id", "")
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    uploads_playlist_id = content_details.get("relatedPlaylists", {}).get("uploads")

                    recent_videos, recent_titles, recent_dates = self._get_recent_uploads(uploads_playlist_id)
                    channel_country = snippet.get("country", fallback_country).upper()

                    creators.append({
                        "platform": "youtube",
                        "creator_id": c_id,
                        "title": snippet.get("title", ""),
                        "handle_or_artist": snippet.get("customUrl", ""),
                        "bio": snippet.get("description", ""),
                        "country": channel_country,
                        "website_url": f"https://www.youtube.com/channel/{c_id}",
                        "owner_email": "",
                        "recent_videos": recent_videos,
                        "recent_publish_dates": recent_dates,
                        "recent_titles": recent_titles,
                        "topic_categories": item.get("topicDetails", {}).get("topicCategories", []),
                    })
                    processed_ids.append(c_id)

            except Exception as e:
                logger.error(f"YouTube Channels API error on batch: {e}")
                break

        return creators, processed_ids

    def _get_recent_uploads(self, playlist_id: str, max_items: int = 10) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        if not playlist_id or self.quota_exhausted:
            return [], [], []

        try:
            playlist_call = lambda: self.youtube.playlistItems().list(
                playlistId=playlist_id, part="snippet,contentDetails", maxResults=max_items
            )
            playlist_response = self._execute_api_call(playlist_call)

            items = playlist_response.get("items", [])
            if not items:
                return [], [], []

            video_ids = [
                item.get("contentDetails", {}).get("videoId")
                for item in items
                if item.get("contentDetails", {}).get("videoId")
            ]

            durations_map = self._get_video_durations(video_ids)

            recent_videos = []
            titles = []
            publish_dates = []

            for item in items:
                snippet = item.get("snippet", {})
                v_id = item.get("contentDetails", {}).get("videoId", "")
                v_title = snippet.get("title", "")
                v_date = snippet.get("publishedAt", "")

                duration_sec = durations_map.get(v_id, 0)
                is_long_form = duration_sec >= 600

                if v_title:
                    titles.append(v_title)
                    publish_dates.append(v_date)
                    recent_videos.append({
                        "video_id": v_id,
                        "title": v_title,
                        "publish_date": v_date,
                        "duration_seconds": duration_sec,
                        "is_long_form": is_long_form,
                    })

            return recent_videos, titles, publish_dates

        except Exception as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            if status != 404:
                logger.error(f"Error fetching playlist {playlist_id}: {e}")
            return [], [], []

    def _get_video_durations(self, video_ids: List[str]) -> Dict[str, int]:
        if not video_ids or self.quota_exhausted:
            return {}

        try:
            videos_call = lambda: self.youtube.videos().list(
                id=",".join(video_ids), part="contentDetails", maxResults=len(video_ids)
            )
            response = self._execute_api_call(videos_call)

            durations = {}
            for item in response.get("items", []):
                v_id = item.get("id")
                iso_duration = item.get("contentDetails", {}).get("duration", "")
                durations[v_id] = self._parse_iso_duration(iso_duration)
            return durations

        except Exception as e:
            logger.warning(f"Failed to fetch video durations: {e}")
            return {}

    def _parse_iso_duration(self, duration_str: str) -> int:
        if not duration_str:
            return 0
        pattern = re.compile(
            r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
        )
        match = pattern.match(duration_str)
        if not match:
            return 0
        parts = match.groupdict()
        days = int(parts["days"] or 0)
        hours = int(parts["hours"] or 0)
        minutes = int(parts["minutes"] or 0)
        seconds = int(parts["seconds"] or 0)
        return days * 86400 + hours * 3600 + minutes * 60 + seconds