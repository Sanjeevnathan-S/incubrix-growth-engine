import logging
import re
import requests
import feedparser
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from config.settings import ALLOWED_COUNTRIES
from src.storage.db import LeadDatabase

logger = logging.getLogger(__name__)

# Geographic Mappings for Tier 1 & Tier 2 Resolution
LOCALE_LANG_MAP = {
    "en-gb": "GB", "en-uk": "GB",
    "en-ca": "CA",
    "en-au": "AU",
    "en-nz": "NZ",
    "en-ie": "IE",
    "en-sg": "SG",
    "en-us": "US",
}

TLD_MAP = {
    ".uk": "GB", ".co.uk": "GB",
    ".ca": "CA",
    ".au": "AU", ".com.au": "AU",
    ".ie": "IE",
    ".nz": "NZ", ".co.nz": "NZ",
    ".sg": "SG", ".com.sg": "SG"
}

LOCATION_REGEXES = {
    "GB": [r"\blondon\b", r"\bmanchester\b", r"\bbirmingham\b", r"\buk\b", r"\bunited kingdom\b", r"\bengland\b", r"\bscotland\b"],
    "CA": [r"\btoronto\b", r"\bvancouver\b", r"\bmontreal\b", r"\bottawa\b", r"\bcanada\b"],
    "AU": [r"\bsydney\b", r"\bmelbourne\b", r"\bbrisbane\b", r"\bperth\b", r"\baustralia\b"],
    "US": [r"\bnew york\b", r"\bcalifornia\b", r"\btexas\b", r"\busa\b", r"\bunited states\b", r"\bsilicon valley\b", r"\blos angeles\b"],
    "IE": [r"\bdublin\b", r"\bireland\b"],
    "NZ": [r"\bauckland\b", r"\bwellington\b", r"\bnew zealand\b"],
    "SG": [r"\bsingapore\b"]
}


class PodcastDiscoveryClient:
    """
    Apple iTunes Search API client with multithreaded XML RSS hydration.
    Integrates DB deduplication prior to network calls, explicit HTTP timeouts,
    and a 4-Tier Geographic Metadata Resolution Engine.
    """

    BASE_URL = "https://itunes.apple.com/search"

    def search_podcasts(
        self,
        query: str,
        db: LeadDatabase,
        countries: List[str] = None,
        limit_per_country: int = 100,
        ttl_days: int = 30,
        max_workers: int = 15
    ) -> List[Dict[str, Any]]:
        target_countries = countries or ALLOWED_COUNTRIES
        aggregated_podcasts = []

        for country in target_countries:
            country_code = country.upper()

            if not db.should_scrape_query(query, country_code, ttl_days=ttl_days):
                logger.info(f"Skipping podcast search for '{query}' [{country_code}] — cached within {ttl_days} days.")
                continue

            params = {
                "term": query,
                "media": "podcast",
                "entity": "podcast",
                "country": country_code.lower(),
                "limit": min(limit_per_country, 200),
            }

            try:
                logger.info(f"Searching Apple Podcasts API for '{query}' [{country_code}]...")
                response = requests.get(self.BASE_URL, params=params, timeout=10)
                response.raise_for_status()
                results = response.json().get("results", [])

                db.record_search(query, country_code, len(results))

                if not results:
                    continue

                # Collect feed URLs and map to Apple API metadata
                candidates_by_url = {}
                for item in results:
                    feed_url = item.get("feedUrl")
                    if feed_url and feed_url not in candidates_by_url:
                        candidates_by_url[feed_url] = item

                # SQLite Deduplication BEFORE initiating HTTP RSS requests (Main Thread)
                raw_urls = list(candidates_by_url.keys())
                unseen_urls = db.filter_unseen_channel_ids(raw_urls)

                logger.info(f"Query '{query}' [{country_code}]: Discovered {len(raw_urls)} feeds, {len(unseen_urls)} NEW.")

                # Parallel RSS XML Fetching (Worker Threads - No DB Writes)
                if unseen_urls:
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [
                            executor.submit(
                                self._hydrate_from_rss, feed_url, candidates_by_url[feed_url], country_code
                            )
                            for feed_url in unseen_urls
                        ]
                        for future in as_completed(futures):
                            try:
                                hydrated_podcast = future.result(timeout=15)
                                if hydrated_podcast:
                                    aggregated_podcasts.append(hydrated_podcast)
                            except Exception as e:
                                logger.warning(f"Error in parallel RSS hydration: {e}")

            except requests.RequestException as e:
                logger.error(f"Apple Podcasts API error for query '{query}' in country '{country_code}': {e}")
                continue

        return aggregated_podcasts

    def _hydrate_from_rss(self, feed_url: str, apple_item: dict, country: str) -> Optional[Dict[str, Any]]:
        xml_content = self._fetch_rss_xml(feed_url)
        if not xml_content:
            return None

        try:
            feed_data = feedparser.parse(xml_content)
            channel = getattr(feed_data, "feed", {})

            recent_episodes = []
            recent_publish_dates = []
            recent_titles = []

            for entry in feed_data.entries[:10]:
                v_title = entry.get("title", "")
                if not v_title:
                    continue

                pub_date = ""
                if "published_parsed" in entry and entry.published_parsed:
                    try:
                        dt = datetime(*entry.published_parsed[:6])
                        pub_date = dt.isoformat()
                    except Exception:
                        pub_date = entry.get("published", "")
                elif "published" in entry:
                    pub_date = entry.get("published", "")

                duration_sec = self._parse_itunes_duration(entry.get("itunes_duration", ""))
                is_long_form = duration_sec >= 600

                recent_titles.append(v_title)
                recent_publish_dates.append(pub_date)
                recent_episodes.append({
                    "title": v_title,
                    "publish_date": pub_date,
                    "duration_seconds": duration_sec,
                    "is_long_form": is_long_form,
                })

            website_url = channel.get("link", "")
            bio = channel.get("summary") or channel.get("subtitle") or channel.get("description", "")
            owner_email = self._extract_owner_email(channel, bio=bio)

            # Resolve Country metadata via 4-Tier Fallback Strategy
            resolved_country = self._resolve_country(
                feed_channel=channel,
                bio=bio,
                website_url=website_url,
                owner_email=owner_email,
                apple_item=apple_item,
                api_country_fallback=country
            )

            return {
                "platform": "podcast",
                "creator_id": feed_url,
                "title": apple_item.get("collectionName", channel.get("title", "")),
                "handle_or_artist": apple_item.get("artistName", channel.get("author", "")),
                "bio": bio,
                "country": resolved_country,
                "website_url": website_url,
                "owner_email": owner_email,
                "recent_episodes": recent_episodes,
                "recent_publish_dates": recent_publish_dates,
                "recent_titles": recent_titles,
                "topic_categories": [apple_item.get("primaryGenreName", "")],
            }

        except Exception as e:
            logger.warning(f"Failed to parse RSS feed content for {feed_url}: {e}")
            return None

    def _resolve_country(
        self,
        feed_channel: Dict[str, Any],
        bio: str,
        website_url: str,
        owner_email: str,
        apple_item: Dict[str, Any],
        api_country_fallback: str
    ) -> str:
        """4-Tier Fallback resolution to accurately stamp podcast candidates with a target country."""
        # Tier 1: RSS XML Language Tag (<language>en-gb</language>)
        lang = str(feed_channel.get("language", "")).lower().strip()
        if lang in LOCALE_LANG_MAP:
            return LOCALE_LANG_MAP[lang]

        # Tier 2: Website & Email Domain TLDs (.co.uk, .ca, .com.au, etc.)
        for text in [website_url, owner_email]:
            if text:
                try:
                    domain = urlparse(text if "://" in text else f"http://{text}").netloc.lower()
                    for tld, country_code in TLD_MAP.items():
                        if domain.endswith(tld):
                            return country_code
                except Exception:
                    pass

        # Tier 3: Text Mining (Currencies & Regional Keywords)
        title = apple_item.get("collectionName", feed_channel.get("title", ""))
        content = f"{title} {bio} {feed_channel.get('description', '')}".lower()

        if "£" in content or " gbp " in content:
            return "GB"
        if "a$" in content or " aud " in content:
            return "AU"
        if "cad $" in content or " cad " in content:
            return "CA"
        if "nzd" in content or "nz$" in content:
            return "NZ"
        if "sgd" in content or "singapore dollar" in content:
            return "SG"

        for country_code, patterns in LOCATION_REGEXES.items():
            if any(re.search(pattern, content) for pattern in patterns):
                return country_code

        # Tier 4: Fallback to iTunes API search country context
        return api_country_fallback.upper() if api_country_fallback else "US"

    def _fetch_rss_xml(self, feed_url: str) -> Optional[bytes]:
        """Fetches RSS XML content using requests with explicit 15s timeout."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*"
            }
            resp = requests.get(feed_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.content  # Returns raw bytes for accurate feedparser charset decoding
        except Exception as e:
            logger.debug(f"RSS download timed out or failed for {feed_url}: {e}")
        return None

    def _extract_owner_email(self, channel: Dict[str, Any], bio: str = "") -> str:
        raw_email = ""
        itunes_owner = channel.get("itunes_owner", {})

        if isinstance(itunes_owner, dict):
            raw_email = itunes_owner.get("email", "")
        elif isinstance(itunes_owner, str):
            raw_email = itunes_owner

        if not raw_email:
            raw_email = channel.get("managingeditor", "") or channel.get("author_detail", {}).get("email", "")

        # Fallback inspection: Search bio/description if RSS metadata tags omit email
        search_corpus = f"{raw_email} {bio} {channel.get('description', '')}"
        match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", search_corpus)
        return match.group(0) if match else ""

    def _parse_itunes_duration(self, duration_str: Any) -> int:
        if not duration_str:
            return 1800  # Default 30 mins for podcast episodes if missing

        try:
            clean_str = str(duration_str).strip()
            if "." in clean_str:
                clean_str = clean_str.split(".")[0]

            parts = clean_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1:
                return int(parts[0])

        except (ValueError, TypeError):
            pass

        return 1800