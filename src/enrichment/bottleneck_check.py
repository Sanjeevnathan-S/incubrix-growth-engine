import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class BottleneckAnalyzer:
    def analyze_creator_bottlenecks(self, creator: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates publication patterns using structured content metadata or titles
        to identify content production bottlenecks for pitching IncuBrix.
        """
        platform = creator.get("platform", "")
        content_items = (
            creator.get("recent_videos")
            or creator.get("recent_episodes")
            or creator.get("recent_content")
            or []
        )

        has_shorts = False
        has_longform = False

        if content_items:
            for item in content_items:
                if isinstance(item, dict):
                    title = item.get("title", "").lower()
                    is_long_form = item.get("is_long_form")
                    
                    if is_long_form is None:
                        duration = item.get("duration_seconds", 0)
                        is_long_form = duration >= 60

                    if is_long_form:
                        has_longform = True
                    
                    if not is_long_form or "#shorts" in title or "short" in title or "reel" in title:
                        has_shorts = True
                elif isinstance(item, str):
                    title_lower = item.lower()
                    if "#shorts" in title_lower or "short" in title_lower or "reel" in title_lower:
                        has_shorts = True
                    else:
                        has_longform = True
        else:
            # Fallback to plain title array
            for title in creator.get("recent_titles", []):
                title_lower = str(title).lower()
                if "#shorts" in title_lower or "short" in title_lower or "reel" in title_lower:
                    has_shorts = True
                else:
                    has_longform = True

        bottlenecks = []
        pitch_hook = ""

        if platform == "podcast":
            bottlenecks.append("Audio/long-form podcast focus: Missing short-form vertical video assets.")
            pitch_hook = "Automate long-form podcast repurposing into high-converting 9:16 vertical clips with captions."
        elif platform == "youtube":
            if has_longform and not has_shorts:
                bottlenecks.append("Long-form video focus without a dedicated vertical clip repurposing workflow.")
                pitch_hook = "Extract weekly YouTube long-form content into viral YouTube Shorts to drive channel discovery."
            elif has_shorts and not has_longform:
                bottlenecks.append("Short-form reliance with limited long-form depth.")
                pitch_hook = "Scale short-form production into structured long-form content pipelines."
            else:
                bottlenecks.append("Manual multi-platform asset management overhead.")
                pitch_hook = "Streamline long-form video processing into automated multi-platform clip distribution."

        return {
            "bottlenecks": bottlenecks,
            "pitch_hook": pitch_hook
        }