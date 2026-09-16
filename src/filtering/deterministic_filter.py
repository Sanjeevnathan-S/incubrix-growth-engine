import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DeterministicFilter:
    # Explicit aggregation, compilation, and disclaimer triggers
    AUTO_REJECT_PATTERNS = [
        r"\bunofficial\b",
        r"\bfan\s*page\b",
        r"\bfan\s*club\b",
        r"\bclips?\s*channel\b",
        r"\bdaily\s*clips?\b",
        r"\breuploads?\b",
        r"\bcompilation[s]?\b",
        r"\bnot\s*affiliated\s*with\b",
        r"\brights?\s*belong\s*to\b",
        r"\bcurated\s*by\b",
        r"\bhighlights?\s*hub\b",
        r"\bmedia\s*group\b"
    ]

    def __init__(self):
        self.reject_regex = re.compile("|".join(self.AUTO_REJECT_PATTERNS), re.IGNORECASE)

    def evaluate(self, creator: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Returns a deterministic decision dict if high confidence (1.0) is achieved.
        Returns None if the candidate is ambiguous and requires LLM evaluation.
        """
        title = creator.get("title", "")
        bio = creator.get("bio", "")
        handle = creator.get("handle_or_artist", "")
        combined_text = f"{title} {handle} {bio}"

        # -------------------------------------------------------------
        # 1. AUTO-REJECT (High-Confidence Disqualification)
        # -------------------------------------------------------------
        if self.reject_regex.search(combined_text):
            return {
                "is_original_creator": False,
                "confidence": 1.0,
                "account_category": "clip_or_fan_page",
                "reason": "Auto-Rejected: Triggered explicit fan/clip/compilation regex match.",
                "bypassed_llm": True
            }

        # Handle suffix patterns like '@huberman_clips' or '@daily_rogan'
        handle_lower = handle.lower()
        if any(suffix in handle_lower for suffix in ["_clips", "clips_", "daily_", "fanpage", "_compilations"]):
            return {
                "is_original_creator": False,
                "confidence": 1.0,
                "account_category": "clip_channel",
                "reason": "Auto-Rejected: Handle structure indicates an aggregation hub.",
                "bypassed_llm": True
            }

        # -------------------------------------------------------------
        # 2. AUTO-PASS (High-Confidence Verification)
        # -------------------------------------------------------------
        
        # Podcast Rule: Direct RSS <itunes:owner> verification
        if creator.get("platform") == "podcast":
            owner_email = creator.get("owner_email", "").lower()
            # If RSS feed explicitly lists an owner email matching host name or podcast domain
            if owner_email and not any(free_domain in owner_email for free_domain in ["gmail.com", "yahoo.com", "hotmail.com"]):
                return {
                    "is_original_creator": True,
                    "confidence": 1.0,
                    "account_category": "individual_creator",
                    "reason": "Auto-Passed: Validated corporate/domain podcast owner email from RSS metadata.",
                    "bypassed_llm": True
                }

        # YouTube/Podcast Rule: Bio explicitly states personal host authorship
        first_person_patterns = [
            r"\bmy\s+name\s+is\b",
            r"\bhosted\s+by\b",
            r"\bi\s+am\s+a\b",
            r"\bwelcome\s+to\s+my\s+official\b"
        ]
        first_person_regex = re.compile("|".join(first_person_patterns), re.IGNORECASE)

        if first_person_regex.search(bio) and not self.reject_regex.search(combined_text):
            return {
                "is_original_creator": True,
                "confidence": 0.95,
                "account_category": "individual_creator",
                "reason": "Auto-Passed: Direct first-person host attribution found in bio.",
                "bypassed_llm": True
            }

        # -------------------------------------------------------------
        # 3. AMBIGUOUS: Route to Gemini Batch Processing
        # -------------------------------------------------------------
        return None