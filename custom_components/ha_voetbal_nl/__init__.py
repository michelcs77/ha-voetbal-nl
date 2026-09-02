from pathlib import Path
import asyncio
import json
import secrets
from datetime import datetime, timezone, timedelta
from functools import partial
import hashlib
import re
from urllib.parse import urljoin

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.components import webhook
from aiohttp.web import Response
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .client import VoetbalNlClient
from .const import (
    CONF_CLUB_CITY,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TEAM_IDS,
    CONF_PLAYER_MANAGEMENT,
    CONF_DRIVING_MANAGEMENT,
    CONF_ROUTE_API_KEY,
    CONF_ROUTE_TEAM_ORIGINS,
    CONF_TRAINING_MANAGEMENT,
    CONF_MATCH_MANAGEMENT,
    DOMAIN,
    PLATFORMS,
    SERVICE_GENERATE_SEASON_PDF,
    SERVICE_SEND_SEASON_PDF,
    SERVICE_SEND_SEASON_PDF_DASHBOARD,
    ATTR_TEAM_ID,
    ATTR_FILENAME,
    CONF_WAHA_MANAGEMENT,
    CONF_WAHA_BASE_URL,
    CONF_WAHA_API_KEY,
    CONF_WAHA_SESSION,
    CONF_WAHA_WEBHOOK_BASE_URL,
    CONF_WAHA_WEBHOOK_LOCAL_ONLY,
    CONF_WAHA_TEAMS,
    CONF_WAHA_TEST_GROUP_ID,
    CONF_WAHA_TEST_GROUP_NAME,
    CONF_WAHA_PROD_GROUP_ID,
    CONF_WAHA_PROD_GROUP_NAME,
    CONF_WAHA_ASSISTANT_NAME,
    CONF_WAHA_IDENTITY_MAPPINGS,
    SERVICE_SEND_ATTENDANCE_POLL,
    SERVICE_CHECK_ATTENDANCE,
    SERVICE_SIMULATE_ATTENDANCE,
    SERVICE_SIMULATE_SCHEDULER,
    SERVICE_SHOW_ATTENDANCE_STATUS,
    ATTR_TEST_MODE,
    ATTR_PERSON,
    ATTR_STATUS,
    ATTR_SCHEDULER_PHASE,
    ATTR_MATCH_ID,
    CONF_WAHA_POLL_DAYS_BEFORE,
    CONF_WAHA_ATTENDANCE_MODE, WAHA_ATTENDANCE_MODE_POLLS, WAHA_ATTENDANCE_MODE_MESSAGES, DEFAULT_WAHA_ATTENDANCE_MODE,
    CONF_WAHA_POLL_TIME,
    CONF_WAHA_REMINDER_DAYS_BEFORE,
    CONF_WAHA_REMINDER_TIME,
    CONF_WAHA_PRODUCTION_ENABLED,
    DEFAULT_POLL_DAYS_BEFORE,
    DEFAULT_POLL_TIME,
    DEFAULT_REMINDER_DAYS_BEFORE,
    DEFAULT_REMINDER_TIME,
    POLL_SCHEDULER_INTERVAL_MINUTES,
    CONF_WAHA_MESSAGE_SCHEDULE, CONF_TRAINING_MESSAGE_SCHEDULE,
    MESSAGE_TYPE_POLL, MESSAGE_TYPE_REMINDER, MESSAGE_TYPE_INFO,
    CONF_TRAINING_POLL_DAYS_BEFORE, CONF_TRAINING_POLL_TIME,
    CONF_TRAINING_REMINDER_DAYS_BEFORE, CONF_TRAINING_REMINDER_TIME, CONF_TRAINING_PRODUCTION_ENABLED,
    DEFAULT_TRAINING_POLL_DAYS_BEFORE, DEFAULT_TRAINING_POLL_TIME,
    DEFAULT_TRAINING_REMINDER_DAYS_BEFORE, DEFAULT_TRAINING_REMINDER_TIME,
    SERVICE_SEND_TRAINING_POLL, SERVICE_CHECK_TRAINING_ATTENDANCE,
    SERVICE_SIMULATE_TRAINING_SCHEDULER, SERVICE_SHOW_TRAINING_ATTENDANCE_STATUS,
    ATTR_TRAINING_ID,
    CONF_MATCHDAY_MESSAGE_ENABLED, CONF_MATCHDAY_MESSAGE_TIME, CONF_MATCHDAY_WEATHER_ENABLED,
    DEFAULT_MATCHDAY_MESSAGE_TIME,
    CONF_TRAINING_INFO_ENABLED, CONF_TRAINING_INFO_HOURS_BEFORE, CONF_TRAINING_WEATHER_ENABLED,
    CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED, DEFAULT_TRAINING_INFO_HOURS_BEFORE,
    SERVICE_SEND_MATCHDAY_INFO, SERVICE_SEND_TRAINING_INFO,
    CONF_GEMINI_API_KEY, CONF_GEMINI_MODEL, DEFAULT_GEMINI_MODEL,
    CONF_MATCHDAY_COACH_ENABLED, CONF_TRAINING_COACH_ENABLED,
)
from .coordinator import VoetbalNlCoordinator
from .models import Club
from .route_cache import RouteCache
from .driving_plan import DrivingPlanStore
from .flagging_plan import FlaggingPlanStore
from .pdf_export import default_pdf_filename, write_season_pdf
from .season_export import build_season_export
from .waha import WahaClient, WahaError
from .attendance import AttendanceStore, now_iso
from .weather import forecast_for_time
from .gemini import GeminiClient, GeminiError




async def _async_collect_pdf_logos(hass: HomeAssistant, export: dict) -> dict[str, bytes]:
    """Fetch/cache all team logos referenced by the export. Missing logos are harmless."""
    urls = set()
    for key in ("team_logo_url",):
        value = export.get(key)
        if value:
            urls.add(str(value))
    for match in export.get("wedstrijden", []):
        for key in ("thuis_logo_url", "uit_logo_url", "tegenstander_logo_url"):
            value = match.get(key)
            if value:
                urls.add(str(value))

    if not urls:
        return {}

    session = async_get_clientsession(hass)
    cache_dir = Path(hass.config.path("www/ha_voetbal_nl/logo_cache"))
    await hass.async_add_executor_job(partial(cache_dir.mkdir, parents=True, exist_ok=True))
    result: dict[str, bytes] = {}

    for original_url in sorted(urls):
        url = urljoin("https://www.voetbal.nl/", original_url)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        cache_path = cache_dir / f"{digest}.img"
        try:
            if cache_path.exists():
                data = await hass.async_add_executor_job(cache_path.read_bytes)
                if data:
                    result[original_url] = data
                    continue
        except OSError:
            pass

        try:
            async with session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 HA-Voetbal.nl",
                    "Referer": "https://www.voetbal.nl/",
                },
                allow_redirects=True,
                timeout=15,
            ) as response:
                if response.status != 200:
                    continue
                data = await response.read()
                if not data or len(data) > 2_000_000:
                    continue
                result[original_url] = data
                try:
                    await hass.async_add_executor_job(cache_path.write_bytes, data)
                except OSError:
                    pass
        except Exception:
            # A logo may never make the PDF action fail. Text-only fallback remains valid.
            continue

    return result


PDF_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_FILENAME): cv.string,
})

SEND_SEASON_PDF_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=False): cv.boolean,
    vol.Optional(ATTR_FILENAME): cv.string,
})

ATTENDANCE_POLL_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
    vol.Optional(ATTR_MATCH_ID): cv.string,
})

ATTENDANCE_CHECK_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
    vol.Optional(ATTR_MATCH_ID): cv.string,
})

ATTENDANCE_SIMULATE_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Required(ATTR_MATCH_ID): cv.string,
    vol.Required(ATTR_PERSON): cv.string,
    vol.Required(ATTR_STATUS): vol.In(["aanwezig", "afwezig", "geblesseerd", "niet_gereageerd"]),
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
})

SCHEDULER_SIMULATE_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Required(ATTR_MATCH_ID): cv.string,
    vol.Required(ATTR_SCHEDULER_PHASE): vol.In(["pollmoment", "remindermoment", "aftrap"]),
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
})


ATTENDANCE_STATUS_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Required(ATTR_MATCH_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
})

TRAINING_POLL_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
    vol.Optional(ATTR_TRAINING_ID): cv.string,
})
TRAINING_CHECK_SERVICE_SCHEMA = TRAINING_POLL_SERVICE_SCHEMA
TRAINING_SCHEDULER_SIMULATE_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Required(ATTR_TRAINING_ID): cv.string,
    vol.Required(ATTR_SCHEDULER_PHASE): vol.In(["pollmoment", "remindermoment", "training_start"]),
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
})
TRAINING_STATUS_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Required(ATTR_TRAINING_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
})

MATCHDAY_INFO_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
    vol.Optional(ATTR_MATCH_ID): cv.string,
})

TRAINING_INFO_SERVICE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TEAM_ID): cv.string,
    vol.Optional(ATTR_TEST_MODE, default=True): cv.boolean,
    vol.Optional(ATTR_TRAINING_ID): cv.string,
})


def _extract_poll_message_id(result: dict) -> str | None:
    """Extract the full WAHA message id returned when a poll is sent."""
    if not isinstance(result, dict):
        return None
    raw_id = result.get("id")
    candidates = []
    if isinstance(raw_id, str):
        candidates.append(raw_id)
    elif isinstance(raw_id, dict):
        candidates.extend([raw_id.get("_serialized"), raw_id.get("serialized")])
    data_id = (result.get("_data") or {}).get("id")
    if isinstance(data_id, str):
        candidates.append(data_id)
    elif isinstance(data_id, dict):
        candidates.extend([data_id.get("_serialized"), data_id.get("serialized")])
    return next((str(x) for x in candidates if x), None)


def _extract_poll_id(result: dict) -> str | None:
    """Extract the legacy inner poll id used by the attendance vote store."""
    if not isinstance(result, dict):
        return None
    raw_id = result.get("id")
    candidates = []
    if isinstance(raw_id, dict):
        candidates.append(raw_id.get("id"))
    data_id = (result.get("_data") or {}).get("id")
    if isinstance(data_id, dict):
        candidates.append(data_id.get("id"))
    candidates.append(_extract_poll_message_id(result))
    value = next((str(x) for x in candidates if x), None)
    if not value:
        return None
    # WAHA's full message id is normally true_<chatId>_<innerId>. The webhook
    # for WEBJS reports only the inner parentMsgKey.id, which remains our store key.
    if value.startswith(("true_", "false_")) and "_" in value:
        parts = value.split("_", 2)
        if len(parts) == 3 and parts[2]:
            return parts[2].split("_", 1)[0]
    return value


def _poll_reply_message_id(poll_id: str, meta: dict) -> str | None:
    """Return a full WAHA message id suitable for reply/pin operations."""
    full = str((meta or {}).get("waha_message_id") or "").strip()
    if full:
        return full
    poll_id = str(poll_id or "").strip()
    if poll_id.startswith(("true_", "false_")):
        return poll_id
    chat_id = str((meta or {}).get("groep_id") or "").strip()
    if poll_id and chat_id:
        return f"true_{chat_id}_{poll_id}"
    return None


def _extract_vote_poll_id(payload: dict) -> str | None:
    data = payload.get("payload") or {}
    internal = data.get("_data") or {}
    parent = internal.get("parentMsgKey") or {}
    if parent.get("id"):
        return str(parent["id"])
    poll = data.get("poll") or {}
    combined = str(poll.get("id") or "")
    # WEBJS compound id contains ..._<message-id>_<participant>.
    match = re.search(r"@g\.us_([^_]+)_", combined)
    return match.group(1) if match else None


def _status_from_vote(selected: list[str]) -> tuple[str | None, str | None]:
    choice = selected[0] if selected else None
    if not selected:
        return "niet_gereageerd", None
    text = (choice or "").casefold()
    if "aanwezig" in text:
        return "aanwezig", choice
    if "afwezig" in text:
        return "afwezig", choice
    if "geblesseerd" in text:
        return "geblesseerd", choice
    return None, choice



def _norm_simulation_person(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").casefold()).strip("_")

def _match_datetime_local(match=None, meta: dict | None = None):
    """Return a timezone-aware local kickoff datetime."""
    date_value = getattr(match, "date_iso", None) if match is not None else (meta or {}).get("datum")
    time_value = getattr(match, "time", None) if match is not None else (meta or {}).get("tijd")
    if not date_value:
        return None
    try:
        naive = datetime.strptime(f"{date_value} {time_value or '23:59'}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None
    return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


def _next_match(team_data, now=None):
    now = now or dt_util.now()
    candidates = []
    for match in team_data.matches:
        kickoff = _match_datetime_local(match=match)
        if kickoff is not None and kickoff >= now:
            candidates.append((kickoff, match))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)


def _scheduled_local_datetime(kickoff, days_before: int, hhmm: str):
    """Build configured local schedule time X calendar days before kickoff."""
    try:
        hour, minute = [int(part) for part in str(hhmm).split(":", 1)]
        target_date = kickoff.date() - timedelta(days=int(days_before))
        return datetime(
            target_date.year, target_date.month, target_date.day, hour, minute,
            tzinfo=dt_util.DEFAULT_TIME_ZONE,
        )
    except (TypeError, ValueError):
        return None


def _training_id(item: dict) -> str:
    try:
        return "training_" + datetime.strptime(str(item.get("datum")), "%d-%m-%Y").strftime("%Y%m%d") + "_" + str(item.get("start") or "0000").replace(":", "")
    except Exception:
        return "training_" + re.sub(r"[^0-9A-Za-z]+", "_", str(item.get("datum") or "unknown"))

def _training_datetime_local(item: dict):
    """Return a timezone-aware local training start for calendar items or stored poll metadata."""
    date_value = str(item.get("datum") or "").strip()
    time_value = str(item.get("start") or item.get("tijd") or "").strip()
    for date_format in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(f"{date_value} {time_value}", f"{date_format} %H:%M")
            return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        except (TypeError, ValueError):
            continue
    return None

def _next_training(team_data, now=None):
    now = now or dt_util.now()
    candidates=[]
    for item in team_data.training_calendar:
        if item.get("status") != "training":
            continue
        start=_training_datetime_local(item)
        if start is not None and start >= now:
            candidates.append((start,item))
    return min(candidates,key=lambda x:x[0]) if candidates else (None,None)

def _training_date_id(item: dict) -> str:
    """Stable date-only training id used by the training schedule sensor.

    Older/public training schedule data exposes IDs such as training_20260818,
    while attendance internals historically added the start time
    (training_20260818_2000). Accept both forms so service calls can safely use
    the ID users actually see in Home Assistant.
    """
    try:
        return "training_" + datetime.strptime(str(item.get("datum")), "%d-%m-%Y").strftime("%Y%m%d")
    except Exception:
        return "training_" + re.sub(r"[^0-9A-Za-z]+", "_", str(item.get("datum") or "unknown"))


def _find_training(team_data, training_id: str):
    requested = str(training_id or "").strip()
    for item in team_data.training_calendar:
        if item.get("status") != "training":
            continue
        # Accept both the internal time-qualified ID and the public date-only ID.
        if requested in {_training_id(item), _training_date_id(item)}:
            return item
    return None

def _team_people(team_data):
    squad = list(dict.fromkeys(list(team_data.selected_players) + list(team_data.manual_players)))
    staff = list(dict.fromkeys(member.name for member in team_data.staff))
    return squad, staff


def _attendance_people(coordinator, team_data, test_mode: bool, group_id: str | None = None):
    """Return people eligible for a WhatsApp poll in the requested environment.

    Explicit identity mappings are authoritative when mappings exist for this
    team/group/environment.  This keeps a person that is only in the HA squad
    (for example a test-only contact) out of production reminders and summaries.
    If no mappings exist for the scope yet, retain legacy behaviour and return
    the complete HA squad/staff so existing teams keep working until they are
    configured.
    """
    squad, staff = _team_people(team_data)
    waha_cfg = getattr(coordinator, "waha_config", {}) or {}
    environment = "test" if bool(test_mode) else "production"
    if group_id is None:
        group_id, _ = _configured_group(coordinator, team_data.team.team_id, bool(test_mode))
    mappings = [
        item for item in (waha_cfg.get(CONF_WAHA_IDENTITY_MAPPINGS, []) or [])
        if isinstance(item, dict)
        and str(item.get("team_id")) == str(team_data.team.team_id)
        and str(item.get("group_id")) == str(group_id)
        and str(item.get("environment")) == environment
    ]
    if not mappings:
        return squad, staff
    eligible_players = []
    eligible_staff = []
    squad_set = set(squad)
    staff_set = set(staff)
    for item in mappings:
        if not bool(item.get("enabled", True)):
            continue
        person = str(item.get("persoon") or "").strip()
        role = str(item.get("rol") or "").strip()
        if role == "speler" and person in squad_set and person not in eligible_players:
            eligible_players.append(person)
        elif role == "staf" and person in staff_set and person not in eligible_staff:
            eligible_staff.append(person)
    return eligible_players, eligible_staff


def _poll_eligible_people(coordinator, team_data, test_mode: bool, group_id: str | None = None):
    """Alias used when storing the fixed participant set on a poll."""
    return _attendance_people(coordinator, team_data, test_mode, group_id)


def _driver_control(team_data, coordinator, summary: dict) -> dict:
    """Compare immutable driving assignment with current attendance responses."""
    match_id = summary.get("wedstrijd_id")
    match = next((m for m in team_data.matches if m.match_id == match_id), None)
    if not match or match.is_home is not False or coordinator.driving_plan is None:
        return {"chauffeurs": [], "chauffeurs_zonder_stem": [], "chauffeurs_conflict": []}
    status = coordinator.driving_plan.status_for_match(team_data, match)
    drivers = list(status.get("chauffeurs", []))
    missing = set(summary.get("niet_gereageerd", []))
    absent = set(summary.get("afwezig", []))
    injured = set(summary.get("geblesseerd", []))
    conflicts = []
    for name in drivers:
        if name in absent:
            conflicts.append({"naam": name, "status": "afwezig", "melding": "Afwezig maar als chauffeur ingepland. Graag zelf actie ondernemen."})
        elif name in injured:
            conflicts.append({"naam": name, "status": "geblesseerd", "melding": "Geblesseerd maar als chauffeur ingepland. Graag zelf actie ondernemen."})
    return {
        "chauffeurs": drivers,
        "chauffeurs_zonder_stem": [name for name in drivers if name in missing],
        "chauffeurs_conflict": conflicts,
    }


def _display_date_iso(value: str | None) -> str:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return str(value or "")


def _format_weather_block(weather: dict | None, title: str) -> list[str]:
    if not weather:
        return []
    temp = weather.get("temperatuur_c")
    chance = weather.get("neerslagkans_pct")
    rain = weather.get("neerslag_mm")
    wind = weather.get("wind_kmh")
    gust = weather.get("windstoten_kmh")
    lines = [f"🌦️ {title}"]
    if temp is not None:
        lines.append(f"🌡️ {float(temp):.0f}°C — {weather.get('omschrijving') or 'onbekend'}")
    if chance is not None:
        lines.append(f"🌧️ Neerslagkans: {float(chance):.0f}%")
    if rain is not None:
        lines.append(f"☔ Neerslag: {float(rain):.1f} mm")
    if wind is not None:
        wind_line = f"💨 Wind: {float(wind):.0f} km/u"
        if gust is not None and float(gust) > float(wind) + 5:
            wind_line += f" (stoten {float(gust):.0f} km/u)"
        lines.append(wind_line)
    return lines


def _training_coordinates(hass, team_data):
    """Best available coordinates for training weather; prefer club home ground."""
    for match in team_data.matches:
        if match.is_home is True and match.latitude is not None and match.longitude is not None:
            return float(match.latitude), float(match.longitude)
    try:
        return float(hass.config.latitude), float(hass.config.longitude)
    except (TypeError, ValueError):
        return None, None


def _meeting_time_for_match(team_data, match, kickoff):
    minutes = int(getattr(team_data, "match_present_minutes", 45) or 45)
    if match.is_home is False and match.route and match.route.reistijd_minuten:
        minutes += int(match.route.reistijd_minuten)
    return kickoff - timedelta(minutes=minutes)


def _match_title(team_data, match):
    if match.is_home is True:
        return f"{team_data.team.name} - {match.opponent}"
    if match.is_home is False:
        return f"{match.opponent} - {team_data.team.name}"
    return match.opponent or team_data.team.name


def _waze_url(match):
    if match.latitude is None or match.longitude is None:
        return None
    return (
        "https://waze.com/ul?ll="
        f"{float(match.latitude):.7f}%2C{float(match.longitude):.7f}"
        "&navigate=yes&utm_source=homeassistant_voetbal_nl"
    )


def _build_pre_poll_match_info(coordinator, team_data, match) -> str:
    """Build the practical match info sent immediately before an attendance poll."""
    kickoff = _match_datetime_local(match=match)
    if kickoff is None:
        raise HomeAssistantError("Wedstrijd heeft geen geldige aftraptijd.")

    title = _match_title(team_data, match)
    meeting = _meeting_time_for_match(team_data, match, kickoff)
    if match.is_home is False:
        header = f"🚌 UITWEDSTRIJD {team_data.team.name.upper()} 🚌"
        location_title = "📍 BESTEMMING"
    elif match.is_home is True:
        header = f"🏟️ THUISWEDSTRIJD {team_data.team.name.upper()} 🏟️"
        location_title = "📍 LOCATIE"
    else:
        header = f"⚽ WEDSTRIJDINFO {team_data.team.name.upper()} ⚽"
        location_title = "📍 LOCATIE"

    lines = [
        header,
        "",
        f"📅 Week {kickoff.isocalendar().week} — {_display_date_iso(match.date_iso)}",
        f"⏰ Aftrap: {match.time or kickoff.strftime('%H:%M')}",
        "",
        "🏆 WEDSTRIJD",
        title,
    ]

    if match.accommodation or match.street or match.postal_city:
        lines += ["", location_title]
        if match.accommodation:
            lines.append(str(match.accommodation))
        address = " ".join(x for x in [match.street, match.postal_city] if x)
        if address:
            lines.append(address)
    if match.field_name:
        lines += ["", f"🥅 Veld: {match.field_name}"]

    lines += ["", "👥 VERZAMELEN", f"⏰ Tijd: {meeting.strftime('%H:%M')}"]
    if match.is_home is False and match.route and match.route.vertrek_naam:
        lines.append(f"📍 {match.route.vertrek_naam}")
    elif match.accommodation:
        lines.append(f"📍 {match.accommodation}")

    if match.is_home is False:
        lines += ["", "🚗 REIS"]
        if match.route and match.route.afstand_enkel_km is not None:
            lines.append(f"📏 Afstand: {float(match.route.afstand_enkel_km):.1f} km")
        if match.route and match.route.reistijd_minuten is not None:
            lines.append(f"⏱️ Reistijd: {int(match.route.reistijd_minuten)} minuten")
        waze = _waze_url(match)
        if waze:
            lines += ["", "🧭 WAZE", waze]
        if coordinator.driving_plan is not None:
            status = coordinator.driving_plan.status_for_match(team_data, match)
            drivers = list(status.get("chauffeurs") or [])
            if drivers:
                lines += ["", "🚙 RIJSCHEMA"] + [f"• {name}" for name in drivers]

    return "\n".join(lines).strip()




def _gemini_settings(coordinator) -> tuple[str, str]:
    options = getattr(coordinator, "local_config", {}) or {}
    model = str(options.get(CONF_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    # Migrate the retired legacy default transparently so diagnostics,
    # validation and generation all report/use the same effective model.
    if model == "gemini-2.5-flash":
        model = DEFAULT_GEMINI_MODEL
    return (
        str(options.get(CONF_GEMINI_API_KEY) or "").strip(),
        model,
    )


def _coach_prompt_match(team_data, match, weather: dict | None, summary: dict | None) -> str:
    opponent = getattr(match, "opponent_name", None) or getattr(match, "opponent", None) or "de tegenstander"
    home_away = "thuis" if getattr(match, "is_home", None) else "uit"
    counts = summary or {}
    weather_line = "onbekend"
    if weather:
        weather_line = f"{weather.get('temperatuur_c', '?')}°C, {weather.get('omschrijving') or 'onbekend'}"
    return (
        "Je bent de digitale voetbalcoach van een Nederlands volwassen amateur-vriendenteam.\n"
        f"Team: {team_data.team.name}. Wedstrijd: {home_away} tegen {opponent}.\n"
        f"Aanwezig: {len(counts.get('aanwezig', []))}; afwezig: {len(counts.get('afwezig', []))}; "
        f"geblesseerd: {len(counts.get('geblesseerd', []))}.\n"
        f"Weer rond aftrap: {weather_line}.\n\n"
        "Schrijf een persoonlijk woordje van de coach van 70 tot 110 woorden en minimaal 4 zinnen. "
        "Gebruik duidelijke kleedkamerhumor, zelfspot en licht sarcasme. Het mag een beetje brutaal en lekker informeel zijn, "
        "alsof de trainer dit zelf in de WhatsApp-groep zet. Maak gerust algemene grappen over conditie, leeftijd, de derde helft, "
        "bier, de scheidsrechter of het niveau van een vriendenteam, maar beledig niemand persoonlijk. "
        "Plaagt het team als geheel, nooit een individu. Vermijd grof of denigrerend taalgebruik en formuleringen zoals 'luie kadavers', "
        "'kantine slopen' of vergelijkbare agressieve/beledigende bewoordingen; kies liever speelse zelfspot en vriendelijke plagerijen. "
        "Verzin geen spelersnamen, blessures, uitslagen, tactische feiten of bijzonderheden over de tegenstander. "
        "Vermijd professionele voetbalclichés en lange tactische analyses. Gebruik enkele passende emoji's en eindig grappig én motiverend. "
        "Geef uitsluitend de coachtekst terug, zonder titel of uitleg."
    )


def _coach_prompt_training(team_data, item: dict, weather: dict | None, summary: dict | None) -> str:
    counts = summary or {}
    weather_line = "onbekend"
    if weather:
        weather_line = f"{weather.get('temperatuur_c', '?')}°C, {weather.get('omschrijving') or 'onbekend'}"
    return (
        "Je bent de digitale voetbalcoach van een Nederlands volwassen amateur-vriendenteam.\n"
        f"Team: {team_data.team.name}. Training op {item.get('datum') or ''} om {item.get('start') or item.get('starttijd') or ''}.\n"
        f"Aanwezig: {len(counts.get('aanwezig', []))}; afwezig: {len(counts.get('afwezig', []))}; "
        f"geblesseerd: {len(counts.get('geblesseerd', []))}.\n"
        f"Weer tijdens training: {weather_line}.\n\n"
        "Schrijf een persoonlijk trainingswoordje van de coach van 70 tot 110 woorden en minimaal 4 zinnen. "
        "Gebruik veel gezellige kleedkamerhumor, zelfspot en licht sarcasme. Maak algemene grappen over trainingsopkomst, conditie, "
        "hesjes, warming-up, partijvormen, te laat komen of de eeuwige discussie of de bal uit was. "
        "Plaagt het team als geheel, nooit een individu. Vermijd grof of denigrerend taalgebruik en formuleringen zoals 'luie kadavers', "
        "'kantine slopen' of vergelijkbare agressieve/beledigende bewoordingen; gebruik liever luchtige zelfspot en vriendelijke kleedkamerplagerij. "
        "Verzin geen spelersnamen, blessures of andere persoonlijke feiten. Houd het vriendelijk en geschikt voor een team-WhatsApp. "
        "Geen zware professionele voetbaltaal. Gebruik enkele passende emoji's en eindig met een grappige, motiverende oproep om te komen trainen. "
        "Geef uitsluitend de coachtekst terug, zonder titel of uitleg."
    )


async def _generate_coach_text(coordinator, prompt: str) -> str | None:
    api_key, model = _gemini_settings(coordinator)
    diag = {"gemini_status": "niet_actief", "gemini_model": model, "gemini_pogingen": 0, "coachbericht_woorden": 0}
    setattr(coordinator, "_gemini_last_diagnostics", diag)
    if not api_key:
        diag["gemini_fout"] = "Gemini API-key ontbreekt."
        return None
    try:
        client = GeminiClient(async_get_clientsession(coordinator.hass), api_key, model)
        diag["gemini_status"] = "bezig"
        diag["gemini_pogingen"] = 1
        text = await client.generate_coach_message(prompt)
        if len(text.split()) < 40:
            retry_prompt = (
                prompt
                + "\n\nJe vorige antwoord was te kort. Schrijf nu echt 70 tot 110 woorden, minimaal 4 volledige zinnen, "
                "met duidelijk meer humor en kleedkamersfeer. Geef alleen de nieuwe coachtekst terug."
            )
            diag["gemini_pogingen"] = 2
            text = await client.generate_coach_message(retry_prompt)
        words = len(text.split())
        diag["coachbericht_woorden"] = words
        if words < 40:
            diag["gemini_status"] = "te_kort"
            diag["gemini_fout"] = f"Coachtekst bleef te kort ({words} woorden)."
            return None
        diag["gemini_status"] = "ok"
        return text
    except Exception as err:
        diag["gemini_status"] = "fout"
        diag["gemini_fout"] = str(err)[:500]
        return None


async def _build_matchday_message(coordinator, team_data, match, weather_enabled: bool = True, coach_enabled: bool = False, test_mode: bool = False) -> tuple[str, dict | None, str | None]:
    kickoff = _match_datetime_local(match=match)
    if kickoff is None:
        raise HomeAssistantError("Wedstrijd heeft geen geldige aftraptijd.")
    title = _match_title(team_data, match)
    meeting = _meeting_time_for_match(team_data, match, kickoff)
    lines = [
        f"⚽ WEDSTRIJDINFO {team_data.team.name.upper()} ⚽",
        "",
        f"📅 Week {kickoff.isocalendar().week} — {_display_date_iso(match.date_iso)}",
        f"⏰ Aftrap: {match.time or kickoff.strftime('%H:%M')}",
        "",
        "🏆 WEDSTRIJD",
        title,
    ]
    if match.accommodation or match.street or match.postal_city:
        lines += ["", "📍 LOCATIE"]
        if match.accommodation:
            lines.append(str(match.accommodation))
        address = " ".join(x for x in [match.street, match.postal_city] if x)
        if address:
            lines.append(address)
    if match.field_name:
        lines += ["", f"🥅 Veld: {match.field_name}"]

    lines += ["", "👥 VERZAMELEN", f"⏰ Tijd: {meeting.strftime('%H:%M')}"]
    if match.is_home is False and match.route and match.route.vertrek_naam:
        lines.append(f"📍 {match.route.vertrek_naam}")
    elif match.accommodation:
        lines.append(f"📍 {match.accommodation}")

    store = getattr(coordinator, "attendance_store", None)
    squad, staff = _attendance_people(coordinator, team_data, test_mode)
    summary = store.summary_for_team(team_data.team.team_id, squad, staff, match.match_id, test_mode) if store is not None else {}

    weather = None
    if weather_enabled and match.latitude is not None and match.longitude is not None:
        weather = await forecast_for_time(
            async_get_clientsession(coordinator.hass), float(match.latitude), float(match.longitude), kickoff
        )
        block = _format_weather_block(weather, "WEER BIJ AFTRAP")
        if block:
            lines += ["", *block]

    if match.is_home is False:
        lines += ["", "🚗 REIS"]
        if match.route and match.route.afstand_enkel_km is not None:
            lines.append(f"📏 Afstand: {float(match.route.afstand_enkel_km):.1f} km")
        if match.route and match.route.reistijd_minuten is not None:
            lines.append(f"⏱️ Reistijd: {int(match.route.reistijd_minuten)} minuten")
        waze = _waze_url(match)
        if waze:
            lines += ["", "🧭 Navigatie via Waze", waze]
        if coordinator.driving_plan is not None:
            status = coordinator.driving_plan.status_for_match(team_data, match)
            drivers = list(status.get("chauffeurs") or [])
            if drivers:
                lines += ["", "🚙 RIJSCHEMA"] + [f"• {name}" for name in drivers]

            store = getattr(coordinator, "attendance_store", None)
            if store is not None:
                squad, staff = _attendance_people(coordinator, team_data, test_mode)
                summary = store.summary_for_team(team_data.team.team_id, squad, staff, match.match_id, test_mode)
                conflicts = _driver_control(team_data, coordinator, summary).get("chauffeurs_conflict", [])
                if conflicts:
                    lines += ["", "🚨 CHAUFFEURCONTROLE"]
                    for item in conflicts:
                        label = "afwezig" if item.get("status") == "afwezig" else "geblesseerd"
                        lines.append(f"• {item.get('naam')} — {label} maar als chauffeur ingepland")
                    lines.append("Graag zelf actie ondernemen of vervanging regelen. Het rijschema is niet aangepast.")

    # v0.10.10: include the assigned assistant referee/flagger in matchday
    # messages only when flagging is enabled for this team. Training messages
    # are intentionally unchanged because a flagger is a match task.
    if getattr(team_data, "flagging_enabled", False) and getattr(coordinator, "flagging_plan", None) is not None:
        flag_status = coordinator.flagging_plan.status_for_match(
            team_data, match, coordinator.driving_plan
        )
        lines += ["", "🚩 VLAGGER"]
        if flag_status.get("status") == "geregeld" and flag_status.get("vlagger"):
            lines.append(f"• {flag_status.get('vlagger')}")
        elif flag_status.get("status") == "conflict" and flag_status.get("vlagger"):
            lines.append(f"• {flag_status.get('vlagger')} — ⚠️ controle nodig")
        else:
            lines.append("• ❌ Nog niet geregeld")
    coach_text = None
    if coach_enabled:
        coach_text = await _generate_coach_text(coordinator, _coach_prompt_match(team_data, match, weather, summary))
        if coach_text:
            lines += ["", "🎙️ WOORDJE VAN DE COACH", coach_text]
    return "\n".join(lines).strip(), weather, coach_text


async def _build_training_info_message(
    coordinator, team_data, item: dict, weather_enabled: bool = True, attendance_enabled: bool = True, coach_enabled: bool = False, test_mode: bool = False
) -> tuple[str, dict | None, str | None]:
    start = _training_datetime_local(item)
    if start is None:
        raise HomeAssistantError("Training heeft geen geldige starttijd.")
    lines = [
        f"⚽ TRAININGSINFO {team_data.team.name.upper()} ⚽",
        "",
        f"📅 {str(item.get('dag') or '').capitalize()} {item.get('datum') or ''}",
        f"🕗 Training: {item.get('start') or ''} - {item.get('einde') or ''}",
    ]
    if item.get("verzameltijd"):
        lines.append(f"👥 Aanwezig: {item.get('verzameltijd')}")
    elif item.get("aanwezig"):
        lines.append(f"👥 Aanwezig: {item.get('aanwezig')}")
    if item.get("veld"):
        lines.append(f"🥅 {item.get('veld')}")

    weather = None
    if weather_enabled:
        lat, lon = _training_coordinates(coordinator.hass, team_data)
        if lat is not None and lon is not None:
            weather = await forecast_for_time(async_get_clientsession(coordinator.hass), lat, lon, start)
            block = _format_weather_block(weather, "WEER TIJDENS TRAINING")
            if block:
                lines += ["", *block]

    store = getattr(coordinator, "attendance_store", None)
    squad, staff = _attendance_people(coordinator, team_data, test_mode)
    summary = store.summary_for_training(team_data.team.team_id, _training_id(item), squad, staff, test_mode) if store is not None else {}
    if attendance_enabled and store is not None:
            lines += [
                "",
                "👥 AANWEZIGHEID",
                f"✅ Aanwezig: {len(summary.get('aanwezig', []))}",
                f"❌ Afwezig: {len(summary.get('afwezig', []))}",
                f"🤕 Geblesseerd: {len(summary.get('geblesseerd', []))}",
                f"❓ Nog niet gereageerd: {len(summary.get('niet_gereageerd', []))}",
            ]
    coach_text = None
    if coach_enabled:
        coach_text = await _generate_coach_text(coordinator, _coach_prompt_training(team_data, item, weather, summary))
        if coach_text:
            lines += ["", "🎙️ WOORDJE VAN DE COACH", coach_text]
    lines += ["", "Tot vanavond! ⚽"]
    return "\n".join(lines).strip(), weather, coach_text


def _configured_group(coordinator, team_id: str, test_mode: bool):
    team_cfg = ((coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_id, {}) or {})
    gid = str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID if test_mode else CONF_WAHA_PROD_GROUP_ID) or "").strip()
    name = str(team_cfg.get(CONF_WAHA_TEST_GROUP_NAME if test_mode else CONF_WAHA_PROD_GROUP_NAME) or "").strip()
    prod = str(team_cfg.get(CONF_WAHA_PROD_GROUP_ID) or "").strip()
    test = str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID) or "").strip()
    if not gid:
        raise HomeAssistantError("Geen WhatsApp-testgroep ingesteld." if test_mode else "Geen WhatsApp-productiegroep ingesteld.")
    if test_mode and (gid != test or (prod and gid == prod)):
        raise HomeAssistantError("Testbericht geblokkeerd door ongeldige groepsconfiguratie.")
    if not test_mode and gid != prod:
        raise HomeAssistantError("Productiebericht geblokkeerd door ongeldige groepsconfiguratie.")
    return gid, name


async def _send_matchday_info(coordinator, team_data, match, test_mode: bool, force: bool = False):
    client = getattr(coordinator, "waha_client", None)
    store = getattr(coordinator, "attendance_store", None)
    if client is None or store is None:
        raise HomeAssistantError("WAHA is nog niet geconfigureerd voor deze integratie.")
    group_id, group_name = _configured_group(coordinator, team_data.team.team_id, test_mode)
    cfg = ((coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_data.team.team_id, {}) or {})
    key = f"matchday:{team_data.team.team_id}:{match.match_id}:{'test' if test_mode else 'prod'}"
    if not force and store.message_sent(key):
        return {"bericht_verzonden": False, "al_verzonden": True, "groep_naam": group_name}
    message, weather, coach_text = await _build_matchday_message(
        coordinator, team_data, match, bool(cfg.get(CONF_MATCHDAY_WEATHER_ENABLED, True)),
        bool(cfg.get(CONF_MATCHDAY_COACH_ENABLED, False)),
    )
    await client.send_text(group_id, message, team_data.team.name)
    store.mark_message_sent(key)
    await store.async_save()
    return {"bericht_verzonden": True, "al_verzonden": False, "groep_id": group_id, "groep_naam": group_name, "weer": weather, "coachbericht": coach_text, **(getattr(coordinator, "_gemini_last_diagnostics", {}) if bool(cfg.get(CONF_MATCHDAY_COACH_ENABLED, False)) else {})}


async def _send_training_info(coordinator, team_data, item: dict, test_mode: bool, force: bool = False):
    client = getattr(coordinator, "waha_client", None)
    store = getattr(coordinator, "attendance_store", None)
    if client is None or store is None:
        raise HomeAssistantError("WAHA is nog niet geconfigureerd voor deze integratie.")
    group_id, group_name = _configured_group(coordinator, team_data.team.team_id, test_mode)
    cfg = ((coordinator.local_config.get("training_management") or {}).get(team_data.team.team_id, {}) or {})
    tid = _training_id(item)
    key = f"traininginfo:{team_data.team.team_id}:{tid}:{'test' if test_mode else 'prod'}"
    if not force and store.message_sent(key):
        return {"bericht_verzonden": False, "al_verzonden": True, "groep_naam": group_name}
    waha_team_cfg = ((coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_data.team.team_id, {}) or {})
    attendance_mode = str(waha_team_cfg.get(CONF_WAHA_ATTENDANCE_MODE, DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE)
    attendance_summary_enabled = bool(cfg.get(CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED, True)) and attendance_mode == WAHA_ATTENDANCE_MODE_POLLS
    message, weather, coach_text = await _build_training_info_message(
        coordinator,
        team_data,
        item,
        bool(cfg.get(CONF_TRAINING_WEATHER_ENABLED, True)),
        attendance_summary_enabled,
        bool(cfg.get(CONF_TRAINING_COACH_ENABLED, False)),
        test_mode,
    )
    await client.send_text(group_id, message, team_data.team.name)
    store.mark_message_sent(key)
    await store.async_save()
    return {"bericht_verzonden": True, "al_verzonden": False, "groep_id": group_id, "groep_naam": group_name, "weer": weather, "coachbericht": coach_text, **(getattr(coordinator, "_gemini_last_diagnostics", {}) if bool(cfg.get(CONF_TRAINING_COACH_ENABLED, False)) else {})}


def _build_reminder_message(team_data, summary: dict, driver_info: dict) -> str:
    """Build one compact group reminder; never alter the driving plan."""
    missing_players = list(summary.get("niet_gereageerd", []))
    missing_staff = list(summary.get("staf_niet_gereageerd", []))
    driver_missing = set(driver_info.get("chauffeurs_zonder_stem", []))
    conflicts = list(driver_info.get("chauffeurs_conflict", []))
    lines = [
        f"⚽ {team_data.team.name} - aanwezigheid",
        f"{summary.get('wedstrijd') or ''}",
        f"📅 {summary.get('datum') or ''}  ⏰ {summary.get('tijd') or ''}",
        "",
    ]
    if missing_players or missing_staff:
        lines.append("Willen jullie nog stemmen in de aanwezigheidspoll?")
        for name in missing_players:
            suffix = " 🚗 chauffeur" if name in driver_missing else ""
            lines.append(f"• {name}{suffix}")
        for name in missing_staff:
            lines.append(f"• {name} (staf)")
        lines.append("")
    if conflicts:
        lines.append("🚨 Chauffeurcontrole:")
        for item in conflicts:
            label = "❌ afwezig" if item.get("status") == "afwezig" else "🤕 geblesseerd"
            lines.append(f"• {item.get('naam')} — {label} — staat als chauffeur gepland.")
        lines.append("Graag zelf actie ondernemen of vervanging regelen. Het rijschema wordt niet aangepast.")
    return "\n".join(lines).strip()


async def _async_attendance_control(
    coordinator, team_data, test_mode: bool, mark_done: bool = False, match_id: str | None = None
):
    """Check non-voters and driver conflicts and optionally send one group reminder."""
    store = getattr(coordinator, "attendance_store", None)
    client = getattr(coordinator, "waha_client", None)
    if store is None or client is None:
        return None
    if match_id:
        match = next((m for m in team_data.matches if m.match_id == match_id), None)
        if match is None:
            return None
        kickoff = _match_datetime_local(match=match)
    else:
        kickoff, match = _next_match(team_data)
        if not match:
            return None
    poll_id, meta = store.latest_poll(team_data.team.team_id, match.match_id, test_mode)
    if not poll_id or not meta or meta.get("gesloten"):
        return None
    if kickoff is not None and dt_util.now() >= kickoff:
        store.update_poll(poll_id, poll_status="gesloten", gesloten=True, gesloten_op=now_iso())
        await store.async_save()
        return None
    squad, staff = _attendance_people(coordinator, team_data, test_mode, str(meta.get("groep_id") or ""))
    summary = store.summary_for_team(team_data.team.team_id, squad, staff, match.match_id, test_mode)
    # summary_for_team picks latest regardless of mode, so ensure this exact poll is summarized for control.
    if summary.get("poll_id") != poll_id:
        # Temporarily derive statuses directly from this poll if a newer test/prod poll exists.
        player_status = {n: "niet_gereageerd" for n in squad}
        staff_status = {n: "niet_gereageerd" for n in staff}
        for vote in store.votes_for_poll(poll_id):
            person, role, answer = vote.get("persoon"), vote.get("rol"), vote.get("status")
            if role == "speler" and person in player_status and answer in {"aanwezig", "afwezig", "geblesseerd"}:
                player_status[person] = answer
            elif role == "staf" and person in staff_status and answer in {"aanwezig", "afwezig", "geblesseerd"}:
                staff_status[person] = answer
        summary = dict(meta)
        summary.update({
            "poll_id": poll_id,
            "wedstrijd_id": match.match_id,
            "niet_gereageerd": [n for n,v in player_status.items() if v == "niet_gereageerd"],
            "afwezig": [n for n,v in player_status.items() if v == "afwezig"],
            "geblesseerd": [n for n,v in player_status.items() if v == "geblesseerd"],
            "staf_niet_gereageerd": [n for n,v in staff_status.items() if v == "niet_gereageerd"],
        })
    driver_info = _driver_control(team_data, coordinator, summary)
    message = _build_reminder_message(team_data, summary, driver_info)
    sent = False
    if message and (summary.get("niet_gereageerd") or summary.get("staf_niet_gereageerd") or driver_info.get("chauffeurs_conflict")):
        await client.send_text(
            str(meta.get("groep_id")),
            message,
            team_data.team.name,
            reply_to=_poll_reply_message_id(poll_id, meta),
        )
        sent = True
    if mark_done:
        store.update_poll(
            poll_id,
            controle_24u_uitgevoerd=True,
            controle_24u_op=now_iso(),
            herinnering_verzonden=sent,
            poll_status="actief",
        )
        await store.async_save()
        coordinator.async_set_updated_data(coordinator.data)
    return {
        "poll_id": poll_id,
        "wedstrijd_id": match.match_id,
        "bericht_verzonden": sent,
        "aantal_niet_gereageerd": len(summary.get("niet_gereageerd", [])),
        "aantal_staf_niet_gereageerd": len(summary.get("staf_niet_gereageerd", [])),
        **driver_info,
    }


async def _async_training_control(coordinator, team_data, test_mode: bool, mark_done: bool=False, training_id: str|None=None):
    store=getattr(coordinator,"attendance_store",None); client=getattr(coordinator,"waha_client",None)
    if store is None or client is None: return None
    if training_id:
        item=_find_training(team_data,training_id); start=_training_datetime_local(item or {})
    else:
        start,item=_next_training(team_data)
    if not item or not start: return None
    tid=_training_id(item)
    poll_id,meta=store.latest_training_poll(team_data.team.team_id,tid,test_mode)
    if not poll_id or not meta or meta.get("gesloten"): return None
    if dt_util.now() >= start:
        store.update_poll(poll_id,poll_status="gesloten",gesloten=True,gesloten_op=now_iso(),sluitreden="training_start")
        await store.async_save(); return None
    squad,staff=_attendance_people(coordinator, team_data, test_mode, str(meta.get("groep_id") or ""))
    summary=store.summary_for_training(team_data.team.team_id,tid,squad,staff,test_mode)
    missing=list(summary.get("niet_gereageerd",[])); missing_staff=list(summary.get("staf_niet_gereageerd",[]))
    lines=[f"⏰ Herinnering trainingspoll - {team_data.team.name}",f"{item.get('dag','').capitalize()} {item.get('datum')} - training {item.get('start')} - {item.get('einde')}",""]
    if missing or missing_staff:
        lines.append("Willen jullie nog stemmen in de trainingspoll?")
        lines += [f"• {n}" for n in missing] + [f"• {n} (staf)" for n in missing_staff]
    sent=False
    if missing or missing_staff:
        await client.send_text(str(meta.get("groep_id")), "\n".join(lines), team_data.team.name); sent=True
    if mark_done:
        store.update_poll(poll_id,controle_24u_uitgevoerd=True,controle_24u_op=now_iso(),herinnering_verzonden=sent)
        await store.async_save(); coordinator.async_set_updated_data(coordinator.data)
    return {"poll_id":poll_id,"training_id":tid,"bericht_verzonden":sent,"aantal_niet_gereageerd":len(missing),"aantal_staf_niet_gereageerd":len(missing_staff)}

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-level actions."""

    async def handle_generate_season_pdf(call: ServiceCall):
        team_id = call.data[ATTR_TEAM_ID].strip()
        requested_filename = call.data.get(ATTR_FILENAME, "").strip()

        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))

        if not found:
            raise HomeAssistantError(f"Team-ID {team_id} is niet geladen in HA Voetbal.nl.")
        if len(found) > 1:
            raise HomeAssistantError(
                f"Team-ID {team_id} komt in meerdere configuraties voor; verwijder de dubbele configuratie."
            )

        _, coordinator, team_data = found[0]

        # Rebuild from live team data so newly changed rijschema assignments
        # are always reflected in the PDF.
        export = build_season_export(team_data, coordinator.driving_plan, coordinator.flagging_plan)
        team_data.season_export_data = export
        if not export:
            raise HomeAssistantError("Er is nog geen seizoensdata beschikbaar voor dit team.")

        filename = requested_filename or default_pdf_filename(
            team_data.team.name, export.get("seizoen", "")
        )
        filename = Path(filename).name
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        # Keep the filename safe and predictable for /local URLs.
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)

        relative_dir = Path("www") / "ha_voetbal_nl"
        destination = Path(hass.config.path(str(relative_dir))) / filename
        logo_bytes = await _async_collect_pdf_logos(hass, export)
        await hass.async_add_executor_job(write_season_pdf, export, destination, logo_bytes)

        cache_token = int(destination.stat().st_mtime_ns) if destination.exists() else int(datetime.now().timestamp())
        url = f"/local/ha_voetbal_nl/{filename}?v={cache_token}"
        team_data.season_export_data["laatste_pdf"] = {
            "bestandsnaam": filename,
            "pad": str(destination),
            "url": url,
        }
        coordinator.async_set_updated_data(coordinator.data)

        return {
            "team_id": team_id,
            "team_naam": team_data.team.name,
            "bestandsnaam": filename,
            "pad": str(destination),
            "url": url,
        }

    async def handle_send_season_pdf(call: ServiceCall):
        """Generate and send the season PDF to the configured WAHA group."""
        team_id = call.data[ATTR_TEAM_ID].strip()
        test_mode = bool(call.data.get(ATTR_TEST_MODE, False))
        requested_filename = call.data.get(ATTR_FILENAME, "").strip()

        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))

        if len(found) != 1:
            raise HomeAssistantError(
                f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl."
            )

        _, coordinator, team_data = found[0]

        # Rebuild from live team data so newly changed rijschema assignments
        # are always reflected in the PDF.
        export = build_season_export(team_data, coordinator.driving_plan, coordinator.flagging_plan)
        team_data.season_export_data = export
        if not export:
            raise HomeAssistantError(
                "Er is nog geen seizoensdata beschikbaar voor dit team."
            )

        filename = requested_filename or default_pdf_filename(
            team_data.team.name, export.get("seizoen", "")
        )
        filename = Path(filename).name
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)

        relative_dir = Path("www") / "ha_voetbal_nl"
        destination = Path(hass.config.path(str(relative_dir))) / filename
        logo_bytes = await _async_collect_pdf_logos(hass, export)
        await hass.async_add_executor_job(
            write_season_pdf, export, destination, logo_bytes
        )

        waha_client = getattr(coordinator, "waha_client", None)
        waha_cfg = getattr(coordinator, "waha_config", {}) or {}
        team_cfg = (waha_cfg.get(CONF_WAHA_TEAMS) or {}).get(team_id, {})
        if waha_client is None:
            raise HomeAssistantError(
                "WAHA is nog niet geconfigureerd voor deze integratie."
            )

        group_id_key = (
            CONF_WAHA_TEST_GROUP_ID if test_mode else CONF_WAHA_PROD_GROUP_ID
        )
        group_name_key = (
            CONF_WAHA_TEST_GROUP_NAME if test_mode else CONF_WAHA_PROD_GROUP_NAME
        )
        group_id = str(team_cfg.get(group_id_key) or "").strip()
        group_name = str(team_cfg.get(group_name_key) or "").strip()
        if not group_id:
            raise HomeAssistantError(
                "Geen WhatsApp-testgroep ingesteld." if test_mode
                else "Geen WhatsApp-productiegroep ingesteld."
            )

        # Explicit safety check: never silently fall back to the other group.
        prod_group = str(team_cfg.get(CONF_WAHA_PROD_GROUP_ID) or "").strip()
        test_group = str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID) or "").strip()
        if test_mode and group_id == prod_group and prod_group:
            raise HomeAssistantError(
                "Veiligheidsstop: testgroep is gelijk aan de productiegroep."
            )
        if not test_mode and group_id == test_group and test_group:
            raise HomeAssistantError(
                "Veiligheidsstop: productiegroep is gelijk aan de testgroep."
            )

        season = str(export.get("seizoen", "")).strip()
        team_name = str(team_data.team.name or "").strip() or "v.v. Cuijk"
        if team_name.casefold().startswith("v.v. "):
            team_title = "v.v. " + team_name[5:].upper()
        else:
            team_title = team_name.upper()
        assistant_name = (
            str(team_cfg.get(CONF_WAHA_ASSISTANT_NAME) or "De AI-Stafchef").strip()
            or "De AI-Stafchef"
        )
        pdf_caption = (
            f"⚽ PROGRAMMAUPDATE – {team_title}\n\n"
            "Beste spelers,\n\n"
            "Hierbij de nieuwste versie van ons seizoensprogramma. "
            "Voor zover momenteel bekend zijn de trainingen, wedstrijden en verdere planning hierin verwerkt.\n\n"
            "Houd er rekening mee dat het programma gedurende het seizoen nog kan wijzigen. "
            "Wijzigingen en nieuwe informatie worden verwerkt zodra deze bekend zijn.\n\n"
            "De AI-Stafchef houdt namens de staf een oogje op het programma en informeert jullie waar nodig over trainingen, wedstrijden, aanwezigheid, reminders, weer, vervoer en andere belangrijke zaken.\n\n"
            "En nee: dat betekent nog steeds niet dat je kunt vergeten zelf op de poll te stemmen. 😉\n\n"
            "📎 Hierbij de actuele PDF.\n\n"
            f"🤖 {assistant_name}\n"
            f"Digitale stafassistent van {team_name}\n"
            ""
        )
        result = await waha_client.send_file(
            group_id,
            str(destination),
            filename=filename,
            caption=pdf_caption,
            mimetype="application/pdf",
        )

        team_data.season_export_data["laatste_pdf"] = {
            "bestandsnaam": filename,
            "pad": str(destination),
            "url": f"/local/ha_voetbal_nl/{filename}",
        }
        coordinator.async_set_updated_data(coordinator.data)

        return {
            "team_id": team_id,
            "team_naam": team_data.team.name,
            "bestandsnaam": filename,
            "groep_id": group_id,
            "groep_naam": group_name,
            "testmodus": test_mode,
            "bericht_verzonden": True,
            "waha_resultaat": result,
        }

    async def handle_send_attendance_poll(call: ServiceCall):
        team_id = call.data[ATTR_TEAM_ID].strip()
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))
        requested_match_id = str(call.data.get(ATTR_MATCH_ID) or "").strip()
        if requested_match_id and not test_mode:
            raise HomeAssistantError("wedstrijd_id mag alleen handmatig worden gebruikt wanneer testmodus aan staat.")

        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))
        if len(found) != 1:
            raise HomeAssistantError(
                f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl."
            )

        _, coordinator, team_data = found[0]
        waha_client = getattr(coordinator, "waha_client", None)
        attendance_store = getattr(coordinator, "attendance_store", None)
        waha_cfg = getattr(coordinator, "waha_config", {}) or {}
        team_cfg = (waha_cfg.get(CONF_WAHA_TEAMS) or {}).get(team_id, {})
        attendance_mode = str(team_cfg.get(CONF_WAHA_ATTENDANCE_MODE, DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE)
        if attendance_mode != WAHA_ATTENDANCE_MODE_POLLS:
            raise HomeAssistantError("Voor dit team staat WhatsApp op alleen berichten. Een aanwezigheidspoll is uitgeschakeld.")
        if waha_client is None or attendance_store is None:
            raise HomeAssistantError("WAHA is nog niet geconfigureerd voor deze integratie.")

        group_id_key = CONF_WAHA_TEST_GROUP_ID if test_mode else CONF_WAHA_PROD_GROUP_ID
        group_name_key = CONF_WAHA_TEST_GROUP_NAME if test_mode else CONF_WAHA_PROD_GROUP_NAME
        group_id = str(team_cfg.get(group_id_key) or "").strip()
        group_name = str(team_cfg.get(group_name_key) or "").strip()
        if not group_id:
            raise HomeAssistantError(
                "Geen WhatsApp-testgroep ingesteld." if test_mode
                else "Geen WhatsApp-productiegroep ingesteld."
            )

        # Safety guard: a test poll may never be sent to the configured production group.
        prod_group_id = str(team_cfg.get(CONF_WAHA_PROD_GROUP_ID) or "").strip()
        test_group_id = str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID) or "").strip()
        if test_mode:
            if not test_group_id or group_id != test_group_id:
                raise HomeAssistantError("Testpoll geblokkeerd: ongeldige testgroepconfiguratie.")
            if prod_group_id and group_id == prod_group_id:
                raise HomeAssistantError(
                    "Testpoll geblokkeerd: testgroep en productiegroep zijn hetzelfde."
                )
        elif not prod_group_id or group_id != prod_group_id:
            raise HomeAssistantError("Productiepoll geblokkeerd: ongeldige productiegroepconfiguratie.")

        # Normal operation always uses the next match. An explicit wedstrijd_id is
        # intentionally test-only so production can never target an arbitrary fixture.
        if requested_match_id:
            match = next((m for m in team_data.matches if m.match_id == requested_match_id), None)
            if match is None:
                raise HomeAssistantError(
                    f"Wedstrijd-ID {requested_match_id} is niet gevonden voor {team_data.team.name}."
                )
            kickoff = _match_datetime_local(match=match)
            if kickoff is None:
                raise HomeAssistantError("De gekozen wedstrijd heeft geen geldige datum/tijd.")
        else:
            kickoff, match = _next_match(team_data)
            if match is None:
                raise HomeAssistantError("Geen toekomstige wedstrijd gevonden voor dit team.")

        if match.is_home is True:
            wedstrijd = f"{team_data.team.name} - {match.opponent}"
        elif match.is_home is False:
            wedstrijd = f"{match.opponent} - {team_data.team.name}"
        else:
            wedstrijd = match.opponent
        display_date = match.date_iso
        try:
            display_date = datetime.strptime(match.date_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
        except (TypeError, ValueError):
            pass
        question = (
            f"⚽ {team_data.team.name} - aanwezigheid\n"
            f"{display_date} {match.time or ''}\n"
            f"{wedstrijd}\n\nBen je erbij?"
        )
        options = ["✅ Aanwezig", "❌ Afwezig", "🤕 Geblesseerd"]
        # v0.9.29: always send practical match information immediately before the poll.
        # This applies equally to manual test polls and automatic production polls.
        try:
            info_message = _build_pre_poll_match_info(coordinator, team_data, match)
            await waha_client.send_text(group_id, info_message, team_data.team.name)
            await asyncio.sleep(2)
            result = await waha_client.send_poll(group_id, question, options)
        except WahaError as err:
            raise HomeAssistantError(f"WAHA wedstrijdinfo/poll verzenden mislukt: {err}") from err
        poll_id = _extract_poll_id(result)
        waha_message_id = _extract_poll_message_id(result)
        if not poll_id:
            raise HomeAssistantError("WAHA heeft geen poll-ID teruggegeven.")

        attendance_store.add_poll(poll_id, {
            "team_id": team_id,
            "team_naam": team_data.team.name,
            "wedstrijd_id": match.match_id,
            "wedstrijd": wedstrijd,
            "datum": match.date_iso,
            "tijd": match.time,
            "groep_id": group_id,
            "groep_naam": group_name,
            "testmodus": test_mode,
            "waha_message_id": waha_message_id,
            "vastgezet": False,
            "vastgezet_op": None,
            "losgemaakt": False,
            "losgemaakt_op": None,
            "verzonden_op": now_iso(),
            "verzonden_timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "poll_status": "actief",
            "eligible_players": _poll_eligible_people(coordinator, team_data, test_mode, group_id)[0],
            "eligible_staff": _poll_eligible_people(coordinator, team_data, test_mode, group_id)[1],
            "controle_24u_uitgevoerd": False,
            "gesloten": False,
        })
        # v0.11.9: pin production match polls for seven days. Pinning is an
        # enhancement only: a WAHA/engine pin failure must never block the poll.
        if not test_mode and waha_message_id:
            try:
                await waha_client.pin_message(group_id, waha_message_id, duration=604800)
            except Exception as err:
                LOGGER.warning(
                    "Wedstrijdpoll %s kon niet worden vastgezet in WhatsApp: %s",
                    poll_id,
                    err,
                )
            else:
                attendance_store.update_poll(
                    poll_id, vastgezet=True, vastgezet_op=now_iso()
                )

        await attendance_store.async_save()
        coordinator.async_set_updated_data(coordinator.data)
        return {
            "team_id": team_id,
            "team_naam": team_data.team.name,
            "wedstrijd_id": match.match_id,
            "wedstrijd": wedstrijd,
            "poll_id": poll_id,
            "groep_id": group_id,
            "groep_naam": group_name,
            "testmodus": test_mode,
            "wedstrijdinfo_verzonden": True,
            "poll_vastgezet": bool(attendance_store.poll(poll_id).get("vastgezet")),
            "waha_message_id": waha_message_id,
            "wachttijd_voor_poll_seconden": 2,
        }

    async def handle_check_attendance(call: ServiceCall):
        team_id = call.data[ATTR_TEAM_ID].strip()
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))
        requested_match_id = str(call.data.get(ATTR_MATCH_ID) or "").strip()
        if requested_match_id and not test_mode:
            raise HomeAssistantError("wedstrijd_id mag alleen handmatig worden gebruikt wanneer testmodus aan staat.")
        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))
        if len(found) != 1:
            raise HomeAssistantError(
                f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl."
            )
        _, coordinator, team_data = found[0]
        if getattr(coordinator, "waha_client", None) is None:
            raise HomeAssistantError("WAHA is nog niet geconfigureerd voor deze integratie.")
        try:
            result = await _async_attendance_control(
                coordinator, team_data, test_mode=test_mode, mark_done=False,
                match_id=requested_match_id or None
            )
        except WahaError as err:
            raise HomeAssistantError(f"WAHA aanwezigheidscontrole mislukt: {err}") from err
        if result is None:
            raise HomeAssistantError(
                "Geen actieve aanwezigheidspoll gevonden voor de gekozen wedstrijd in deze modus."
            )
        return {"team_id": team_id, "team_naam": team_data.team.name, "testmodus": test_mode, **result}

    async def handle_simulate_attendance(call: ServiceCall):
        """Inject or remove one synthetic vote in a test poll only."""
        team_id = call.data[ATTR_TEAM_ID].strip()
        match_id = call.data[ATTR_MATCH_ID].strip()
        person = call.data[ATTR_PERSON].strip()
        status = call.data[ATTR_STATUS]
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))
        if not test_mode:
            raise HomeAssistantError("Simuleren is uitsluitend toegestaan in testmodus.")

        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))
        if len(found) != 1:
            raise HomeAssistantError(f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl.")
        _, coordinator, team_data = found[0]
        store = getattr(coordinator, "attendance_store", None)
        if store is None:
            raise HomeAssistantError("Aanwezigheidsopslag is niet beschikbaar.")
        match = next((m for m in team_data.matches if m.match_id == match_id), None)
        if match is None:
            raise HomeAssistantError(f"Wedstrijd-ID {match_id} is niet gevonden voor {team_data.team.name}.")
        poll_id, meta = store.latest_poll(team_id, match_id, True)
        if not poll_id or not meta or meta.get("gesloten"):
            raise HomeAssistantError("Geen actieve testpoll gevonden voor deze wedstrijd.")

        squad, staff = _team_people(team_data)
        role = "speler" if person in squad else ("staf" if person in staff else None)
        if role is None:
            raise HomeAssistantError(f"{person} is geen speler of staflid van {team_data.team.name}.")

        voter_id = f"simulation:{_norm_simulation_person(person)}"
        vote_key = f"{poll_id}|{voter_id}"
        if status == "niet_gereageerd":
            store.data.setdefault("votes", {}).pop(vote_key, None)
        else:
            labels = {"aanwezig": "✅ Aanwezig", "afwezig": "❌ Afwezig", "geblesseerd": "🤕 Geblesseerd"}
            store.record_vote(poll_id, voter_id, {
                "voter_id": voter_id,
                "wa_id": voter_id,
                "contact_naam": person,
                "persoon": person,
                "rol": role,
                "status": status,
                "keuze": labels[status],
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "gesimuleerd": True,
            })
        await store.async_save()
        coordinator.async_set_updated_data(coordinator.data)
        driver_info = _driver_control(
            team_data, coordinator,
            store.summary_for_team(team_id, squad, staff, match_id, True),
        )
        return {
            "team_id": team_id, "team_naam": team_data.team.name,
            "wedstrijd_id": match_id, "poll_id": poll_id,
            "persoon": person, "rol": role, "status": status,
            "testmodus": True, "gesimuleerd": True,
            **driver_info,
        }

    async def handle_simulate_scheduler(call: ServiceCall):
        """Safely simulate poll -> reminder -> kickoff using only the configured test group."""
        team_id = call.data[ATTR_TEAM_ID].strip()
        match_id = call.data[ATTR_MATCH_ID].strip()
        phase = call.data[ATTR_SCHEDULER_PHASE]
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))
        if not test_mode:
            raise HomeAssistantError("Schedulersimulatie is uitsluitend toegestaan in testmodus.")

        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))
        if len(found) != 1:
            raise HomeAssistantError(f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl.")
        _, coordinator, team_data = found[0]
        client = getattr(coordinator, "waha_client", None)
        store = getattr(coordinator, "attendance_store", None)
        if client is None or store is None:
            raise HomeAssistantError("WAHA is nog niet geconfigureerd voor deze integratie.")
        match = next((m for m in team_data.matches if m.match_id == match_id), None)
        if match is None:
            raise HomeAssistantError(f"Wedstrijd-ID {match_id} is niet gevonden voor {team_data.team.name}.")

        team_cfg = (coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_id, {})
        test_group_id = str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID) or "").strip()
        test_group_name = str(team_cfg.get(CONF_WAHA_TEST_GROUP_NAME) or "").strip()
        prod_group_id = str(team_cfg.get(CONF_WAHA_PROD_GROUP_ID) or "").strip()
        if not test_group_id:
            raise HomeAssistantError("Geen WhatsApp-testgroep ingesteld.")
        if prod_group_id and test_group_id == prod_group_id:
            raise HomeAssistantError("Schedulersimulatie geblokkeerd: testgroep en productiegroep zijn hetzelfde.")

        if match.is_home is True:
            wedstrijd = f"{team_data.team.name} - {match.opponent}"
        elif match.is_home is False:
            wedstrijd = f"{match.opponent} - {team_data.team.name}"
        else:
            wedstrijd = match.opponent

        if phase == "pollmoment":
            # Close only earlier scheduler simulations for this same match. Manual test polls remain untouched.
            changed = False
            for old_poll_id, old_meta in store.polls_for_match(team_id, match_id, True):
                if old_meta.get("scheduler_simulatie") and not old_meta.get("gesloten"):
                    store.update_poll(
                        old_poll_id, poll_status="gesloten", gesloten=True,
                        gesloten_op=now_iso(), sluitreden="nieuwe_scheduler_simulatie"
                    )
                    changed = True
            if changed:
                await store.async_save()

            display_date = match.date_iso
            try:
                display_date = datetime.strptime(match.date_iso, "%Y-%m-%d").strftime("%d-%m-%Y")
            except (TypeError, ValueError):
                pass
            question = (
                f"🧪 SCHEDULERTEST - {team_data.team.name}\n"
                f"{display_date} {match.time or ''}\n"
                f"{wedstrijd}\n\nBen je erbij?"
            )
            # Mirror the real production flow: match info first, poll two seconds later.
            info_message = _build_pre_poll_match_info(coordinator, team_data, match)
            await client.send_text(test_group_id, info_message, team_data.team.name)
            await asyncio.sleep(2)
            result = await client.send_poll(
                test_group_id, question, ["✅ Aanwezig", "❌ Afwezig", "🤕 Geblesseerd"]
            )
            poll_id = _extract_poll_id(result)
            if not poll_id:
                raise HomeAssistantError("WAHA heeft geen poll-ID teruggegeven.")
            store.add_poll(poll_id, {
                "team_id": team_id, "team_naam": team_data.team.name,
                "wedstrijd_id": match.match_id, "wedstrijd": wedstrijd,
                "datum": match.date_iso, "tijd": match.time,
                "groep_id": test_group_id, "groep_naam": test_group_name,
                "testmodus": True, "scheduler_simulatie": True,
                "simulatie_fase": "pollmoment",
                "verzonden_op": now_iso(),
                "verzonden_timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "poll_status": "actief",
                "eligible_players": _poll_eligible_people(coordinator, team_data, True, test_group_id)[0],
                "eligible_staff": _poll_eligible_people(coordinator, team_data, True, test_group_id)[1],
                "controle_24u_uitgevoerd": False, "gesloten": False,
            })
            await store.async_save()
            coordinator.async_set_updated_data(coordinator.data)
            return {
                "team_id": team_id, "team_naam": team_data.team.name,
                "wedstrijd_id": match_id, "wedstrijd": wedstrijd,
                "fase": phase, "poll_id": poll_id,
                "groep_id": test_group_id, "groep_naam": test_group_name,
                "testmodus": True, "poll_status": "actief",
                "productiegroep_aangeraakt": False, "rijschema_aangepast": False,
            }

        poll_id, meta = store.latest_poll(team_id, match_id, True)
        if not poll_id or not meta or not meta.get("scheduler_simulatie"):
            raise HomeAssistantError("Geen actieve schedulersimulatie gevonden. Start eerst met fase pollmoment.")

        if phase == "remindermoment":
            if meta.get("gesloten"):
                raise HomeAssistantError("De schedulersimulatie is al afgesloten. Start opnieuw met pollmoment.")
            result = await _async_attendance_control(
                coordinator, team_data, test_mode=True, mark_done=True, match_id=match_id
            )
            if result is None:
                raise HomeAssistantError("De reminderfase kon niet worden uitgevoerd.")
            store.update_poll(poll_id, scheduler_simulatie=True, simulatie_fase="remindermoment")
            await store.async_save()
            coordinator.async_set_updated_data(coordinator.data)
            return {
                "team_id": team_id, "team_naam": team_data.team.name,
                "wedstrijd_id": match_id, "wedstrijd": wedstrijd,
                "fase": phase, "testmodus": True,
                "productiegroep_aangeraakt": False, "rijschema_aangepast": False,
                **result,
            }

        # phase == aftrap: close the simulated poll immediately, without sending another message.
        store.update_poll(
            poll_id, poll_status="gesloten", gesloten=True, gesloten_op=now_iso(),
            sluitreden="scheduler_simulatie_aftrap", scheduler_simulatie=True, simulatie_fase="aftrap"
        )
        await store.async_save()
        coordinator.async_set_updated_data(coordinator.data)
        return {
            "team_id": team_id, "team_naam": team_data.team.name,
            "wedstrijd_id": match_id, "wedstrijd": wedstrijd,
            "fase": phase, "poll_id": poll_id,
            "poll_status": "gesloten", "gesloten": True,
            "testmodus": True, "bericht_verzonden": False,
            "productiegroep_aangeraakt": False, "rijschema_aangepast": False,
        }

    async def handle_show_attendance_status(call: ServiceCall):
        """Read one exact match poll from storage without mutating anything."""
        team_id = call.data[ATTR_TEAM_ID].strip()
        match_id = call.data[ATTR_MATCH_ID].strip()
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))

        found = []
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for team_data in coordinator.data.teams:
                if team_data.team.team_id == team_id:
                    found.append((entry_id, coordinator, team_data))
        if len(found) != 1:
            raise HomeAssistantError(f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl.")
        _, coordinator, team_data = found[0]
        store = getattr(coordinator, "attendance_store", None)
        if store is None:
            raise HomeAssistantError("Aanwezigheidsopslag is niet beschikbaar.")
        match = next((m for m in team_data.matches if m.match_id == match_id), None)
        if match is None:
            raise HomeAssistantError(f"Wedstrijd-ID {match_id} is niet gevonden voor {team_data.team.name}.")

        poll_id, meta = store.latest_poll(team_id, match_id, test_mode)
        if not poll_id or not meta:
            raise HomeAssistantError("Geen aanwezigheidspoll gevonden voor de gekozen wedstrijd in deze modus.")

        squad, staff = _attendance_people(coordinator, team_data, test_mode, str(meta.get("groep_id") or ""))
        player_status = {name: "niet_gereageerd" for name in squad}
        staff_status = {name: "niet_gereageerd" for name in staff}
        unknown = []
        stored_votes = []
        for vote in store.votes_for_poll(poll_id):
            person = vote.get("persoon") or vote.get("speler")
            role = vote.get("rol")
            status = vote.get("status")
            if status not in {"aanwezig", "afwezig", "geblesseerd"}:
                continue
            if role == "speler" and person in player_status:
                player_status[person] = status
            elif role == "staf" and person in staff_status:
                staff_status[person] = status
            elif person in player_status:
                player_status[person] = status
            else:
                unknown.append({"naam": vote.get("contact_naam"), "keuze": vote.get("keuze")})
            stored_votes.append({
                "persoon": person or vote.get("contact_naam") or "onbekend",
                "rol": role or "onbekend",
                "status": status,
                "keuze": vote.get("keuze"),
                "timestamp": int(vote.get("timestamp") or 0),
                "gesimuleerd": bool(vote.get("gesimuleerd")),
            })
        stored_votes.sort(key=lambda item: (item.get("persoon") or "").casefold())

        base_summary = {
            "wedstrijd_id": match_id,
            "niet_gereageerd": [n for n, v in player_status.items() if v == "niet_gereageerd"],
            "afwezig": [n for n, v in player_status.items() if v == "afwezig"],
            "geblesseerd": [n for n, v in player_status.items() if v == "geblesseerd"],
        }
        driver_info = _driver_control(team_data, coordinator, base_summary)
        return {
            "team_id": team_id, "team_naam": team_data.team.name,
            "wedstrijd_id": match_id, "wedstrijd": meta.get("wedstrijd"),
            "poll_id": poll_id, "testmodus": bool(meta.get("testmodus")),
            "scheduler_simulatie": bool(meta.get("scheduler_simulatie")),
            "simulatie_fase": meta.get("simulatie_fase"),
            "poll_status": meta.get("poll_status", "actief"),
            "gesloten": bool(meta.get("gesloten")), "gesloten_op": meta.get("gesloten_op"),
            "sluitreden": meta.get("sluitreden"),
            "aantal_opgeslagen_stemmen": len(stored_votes), "stemmen": stored_votes,
            "aanwezig": [n for n, v in player_status.items() if v == "aanwezig"],
            "afwezig": [n for n, v in player_status.items() if v == "afwezig"],
            "geblesseerd": [n for n, v in player_status.items() if v == "geblesseerd"],
            "niet_gereageerd": base_summary["niet_gereageerd"],
            "staf_aanwezig": [n for n, v in staff_status.items() if v == "aanwezig"],
            "staf_afwezig": [n for n, v in staff_status.items() if v == "afwezig"],
            "staf_geblesseerd": [n for n, v in staff_status.items() if v == "geblesseerd"],
            "staf_niet_gereageerd": [n for n, v in staff_status.items() if v == "niet_gereageerd"],
            "onbekende_stemmers": unknown, **driver_info,
            "alleen_lezen": True, "bericht_verzonden": False, "rijschema_aangepast": False,
        }

    async def _training_context(team_id: str):
        found=[]
        for _,coord in hass.data.get(DOMAIN,{}).items():
            if not hasattr(coord,"data") or coord.data is None: continue
            for td in coord.data.teams:
                if td.team.team_id==team_id: found.append((coord,td))
        if len(found)!=1: raise HomeAssistantError(f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl.")
        return found[0]

    async def handle_send_training_poll(call: ServiceCall):
        team_id=call.data[ATTR_TEAM_ID].strip(); test_mode=bool(call.data.get(ATTR_TEST_MODE,True)); requested=str(call.data.get(ATTR_TRAINING_ID) or "").strip()
        if requested and not test_mode: raise HomeAssistantError("training_id mag alleen handmatig worden gebruikt wanneer testmodus aan staat.")
        coordinator,td=await _training_context(team_id); client=coordinator.waha_client; store=coordinator.attendance_store
        if client is None: raise HomeAssistantError("WAHA is nog niet geconfigureerd voor deze integratie.")
        team_cfg=(coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_id,{})
        attendance_mode=str(team_cfg.get(CONF_WAHA_ATTENDANCE_MODE,DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE)
        if attendance_mode != WAHA_ATTENDANCE_MODE_POLLS:
            raise HomeAssistantError("Voor dit team staat WhatsApp op alleen berichten. Een trainingspoll is uitgeschakeld.")
        gid=str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID if test_mode else CONF_WAHA_PROD_GROUP_ID) or "").strip()
        gname=str(team_cfg.get(CONF_WAHA_TEST_GROUP_NAME if test_mode else CONF_WAHA_PROD_GROUP_NAME) or "").strip()
        prod=str(team_cfg.get(CONF_WAHA_PROD_GROUP_ID) or "").strip(); test=str(team_cfg.get(CONF_WAHA_TEST_GROUP_ID) or "").strip()
        if not gid:
            raise HomeAssistantError("Geen WhatsApp-groep ingesteld voor deze modus.")
        if test_mode:
            if gid != test:
                raise HomeAssistantError("Trainingstestpoll geblokkeerd: ongeldige testgroepconfiguratie.")
            if prod and gid == prod:
                raise HomeAssistantError("Trainingstestpoll geblokkeerd: testgroep en productiegroep zijn hetzelfde.")
        elif not prod or gid != prod:
            raise HomeAssistantError("Productie-trainingspoll geblokkeerd: ongeldige productiegroepconfiguratie.")
        if requested:
            item=_find_training(td,requested); start=_training_datetime_local(item or {})
        else: start,item=_next_training(td)
        if not item or not start: raise HomeAssistantError("Geen toekomstige training gevonden.")
        tid=_training_id(item)
        q=(f"⚽ {td.team.name} - training\n{item.get('dag','').capitalize()} {item.get('datum')}\n"
           f"Aanwezig: {item.get('verzameltijd') or '-'} | Training: {item.get('start')} - {item.get('einde')}\n"
           f"{item.get('veld') or ''}\n\nBen je erbij?")
        result=await client.send_poll(gid,q,["✅ Aanwezig","❌ Afwezig","🤕 Geblesseerd"]); pid=_extract_poll_id(result)
        if not pid: raise HomeAssistantError("WAHA heeft geen poll-ID teruggegeven.")
        iso=datetime.strptime(item['datum'],"%d-%m-%Y").strftime("%Y-%m-%d")
        store.add_poll(pid,{"type":"training","team_id":team_id,"team_naam":td.team.name,"training_id":tid,"training":f"{item.get('dag','').capitalize()} {item.get('datum')} {item.get('start')}","datum":iso,"tijd":item.get('start'),"dag":item.get('dag'),"verzameltijd":item.get('verzameltijd'),"eindtijd":item.get('einde'),"veld":item.get('veld'),"groep_id":gid,"groep_naam":gname,"testmodus":test_mode,"eligible_players":_poll_eligible_people(coordinator, td, test_mode, gid)[0],"eligible_staff":_poll_eligible_people(coordinator, td, test_mode, gid)[1],"verzonden_op":now_iso(),"verzonden_timestamp":int(datetime.now(timezone.utc).timestamp()*1000),"poll_status":"actief","controle_24u_uitgevoerd":False,"gesloten":False})
        await store.async_save(); coordinator.async_set_updated_data(coordinator.data)
        return {"team_id":team_id,"team_naam":td.team.name,"training_id":tid,"datum":item.get('datum'),"tijd":item.get('start'),"poll_id":pid,"groep_id":gid,"groep_naam":gname,"testmodus":test_mode}

    async def handle_check_training_attendance(call: ServiceCall):
        team_id=call.data[ATTR_TEAM_ID].strip(); test=bool(call.data.get(ATTR_TEST_MODE,True)); tid=str(call.data.get(ATTR_TRAINING_ID) or "").strip()
        if tid and not test: raise HomeAssistantError("training_id mag alleen in testmodus worden gebruikt.")
        coordinator,td=await _training_context(team_id)
        result=await _async_training_control(coordinator,td,test,True,tid or None)
        if result is None: raise HomeAssistantError("Geen actieve trainingspoll gevonden voor de gekozen training in deze modus.")
        return {"team_id":team_id,"team_naam":td.team.name,"testmodus":test,**result}

    async def handle_simulate_training_scheduler(call: ServiceCall):
        team_id=call.data[ATTR_TEAM_ID].strip(); tid=call.data[ATTR_TRAINING_ID].strip(); phase=call.data[ATTR_SCHEDULER_PHASE]
        if not bool(call.data.get(ATTR_TEST_MODE,True)): raise HomeAssistantError("Trainingsschedulersimulatie is uitsluitend toegestaan in testmodus.")
        coordinator,td=await _training_context(team_id); item=_find_training(td,tid)
        if not item: raise HomeAssistantError(f"Training-ID {tid} is niet gevonden of de training vervalt.")
        store=coordinator.attendance_store
        if phase=="pollmoment":
            # use normal test poll service, then mark latest as simulation
            resp=await handle_send_training_poll(type("C",(),{"data":{ATTR_TEAM_ID:team_id,ATTR_TRAINING_ID:tid,ATTR_TEST_MODE:True}})())
            pid=resp["poll_id"]; store.update_poll(pid,training_scheduler_simulatie=True,simulatie_fase="pollmoment"); await store.async_save()
            return {**resp,"fase":phase,"poll_status":"actief","productiegroep_aangeraakt":False}
        canonical_tid = _training_id(item)
        pid,meta=store.latest_training_poll(team_id,canonical_tid,True)
        if not pid or not meta or not meta.get("training_scheduler_simulatie"): raise HomeAssistantError("Geen actieve trainingsschedulersimulatie gevonden. Start eerst met pollmoment.")
        if phase=="remindermoment":
            if meta.get("gesloten"): raise HomeAssistantError("De trainingsschedulersimulatie is al gesloten.")
            result=await _async_training_control(coordinator,td,True,True,tid); store.update_poll(pid,simulatie_fase="remindermoment"); await store.async_save()
            return {"team_id":team_id,"training_id":tid,"fase":phase,"testmodus":True,"productiegroep_aangeraakt":False,**(result or {})}
        store.update_poll(pid,poll_status="gesloten",gesloten=True,gesloten_op=now_iso(),sluitreden="scheduler_simulatie_training_start",simulatie_fase="training_start")
        await store.async_save(); coordinator.async_set_updated_data(coordinator.data)
        return {"team_id":team_id,"training_id":tid,"fase":phase,"poll_id":pid,"poll_status":"gesloten","gesloten":True,"testmodus":True,"bericht_verzonden":False,"productiegroep_aangeraakt":False}

    async def handle_show_training_attendance_status(call: ServiceCall):
        team_id=call.data[ATTR_TEAM_ID].strip(); tid=call.data[ATTR_TRAINING_ID].strip(); test=bool(call.data.get(ATTR_TEST_MODE,True))
        coordinator,td=await _training_context(team_id); store=coordinator.attendance_store; item=_find_training(td,tid)
        if not item: raise HomeAssistantError(f"Training-ID {tid} is niet gevonden.")
        canonical_tid = _training_id(item)
        pid,meta=store.latest_training_poll(team_id,canonical_tid,test)
        if not pid or not meta: raise HomeAssistantError("Geen trainingspoll gevonden voor deze training in deze modus.")
        squad,staff=_team_people(td); summary=store.summary_for_training(team_id,canonical_tid,squad,staff,test)
        votes=[]
        for v in store.votes_for_poll(pid): votes.append({"persoon":v.get("persoon") or v.get("contact_naam") or "onbekend","rol":v.get("rol") or "onbekend","status":v.get("status"),"keuze":v.get("keuze"),"timestamp":int(v.get("timestamp") or 0)})
        return {"team_id":team_id,"team_naam":td.team.name,"training_id":tid,"poll_id":pid,"testmodus":test,"poll_status":meta.get("poll_status","actief"),"gesloten":bool(meta.get("gesloten")),"gesloten_op":meta.get("gesloten_op"),"sluitreden":meta.get("sluitreden"),"stemmen":votes,"aanwezig":summary.get("aanwezig",[]),"afwezig":summary.get("afwezig",[]),"geblesseerd":summary.get("geblesseerd",[]),"niet_gereageerd":summary.get("niet_gereageerd",[]),"staf_aanwezig":summary.get("staf_aanwezig",[]),"staf_afwezig":summary.get("staf_afwezig",[]),"staf_geblesseerd":summary.get("staf_geblesseerd",[]),"staf_niet_gereageerd":summary.get("staf_niet_gereageerd",[]),"onbekende_stemmers":summary.get("onbekende_stemmers",[]),"alleen_lezen":True,"bericht_verzonden":False}

    async def handle_send_matchday_info(call: ServiceCall):
        team_id = call.data[ATTR_TEAM_ID].strip()
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))
        requested_match_id = str(call.data.get(ATTR_MATCH_ID) or "").strip()
        if requested_match_id and not test_mode:
            raise HomeAssistantError("wedstrijd_id mag alleen handmatig worden gebruikt wanneer testmodus aan staat.")
        found = []
        for _entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if not hasattr(coordinator, "data") or coordinator.data is None:
                continue
            for td in coordinator.data.teams:
                if td.team.team_id == team_id:
                    found.append((coordinator, td))
        if len(found) != 1:
            raise HomeAssistantError(f"Team-ID {team_id} is niet exact één keer geladen in HA Voetbal.nl.")
        coordinator, td = found[0]
        if requested_match_id:
            match = next((m for m in td.matches if m.match_id == requested_match_id), None)
        else:
            _, match = _next_match(td)
        if match is None:
            raise HomeAssistantError("Geen geschikte wedstrijd gevonden.")
        try:
            result = await _send_matchday_info(coordinator, td, match, test_mode, force=test_mode)
        except WahaError as err:
            raise HomeAssistantError(f"WAHA wedstrijddagbericht verzenden mislukt: {err}") from err
        return {"team_id": team_id, "team_naam": td.team.name, "wedstrijd_id": match.match_id, "wedstrijd": _match_title(td, match), "testmodus": test_mode, **result}

    async def handle_send_training_info(call: ServiceCall):
        team_id = call.data[ATTR_TEAM_ID].strip()
        test_mode = bool(call.data.get(ATTR_TEST_MODE, True))
        requested_training_id = str(call.data.get(ATTR_TRAINING_ID) or "").strip()
        if requested_training_id and not test_mode:
            raise HomeAssistantError("training_id mag alleen handmatig worden gebruikt wanneer testmodus aan staat.")
        coordinator, td = await _training_context(team_id)
        if requested_training_id:
            item = _find_training(td, requested_training_id)
        else:
            _, item = _next_training(td)
        if not item:
            raise HomeAssistantError("Geen geschikte training gevonden.")
        try:
            result = await _send_training_info(coordinator, td, item, test_mode, force=test_mode)
        except WahaError as err:
            raise HomeAssistantError(f"WAHA trainingsdagbericht verzenden mislukt: {err}") from err
        return {"team_id": team_id, "team_naam": td.team.name, "training_id": _training_id(item), "datum": item.get("datum"), "testmodus": test_mode, **result}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_SEASON_PDF,
        handle_generate_season_pdf,
        schema=PDF_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SEASON_PDF,
        handle_send_season_pdf,
        schema=SEND_SEASON_PDF_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SEASON_PDF_DASHBOARD,
        handle_send_season_pdf,
        schema=SEND_SEASON_PDF_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_ATTENDANCE_POLL,
        handle_send_attendance_poll,
        schema=ATTENDANCE_POLL_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_ATTENDANCE,
        handle_check_attendance,
        schema=ATTENDANCE_CHECK_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIMULATE_ATTENDANCE,
        handle_simulate_attendance,
        schema=ATTENDANCE_SIMULATE_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIMULATE_SCHEDULER,
        handle_simulate_scheduler,
        schema=SCHEDULER_SIMULATE_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOW_ATTENDANCE_STATUS,
        handle_show_attendance_status,
        schema=ATTENDANCE_STATUS_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_SEND_TRAINING_POLL, handle_send_training_poll, schema=TRAINING_POLL_SERVICE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_CHECK_TRAINING_ATTENDANCE, handle_check_training_attendance, schema=TRAINING_CHECK_SERVICE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_SIMULATE_TRAINING_SCHEDULER, handle_simulate_training_scheduler, schema=TRAINING_SCHEDULER_SIMULATE_SERVICE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_SHOW_TRAINING_ATTENDANCE_STATUS, handle_show_training_attendance_status, schema=TRAINING_STATUS_SERVICE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_SEND_MATCHDAY_INFO, handle_send_matchday_info, schema=MATCHDAY_INFO_SERVICE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_SEND_TRAINING_INFO, handle_send_training_info, schema=TRAINING_INFO_SERVICE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_migrate_entry(hass, entry):
    """Migrate older HA Voetbal.nl config entries to schema version 4.

    v0.6.0 added player management through config-entry options. The existing
    entry.data schema itself did not change, so migration only needs to advance
    the stored config-entry version.
    """
    if entry.version < 4:
        hass.config_entries.async_update_entry(
            entry,
            version=4,
        )
    return True



async def async_setup_entry(hass, entry):
    client = VoetbalNlClient(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )

    club = Club(
        club_id=entry.data[CONF_CLUB_ID],
        name=entry.data[CONF_CLUB_NAME],
        city=entry.data.get(CONF_CLUB_CITY, ""),
    )

    club_data = await client.async_get_club_data(club)
    selected_ids = set(entry.data.get(CONF_TEAM_IDS, []))
    teams = [
        team for team in club_data.teams
        if team.team_id in selected_ids
    ]

    route_config = {
        "api_key": entry.options.get(CONF_ROUTE_API_KEY, ""),
        "team_origins": entry.options.get(CONF_ROUTE_TEAM_ORIGINS, {}),
    }

    route_cache = RouteCache(hass, entry.entry_id)
    await route_cache.async_load()

    driving_plan = DrivingPlanStore(hass, entry.entry_id)
    await driving_plan.async_load()
    flagging_plan = FlaggingPlanStore(hass, entry.entry_id)
    await flagging_plan.async_load()

    coordinator = VoetbalNlCoordinator(
        hass,
        client,
        club,
        teams,
        route_config=route_config,
        route_cache=route_cache,
        driving_plan=driving_plan,
        flagging_plan=flagging_plan,
        local_config={
            "player_management": entry.options.get(CONF_PLAYER_MANAGEMENT, {}),
            "driving_management": entry.options.get(CONF_DRIVING_MANAGEMENT, {}),
            "flagging_management": entry.options.get("flagging_management", {}),
            "training_management": entry.options.get(CONF_TRAINING_MANAGEMENT, {}),
            "match_management": entry.options.get(CONF_MATCH_MANAGEMENT, {}),
            CONF_GEMINI_API_KEY: entry.options.get(CONF_GEMINI_API_KEY, ""),
            CONF_GEMINI_MODEL: entry.options.get(CONF_GEMINI_MODEL, DEFAULT_GEMINI_MODEL),
        },
    )

    # v0.9.14: optional WAHA integration, independent from the existing football polling.
    attendance_store = AttendanceStore(hass, entry.entry_id)
    await attendance_store.async_load()
    coordinator.attendance_store = attendance_store
    coordinator.waha_config = dict(entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
    coordinator.waha_client = None
    coordinator.waha_webhook_id = None

    waha_cfg = coordinator.waha_config
    base_url = str(waha_cfg.get(CONF_WAHA_BASE_URL) or "").strip()
    api_key = str(waha_cfg.get(CONF_WAHA_API_KEY) or "").strip()
    session_name = str(waha_cfg.get(CONF_WAHA_SESSION) or "default").strip() or "default"
    if base_url and api_key:
        coordinator.waha_client = WahaClient(
            async_get_clientsession(hass),
            base_url,
            api_key,
            session_name,
            team_configs=waha_cfg.get(CONF_WAHA_TEAMS, {}) or {},
        )
        webhook_id = hashlib.sha256(
            f"{entry.entry_id}:{api_key}:waha-poll-vote".encode("utf-8")
        ).hexdigest()[:48]
        coordinator.waha_webhook_id = webhook_id

        async def _handle_waha_vote(_hass, _webhook_id, request):
            try:
                body = await request.json()
            except Exception:
                return Response(status=200)
            if body.get("event") != "poll.vote":
                return Response(status=200)
            poll_id = _extract_vote_poll_id(body)
            if not poll_id:
                return Response(status=200)
            poll_meta = attendance_store.poll(poll_id)
            if not poll_meta:
                # Ignore votes from unrelated polls; this keeps the handler isolated.
                return Response(status=200)
            kickoff = _match_datetime_local(meta=poll_meta)
            if poll_meta.get("gesloten") or (kickoff is not None and dt_util.now() >= kickoff):
                if not poll_meta.get("gesloten"):
                    attendance_store.update_poll(
                        poll_id, poll_status="gesloten", gesloten=True, gesloten_op=now_iso()
                    )
                    await attendance_store.async_save()
                    coordinator.async_set_updated_data(coordinator.data)
                # From kickoff onwards this poll is historical only.
                return Response(status=200)
            payload = body.get("payload") or {}
            vote = payload.get("vote") or {}
            voter = str(vote.get("from") or ((payload.get("_data") or {}).get("voter")) or "")
            selected = vote.get("selectedOptions") or [
                x.get("name") for x in ((payload.get("_data") or {}).get("selectedOptions") or [])
                if isinstance(x, dict) and x.get("name")
            ]
            status, choice = _status_from_vote(list(selected))
            if not voter or not status:
                return Response(status=200)

            wa_id = voter
            contact_name = ""
            matched_person = None
            matched_role = None
            try:
                resolved = await coordinator.waha_client.resolve_lid(voter)
                if resolved:
                    wa_id = resolved
            except Exception:
                pass

            team_id = poll_meta.get("team_id")
            team_data = next(
                (x for x in coordinator.data.teams if x.team.team_id == team_id), None
            )
            squad = []
            staff = []
            if team_data is not None:
                squad = list(dict.fromkeys(
                    list(team_data.selected_players) + list(team_data.manual_players)
                ))
                staff = list(dict.fromkeys(member.name for member in team_data.staff))

            # v0.9.41: explicit configuration mapping has priority over every
            # automatic/legacy mapping. Scope it to team + WhatsApp group +
            # production/test environment so one team's test group can never
            # accidentally affect another team.
            environment = "test" if bool(poll_meta.get("testmodus")) else "production"
            configured_mappings = list(
                waha_cfg.get(CONF_WAHA_IDENTITY_MAPPINGS, []) or []
            )
            manual_mapping = next(
                (item for item in configured_mappings
                 if isinstance(item, dict)
                 and str(item.get("team_id")) == str(team_id)
                 and str(item.get("group_id")) == str(poll_meta.get("groep_id"))
                 and str(item.get("environment")) == environment
                 and str(item.get("wa_id")) == str(wa_id)
                 and bool(item.get("enabled", True))),
                None,
            )
            if manual_mapping:
                matched_person = str(manual_mapping.get("persoon") or "").strip() or None
                matched_role = str(manual_mapping.get("rol") or "").strip() or None
                contact_name = str(manual_mapping.get("whatsapp_name") or "").strip()

            # v0.9.16: reuse a durable number-to-person mapping first. This makes
            # later votes independent of contact-name changes in WhatsApp.
            saved_mapping = attendance_store.mapping(wa_id)
            if manual_mapping is None and saved_mapping:
                saved_person = saved_mapping.get("persoon")
                saved_role = saved_mapping.get("rol")
                if saved_role == "speler" and saved_person in squad:
                    matched_person, matched_role = saved_person, "speler"
                elif saved_role == "staf" and saved_person in staff:
                    matched_person, matched_role = saved_person, "staf"
                contact_name = str(saved_mapping.get("contact_naam") or "").strip()

            # No valid configured/stored mapping yet: resolve the current WAHA
            # contact name and use the automatic matching rules.
            if matched_person is None:
                try:
                    contact = await coordinator.waha_client.contact(wa_id)
                    contact_name = str(
                        contact.get("name") or contact.get("pushname") or contact.get("shortName") or ""
                    ).strip()
                except Exception:
                    pass
                if team_data is not None:
                    matched_person, matched_role = attendance_store.match_person(
                        contact_name, squad, staff
                    )

            attendance_store.add_mapping(
                wa_id, contact_name, matched_person, matched_role
            )
            changed = attendance_store.record_vote(poll_id, voter, {
                "voter_id": voter,
                "wa_id": wa_id,
                "contact_naam": contact_name,
                "persoon": matched_person,
                "speler": matched_person if matched_role == "speler" else None,
                "rol": matched_role,
                "status": status,
                "keuze": choice,
                "timestamp": int(vote.get("timestamp") or body.get("timestamp") or 0),
            })
            if changed:
                await attendance_store.async_save()
                coordinator.async_set_updated_data(coordinator.data)

                # v0.9.17: the driving plan remains immutable. If a planned driver
                # votes absent/injured, send one clear signal to the same poll group.
                if matched_role == "speler" and status in {"afwezig", "geblesseerd"} and team_data is not None:
                    match = next(
                        (m for m in team_data.matches if m.match_id == poll_meta.get("wedstrijd_id")),
                        None,
                    )
                    if match is not None and match.is_home is False and coordinator.driving_plan is not None:
                        drivers = coordinator.driving_plan.status_for_match(team_data, match).get("chauffeurs", [])
                        if matched_person in drivers and not attendance_store.conflict_notice_sent(
                            poll_id, matched_person, status
                        ):
                            label = "❌ afwezig" if status == "afwezig" else "🤕 geblesseerd"
                            warning = (
                                f"🚗 Chauffeurwaarschuwing - {team_data.team.name}\n"
                                f"{matched_person} heeft gestemd: {label}.\n"
                                f"{poll_meta.get('wedstrijd') or ''} - {poll_meta.get('datum') or ''} {poll_meta.get('tijd') or ''}\n\n"
                                "Deze speler staat als chauffeur gepland. Graag zelf actie ondernemen "
                                "of vervanging regelen. Het rijschema is niet aangepast."
                            )
                            # Keep the existing group warning. A failure here must never
                            # prevent the vote itself from being stored.
                            try:
                                await coordinator.waha_client.send_text(
                                    str(poll_meta.get("groep_id")),
                                    warning,
                                    team_data.team.name,
                                )
                                attendance_store.mark_conflict_notice(
                                    poll_id, matched_person, status
                                )
                                await attendance_store.async_save()
                            except Exception:
                                pass

                            # v0.11.10: for production polls, also warn the planned
                            # driver directly. The vote webhook already gives us the
                            # correct WhatsApp identity (PN/@c.us or @lid), so no
                            # separate phone-number administration is required.
                            # Test polls deliberately never send private messages.
                            private_key = (
                                f"driverprivate:{poll_id}:"
                                f"{_norm_simulation_person(matched_person)}:{status}"
                            )
                            if (
                                not bool(poll_meta.get("testmodus"))
                                and wa_id
                                and not attendance_store.message_sent(private_key)
                            ):
                                private_warning = (
                                    f"🚗 Chauffeurwaarschuwing - {team_data.team.name}\n"
                                    f"{matched_person}, je hebt gestemd: {label}.\n"
                                    f"{poll_meta.get('wedstrijd') or ''} - "
                                    f"{poll_meta.get('datum') or ''} {poll_meta.get('tijd') or ''}\n\n"
                                    "Je staat voor deze wedstrijd als chauffeur gepland. "
                                    "Graag zelf actie ondernemen of vervanging regelen. "
                                    "Het rijschema is niet aangepast."
                                )
                                try:
                                    await coordinator.waha_client.send_text(
                                        str(wa_id),
                                        private_warning,
                                        team_data.team.name,
                                    )
                                    attendance_store.mark_message_sent(private_key)
                                    await attendance_store.async_save()
                                except Exception:
                                    # Private delivery is best-effort and may never
                                    # interfere with the group warning or poll flow.
                                    pass
            return Response(status=200)

        webhook.async_register(
            hass,
            DOMAIN,
            f"HA Voetbal.nl WAHA poll votes {entry.entry_id}",
            webhook_id,
            _handle_waha_vote,
            local_only=bool(waha_cfg.get(CONF_WAHA_WEBHOOK_LOCAL_ONLY, True)),
            allowed_methods=["POST"],
        )

        webhook_base = str(waha_cfg.get(CONF_WAHA_WEBHOOK_BASE_URL) or "").strip().rstrip("/")
        if webhook_base:
            callback_url = f"{webhook_base}/api/webhook/{webhook_id}"
            try:
                await coordinator.waha_client.ensure_webhook(callback_url, "poll.vote")
            except Exception:
                # Keep football integration available even when WAHA is temporarily offline.
                pass

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # v0.9.20: configurable poll lifecycle scheduler. It never changes the driving plan.
    coordinator.attendance_scheduler_unsub = None
    if coordinator.waha_client is not None:
        async def _attendance_tick(_now=None):
            current = dt_util.now()
            store = coordinator.attendance_store
            changed_store = False

            # Close every known match poll at kickoff. Late WhatsApp votes are then
            # ignored. A pinned production poll is unpinned 2.5 hours after kickoff,
            # when the match is safely over. Unpin failures are retried next tick.
            for poll_id, meta in list(store.data.get("polls", {}).items()):
                if meta.get("type") == "training":
                    continue
                kickoff = _match_datetime_local(meta=meta)
                if kickoff is None:
                    continue
                if current >= kickoff and not meta.get("gesloten"):
                    store.update_poll(
                        poll_id, poll_status="gesloten", gesloten=True, gesloten_op=now_iso()
                    )
                    changed_store = True

                unpin_at = kickoff + timedelta(hours=2, minutes=30)
                if (
                    current >= unpin_at
                    and not bool(meta.get("testmodus"))
                    and bool(meta.get("vastgezet"))
                    and not bool(meta.get("losgemaakt"))
                ):
                    message_id = _poll_reply_message_id(poll_id, meta)
                    chat_id = str(meta.get("groep_id") or "").strip()
                    if message_id and chat_id:
                        try:
                            await coordinator.waha_client.unpin_message(chat_id, message_id)
                        except Exception as err:
                            LOGGER.warning(
                                "Wedstrijdpoll %s kon nog niet worden losgemaakt in WhatsApp: %s",
                                poll_id,
                                err,
                            )
                        else:
                            store.update_poll(
                                poll_id, losgemaakt=True, losgemaakt_op=now_iso()
                            )
                            changed_store = True

            if changed_store:
                await store.async_save()
                coordinator.async_set_updated_data(coordinator.data)

            for team_data in coordinator.data.teams:
                team_id = team_data.team.team_id
                team_cfg = (coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_id, {})
                prod_group = str(team_cfg.get(CONF_WAHA_PROD_GROUP_ID) or "").strip()
                if not prod_group:
                    continue
                kickoff, match = _next_match(team_data, current)
                if match is None or kickoff is None:
                    continue
                remaining = kickoff - current
                if remaining.total_seconds() <= 0:
                    continue

                attendance_mode = str(team_cfg.get(CONF_WAHA_ATTENDANCE_MODE, DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE)
                poll_days = int(team_cfg.get(CONF_WAHA_POLL_DAYS_BEFORE, DEFAULT_POLL_DAYS_BEFORE))
                poll_time = str(team_cfg.get(CONF_WAHA_POLL_TIME, DEFAULT_POLL_TIME))
                reminder_days = int(team_cfg.get(CONF_WAHA_REMINDER_DAYS_BEFORE, DEFAULT_REMINDER_DAYS_BEFORE))
                reminder_time = str(team_cfg.get(CONF_WAHA_REMINDER_TIME, DEFAULT_REMINDER_TIME))
                poll_at = _scheduled_local_datetime(kickoff, poll_days, poll_time)
                reminder_at = _scheduled_local_datetime(kickoff, reminder_days, reminder_time)

                poll_id, meta = store.latest_poll(team_id, match.match_id, False)

                # v0.11.6: dynamic per-team planning. Presence of a schedule list means
                # the new planner owns poll/reminder/info timing for this team.
                message_schedule = team_cfg.get(CONF_WAHA_MESSAGE_SCHEDULE)
                if isinstance(message_schedule, list):
                    rules = [x for x in message_schedule if isinstance(x, dict) and x.get("enabled", True)]
                    poll_rules = [x for x in rules if x.get("type") == MESSAGE_TYPE_POLL]
                    reminder_rules = [x for x in rules if x.get("type") == MESSAGE_TYPE_REMINDER]
                    info_rules = [x for x in rules if x.get("type") == MESSAGE_TYPE_INFO]

                    if attendance_mode == WAHA_ATTENDANCE_MODE_POLLS and poll_id is None and poll_rules:
                        rule = poll_rules[0]
                        due = _scheduled_local_datetime(kickoff, int(rule.get("days_before", 0)), str(rule.get("time") or DEFAULT_POLL_TIME))
                        if due is not None and current >= due and current < kickoff:
                            try:
                                await hass.services.async_call(DOMAIN, SERVICE_SEND_ATTENDANCE_POLL, {ATTR_TEAM_ID: team_id, ATTR_TEST_MODE: False}, blocking=True)
                            except Exception:
                                pass
                            continue

                    # Refresh poll metadata in case it was created in a prior tick.
                    poll_id, meta = store.latest_poll(team_id, match.match_id, False)
                    if attendance_mode == WAHA_ATTENDANCE_MODE_POLLS and poll_id and meta and not meta.get("gesloten"):
                        for rule in reminder_rules:
                            due = _scheduled_local_datetime(kickoff, int(rule.get("days_before", 0)), str(rule.get("time") or DEFAULT_REMINDER_TIME))
                            rule_id = str(rule.get("id") or f"reminder_{rule.get('days_before',0)}_{rule.get('time','1900')}")
                            sent_key = f"matchreminder:{team_id}:{match.match_id}:{rule_id}:prod"
                            if due is None or current < due or current >= kickoff or store.message_sent(sent_key):
                                continue
                            try:
                                await _async_attendance_control(coordinator, team_data, test_mode=False, mark_done=False, match_id=match.match_id)
                            except Exception:
                                continue
                            store.mark_message_sent(sent_key)
                            await store.async_save()

                    for rule in info_rules:
                        due = _scheduled_local_datetime(kickoff, int(rule.get("days_before", 0)), str(rule.get("time") or DEFAULT_MATCHDAY_MESSAGE_TIME))
                        if due is not None and current >= due and current < kickoff:
                            try:
                                await _send_matchday_info(coordinator, team_data, match, False, force=False)
                            except Exception:
                                pass
                    continue

                if attendance_mode == WAHA_ATTENDANCE_MODE_MESSAGES:
                    # No poll and no poll reminder for this team. Use the existing
                    # match information message on the configured matchday time.
                    matchday_enabled = bool(team_cfg.get(CONF_MATCHDAY_MESSAGE_ENABLED, True))
                    matchday_time = str(team_cfg.get(CONF_MATCHDAY_MESSAGE_TIME, DEFAULT_MATCHDAY_MESSAGE_TIME))
                    matchday_at = _scheduled_local_datetime(kickoff, 0, matchday_time)
                    if (matchday_enabled and matchday_at is not None and current.date() == kickoff.date()
                            and current >= matchday_at and current < kickoff):
                        try:
                            await _send_matchday_info(coordinator, team_data, match, False, force=False)
                        except Exception:
                            pass
                    continue

                # Configured X calendar days before the match at the selected local clock time.
                # A restart after the scheduled moment catches up once, as long as kickoff has not passed.
                production_enabled = bool(team_cfg.get(CONF_WAHA_PRODUCTION_ENABLED, True))
                if poll_id is None and production_enabled and poll_at is not None and current >= poll_at:
                    try:
                        await hass.services.async_call(
                            DOMAIN,
                            SERVICE_SEND_ATTENDANCE_POLL,
                            {ATTR_TEAM_ID: team_id, ATTR_TEST_MODE: False},
                            blocking=True,
                        )
                    except Exception:
                        # A temporary WAHA failure must never affect football data refresh.
                        pass
                    # Never run the reminder in the same cycle as a newly-created poll.
                    continue

                # Configured reminder moment: execute exactly once for the active production poll.
                if (
                    poll_id
                    and meta
                    and not meta.get("gesloten")
                    and not meta.get("controle_24u_uitgevoerd")
                    and reminder_at is not None
                    and current >= reminder_at
                ):
                    try:
                        await _async_attendance_control(
                            coordinator, team_data, test_mode=False, mark_done=True
                        )
                    except Exception:
                        pass

                # v0.9.28: configurable matchday information message on match day.
                matchday_enabled = bool(team_cfg.get(CONF_MATCHDAY_MESSAGE_ENABLED, True))
                matchday_time = str(team_cfg.get(CONF_MATCHDAY_MESSAGE_TIME, DEFAULT_MATCHDAY_MESSAGE_TIME))
                matchday_at = _scheduled_local_datetime(kickoff, 0, matchday_time)
                if (
                    matchday_enabled
                    and matchday_at is not None
                    and current.date() == kickoff.date()
                    and current >= matchday_at
                    and current < kickoff
                ):
                    try:
                        await _send_matchday_info(coordinator, team_data, match, False, force=False)
                    except Exception:
                        pass

        coordinator.attendance_scheduler_unsub = async_track_time_interval(
            hass, _attendance_tick, timedelta(minutes=POLL_SCHEDULER_INTERVAL_MINUTES)
        )
        # Run once after setup so a restart does not skip a due poll/control.
        hass.async_create_task(_attendance_tick())

    # v0.9.24: independent training attendance scheduler using training settings.
    coordinator.training_attendance_scheduler_unsub = None
    if coordinator.waha_client is not None:
        async def _training_attendance_tick(_now=None):
            current=dt_util.now(); store=coordinator.attendance_store
            training_cfg_all=(entry.options.get(CONF_TRAINING_MANAGEMENT,{}) or {})
            changed_store=False
            # Finish every already-created production training poll at training start.
            # This lifecycle continues even when creation of NEW production polls is disabled.
            for poll_id, meta in list(store.data.get("polls", {}).items()):
                if meta.get("type") != "training" or meta.get("testmodus") or meta.get("gesloten"):
                    continue
                training_start = _training_datetime_local(meta)
                if training_start is not None and current >= training_start:
                    store.update_poll(poll_id, poll_status="gesloten", gesloten=True, gesloten_op=now_iso(), sluitreden="training_start")
                    changed_store=True
            if changed_store:
                await store.async_save()
                coordinator.async_set_updated_data(coordinator.data)
            for td in coordinator.data.teams:
                team_id=td.team.team_id
                wcfg=(coordinator.waha_config.get(CONF_WAHA_TEAMS) or {}).get(team_id,{})
                if not str(wcfg.get(CONF_WAHA_PROD_GROUP_ID) or '').strip(): continue
                start,item=_next_training(td,current)
                if not item or not start: continue
                tid=_training_id(item); cfg=dict(training_cfg_all.get(team_id,{}) or {})
                attendance_mode=str(wcfg.get(CONF_WAHA_ATTENDANCE_MODE,DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE)
                poll_days=int(cfg.get(CONF_TRAINING_POLL_DAYS_BEFORE,DEFAULT_TRAINING_POLL_DAYS_BEFORE))
                poll_time=str(cfg.get(CONF_TRAINING_POLL_TIME,DEFAULT_TRAINING_POLL_TIME))
                rem_days=int(cfg.get(CONF_TRAINING_REMINDER_DAYS_BEFORE,DEFAULT_TRAINING_REMINDER_DAYS_BEFORE))
                rem_time=str(cfg.get(CONF_TRAINING_REMINDER_TIME,DEFAULT_TRAINING_REMINDER_TIME))
                poll_at=_scheduled_local_datetime(start,poll_days,poll_time); rem_at=_scheduled_local_datetime(start,rem_days,rem_time)
                pid,meta=store.latest_training_poll(team_id,tid,False)
                message_schedule = cfg.get(CONF_TRAINING_MESSAGE_SCHEDULE)
                if isinstance(message_schedule, list):
                    rules=[x for x in message_schedule if isinstance(x,dict) and x.get("enabled",True)]
                    poll_rules=[x for x in rules if x.get("type")==MESSAGE_TYPE_POLL]
                    reminder_rules=[x for x in rules if x.get("type")==MESSAGE_TYPE_REMINDER]
                    info_rules=[x for x in rules if x.get("type")==MESSAGE_TYPE_INFO]
                    if attendance_mode==WAHA_ATTENDANCE_MODE_POLLS and pid is None and poll_rules:
                        rule=poll_rules[0]
                        due=_scheduled_local_datetime(start,int(rule.get("days_before",0)),str(rule.get("time") or DEFAULT_TRAINING_POLL_TIME))
                        if due is not None and current>=due and current<start:
                            try: await hass.services.async_call(DOMAIN,SERVICE_SEND_TRAINING_POLL,{ATTR_TEAM_ID:team_id,ATTR_TEST_MODE:False},blocking=True)
                            except Exception: pass
                            continue
                    pid,meta=store.latest_training_poll(team_id,tid,False)
                    if attendance_mode==WAHA_ATTENDANCE_MODE_POLLS and pid and meta and not meta.get("gesloten"):
                        for rule in reminder_rules:
                            due=_scheduled_local_datetime(start,int(rule.get("days_before",0)),str(rule.get("time") or DEFAULT_TRAINING_REMINDER_TIME))
                            rule_id=str(rule.get("id") or f"reminder_{rule.get('days_before',0)}_{rule.get('time','1900')}")
                            sent_key=f"trainingreminder:{team_id}:{tid}:{rule_id}:prod"
                            if due is None or current<due or current>=start or store.message_sent(sent_key): continue
                            try: await _async_training_control(coordinator,td,False,False,training_id=tid)
                            except Exception: continue
                            store.mark_message_sent(sent_key); await store.async_save()
                    if info_rules:
                        for rule in info_rules:
                            due=_scheduled_local_datetime(start,int(rule.get("days_before",0)),str(rule.get("time") or '18:00'))
                            if due is not None and current>=due and current<start:
                                try: await _send_training_info(coordinator,td,item,False,force=False)
                                except Exception: pass
                    else:
                        # Preserve the pre-v0.11.6 X-hours-before training info setting until
                        # the user explicitly adds an info rule to the new planner.
                        info_enabled=bool(cfg.get(CONF_TRAINING_INFO_ENABLED,True))
                        info_hours=int(cfg.get(CONF_TRAINING_INFO_HOURS_BEFORE,DEFAULT_TRAINING_INFO_HOURS_BEFORE))
                        info_at=start-timedelta(hours=max(0,info_hours))
                        if info_enabled and current>=info_at and current<start:
                            try: await _send_training_info(coordinator,td,item,False,force=False)
                            except Exception: pass
                    continue
                production_enabled=bool(cfg.get(CONF_TRAINING_PRODUCTION_ENABLED,True))
                if attendance_mode == WAHA_ATTENDANCE_MODE_MESSAGES:
                    # No poll, no poll reminder, and no attendance summary.
                    info_enabled=bool(cfg.get(CONF_TRAINING_INFO_ENABLED,True))
                    info_hours=int(cfg.get(CONF_TRAINING_INFO_HOURS_BEFORE,DEFAULT_TRAINING_INFO_HOURS_BEFORE))
                    info_at=start-timedelta(hours=max(0,info_hours))
                    if info_enabled and current>=info_at and current<start:
                        try: await _send_training_info(coordinator,td,item,False,force=False)
                        except Exception: pass
                    continue
                if pid is None and production_enabled and poll_at is not None and current>=poll_at and current<start:
                    try:
                        await hass.services.async_call(DOMAIN,SERVICE_SEND_TRAINING_POLL,{ATTR_TEAM_ID:team_id,ATTR_TEST_MODE:False},blocking=True)
                    except Exception: pass
                    continue
                if pid and meta and not meta.get('gesloten') and not meta.get('controle_24u_uitgevoerd') and rem_at is not None and current>=rem_at and current<start:
                    try: await _async_training_control(coordinator,td,False,True)
                    except Exception: pass
                # v0.9.28: configurable training information message X hours before start.
                info_enabled = bool(cfg.get(CONF_TRAINING_INFO_ENABLED, True))
                info_hours = int(cfg.get(CONF_TRAINING_INFO_HOURS_BEFORE, DEFAULT_TRAINING_INFO_HOURS_BEFORE))
                info_at = start - timedelta(hours=max(0, info_hours))
                if info_enabled and current >= info_at and current < start:
                    try:
                        await _send_training_info(coordinator, td, item, False, force=False)
                    except Exception:
                        pass
        coordinator.training_attendance_scheduler_unsub=async_track_time_interval(hass,_training_attendance_tick,timedelta(minutes=POLL_SCHEDULER_INTERVAL_MINUTES))
        hass.async_create_task(_training_attendance_tick())

    return True

async def async_unload_entry(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        webhook_id = getattr(coordinator, "waha_webhook_id", None) if coordinator else None
        if webhook_id:
            webhook.async_unregister(hass, webhook_id)
        scheduler_unsub = getattr(coordinator, "attendance_scheduler_unsub", None) if coordinator else None
        if scheduler_unsub:
            scheduler_unsub()
        training_scheduler_unsub = getattr(coordinator, "training_attendance_scheduler_unsub", None) if coordinator else None
        if training_scheduler_unsub:
            training_scheduler_unsub()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
