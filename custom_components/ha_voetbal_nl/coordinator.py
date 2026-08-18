import asyncio
from datetime import date, timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import VoetbalNlError
from .route import async_calculate_route, RouteError
from .driving import build_driving_schedule
from .driving_plan import _choose_supplemental
from .flagging_plan import rebuild_flagging_schedule, FlaggingPlanStore
from .season_export import build_season_export
from .school_holidays import (
    async_get_school_holidays,
    build_training_calendar,
    season_bounds,
)

_LOGGER = logging.getLogger(__name__)

class VoetbalNlCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, client, club, teams, route_config=None, route_cache=None, driving_plan=None, flagging_plan=None, local_config=None):
        super().__init__(
            hass,
            logger=_LOGGER,
            name="ha_voetbal_nl",
            update_interval=timedelta(hours=6),
        )
        self.client = client
        self.club = club
        self.teams = teams
        self.route_config = route_config or {}
        self.route_cache = route_cache
        self.driving_plan = driving_plan
        self.flagging_plan = flagging_plan
        self.local_config = local_config or {}

    async def async_add_supplemental_driving_plan(self, team_id):
        """Plan only away matches that do not yet have a persisted assignment."""
        if self.driving_plan is None or self.data is None:
            return 0
        team_data = next(
            (x for x in self.data.teams if x.team.team_id == team_id),
            None,
        )
        if team_data is None:
            return 0

        missing = [
            match for match in team_data.matches
            if match.is_home is False
            and self.driving_plan.get_assignment(team_id, match.match_id) is None
        ]
        assignments = _choose_supplemental(team_data, self.driving_plan, missing)
        for match in missing:
            self.driving_plan.set_assignment(
                team_id,
                match.match_id,
                assignments.get(match.match_id, []),
                team_data.driving_cars,
                source="aanvullend",
            )
        if missing:
            await self.driving_plan.async_save()
        return len(missing)

    async def async_rebuild_match_tasks(self, team_id):
        """Explicitly rebuild driving and flagger plans for one team."""
        if self.data is None or self.driving_plan is None or self.flagging_plan is None:
            return False
        team_data = next((x for x in self.data.teams if x.team.team_id == team_id), None)
        if team_data is None:
            return False
        self.driving_plan.clear_team(team_id)
        initial = build_driving_schedule(team_data)
        by_id = {item["wedstrijd_id"]: item for item in initial.get("schema", [])}
        for match in team_data.matches:
            if match.is_home is False:
                row=by_id.get(match.match_id,{})
                self.driving_plan.set_assignment(team_id, match.match_id, row.get("chauffeurs",[]), team_data.driving_cars, source="herberekend")
        self.driving_plan.set_initialized(team_id, True)
        self.flagging_plan.clear_team(team_id)
        if team_data.flagging_enabled:
            assignments,_=rebuild_flagging_schedule(team_data,self.driving_plan)
            for match in team_data.matches:
                self.flagging_plan.set_assignment(team_id,match.match_id,assignments.get(match.match_id,""),source="herberekend")
            self.flagging_plan.set_initialized(team_id, True)
        await self.driving_plan.async_save(); await self.flagging_plan.async_save()
        return True

    async def _async_update_data(self):
        try:
            data = await self.client.async_get_multi_team_data(
                self.club,
                self.teams,
            )

            api_key = self.route_config.get("api_key", "")
            team_origins = self.route_config.get("team_origins", {})
            route_jobs = []

            for team_data in data.teams:
                home_match = next(
                    (
                        match for match in team_data.matches
                        if match.is_home is True
                        and match.latitude is not None
                        and match.longitude is not None
                    ),
                    None,
                )

                default_origin = None
                if home_match is not None:
                    default_origin = {
                        "mode": "club",
                        "name": home_match.accommodation
                        or f"Thuisaccommodatie {team_data.team.name}",
                        "latitude": home_match.latitude,
                        "longitude": home_match.longitude,
                    }

                override = team_origins.get(team_data.team.team_id, {})
                mode = override.get("mode", "club")
                if mode == "custom":
                    try:
                        origin = {
                            "mode": "custom",
                            "name": override.get("name") or "Eigen vertrekpunt",
                            "latitude": float(override["latitude"]),
                            "longitude": float(override["longitude"]),
                        }
                    except (KeyError, TypeError, ValueError):
                        origin = None
                else:
                    origin = default_origin

                for match in team_data.matches:
                    if match.is_home is not False:
                        continue

                    if origin is None:
                        match.route.status = "geen_vertrekpunt"
                        continue

                    match.route.vertrek_type = origin["mode"]
                    match.route.vertrek_naam = origin["name"]
                    match.route.vertrek_latitude = origin["latitude"]
                    match.route.vertrek_longitude = origin["longitude"]

                    if not api_key:
                        match.route.status = "api_key_ontbreekt"
                        continue
                    if match.latitude is None or match.longitude is None:
                        match.route.status = "geen_coordinaten"
                        continue

                    cache_key = None
                    cached = None
                    if self.route_cache is not None:
                        cache_key = self.route_cache.make_key(
                            origin["latitude"],
                            origin["longitude"],
                            match.latitude,
                            match.longitude,
                        )
                        cached = self.route_cache.get(cache_key)

                    if cached:
                        match.route.status = "cache"
                        match.route.afstand_enkel_km = cached.get("afstand_enkel_km")
                        match.route.afstand_retour_km = cached.get("afstand_retour_km")
                        match.route.reistijd_minuten = cached.get("reistijd_minuten")
                        continue

                    route_jobs.append((match, origin, cache_key))

            # Keep ORS concurrency modest. This makes first setup much faster
            # without bursting the public API.
            semaphore = asyncio.Semaphore(2)
            cache_changed = False

            async def _route_one(match, origin, cache_key):
                nonlocal cache_changed
                async with semaphore:
                    try:
                        result = await async_calculate_route(
                            self.client._session,
                            api_key,
                            origin["latitude"],
                            origin["longitude"],
                            match.latitude,
                            match.longitude,
                        )
                    except RouteError as err:
                        match.route.status = "route_fout"
                        match.route.fout = str(err)
                        return

                    match.route.status = "berekend"
                    match.route.afstand_enkel_km = result["afstand_enkel_km"]
                    match.route.afstand_retour_km = result["afstand_retour_km"]
                    match.route.reistijd_minuten = result["reistijd_minuten"]

                    if self.route_cache is not None and cache_key:
                        self.route_cache.set(cache_key, result)
                        cache_changed = True

            if route_jobs:
                await asyncio.gather(
                    *(
                        _route_one(match, origin, cache_key)
                        for match, origin, cache_key in route_jobs
                    )
                )

            if cache_changed and self.route_cache is not None:
                await self.route_cache.async_save()


            default_season_start, default_season_end, default_schoolyear = season_bounds(date.today())
            holiday_cache = {}

            player_management = self.local_config.get("player_management", {})
            driving_management = self.local_config.get("driving_management", {})
            training_management = self.local_config.get("training_management", {})
            match_management = self.local_config.get("match_management", {})
            for team_data in data.teams:
                player_cfg = player_management.get(team_data.team.team_id, {})
                visible_names = [player.name for player in team_data.players]
                selected = player_cfg.get("selected")
                if selected is None:
                    selected = visible_names
                selected_set = set(selected)
                team_data.selected_players = [
                    name for name in visible_names if name in selected_set
                ]
                team_data.manual_players = list(dict.fromkeys(
                    name.strip()
                    for name in player_cfg.get("manual", [])
                    if name.strip()
                ))
                drive_cfg = driving_management.get(team_data.team.team_id, {})
                team_data.driving_excluded = list(dict.fromkeys(
                    name.strip()
                    for name in drive_cfg.get("excluded", [])
                    if name.strip()
                ))
                try:
                    team_data.driving_cars = max(1, int(drive_cfg.get("cars", 4)))
                except (TypeError, ValueError):
                    team_data.driving_cars = 4
                team_data.driving_extra = list(dict.fromkeys(
                    name.strip() for name in drive_cfg.get("extra_drivers", []) if str(name).strip()
                ))
                flag_cfg = self.local_config.get("flagging_management", {}).get(team_data.team.team_id, {})
                team_data.flagging_enabled = bool(flag_cfg.get("enabled", False))
                team_data.flagging_excluded = list(dict.fromkeys(
                    name.strip() for name in flag_cfg.get("excluded", []) if str(name).strip()
                ))
                team_data.flagging_extra = list(dict.fromkeys(
                    name.strip() for name in flag_cfg.get("extra", []) if str(name).strip()
                ))

                training_cfg = training_management.get(team_data.team.team_id, {})
                team_data.training_sessions = list(training_cfg.get("sessions", []))

                # v0.9.10: the concrete training calendar can start/end on
                # dates selected per team. Existing installs keep the former
                # season bounds until the user saves the training options.
                def _configured_training_date(key, fallback):
                    value = training_cfg.get(key)
                    if not value:
                        return fallback
                    try:
                        return date.fromisoformat(str(value))
                    except ValueError:
                        return fallback

                season_start = _configured_training_date(
                    "schedule_start", default_season_start
                )
                season_end = _configured_training_date(
                    "schedule_end", default_season_end
                )
                if season_end < season_start:
                    season_start, season_end = default_season_start, default_season_end

                if season_start.year != season_end.year:
                    schoolyear = f"{season_start.year}-{season_end.year}"
                else:
                    schoolyear = default_schoolyear

                match_cfg = match_management.get(team_data.team.team_id, {})
                present_value = match_cfg.get("match_present_minutes")
                if present_value is None:
                    # Backward compatibility: v0.9.0-v0.9.2 stored this under
                    # training_management. Use it until the user saves the new
                    # Wedstrijdinstellingen screen.
                    present_value = training_cfg.get("match_present_minutes", 45)
                try:
                    team_data.match_present_minutes = max(
                        0, min(180, int(present_value))
                    )
                except (TypeError, ValueError):
                    team_data.match_present_minutes = 45

                team_data.school_holidays_enabled = bool(
                    training_cfg.get("school_holidays_enabled", False)
                )
                team_data.school_holiday_region = str(
                    training_cfg.get("school_holiday_region", "auto")
                )
                overrides = training_cfg.get("holiday_training_overrides")
                if overrides is None:
                    # Backward compatibility with v0.9.1.
                    overrides = [
                        item.get("datum", "")
                        for item in training_cfg.get("exception_dates", [])
                        if item.get("datum")
                    ]
                team_data.training_exception_dates = [
                    {"datum": value, "type": "toch_trainen"}
                    for value in overrides
                    if value
                ]

                region = team_data.school_holiday_region.casefold()
                # 'auto' blijft veilig: zonder betrouwbare gemeente/provincie-
                # mapping gokken we niet. De gebruiker kan Noord/Midden/Zuid kiezen.
                resolved_region = region if region in {"noord", "midden", "zuid"} else None

                holidays = []
                holiday_source = "uitgeschakeld"
                if team_data.school_holidays_enabled:
                    if resolved_region is None:
                        holiday_source = "regio_auto_niet_bepaald"
                    else:
                        season_start_year = season_start.year
                        relevant_schoolyears = (
                            f"{season_start_year - 1}-{season_start_year}",
                            f"{season_start_year}-{season_start_year + 1}",
                        )
                        sources = []
                        combined = []
                        for holiday_schoolyear in relevant_schoolyears:
                            cache_key = (holiday_schoolyear, resolved_region)
                            if cache_key not in holiday_cache:
                                holiday_cache[cache_key] = await async_get_school_holidays(
                                    self.client._session,
                                    holiday_schoolyear,
                                    resolved_region,
                                )
                            rows, source = holiday_cache[cache_key]
                            sources.append(source)
                            for item in rows:
                                if (
                                    item["einde"] >= season_start
                                    and item["start"] <= season_end
                                ):
                                    combined.append(item)

                        # Deduplicate overlapping results from live/fallback data.
                        seen = set()
                        for item in sorted(
                            combined,
                            key=lambda x: (x["start"], x["einde"], x["naam"]),
                        ):
                            key = (item["naam"], item["start"], item["einde"])
                            if key not in seen:
                                seen.add(key)
                                holidays.append(item)

                        holiday_source = "+".join(dict.fromkeys(sources))

                team_data.training_season = schoolyear.replace("-", "/")
                team_data.training_season_start = season_start.strftime("%d-%m-%Y")
                team_data.training_season_end = season_end.strftime("%d-%m-%Y")
                team_data.school_holiday_source = holiday_source
                team_data.school_holidays = [
                    {
                        "naam": item["naam"],
                        "start": item["start"].strftime("%d-%m-%Y"),
                        "einde": item["einde"].strftime("%d-%m-%Y"),
                    }
                    for item in holidays
                ]
                team_data.training_calendar = build_training_calendar(
                    team_data.training_sessions,
                    season_start,
                    season_end,
                    holidays,
                    team_data.school_holidays_enabled,
                    {
                        item["datum"]
                        for item in team_data.training_exception_dates
                        if item.get("datum")
                    },
                )


            # Stable rijschema:
            # - first load snapshots the current away schedule as the basis;
            # - existing assignments are never overwritten automatically;
            # - newly added away matches are automatically supplemented.
            #
            # This keeps manually arranged schedules stable while making sure
            # new fixtures do not remain empty until somebody opens the
            # configuration flow and ticks "aanvullend rijschema".
            driving_plan_changed = False
            if self.driving_plan is not None:
                for team_data in data.teams:
                    team_id = team_data.team.team_id

                    if not self.driving_plan.is_initialized(team_id):
                        initial = build_driving_schedule(team_data)
                        by_id = {
                            item["wedstrijd_id"]: item
                            for item in initial.get("schema", [])
                        }
                        for match in team_data.matches:
                            if match.is_home is not False:
                                continue
                            row = by_id.get(match.match_id, {})
                            self.driving_plan.set_assignment(
                                team_id,
                                match.match_id,
                                row.get("chauffeurs", []),
                                team_data.driving_cars,
                                source="basis",
                            )
                        self.driving_plan.set_initialized(team_id, True)
                        driving_plan_changed = True

                    # Automatically add assignments for away matches that
                    # appeared after the original plan was initialized.
                    # Existing assignments remain untouched.
                    missing = [
                        match
                        for match in team_data.matches
                        if match.is_home is False
                        and self.driving_plan.get_assignment(
                            team_id, match.match_id
                        ) is None
                    ]
                    if missing:
                        assignments = _choose_supplemental(
                            team_data,
                            self.driving_plan,
                            missing,
                        )
                        for match in missing:
                            self.driving_plan.set_assignment(
                                team_id,
                                match.match_id,
                                assignments.get(match.match_id, []),
                                team_data.driving_cars,
                                source="aanvullend_auto",
                            )
                        driving_plan_changed = True

                    if self.flagging_plan is not None and team_data.flagging_enabled:
                        if not self.flagging_plan.is_initialized(team_id):
                            assignments, _warnings = rebuild_flagging_schedule(team_data, self.driving_plan)
                            for match in team_data.matches:
                                if team_data.flagging_enabled:
                                    self.flagging_plan.set_assignment(team_id, match.match_id, assignments.get(match.match_id, ""), source="basis")
                            self.flagging_plan.set_initialized(team_id, True)
                            driving_plan_changed = True

                    team_data.season_export_data = build_season_export(
                        team_data,
                        self.driving_plan,
                    )

                if driving_plan_changed:
                    await self.driving_plan.async_save()
                if self.flagging_plan is not None:
                    await self.flagging_plan.async_save()

            return data
        except VoetbalNlError as err:
            raise UpdateFailed(str(err)) from err
