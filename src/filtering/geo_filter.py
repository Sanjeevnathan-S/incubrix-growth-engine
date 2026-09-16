from typing import Dict, Any, List
from config.settings import ALLOWED_COUNTRIES

class GeographicFilter:
    def __init__(self, allowed_countries: List[str] = None):
        self.allowed_countries = set(allowed_countries or ALLOWED_COUNTRIES)

    def is_valid_geo(self, creator: Dict[str, Any]) -> bool:
        country = creator.get("country", "").upper()
        return country in self.allowed_countries