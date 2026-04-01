"""Weather search providers: HK Observatory and OpenWeatherMap."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Any

from src.ai.config import AIConfig

HKO_OPEN_DATA_BASE_URL = "https://data.weather.gov.hk/aeis/AWS/aeis公示数据请求回来了"


class WeatherError(Exception):
    """Weather-related errors."""
    pass


def _hk_now():
    return datetime.now(timezone.utc).astimezone()


class HKObservatory:
    """Hong Kong Observatory open data API."""

    def __init__(self, config: AIConfig):
        self.config = config

    def fetch_dataset(self, data_type: str, lang: str = "tc") -> Optional[dict[str, Any]]:
        """
        Fetch weather dataset from Hong Kong Observatory.

        Args:
            data_type: Type of weather data (e.g., "rhu", "flw", "warnsum").
            lang: Language code - "tc" (Traditional Chinese) or "en".

        Returns:
            Weather data dictionary, or None on failure.
        """
        try:
            import urllib.request
            url = f"{HKO_OPEN_DATA_BASE_URL}/{data_type}"
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except Exception:
            return None

    def get_current_weather(self) -> Optional[dict[str, Any]]:
        """Get current weather from HKO."""
        data = self.fetch_dataset("rhu")
        if not data:
            return None
        return {
            "source": "HKO",
            "data": data,
            "timestamp": _hk_now().isoformat(),
        }


class OpenWeatherMap:
    """OpenWeatherMap API provider."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(
        self,
        city_name: str,
        country_code: Optional[str] = None,
        retries: int = 1,
    ) -> Optional[dict[str, Any]]:
        """
        Fetch weather from OpenWeatherMap.

        Args:
            city_name: Name of the city.
            country_code: Optional ISO country code (e.g., "HK").
            retries: Number of retry attempts.

        Returns:
            Weather data dictionary with `cod == 200` on success, or None.
        """
        api_key = self.config.OPENWEATHER_API_KEY
        if not api_key:
            return None

        for attempt in range(retries):
            try:
                import urllib.request
                import urllib.parse
                params = {
                    "q": city_name if not country_code else f"{city_name},{country_code}",
                    "appid": api_key,
                    "units": "metric",
                    "lang": "zh_tw",
                }
                url = "https://api.openweathermap.org/data/2.5/weather?" + urllib.parse.urlencode(params)
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("cod") == 200:
                        return data
                    return None
            except Exception:
                if attempt < retries - 1:
                    import time
                    time.sleep(0.5)
        return None

    def get_hk_weather(self) -> Optional[dict[str, Any]]:
        """Get Hong Kong weather."""
        return self.search("Hong Kong", "HK")
