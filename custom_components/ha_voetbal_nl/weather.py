"""Weather forecast helper for HA Voetbal.nl match/training messages."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from aiohttp import ClientError, ClientSession

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_NL = {
    0: "onbewolkt",
    1: "overwegend helder",
    2: "half bewolkt",
    3: "bewolkt",
    45: "mist",
    48: "aanvriezende mist",
    51: "lichte motregen",
    53: "motregen",
    55: "dichte motregen",
    56: "lichte ijzelmotregen",
    57: "ijzelmotregen",
    61: "lichte regen",
    63: "regen",
    65: "zware regen",
    66: "lichte ijzel",
    67: "ijzel",
    71: "lichte sneeuw",
    73: "sneeuw",
    75: "zware sneeuw",
    77: "sneeuwkorrels",
    80: "lichte regenbuien",
    81: "regenbuien",
    82: "zware regenbuien",
    85: "lichte sneeuwbuien",
    86: "zware sneeuwbuien",
    95: "onweer",
    96: "onweer met lichte hagel",
    99: "onweer met zware hagel",
}


def weather_description(code: int | None) -> str:
    return _WMO_NL.get(int(code), "onbekend") if code is not None else "onbekend"


async def forecast_for_time(
    session: ClientSession,
    latitude: float,
    longitude: float,
    when_local: datetime,
) -> dict[str, Any] | None:
    """Return nearest-hour Open-Meteo forecast for a local event time."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m,wind_gusts_10m",
        "timezone": "auto",
        "forecast_days": 2,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    try:
        async with session.get(OPEN_METEO_URL, params=params, timeout=15) as response:
            if response.status >= 400:
                return None
            data = await response.json()
    except (ClientError, ValueError, TimeoutError):
        return None

    hourly = data.get("hourly") or {}
    times = list(hourly.get("time") or [])
    if not times:
        return None

    target = when_local.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    parsed: list[tuple[float, int]] = []
    for idx, value in enumerate(times):
        try:
            candidate = datetime.fromisoformat(str(value))
            parsed.append((abs((candidate - target).total_seconds()), idx))
        except ValueError:
            continue
    if not parsed:
        return None
    _, idx = min(parsed, key=lambda x: x[0])

    def pick(name, default=None):
        values = hourly.get(name) or []
        return values[idx] if idx < len(values) else default

    code = pick("weather_code")
    return {
        "tijd": times[idx],
        "temperatuur_c": pick("temperature_2m"),
        "neerslagkans_pct": pick("precipitation_probability"),
        "neerslag_mm": pick("precipitation"),
        "wind_kmh": pick("wind_speed_10m"),
        "windstoten_kmh": pick("wind_gusts_10m"),
        "weather_code": code,
        "omschrijving": weather_description(code),
    }
