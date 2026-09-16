import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class LinkScraper:
    COMMERCIAL_DOMAINS = [
        "linktr.ee", "beacons.ai", "beacons.page", "stan.store",
        "patreon.com", "substack.com", "skool.com", "kajabi.com",
        "teachable.com", "gumroad.com", "shopify.com"
    ]

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def extract_monetization_and_contact(self, bio_text: str, external_links: List[str] = None) -> Dict[str, Any]:
        """
        Parses bios and external URLs to identify commercial infrastructure and contact info.
        """
        combined_links = set(external_links or [])
        url_pattern = r'https?://[^\s<>"]+'
        found_urls = re.findall(url_pattern, bio_text)
        combined_links.update(found_urls)

        monetization_signals = []
        extracted_emails = set()
        email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

        # Extract direct emails inside text
        for email in re.findall(email_regex, bio_text):
            if not email.endswith((".png", ".jpg", ".jpeg", ".gif")):
                extracted_emails.add(email)

        # Inspect links for monetization signatures
        for link in combined_links:
            link_lower = link.lower()
            for domain in self.COMMERCIAL_DOMAINS:
                if domain in link_lower:
                    monetization_signals.append(f"Monetization platform: {domain}")

        return {
            "emails": list(extracted_emails),
            "monetization_signals": list(set(monetization_signals)),
            "external_links": list(combined_links)
        }

    def scrape_landing_page_email(self, url: str) -> str:
        """
        Scrapes a target link-in-bio page or creator landing page for a public email address.
        """
        if not url:
            return ""
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                emails = re.findall(email_regex, soup.get_text())
                for email in emails:
                    if not email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                        return email
        except Exception as e:
            logger.debug(f"Failed scraping landing page {url}: {e}")
        return ""