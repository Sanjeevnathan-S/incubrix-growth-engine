import time
import logging
import socket
import feedparser
import requests
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import scrapetube
from config.settings import ALLOWED_COUNTRIES

logger = logging.getLogger(__name__)

COUNTRY_KEYWORDS = {
    "US": "United States",
    "GB": "UK",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
    "FR": "France",
    "IN": "India",
    "NL": "Netherlands",
    "ES": "Spain",
    "IT": "Italy",
    "BR": "Brazil",
}


class YouTubeScraperClient:
    """
    Alternative YouTube discovery client using scrapetube for light channel search
    and zero-quota RSS feeds for recent video uploads during API-fallback mode.
    """

    def __init__(self, api_key: str = None):
        pass

    def search_creators(
        self,
        query: str,
        countries: List[str] = None,
        max_results_per_country: int = 20,
    ) -> List[Dict[str, Any]]:
        target_countries = countries or ALLOWED_COUNTRIES
        seen_channel_ids = set()
        raw_candidates = []

        prev_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(10.0)

        try:
            for country in target_countries:
                country_code = country.upper()
                geo_modifier = COUNTRY_KEYWORDS.get(country_code, country_code)
                regional_query = f"{query} {geo_modifier}"

                try:
                    logger.info(f"Scraping YouTube discovery for '{regional_query}' [{country_code}]...")

                    results = scrapetube.get_search(
                        query=regional_query,
                        results_type="channel",
                        limit=max_results_per_country,
                    )

                    for item in results:
                        channel_id = item.get("channelId")
                        if not channel_id or channel_id in seen_channel_ids:
                            continue

                        seen_channel_ids.add(channel_id)

                        title = ""
                        title_runs = item.get("title", {}).get("runs", [])
                        if title_runs:
                            title = title_runs[0].get("text", "")

                        bio = ""
                        desc_runs = item.get("descriptionSnippet", {}).get("runs", [])
                        if desc_runs:
                            bio = "".join([r.get("text", "") for r in desc_runs])

                        handle = (
                            item.get("navigationEndpoint", {})
                            .get("browseEndpoint", {})
                            .get("canonicalBaseUrl", "")
                        )

                        raw_candidates.append({
                            "platform": "youtube",
                            "creator_id": channel_id,
                            "title": title,
                            "handle_or_artist": handle,
                            "bio": bio,
                            "country": country_code,
                            "website_url": f"https://www.youtube.com/channel/{channel_id}",
                            "owner_email": "",
                            "recent_videos": [],
                            "recent_publish_dates": [],
                            "recent_titles": [],
                            "topic_categories": [],
                        })

                except Exception as e:
                    logger.error(f"scrapetube search error for query '{regional_query}': {e}")
                    continue
        finally:
            socket.setdefaulttimeout(prev_timeout)

        return raw_candidates

    def enrich_creator_via_rss(self, candidate: Dict[str, Any], max_items: int = 10) -> Dict[str, Any]:
        """Populates recent uploads via RSS feed when operating in pure scraper fallback mode."""
        channel_id = candidate.get("creator_id")
        if not channel_id:
            return candidate

        recent_videos, recent_titles, recent_dates = self._get_recent_uploads_rss(channel_id, max_items=max_items)
        candidate["recent_videos"] = recent_videos
        candidate["recent_titles"] = recent_titles
        candidate["recent_publish_dates"] = recent_dates
        return candidate

    def enrich_creators_via_rss_parallel(
        self, candidates: List[Dict[str, Any]], max_items: int = 10, max_workers: int = 10
    ) -> List[Dict[str, Any]]:
        """Concurrently fetches RSS feeds for a list of candidates across worker threads."""
        if not candidates:
            return []

        enriched_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self.enrich_creator_via_rss, cand, max_items)
                for cand in candidates
            ]
            for future in as_completed(futures):
                try:
                    enriched_results.append(future.result())
                except Exception as e:
                    logger.warning(f"Parallel RSS fetching error: {e}")

        return enriched_results

    def _get_recent_uploads_rss(
        self, channel_id: str, max_items: int = 10
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        recent_videos = []
        titles = []
        publish_dates = []
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

        try:
            response = requests.get(rss_url, timeout=5.0)
            if response.status_code != 200:
                return [], [], []

            feed = feedparser.parse(response.content)
            for entry in feed.entries[:max_items]:
                v_title = entry.get("title", "")
                v_date = entry.get("published", "")
                v_link = entry.get("link", "")
                v_id = entry.get("yt_videoid", "")

                if not v_title:
                    continue

                is_short = (
                    "#shorts" in v_title.lower()
                    or "#short" in v_title.lower()
                    or "/shorts/" in v_link.lower()
                )

                duration_sec = 30 if is_short else 0

                titles.append(v_title)
                publish_dates.append(v_date)

                recent_videos.append({
                    "video_id": v_id,
                    "title": v_title,
                    "publish_date": v_date,
                    "duration_seconds": duration_sec,
                    "is_long_form": not is_short,
                })

        except Exception as e:
            logger.debug(f"RSS fetch error for channel {channel_id}: {e}")

        return recent_videos, titles, publish_dates