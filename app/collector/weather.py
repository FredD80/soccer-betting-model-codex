import httpx

from app.collector._retry import http_retry

_BASE = "https://api.openweathermap.org/data/2.5"
_ENCLOSURE_WEIGHTS = {"Open": 1.0, "Semi-Enclosed": 0.5, "Closed": 0.0}
_WIND_THRESHOLD_MPS = 7.0   # ~25 km/h — material impact threshold


class WeatherClient:
    def __init__(self, api_key: str):
        self._key = api_key

    @http_retry
    def fetch_current(self, lat: float, lon: float) -> dict:
        if not self._key:
            raise ValueError("openweathermap_key is not configured")
        resp = httpx.get(f"{_BASE}/weather",
                         params={"lat": lat, "lon": lon,
                                 "appid": self._key, "units": "metric"},
                         timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "wind_speed": data.get("wind", {}).get("speed", 0.0),
            "temp_celsius": data.get("main", {}).get("temp", 15.0),
            "has_rain": bool(data.get("rain")),
            "has_snow": bool(data.get("snow")),
            "description": data.get("weather", [{}])[0].get("description", ""),
        }


class WindModifier:
    @staticmethod
    def calculate(wind_speed_mps: float, enclosure: str) -> float:
        """Returns xG multiplier. 1.0 = no change. <1.0 = downward modifier."""
        enclosure_weight = _ENCLOSURE_WEIGHTS.get(enclosure, 1.0)
        if wind_speed_mps < _WIND_THRESHOLD_MPS or enclosure_weight == 0.0:
            return 1.0
        # Linear penalty: 0.01 per m/s above threshold, scaled by enclosure weight
        penalty = min(0.10, (wind_speed_mps - _WIND_THRESHOLD_MPS) * 0.01)
        return 1.0 - (penalty * enclosure_weight)
