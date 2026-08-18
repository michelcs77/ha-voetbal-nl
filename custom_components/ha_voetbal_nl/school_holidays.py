"""Schoolvakanties en concrete trainingskalender.

De runtime probeert eerst de officiële Rijksoverheid Open Data-feed.
Omdat die feed historisch achter kan lopen, bevat deze module daarnaast
een fallback met reeds officieel gepubliceerde vakantiedata.

Een seizoen loopt voor deze integratie van 1 augustus t/m 31 juli.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging

_LOGGER = logging.getLogger(__name__)

API_URLS = (
    "https://opendata.rijksoverheid.nl/v1/infotypes/schoolholidays/schoolyear/{schoolyear}?output=json",
    "https://opendata.rijksoverheid.nl/v1/sources/rijksoverheid/infotypes/schoolholidays/schoolyear/{schoolyear}?output=json",
)

DAY_TO_WEEKDAY = {
    "maandag": 0,
    "dinsdag": 1,
    "woensdag": 2,
    "donderdag": 3,
    "vrijdag": 4,
    "zaterdag": 5,
    "zondag": 6,
}

# Officieel gepubliceerde data. Structuur: schooljaar -> regio -> vakanties.
# Dit is tevens fallback als de Open Data-feed het betreffende schooljaar
# nog niet bevat. Nieuwe jaren worden bij voorkeur live uit de feed gelezen.
OFFICIAL_FALLBACK = {
    "2025-2026": {
        "noord": [
            ("Herfstvakantie", "2025-10-18", "2025-10-26"),
            ("Kerstvakantie", "2025-12-20", "2026-01-04"),
            ("Voorjaarsvakantie", "2026-02-21", "2026-03-01"),
            ("Meivakantie", "2026-04-25", "2026-05-03"),
            ("Zomervakantie", "2026-07-04", "2026-08-16"),
        ],
        "midden": [
            ("Herfstvakantie", "2025-10-18", "2025-10-26"),
            ("Kerstvakantie", "2025-12-20", "2026-01-04"),
            ("Voorjaarsvakantie", "2026-02-14", "2026-02-22"),
            ("Meivakantie", "2026-04-25", "2026-05-03"),
            ("Zomervakantie", "2026-07-18", "2026-08-30"),
        ],
        "zuid": [
            ("Herfstvakantie", "2025-10-11", "2025-10-19"),
            ("Kerstvakantie", "2025-12-20", "2026-01-04"),
            ("Voorjaarsvakantie", "2026-02-14", "2026-02-22"),
            ("Meivakantie", "2026-04-25", "2026-05-03"),
            ("Zomervakantie", "2026-07-11", "2026-08-23"),
        ],
    },
    "2026-2027": {
        "noord": [
            ("Herfstvakantie", "2026-10-10", "2026-10-18"),
            ("Kerstvakantie", "2026-12-19", "2027-01-03"),
            ("Voorjaarsvakantie", "2027-02-20", "2027-02-28"),
            ("Meivakantie", "2027-04-24", "2027-05-02"),
            ("Zomervakantie", "2027-07-10", "2027-08-22"),
        ],
        "midden": [
            ("Herfstvakantie", "2026-10-17", "2026-10-25"),
            ("Kerstvakantie", "2026-12-19", "2027-01-03"),
            ("Voorjaarsvakantie", "2027-02-20", "2027-02-28"),
            ("Meivakantie", "2027-04-24", "2027-05-02"),
            ("Zomervakantie", "2027-07-17", "2027-08-29"),
        ],
        "zuid": [
            ("Herfstvakantie", "2026-10-17", "2026-10-25"),
            ("Kerstvakantie", "2026-12-19", "2027-01-03"),
            ("Voorjaarsvakantie", "2027-02-13", "2027-02-21"),
            ("Meivakantie", "2027-04-24", "2027-05-02"),
            ("Zomervakantie", "2027-07-24", "2027-09-05"),
        ],
    },
    "2027-2028": {
        "noord": [
            ("Herfstvakantie", "2027-10-16", "2027-10-24"),
            ("Kerstvakantie", "2027-12-25", "2028-01-09"),
        ],
        "midden": [
            ("Herfstvakantie", "2027-10-16", "2027-10-24"),
            ("Kerstvakantie", "2027-12-25", "2028-01-09"),
        ],
        "zuid": [
            ("Herfstvakantie", "2027-10-23", "2027-10-31"),
            ("Kerstvakantie", "2027-12-25", "2028-01-09"),
        ],
    },
    "2028-2029": {
        "noord": [
            ("Herfstvakantie", "2028-10-14", "2028-10-22"),
            ("Kerstvakantie", "2028-12-23", "2029-01-07"),
            ("Voorjaarsvakantie", "2029-02-17", "2029-02-25"),
            ("Meivakantie", "2029-04-28", "2029-05-06"),
            ("Zomervakantie", "2029-07-21", "2029-09-02"),
        ],
        "midden": [
            ("Herfstvakantie", "2028-10-21", "2028-10-29"),
            ("Kerstvakantie", "2028-12-23", "2029-01-07"),
            ("Voorjaarsvakantie", "2029-02-17", "2029-02-25"),
            ("Meivakantie", "2029-04-28", "2029-05-06"),
            ("Zomervakantie", "2029-07-07", "2029-08-19"),
        ],
        "zuid": [
            ("Herfstvakantie", "2028-10-21", "2028-10-29"),
            ("Kerstvakantie", "2028-12-23", "2029-01-07"),
            ("Voorjaarsvakantie", "2029-02-10", "2029-02-18"),
            ("Meivakantie", "2029-04-28", "2029-05-06"),
            ("Zomervakantie", "2029-07-14", "2029-08-26"),
        ],
    },
    "2029-2030": {
        "noord": [
            ("Herfstvakantie", "2029-10-20", "2029-10-28"),
            ("Kerstvakantie", "2029-12-22", "2030-01-06"),
            ("Voorjaarsvakantie", "2030-02-16", "2030-02-24"),
            ("Meivakantie", "2030-04-27", "2030-05-05"),
            ("Zomervakantie", "2030-07-20", "2030-09-01"),
        ],
        "midden": [
            ("Herfstvakantie", "2029-10-20", "2029-10-28"),
            ("Kerstvakantie", "2029-12-22", "2030-01-06"),
            ("Voorjaarsvakantie", "2030-02-23", "2030-03-03"),
            ("Meivakantie", "2030-04-27", "2030-05-05"),
            ("Zomervakantie", "2030-07-13", "2030-08-25"),
        ],
        "zuid": [
            ("Herfstvakantie", "2029-10-13", "2029-10-21"),
            ("Kerstvakantie", "2029-12-22", "2030-01-06"),
            ("Voorjaarsvakantie", "2030-02-23", "2030-03-03"),
            ("Meivakantie", "2030-04-27", "2030-05-05"),
            ("Zomervakantie", "2030-07-06", "2030-08-18"),
        ],
    },
}


def season_for_date(today: date) -> tuple[int, int]:
    """Geef (startjaar, eindjaar) voor seizoen 1 aug t/m 31 juli."""
    start_year = today.year if today.month >= 8 else today.year - 1
    return start_year, start_year + 1


def season_bounds(today: date) -> tuple[date, date, str]:
    start_year, end_year = season_for_date(today)
    return date(start_year, 8, 1), date(end_year, 7, 31), f"{start_year}-{end_year}"


def _normalise_region(value: str | None) -> str | None:
    if not value:
        return None
    value = str(value).strip().casefold()
    aliases = {
        "north": "noord", "noord": "noord",
        "middle": "midden", "central": "midden", "midden": "midden",
        "south": "zuid", "zuid": "zuid",
    }
    return aliases.get(value)


def _parse_date(value) -> date | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _extract_api_holidays(payload, schoolyear: str, region: str) -> list[dict]:
    """Parseer de bekende Rijksoverheid JSON-structuur defensief."""
    docs = payload if isinstance(payload, list) else [payload]
    result = []

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        contents = doc.get("content", [])
        if isinstance(contents, dict):
            contents = [contents]
        for content in contents:
            if not isinstance(content, dict):
                continue
            if content.get("schoolyear") and str(content["schoolyear"]) != schoolyear:
                continue
            vacations = content.get("vacations", [])
            if isinstance(vacations, dict):
                vacations = [vacations]
            for vacation in vacations:
                if not isinstance(vacation, dict):
                    continue
                vacation_name = str(vacation.get("type") or "Schoolvakantie")
                regions = vacation.get("regions", [])
                if isinstance(regions, dict):
                    regions = [regions]
                for item in regions:
                    if not isinstance(item, dict):
                        continue
                    if _normalise_region(item.get("region")) != region:
                        continue
                    start = _parse_date(item.get("startdate"))
                    end = _parse_date(item.get("enddate"))
                    if start and end:
                        result.append({
                            "naam": vacation_name,
                            "start": start,
                            "einde": end,
                        })
    return result


def fallback_holidays(schoolyear: str, region: str) -> list[dict]:
    rows = OFFICIAL_FALLBACK.get(schoolyear, {}).get(region, [])
    return [
        {
            "naam": name,
            "start": datetime.strptime(start, "%Y-%m-%d").date(),
            "einde": datetime.strptime(end, "%Y-%m-%d").date(),
        }
        for name, start, end in rows
    ]


async def async_get_school_holidays(session, schoolyear: str, region: str):
    """Lees vakanties; live feed eerst, officiële fallback daarna."""
    region = _normalise_region(region)
    if region not in {"noord", "midden", "zuid"}:
        return [], "regio_onbekend"

    for url_template in API_URLS:
        url = url_template.format(schoolyear=schoolyear)
        try:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    continue
                payload = await response.json(content_type=None)
                parsed = _extract_api_holidays(payload, schoolyear, region)
                if parsed:
                    return parsed, "rijksoverheid_open_data"
        except Exception as err:  # netwerk/feed mag integratie niet breken
            _LOGGER.debug("Schoolvakantie-feed niet bruikbaar (%s): %s", url, err)

    fallback = fallback_holidays(schoolyear, region)
    if fallback:
        return fallback, "rijksoverheid_officiele_fallback"
    return [], "geen_vakantiedata"


def build_training_calendar(
    sessions: list[dict],
    season_start: date,
    season_end: date,
    holidays: list[dict],
    holidays_enabled: bool,
    override_iso_dates: set[str],
) -> list[dict]:
    """Genereer alle concrete trainingsdagen voor het volledige seizoen."""
    sessions_by_weekday: dict[int, list[dict]] = {}
    for session in sessions:
        weekday = DAY_TO_WEEKDAY.get(str(session.get("dag", "")).casefold())
        if weekday is not None:
            sessions_by_weekday.setdefault(weekday, []).append(session)

    calendar = []
    current = season_start
    while current <= season_end:
        for session in sessions_by_weekday.get(current.weekday(), []):
            iso = current.isoformat()
            holiday = next(
                (
                    item for item in holidays
                    if item["start"] <= current <= item["einde"]
                ),
                None,
            )

            if holidays_enabled and holiday is not None:
                if iso in override_iso_dates:
                    status = "training"
                    reason = "Toch trainen tijdens schoolvakantie"
                    holiday_name = holiday["naam"]
                else:
                    status = "vervallen"
                    reason = holiday["naam"]
                    holiday_name = holiday["naam"]
            else:
                status = "training"
                reason = "Normale trainingsdag"
                holiday_name = None

            calendar.append({
                "datum": current.strftime("%d-%m-%Y"),
                "dag": session.get("dag"),
                "verzameltijd": session.get("verzameltijd"),
                "start": session.get("start"),
                "einde": session.get("einde"),
                "veld": session.get("veld"),
                "status": status,
                "reden": reason,
                "vakantie": holiday_name,
            })
        current += timedelta(days=1)

    return calendar
