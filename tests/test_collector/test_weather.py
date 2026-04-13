import pytest
import respx
import httpx
from app.collector.weather import WeatherClient, WindModifier

BASE = "https://api.openweathermap.org/data/2.5"


@respx.mock
def test_fetch_match_day_weather():
    respx.get(f"{BASE}/weather").mock(return_value=httpx.Response(200, json={
        "wind": {"speed": 9.2}, "rain": {}, "snow": {},
        "main": {"temp": 15.0},
        "weather": [{"description": "light rain"}]
    }))
    client = WeatherClient(api_key="test-key")
    w = client.fetch_current(lat=51.555, lon=-0.108)
    assert w["wind_speed"] == pytest.approx(9.2)
    assert w["temp_celsius"] == pytest.approx(15.0)


def test_wind_modifier_open_stadium():
    mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Open")
    assert mod < 1.0


def test_wind_modifier_closed_stadium():
    mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Closed")
    assert mod == pytest.approx(1.0)  # no modifier for enclosed


def test_wind_modifier_semi_enclosed():
    open_mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Open")
    semi_mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Semi-Enclosed")
    closed_mod = WindModifier.calculate(wind_speed_mps=10.0, enclosure="Closed")
    assert open_mod <= semi_mod <= closed_mod


def test_missing_key_raises():
    client = WeatherClient(api_key="")
    with pytest.raises(ValueError):
        client.fetch_current(lat=51.0, lon=-0.1)
