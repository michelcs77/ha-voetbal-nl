from __future__ import annotations

from aiohttp import ClientSession

ORS_URL = "https://api.heigit.org/openrouteservice/v2/directions/driving-car/json"

class RouteError(Exception):
    pass

async def async_calculate_route(
    session: ClientSession,
    api_key: str,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
):
    """Calculate a driving route with openrouteservice."""
    if not api_key:
        return None
    payload = {
        "coordinates": [
            [float(origin_lon), float(origin_lat)],
            [float(destination_lon), float(destination_lat)],
        ]
    }
    headers = {
        "Authorization": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with session.post(
            ORS_URL,
            json=payload,
            headers=headers,
            timeout=30,
        ) as response:
            if response.status != 200:
                body = (await response.text()).strip().replace("\n", " ")
                if len(body) > 220:
                    body = body[:220] + "..."
                raise RouteError(
                    f"ORS HTTP {response.status}: {body or 'geen fouttekst'}"
                )
            data = await response.json()
    except RouteError:
        raise
    except Exception as err:
        raise RouteError(str(err)) from err

    routes = data.get("routes") or []
    if not routes:
        raise RouteError("ORS gaf geen route terug")
    summary = routes[0].get("summary") or {}
    distance_m = summary.get("distance")
    duration_s = summary.get("duration")
    if distance_m is None or duration_s is None:
        raise RouteError("ORS route mist distance/duration")

    return {
        "afstand_enkel_km": round(float(distance_m) / 1000.0, 1),
        "afstand_retour_km": round(float(distance_m) * 2 / 1000.0, 1),
        "reistijd_minuten": int(round(float(duration_s) / 60.0)),
    }
