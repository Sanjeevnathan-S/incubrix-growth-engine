import re
import logging
import feedparser
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class RSSParser:
    @staticmethod
    def extract_deep_signals(feed_url: str) -> Dict[str, Any]:
        """
        Parses podcast RSS XML to extract show-notes links and owner contact info.
        """
        try:
            feed = feedparser.parse(feed_url)
            channel = feed.feed
            
            show_notes_links = []
            found_emails = set()

            # 1. Extract structural owner email tags
            itunes_owner = channel.get("itunes_owner", {})
            if itunes_owner.get("email"):
                found_emails.add(itunes_owner.get("email"))

            managing_editor = channel.get("managingeditor")
            if managing_editor:
                found_emails.add(managing_editor)

            # 2. Extract emails and external links embedded within episode show notes
            email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            url_regex = r'https?://[^\s<>"]+'

            for entry in feed.entries[:5]:
                summary = f"{entry.get('summary', '')} {entry.get('description', '')}"
                
                # Extract emails
                for email in re.findall(email_regex, summary):
                    if not email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                        found_emails.add(email)

                # Extract external links
                links = re.findall(url_regex, summary)
                show_notes_links.extend(links)

            return {
                "parsed_emails": [e for e in found_emails if e],
                "show_notes_links": list(set(show_notes_links))
            }
        except Exception as e:
            logger.error(f"Error extracting deep RSS signals from {feed_url}: {e}")
            return {"parsed_emails": [], "show_notes_links": []}