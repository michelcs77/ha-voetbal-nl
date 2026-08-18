import logging
import re
from datetime import date, datetime

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

LOGGER = logging.getLogger(__name__)

from .client import VoetbalNlAuthError, VoetbalNlClient, VoetbalNlConnectionError
from .school_holidays import season_bounds
from .waha import WahaClient, WahaError
from .gemini import GeminiClient, GeminiError
from .const import (
    CONF_CLUB_CITY,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_CLUB_QUERY,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TEAM_IDS,
    CONF_PLAYER_MANAGEMENT,
    CONF_DRIVING_MANAGEMENT,
    CONF_DRIVING_CARS,
    CONF_DRIVING_EXCLUDED,
    CONF_DRIVING_ADD_SUPPLEMENT,
    CONF_DRIVING_EXTRA_DRIVERS,
    CONF_DRIVING_EXTRA_MANUAL,
    CONF_DRIVING_UNAVAILABLE,
    CONF_FLAGGING_MANAGEMENT,
    CONF_FLAGGING_ENABLED,
    CONF_FLAGGING_ALLOWED,
    CONF_FLAGGING_EXTRA,
    CONF_FLAGGING_EXTRA_MANUAL,
    CONF_FLAGGING_REBUILD,
    DEFAULT_DRIVING_CARS,
    CONF_TRAINING_MANAGEMENT,
    CONF_MATCH_MANAGEMENT,
    CONF_MATCH_PRESENT_MINUTES,
    DEFAULT_MATCH_PRESENT_MINUTES,
    CONF_ROUTE_API_KEY,
    CONF_ROUTE_TEAM_ORIGINS,
    CONF_ROUTE_ORIGIN_MODE,
    CONF_ROUTE_ORIGIN_NAME,
    CONF_ROUTE_ORIGIN_LATITUDE,
    CONF_ROUTE_ORIGIN_LONGITUDE,
    ROUTE_ORIGIN_CLUB,
    ROUTE_ORIGIN_CUSTOM,
    DOMAIN,
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
    CONF_TRAINING_POLL_DAYS_BEFORE,
    CONF_TRAINING_POLL_TIME,
    CONF_TRAINING_REMINDER_DAYS_BEFORE,
    CONF_TRAINING_REMINDER_TIME,
    CONF_TRAINING_PRODUCTION_ENABLED,
    DEFAULT_TRAINING_POLL_DAYS_BEFORE,
    DEFAULT_TRAINING_POLL_TIME,
    DEFAULT_TRAINING_REMINDER_DAYS_BEFORE,
    DEFAULT_TRAINING_REMINDER_TIME,
    CONF_MATCHDAY_MESSAGE_ENABLED, CONF_MATCHDAY_MESSAGE_TIME, CONF_MATCHDAY_WEATHER_ENABLED,
    DEFAULT_MATCHDAY_MESSAGE_TIME,
    CONF_TRAINING_INFO_ENABLED, CONF_TRAINING_INFO_HOURS_BEFORE, CONF_TRAINING_WEATHER_ENABLED,
    CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED, DEFAULT_TRAINING_INFO_HOURS_BEFORE,
    CONF_GEMINI_API_KEY, CONF_GEMINI_MODEL, DEFAULT_GEMINI_MODEL,
    CONF_MATCHDAY_COACH_ENABLED, CONF_TRAINING_COACH_ENABLED,
)

class HaVoetbalNlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 4

    @staticmethod
    def async_get_options_flow(config_entry):
        return HaVoetbalNlOptionsFlow()

    def __init__(self):
        self._email = ""
        self._password = ""
        self._clubs = {}
        self._club = None
        self._teams = {}
        self._team_labels = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]

            client = VoetbalNlClient(
                async_get_clientsession(self.hass),
                self._email,
                self._password,
            )
            try:
                await client.async_login()
            except VoetbalNlAuthError:
                errors["base"] = "invalid_auth"
            except VoetbalNlConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return await self.async_step_club_search()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    async def async_step_club_search(self, user_input=None):
        errors = {}
        if user_input is not None:
            query = user_input[CONF_CLUB_QUERY].strip()
            client = VoetbalNlClient(
                async_get_clientsession(self.hass),
                self._email,
                self._password,
            )
            try:
                clubs = await client.async_search_clubs(query)
            except VoetbalNlAuthError:
                errors["base"] = "invalid_auth"
            except VoetbalNlConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                if not clubs:
                    errors["base"] = "no_clubs"
                else:
                    self._clubs = {club.club_id: club for club in clubs}
                    return await self.async_step_club_select()

        return self.async_show_form(
            step_id="club_search",
            data_schema=vol.Schema({
                vol.Required(CONF_CLUB_QUERY): str,
            }),
            errors=errors,
        )

    async def _load_team_choices(self, club):
        client = VoetbalNlClient(
            async_get_clientsession(self.hass),
            self._email,
            self._password,
        )
        club_data = await client.async_get_club_data(club)
        self._teams = {team.team_id: team for team in club_data.teams}

        grouped = {}
        for team in club_data.teams:
            grouped.setdefault(team.name.casefold(), []).append(team)

        labels = {}
        for teams in grouped.values():
            if len(teams) == 1:
                team = teams[0]
                labels[team.team_id] = f"{team.name} — {team.team_id}"
                continue

            for team in teams:
                try:
                    meta = await client.async_get_team_metadata(team)
                except Exception:
                    meta = None

                parts = [team.name]
                if meta and meta.days:
                    parts.append("/".join(meta.days))
                if meta and meta.competitions:
                    parts.append(meta.competitions[0])
                parts.append(team.team_id)
                labels[team.team_id] = " — ".join(parts)

        self._team_labels = labels

    def _team_selector(self, suggested=None):
        options = [
            SelectOptionDict(
                value=team_id,
                label=self._team_labels.get(
                    team_id,
                    f"{team.name} — {team_id}",
                ),
            )
            for team_id, team in sorted(
                self._teams.items(),
                key=lambda item: (
                    self._team_labels.get(item[0], item[1].name).casefold()
                ),
            )
        ]

        key = vol.Required(CONF_TEAM_IDS)
        if suggested:
            key = vol.Required(
                CONF_TEAM_IDS,
                description={"suggested_value": list(suggested)},
            )

        return vol.Schema({
            key: SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode="dropdown",
                )
            )
        })

    async def async_step_club_select(self, user_input=None):
        errors = {}

        if user_input is not None:
            self._club = self._clubs[user_input[CONF_CLUB_ID]]
            try:
                await self._load_team_choices(self._club)
            except VoetbalNlAuthError:
                errors["base"] = "invalid_auth"
            except VoetbalNlConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                if not self._teams:
                    errors["base"] = "no_teams"
                else:
                    return await self.async_step_team_select()

        options = {
            club_id: (
                f"{club.name} — {club.city} [{club.club_id}]"
                if club.city
                else f"{club.name} [{club.club_id}]"
            )
            for club_id, club in self._clubs.items()
        }

        return self.async_show_form(
            step_id="club_select",
            data_schema=vol.Schema({
                vol.Required(CONF_CLUB_ID): vol.In(options),
            }),
            errors=errors,
        )

    async def async_step_team_select(self, user_input=None):
        errors = {}

        if user_input is not None:
            team_ids = list(dict.fromkeys(user_input.get(CONF_TEAM_IDS, [])))

            if not team_ids:
                errors["base"] = "select_team"
            else:
                teams = [
                    self._teams[team_id]
                    for team_id in team_ids
                    if team_id in self._teams
                ]

                client = VoetbalNlClient(
                    async_get_clientsession(self.hass),
                    self._email,
                    self._password,
                )
                try:
                    # Validate all selected teams, including players.
                    await client.async_get_multi_team_data(self._club, teams)
                except VoetbalNlAuthError:
                    errors["base"] = "invalid_auth"
                except VoetbalNlConnectionError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(
                        f"{self._email.casefold()}::{self._club.club_id}"
                    )
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"{self._club.name} ({self._club.city})",
                        data={
                            CONF_EMAIL: self._email,
                            CONF_PASSWORD: self._password,
                            CONF_CLUB_ID: self._club.club_id,
                            CONF_CLUB_NAME: self._club.name,
                            CONF_CLUB_CITY: self._club.city,
                            CONF_TEAM_IDS: team_ids,
                        },
                    )

        return self.async_show_form(
            step_id="team_select",
            data_schema=self._team_selector(),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Allow selected teams to be added or removed later."""
        entry = self._get_reconfigure_entry()
        self._email = entry.data[CONF_EMAIL]
        self._password = entry.data[CONF_PASSWORD]

        from .models import Club
        self._club = Club(
            club_id=entry.data[CONF_CLUB_ID],
            name=entry.data[CONF_CLUB_NAME],
            city=entry.data.get(CONF_CLUB_CITY, ""),
        )

        errors = {}

        if not self._teams:
            try:
                await self._load_team_choices(self._club)
            except VoetbalNlAuthError:
                errors["base"] = "invalid_auth"
            except VoetbalNlConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        if user_input is not None and not errors:
            team_ids = list(dict.fromkeys(user_input.get(CONF_TEAM_IDS, [])))
            if not team_ids:
                errors["base"] = "select_team"
            else:
                new_data = dict(entry.data)
                new_data[CONF_TEAM_IDS] = team_ids
                return self.async_update_reload_and_abort(
                    entry,
                    data=new_data,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._team_selector(
                entry.data.get(CONF_TEAM_IDS, [])
            ) if self._teams else vol.Schema({}),
            errors=errors,
        )


class HaVoetbalNlOptionsFlow(OptionsFlowWithReload):
    """Manage visible and manual players per selected team."""

    def __init__(self):
        self._team_id = None
        self._waha_temp = {}
        self._waha_sessions = []
        self._waha_groups = []
        self._team_remove_id = None
        self._team_remove_name = None

    def _coordinator(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        """Hoofdmenu voor configuratie."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            section = user_input["config_section"]
            if section == "players":
                return await self.async_step_players_team()
            if section == "route":
                return await self.async_step_route()
            if section == "driving":
                return await self.async_step_driving_team()
            if section == "match_tasks":
                return await self.async_step_match_tasks_team()
            if section == "training":
                return await self.async_step_training_team()
            if section == "matches":
                return await self.async_step_match_team()
            if section == "whatsapp":
                return await self.async_step_whatsapp_start()
            if section == "gemini":
                return await self.async_step_gemini()
            if section == "team_remove":
                return await self.async_step_team_remove()
            return self.async_abort(reason="unknown_section")

        options = [
            SelectOptionDict(value="players", label="👥 Spelersbeheer — Selectie en handmatig toegevoegde spelers beheren"),
            SelectOptionDict(value="route", label="🗺️ Route-instellingen — ORS, vertrekpunt en routeberekening instellen"),
            SelectOptionDict(value="driving", label="🚗 Rijschema — Auto's, chauffeurs en uitsluitingen beheren"),
            SelectOptionDict(value="match_tasks", label="🚩 Wedstrijdtaken — Vlagger per team en herberekening"),
            SelectOptionDict(value="training", label="🏋️ Trainingsschema — Trainingsdagen, tijden, verzameltijd en veld beheren"),
            SelectOptionDict(value="matches", label="⚽ Wedstrijdinstellingen — Verzameltijd en toekomstige wedstrijdopties beheren"),
            SelectOptionDict(value="whatsapp", label="💬 WhatsApp / WAHA — Polls, testgroep en spelersgroep koppelen"),
            SelectOptionDict(value="gemini", label="🤖 AI Coach / Gemini — API-key en model instellen"),
            SelectOptionDict(value="team_remove", label="🗑️ Team verwijderen — Kies één team en verwijder het veilig"),
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("config_section"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        mode="list",
                    )
                )
            }),
        )

    async def _load_all_team_choices_for_removal(self):
        """Load all club teams so removal is always based on the full club roster."""
        entry = self.config_entry
        email = str(entry.data.get(CONF_EMAIL) or "").strip()
        password = entry.data.get(CONF_PASSWORD)
        club_id = entry.data.get(CONF_CLUB_ID)
        club_name = entry.data.get(CONF_CLUB_NAME, "")
        club_city = entry.data.get(CONF_CLUB_CITY, "")

        from .models import Club
        club = Club(
            club_id=club_id,
            name=club_name,
            city=club_city,
        )
        client = VoetbalNlClient(
            async_get_clientsession(self.hass),
            email,
            password,
        )
        club_data = await client.async_get_club_data(club)
        teams = list(getattr(club_data, "teams", []) or [])

        labels = {}
        for team in teams:
            labels[team.team_id] = f"{team.name} — {team.team_id}"

        return teams, labels

    def _remove_team_entities_from_registry(self, team_id: str) -> int:
        """Remove registry entities belonging only to the removed team."""
        registry = er.async_get(self.hass)
        needle = f"_{team_id}_"
        removed = 0

        for entity_id, entry in list(registry.entities.items()):
            if entry.config_entry_id != self.config_entry.entry_id:
                continue
            if needle not in (entry.unique_id or ""):
                continue
            registry.async_remove(entity_id)
            removed += 1

        LOGGER.info(
            "Removed %s HA Voetbal.nl entity-registry entries for team %s",
            removed,
            team_id,
        )
        return removed

    async def async_step_team_remove(self, user_input=None):
        """Choose exactly one team to remove from the active integration."""
        errors = {}

        if user_input is not None:
            team_id = str(user_input.get("team_remove_id") or "").strip()
            if not team_id:
                errors["base"] = "select_team_remove"
            else:
                active_ids = list(self.config_entry.data.get(CONF_TEAM_IDS, []) or [])
                if team_id not in active_ids:
                    errors["base"] = "team_not_active"
                elif len(active_ids) <= 1:
                    errors["base"] = "cannot_remove_last_team"
                else:
                    try:
                        teams, labels = await self._load_all_team_choices_for_removal()
                    except VoetbalNlAuthError:
                        errors["base"] = "invalid_auth"
                    except VoetbalNlConnectionError:
                        errors["base"] = "cannot_connect"
                    except Exception:
                        errors["base"] = "unknown"
                    else:
                        selected = next((t for t in teams if t.team_id == team_id), None)
                        if selected is None:
                            errors["base"] = "team_not_found"
                        else:
                            self._team_remove_id = team_id
                            self._team_remove_name = labels.get(team_id, f"{selected.name} — {team_id}")
                            return await self.async_step_team_remove_confirm()

        try:
            teams, labels = await self._load_all_team_choices_for_removal()
        except VoetbalNlAuthError:
            errors["base"] = "invalid_auth"
            teams, labels = [], {}
        except VoetbalNlConnectionError:
            errors["base"] = "cannot_connect"
            teams, labels = [], {}
        except Exception:
            errors["base"] = "unknown"
            teams, labels = [], {}

        active_ids = set(self.config_entry.data.get(CONF_TEAM_IDS, []) or [])
        options = [
            SelectOptionDict(
                value=team.team_id,
                label=f"{labels.get(team.team_id, team.name + ' — ' + team.team_id)} — actief",
            )
            for team in teams
            if team.team_id in active_ids
        ]

        return self.async_show_form(
            step_id="team_remove",
            data_schema=vol.Schema({
                vol.Required("team_remove_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        mode="list",
                    )
                ),
            }),
            errors=errors,
            description_placeholders={
                "club": str(self.config_entry.data.get(CONF_CLUB_NAME) or ""),
            },
        )

    async def async_step_team_remove_confirm(self, user_input=None):
        """Confirm removal of exactly one selected team."""
        errors = {}

        if user_input is not None:
            if not user_input.get("confirm_remove", False):
                return await self.async_step_team_remove()

            team_id = self._team_remove_id
            active_ids = list(self.config_entry.data.get(CONF_TEAM_IDS, []) or [])
            if not team_id or team_id not in active_ids:
                errors["base"] = "team_not_active"
            elif len(active_ids) <= 1:
                errors["base"] = "cannot_remove_last_team"
            else:
                new_data = dict(self.config_entry.data)
                new_data[CONF_TEAM_IDS] = [x for x in active_ids if x != team_id]

                # Only the active team selection changes. All options/configuration
                # for the remaining teams are left untouched.
                # OptionsFlow cannot use the ConfigFlow convenience helper here,
                # so update the entry directly and then reload the integration.
                removed_entities = self._remove_team_entities_from_registry(team_id)
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                )
                LOGGER.info(
                    "Team %s removed from active selection; %s registry entities cleaned up",
                    team_id,
                    removed_entities,
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_abort(reason="team_removed")

        return self.async_show_form(
            step_id="team_remove_confirm",
            data_schema=vol.Schema({
                vol.Required("confirm_remove", default=False): bool,
            }),
            errors=errors,
            description_placeholders={
                "team": self._team_remove_name or "onbekend team",
                "team_id": self._team_remove_id or "",
            },
        )

    async def async_step_players_team(self, user_input=None):
        """Kies een team voor spelersbeheer."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            self._team_id = user_input["players_team_id"]
            return await self.async_step_players()

        options = [
            SelectOptionDict(
                value=item.team.team_id,
                label=f"{item.team.name} — {item.team.team_id}",
            )
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="players_team",
            data_schema=vol.Schema({
                vol.Required("players_team_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        mode="dropdown",
                    )
                )
            }),
        )

    async def async_step_driving_team(self, user_input=None):
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._team_id = user_input["driving_team_id"]
            return await self.async_step_driving()
        options = [
            SelectOptionDict(
                value=item.team.team_id,
                label=f"{item.team.name} — {item.team.team_id}",
            )
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="driving_team",
            data_schema=vol.Schema({
                vol.Required("driving_team_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=options, multiple=False, mode="dropdown"
                    )
                )
            }),
        )

    async def async_step_driving(self, user_input=None):
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        team_data = next(
            (x for x in coordinator.data.teams if x.team.team_id == self._team_id),
            None,
        )
        if team_data is None:
            return self.async_abort(reason="team_not_found")

        squad = list(dict.fromkeys(
            list(team_data.selected_players) + list(team_data.manual_players)
        ))
        all_cfg = dict(self.config_entry.options.get(CONF_DRIVING_MANAGEMENT, {}))
        current = dict(all_cfg.get(self._team_id, {}))
        current_cars = int(current.get("cars", DEFAULT_DRIVING_CARS))
        current_excluded = list(current.get("excluded", []))
        current_extra = list(current.get("extra_drivers", []))
        current_unavailable = list(current.get(CONF_DRIVING_UNAVAILABLE, []))
        current_unavailable_text = "; ".join(
            f"{item.get('name', '')} | {item.get('date', '')}"
            for item in current_unavailable if isinstance(item, dict) and item.get("name") and item.get("date")
        )

        if user_input is not None:
            cars = int(user_input[CONF_DRIVING_CARS])
            excluded = list(dict.fromkeys(
                user_input.get(CONF_DRIVING_EXCLUDED, [])
            ))
            extra = list(dict.fromkeys(user_input.get(CONF_DRIVING_EXTRA_DRIVERS, [])))
            manual = [" ".join(x.split()) for x in str(user_input.get(CONF_DRIVING_EXTRA_MANUAL, "")).split(",") if x.strip()]
            extra = list(dict.fromkeys(extra + manual))
            unavailable = []
            raw_unavailable = str(user_input.get(CONF_DRIVING_UNAVAILABLE, ""))
            for entry in re.split(r"[;\n]+", raw_unavailable):
                entry = " ".join(entry.split())
                if not entry:
                    continue
                if "|" not in entry:
                    continue
                name, raw_date = [x.strip() for x in entry.split("|", 1)]
                parsed = None
                for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
                    try:
                        parsed = datetime.strptime(raw_date, fmt).date().isoformat()
                        break
                    except ValueError:
                        pass
                if name and parsed:
                    unavailable.append({"name": name, "date": parsed})
            all_cfg[self._team_id] = {
                "cars": cars,
                "excluded": excluded,
                "extra_drivers": extra,
                CONF_DRIVING_UNAVAILABLE: unavailable,
            }
            if user_input.get(CONF_DRIVING_ADD_SUPPLEMENT, False):
                await coordinator.async_add_supplemental_driving_plan(
                    self._team_id
                )
            new_options = dict(self.config_entry.options)
            new_options[CONF_DRIVING_MANAGEMENT] = all_cfg
            return self.async_create_entry(title="", data=new_options)

        player_options = [
            SelectOptionDict(value=name, label=name) for name in list(dict.fromkeys(squad + [x.name for x in team_data.staff]))
        ]
        return self.async_show_form(
            step_id="driving",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_DRIVING_CARS,
                    description={"suggested_value": current_cars},
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
                vol.Optional(
                    CONF_DRIVING_EXCLUDED,
                    default=current_excluded,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=player_options,
                        multiple=True,
                        mode="dropdown",
                    )
                ),
                vol.Optional(
                    CONF_DRIVING_EXTRA_DRIVERS,
                    default=current_extra,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=player_options,
                        multiple=True,
                        mode="dropdown",
                    )
                ),
                vol.Optional(
                    CONF_DRIVING_UNAVAILABLE,
                    default=current_unavailable_text,
                ): TextSelector(TextSelectorConfig(type="text")),
                vol.Optional(
                    CONF_DRIVING_ADD_SUPPLEMENT,
                    default=False,
                ): bool,
            }),
            description_placeholders={"team": team_data.team.name, "temporary_driver_help": "Gebruik: Naam | DD-MM-JJJJ. Meerdere regels scheiden met ;. Alleen op die datum niet beschikbaar om te rijden."},
        )

    async def async_step_match_tasks_team(self, user_input=None):
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._team_id = user_input["match_tasks_team_id"]
            return await self.async_step_match_tasks()
        options=[SelectOptionDict(value=x.team.team_id,label=f"{x.team.name} — {x.team.team_id}") for x in coordinator.data.teams]
        return self.async_show_form(step_id="match_tasks_team",data_schema=vol.Schema({vol.Required("match_tasks_team_id"): SelectSelector(SelectSelectorConfig(options=options,multiple=False,mode="dropdown"))}))

    async def async_step_match_tasks(self, user_input=None):
        coordinator=self._coordinator()
        if coordinator is None: return self.async_abort(reason="not_loaded")
        team=next((x for x in coordinator.data.teams if x.team.team_id==self._team_id),None)
        if team is None: return self.async_abort(reason="team_not_found")
        all_cfg=dict(self.config_entry.options.get(CONF_FLAGGING_MANAGEMENT,{}))
        current=dict(all_cfg.get(self._team_id,{}))
        people=list(dict.fromkeys(list(team.selected_players)+list(team.manual_players)+list(team.driving_extra)+[x.name for x in team.staff]))
        current_enabled=bool(current.get("enabled",False))
        # v0.10.1: whitelist. Only explicitly selected people may be planned as flaggers.
        current_allowed=list(current.get("flaggers",[]))
        stored_extra=list(current.get("extra",[]))
        current_extra=[x for x in stored_extra if x in people]
        current_extra_manual=[x for x in stored_extra if x not in people]
        if user_input is not None:
            allowed=list(dict.fromkeys(user_input.get(CONF_FLAGGING_ALLOWED,[])))
            extra=list(dict.fromkeys(user_input.get(CONF_FLAGGING_EXTRA,[])))
            manual=[" ".join(x.split()) for x in str(user_input.get(CONF_FLAGGING_EXTRA_MANUAL, "")).replace(";", ",").split(",") if x.strip()]
            cfg={
                "enabled": bool(user_input.get(CONF_FLAGGING_ENABLED,False)),
                "flaggers": allowed,
                "extra": list(dict.fromkeys(extra+manual)),
            }
            all_cfg[self._team_id]=cfg
            new_options=dict(self.config_entry.options); new_options[CONF_FLAGGING_MANAGEMENT]=all_cfg
            if user_input.get(CONF_FLAGGING_REBUILD,False):
                team.flagging_enabled = cfg["enabled"]
                team.flagging_allowed = cfg["flaggers"]
                team.flagging_extra = cfg["extra"]
                await coordinator.async_rebuild_match_tasks(self._team_id)
            return self.async_create_entry(title="",data=new_options)
        opts=[SelectOptionDict(value=n,label=n) for n in people]
        return self.async_show_form(step_id="match_tasks",data_schema=vol.Schema({
            vol.Required(CONF_FLAGGING_ENABLED,default=current_enabled): bool,
            vol.Optional(CONF_FLAGGING_ALLOWED,default=current_allowed): SelectSelector(SelectSelectorConfig(options=opts,multiple=True,mode="dropdown")),
            vol.Optional(CONF_FLAGGING_EXTRA,default=current_extra): SelectSelector(SelectSelectorConfig(options=opts,multiple=True,mode="dropdown")),
            vol.Optional(CONF_FLAGGING_EXTRA_MANUAL,default=", ".join(current_extra_manual)): TextSelector(TextSelectorConfig(type="text")),
            vol.Optional(CONF_FLAGGING_REBUILD,default=False): bool,
        }),description_placeholders={"team":team.team.name})

    async def async_step_match_team(self, user_input=None):
        """Kies team voor wedstrijdinstellingen."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            self._team_id = user_input["match_team_id"]
            return await self.async_step_match_settings()

        options = [
            SelectOptionDict(
                value=item.team.team_id,
                label=f"{item.team.name} — {item.team.team_id}",
            )
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="match_team",
            data_schema=vol.Schema({
                vol.Required("match_team_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        mode="dropdown",
                    )
                )
            }),
        )

    async def async_step_match_settings(self, user_input=None):
        """Wedstrijdinstellingen per team."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        team_data = next(
            (
                item for item in coordinator.data.teams
                if item.team.team_id == self._team_id
            ),
            None,
        )
        if team_data is None:
            return self.async_abort(reason="team_not_found")

        match_management = dict(
            self.config_entry.options.get(CONF_MATCH_MANAGEMENT, {})
        )
        current = dict(match_management.get(self._team_id, {}))

        # Compatibility fallback to old training config.
        if "match_present_minutes" in current:
            default_present = int(current["match_present_minutes"])
        else:
            training_management = self.config_entry.options.get(
                CONF_TRAINING_MANAGEMENT, {}
            )
            old_training_cfg = training_management.get(self._team_id, {})
            default_present = int(
                old_training_cfg.get(
                    "match_present_minutes",
                    DEFAULT_MATCH_PRESENT_MINUTES,
                )
            )

        if user_input is not None:
            present = int(user_input[CONF_MATCH_PRESENT_MINUTES])
            if present < 0 or present > 180:
                return self.async_show_form(
                    step_id="match_settings",
                    data_schema=vol.Schema({
                        vol.Required(
                            CONF_MATCH_PRESENT_MINUTES,
                            default=default_present,
                        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
                    }),
                    errors={"base": "invalid_present_minutes"},
                    description_placeholders={"team": team_data.team.name},
                )

            match_management[self._team_id] = {
                "match_present_minutes": present,
            }

            # Migrate the old setting out of training_management once saved.
            new_options = dict(self.config_entry.options)
            new_options[CONF_MATCH_MANAGEMENT] = match_management

            training_management = dict(
                new_options.get(CONF_TRAINING_MANAGEMENT, {})
            )
            if self._team_id in training_management:
                old_cfg = dict(training_management[self._team_id])
                old_cfg.pop("match_present_minutes", None)
                training_management[self._team_id] = old_cfg
                new_options[CONF_TRAINING_MANAGEMENT] = training_management

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="match_settings",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MATCH_PRESENT_MINUTES,
                    default=default_present,
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
            }),
            description_placeholders={"team": team_data.team.name},
        )

    async def async_step_training_team(self, user_input=None):
        """Kies team voor trainingsschema."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            self._team_id = user_input["training_team_id"]
            return await self.async_step_training()

        options = [
            SelectOptionDict(
                value=item.team.team_id,
                label=f"{item.team.name} — {item.team.team_id}",
            )
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="training_team",
            data_schema=vol.Schema({
                vol.Required("training_team_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        mode="dropdown",
                    )
                )
            }),
        )

    async def async_step_training(self, user_input=None):
        """Beheer maximaal drie wekelijkse trainingsmomenten."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        team_data = next(
            (item for item in coordinator.data.teams
             if item.team.team_id == self._team_id),
            None,
        )
        if team_data is None:
            return self.async_abort(reason="team_not_found")

        current = dict(self.config_entry.options.get(CONF_TRAINING_MANAGEMENT, {}))
        cfg = dict(current.get(self._team_id, {}))
        sessions = list(cfg.get("sessions", []))
        while len(sessions) < 3:
            sessions.append({})

        if user_input is not None:
            new_sessions = []
            for idx in range(1, 4):
                day = user_input.get(f"training_{idx}_day", "geen")
                if day == "geen":
                    continue
                start = str(user_input.get(f"training_{idx}_start", "")).strip()
                end = str(user_input.get(f"training_{idx}_end", "")).strip()
                meeting = str(user_input.get(f"training_{idx}_meeting", "")).strip()
                field = str(user_input.get(f"training_{idx}_field", "")).strip()
                new_sessions.append({
                    "dag": day,
                    "verzameltijd": meeting,
                    "start": start,
                    "einde": end,
                    "veld": field,
                })

            # Configurable training calendar boundaries.  Store as ISO
            # internally, while the options UI uses DD-MM-YYYY consistently.
            default_start, default_end, _ = season_bounds(date.today())
            raw_start = str(
                user_input.get("training_schedule_start", default_start.strftime("%d-%m-%Y"))
            ).strip()
            raw_end = str(
                user_input.get("training_schedule_end", default_end.strftime("%d-%m-%Y"))
            ).strip()
            invalid_range_dates = []
            parsed_start = None
            parsed_end = None
            for label, value in (("start", raw_start), ("end", raw_end)):
                if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", value):
                    invalid_range_dates.append(value or label)
                    continue
                try:
                    parsed = datetime.strptime(value, "%d-%m-%Y").date()
                except ValueError:
                    invalid_range_dates.append(value)
                    continue
                if label == "start":
                    parsed_start = parsed
                else:
                    parsed_end = parsed

            if invalid_range_dates or parsed_start is None or parsed_end is None:
                return self.async_show_form(
                    step_id="training",
                    data_schema=self._training_schema(
                        sessions,
                        cfg,
                        raw_override_value=str(user_input.get("holiday_training_overrides", "")),
                        raw_start_value=raw_start,
                        raw_end_value=raw_end,
                    ),
                    errors={"base": "invalid_training_period_dates"},
                    description_placeholders={
                        "team": team_data.team.name,
                        "invalid_dates": ", ".join(invalid_range_dates),
                    },
                )

            if parsed_end < parsed_start:
                return self.async_show_form(
                    step_id="training",
                    data_schema=self._training_schema(
                        sessions,
                        cfg,
                        raw_override_value=str(user_input.get("holiday_training_overrides", "")),
                        raw_start_value=raw_start,
                        raw_end_value=raw_end,
                    ),
                    errors={"base": "training_period_end_before_start"},
                    description_placeholders={"team": team_data.team.name},
                )

            holiday_training_overrides = []
            raw_overrides = str(
                user_input.get("holiday_training_overrides", "")
            )
            invalid_dates = []

            for line in raw_overrides.splitlines():
                date_value = line.strip()
                if not date_value:
                    continue

                if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", date_value):
                    invalid_dates.append(date_value)
                    continue

                try:
                    parsed = datetime.strptime(date_value, "%d-%m-%Y")
                except ValueError:
                    invalid_dates.append(date_value)
                    continue

                iso_date = parsed.strftime("%Y-%m-%d")
                if iso_date not in holiday_training_overrides:
                    holiday_training_overrides.append(iso_date)

            if invalid_dates:
                return self.async_show_form(
                    step_id="training",
                    data_schema=self._training_schema(
                        sessions,
                        cfg,
                        raw_override_value=raw_overrides,
                    ),
                    errors={"base": "invalid_training_override_dates"},
                    description_placeholders={
                        "team": team_data.team.name,
                        "invalid_dates": ", ".join(invalid_dates),
                    },
                )

            training_poll_days = int(user_input.get(CONF_TRAINING_POLL_DAYS_BEFORE, DEFAULT_TRAINING_POLL_DAYS_BEFORE))
            training_poll_time = str(user_input.get(CONF_TRAINING_POLL_TIME, DEFAULT_TRAINING_POLL_TIME)).strip()
            training_reminder_days = int(user_input.get(CONF_TRAINING_REMINDER_DAYS_BEFORE, DEFAULT_TRAINING_REMINDER_DAYS_BEFORE))
            training_reminder_time = str(user_input.get(CONF_TRAINING_REMINDER_TIME, DEFAULT_TRAINING_REMINDER_TIME)).strip()
            time_re = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
            training_info_hours = int(user_input.get(CONF_TRAINING_INFO_HOURS_BEFORE, DEFAULT_TRAINING_INFO_HOURS_BEFORE))
            if (not time_re.fullmatch(training_poll_time) or not time_re.fullmatch(training_reminder_time)
                    or training_poll_days < 0 or training_poll_days > 14
                    or training_info_hours < 0 or training_info_hours > 24
                    or training_reminder_days < 0 or training_reminder_days > 14
                    or training_reminder_days > training_poll_days
                    or (training_reminder_days == training_poll_days and training_reminder_time <= training_poll_time)):
                return self.async_show_form(
                    step_id="training",
                    data_schema=self._training_schema(new_sessions + [{}] * (3-len(new_sessions)), cfg),
                    errors={"base": "invalid_training_poll_schedule"},
                    description_placeholders={"team": team_data.team.name},
                )

            current[self._team_id] = {
                "sessions": new_sessions,
                "school_holidays_enabled": bool(
                    user_input.get("school_holidays_enabled", False)
                ),
                "school_holiday_region": str(
                    user_input.get("school_holiday_region", "auto")
                ),
                "schedule_start": parsed_start.isoformat(),
                "schedule_end": parsed_end.isoformat(),
                CONF_TRAINING_POLL_DAYS_BEFORE: training_poll_days,
                CONF_TRAINING_POLL_TIME: training_poll_time,
                CONF_TRAINING_REMINDER_DAYS_BEFORE: training_reminder_days,
                CONF_TRAINING_REMINDER_TIME: training_reminder_time,
                CONF_TRAINING_PRODUCTION_ENABLED: bool(user_input.get(CONF_TRAINING_PRODUCTION_ENABLED, True)),
                CONF_TRAINING_INFO_ENABLED: bool(user_input.get(CONF_TRAINING_INFO_ENABLED, True)),
                CONF_TRAINING_INFO_HOURS_BEFORE: int(user_input.get(CONF_TRAINING_INFO_HOURS_BEFORE, DEFAULT_TRAINING_INFO_HOURS_BEFORE)),
                CONF_TRAINING_WEATHER_ENABLED: bool(user_input.get(CONF_TRAINING_WEATHER_ENABLED, True)),
                CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED: bool(user_input.get(CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED, True)),
                CONF_TRAINING_COACH_ENABLED: bool(user_input.get(CONF_TRAINING_COACH_ENABLED, False)),
                # Internal storage remains ISO for reliable date comparisons.
                # Semantics: these dates FORCE a normal training to continue
                # even when the date falls inside a configured school holiday.
                "holiday_training_overrides": holiday_training_overrides,
            }
            new_options = dict(self.config_entry.options)
            new_options[CONF_TRAINING_MANAGEMENT] = current
            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="training",
            data_schema=self._training_schema(
                sessions,
                cfg,
            ),
            description_placeholders={"team": team_data.team.name},
        )

    def _training_schema(self, sessions, cfg, raw_override_value=None, raw_start_value=None, raw_end_value=None):
        days = [
            SelectOptionDict(value="geen", label="— Geen training —"),
            SelectOptionDict(value="maandag", label="Maandag"),
            SelectOptionDict(value="dinsdag", label="Dinsdag"),
            SelectOptionDict(value="woensdag", label="Woensdag"),
            SelectOptionDict(value="donderdag", label="Donderdag"),
            SelectOptionDict(value="vrijdag", label="Vrijdag"),
            SelectOptionDict(value="zaterdag", label="Zaterdag"),
            SelectOptionDict(value="zondag", label="Zondag"),
        ]
        region_options = [
            SelectOptionDict(value="auto", label="Automatisch op basis van clublocatie"),
            SelectOptionDict(value="noord", label="Regio Noord"),
            SelectOptionDict(value="midden", label="Regio Midden"),
            SelectOptionDict(value="zuid", label="Regio Zuid"),
        ]
        stored_overrides = cfg.get("holiday_training_overrides")
        if stored_overrides is None:
            # v0.9.1 compatibility: migrate dates from the former
            # exception_dates field if present.
            stored_overrides = [
                item.get("datum", "")
                for item in cfg.get("exception_dates", [])
                if item.get("datum")
            ]

        override_default = "\n".join(
            datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
            for value in stored_overrides
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value))
        )
        if raw_override_value is not None:
            override_default = raw_override_value
        default_start, default_end, _ = season_bounds(date.today())
        stored_start = str(cfg.get("schedule_start", default_start.isoformat()))
        stored_end = str(cfg.get("schedule_end", default_end.isoformat()))

        def _display_stored_date(value, fallback):
            try:
                return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
            except (TypeError, ValueError):
                return fallback.strftime("%d-%m-%Y")

        start_default = raw_start_value if raw_start_value is not None else _display_stored_date(stored_start, default_start)
        end_default = raw_end_value if raw_end_value is not None else _display_stored_date(stored_end, default_end)

        schema = {
            vol.Required(CONF_TRAINING_POLL_DAYS_BEFORE, default=int(cfg.get(CONF_TRAINING_POLL_DAYS_BEFORE, DEFAULT_TRAINING_POLL_DAYS_BEFORE))): vol.All(vol.Coerce(int), vol.Range(min=0, max=14)),
            vol.Required(CONF_TRAINING_POLL_TIME, default=str(cfg.get(CONF_TRAINING_POLL_TIME, DEFAULT_TRAINING_POLL_TIME))): str,
            vol.Required(CONF_TRAINING_REMINDER_DAYS_BEFORE, default=int(cfg.get(CONF_TRAINING_REMINDER_DAYS_BEFORE, DEFAULT_TRAINING_REMINDER_DAYS_BEFORE))): vol.All(vol.Coerce(int), vol.Range(min=0, max=14)),
            vol.Required(CONF_TRAINING_REMINDER_TIME, default=str(cfg.get(CONF_TRAINING_REMINDER_TIME, DEFAULT_TRAINING_REMINDER_TIME))): str,
            vol.Required(CONF_TRAINING_PRODUCTION_ENABLED, default=bool(cfg.get(CONF_TRAINING_PRODUCTION_ENABLED, True))): bool,
            vol.Required(CONF_TRAINING_INFO_ENABLED, default=bool(cfg.get(CONF_TRAINING_INFO_ENABLED, True))): bool,
            vol.Required(CONF_TRAINING_INFO_HOURS_BEFORE, default=int(cfg.get(CONF_TRAINING_INFO_HOURS_BEFORE, DEFAULT_TRAINING_INFO_HOURS_BEFORE))): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Required(CONF_TRAINING_WEATHER_ENABLED, default=bool(cfg.get(CONF_TRAINING_WEATHER_ENABLED, True))): bool,
            vol.Required(CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED, default=bool(cfg.get(CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED, True))): bool,
            vol.Required(CONF_TRAINING_COACH_ENABLED, default=bool(cfg.get(CONF_TRAINING_COACH_ENABLED, False))): bool,
            vol.Required(
                "training_schedule_start",
                default=start_default,
            ): str,
            vol.Required(
                "training_schedule_end",
                default=end_default,
            ): str,
            vol.Optional(
                "school_holidays_enabled",
                default=bool(cfg.get("school_holidays_enabled", False)),
            ): bool,
            vol.Required(
                "school_holiday_region",
                default=str(cfg.get("school_holiday_region", "auto")),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=region_options, multiple=False, mode="dropdown"
                )
            ),
            vol.Optional(
                "holiday_training_overrides",
                description={"suggested_value": override_default},
            ): TextSelector(
                TextSelectorConfig(multiline=True)
            ),
        }
        for idx in range(1, 4):
            item = sessions[idx - 1] if idx - 1 < len(sessions) else {}
            schema[vol.Required(
                f"training_{idx}_day",
                default=item.get("dag", "geen"),
            )] = SelectSelector(
                SelectSelectorConfig(options=days, multiple=False, mode="dropdown")
            )
            schema[vol.Optional(
                f"training_{idx}_meeting",
                default=item.get("verzameltijd", ""),
            )] = str
            schema[vol.Optional(
                f"training_{idx}_start",
                default=item.get("start", ""),
            )] = str
            schema[vol.Optional(
                f"training_{idx}_end",
                default=item.get("einde", ""),
            )] = str
            schema[vol.Optional(
                f"training_{idx}_field",
                default=item.get("veld", ""),
            )] = str
        return vol.Schema(schema)

    async def async_step_gemini(self, user_input=None):
        """Configure and validate the shared Gemini API connection."""
        current = dict(self.config_entry.options)
        errors = {}
        default_key = str(current.get(CONF_GEMINI_API_KEY) or "")
        default_model = str(current.get(CONF_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL)
        if default_model == "gemini-2.5-flash":
            default_model = DEFAULT_GEMINI_MODEL
        if user_input is not None:
            api_key = str(user_input.get(CONF_GEMINI_API_KEY) or "").strip()
            model = str(user_input.get(CONF_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
            if model == "gemini-2.5-flash":
                model = DEFAULT_GEMINI_MODEL
            if not api_key:
                errors["base"] = "missing_gemini_api_key"
            else:
                try:
                    await GeminiClient(async_get_clientsession(self.hass), api_key, model).validate()
                except Exception:
                    errors["base"] = "cannot_connect_gemini"
                else:
                    new_options = dict(self.config_entry.options)
                    new_options[CONF_GEMINI_API_KEY] = api_key
                    new_options[CONF_GEMINI_MODEL] = model
                    return self.async_create_entry(title="", data=new_options)
        return self.async_show_form(
            step_id="gemini",
            data_schema=vol.Schema({
                vol.Required(CONF_GEMINI_API_KEY, default=default_key): TextSelector(TextSelectorConfig(type="password")),
                vol.Required(CONF_GEMINI_MODEL, default=default_model): str,
            }),
            errors=errors,
        )

    async def async_step_whatsapp_start(self, user_input=None):
        """Start WAHA configuration without silently choosing a group."""
        current = dict(self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
        configured = bool(
            str(current.get(CONF_WAHA_BASE_URL) or "").strip()
            and str(current.get(CONF_WAHA_API_KEY) or "").strip()
            and str(current.get(CONF_WAHA_SESSION) or "").strip()
        )
        if not configured:
            return await self.async_step_whatsapp_connection()

        if user_input is not None:
            action = user_input["waha_action"]
            if action == "connection":
                return await self.async_step_whatsapp_connection()
            if action == "groups":
                return await self.async_step_whatsapp_load_groups()
            if action == "identity":
                return await self.async_step_whatsapp_identity_start()
            return self.async_abort(reason="unknown_section")

        options = [
            SelectOptionDict(value="connection", label="🔌 WAHA verbinding — URL, API-key, webhook en sessie"),
            SelectOptionDict(value="groups", label="👥 WhatsApp groepen — testgroep en productiegroep per team"),
            SelectOptionDict(value="identity", label="🔗 WhatsApp matching — HA-naam ↔ WhatsApp-naam, rol en productie/test"),
        ]
        return self.async_show_form(
            step_id="whatsapp_start",
            data_schema=vol.Schema({
                vol.Required("waha_action"): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=False, mode="list")
                )
            }),
        )

    async def async_step_whatsapp_identity_start(self, user_input=None):
        """Refresh WAHA groups and start the manual WhatsApp identity matcher."""
        current = dict(self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
        base_url = str(current.get(CONF_WAHA_BASE_URL) or "").strip()
        api_key = str(current.get(CONF_WAHA_API_KEY) or "").strip()
        session_name = str(current.get(CONF_WAHA_SESSION) or "default").strip() or "default"
        if not base_url or not api_key:
            return await self.async_step_whatsapp_connection()

        client = WahaClient(
            async_get_clientsession(self.hass), base_url, api_key, session_name
        )
        try:
            groups = await client.groups()
        except Exception:
            return self.async_show_form(
                step_id="whatsapp_identity_start",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_load_waha_groups"},
            )

        self._waha_groups = groups if isinstance(groups, list) else []
        self._waha_temp = {
            CONF_WAHA_BASE_URL: base_url,
            CONF_WAHA_API_KEY: api_key,
            CONF_WAHA_SESSION: session_name,
            CONF_WAHA_WEBHOOK_BASE_URL: str(
                current.get(CONF_WAHA_WEBHOOK_BASE_URL) or "http://homeassistant:8123"
            ),
            CONF_WAHA_WEBHOOK_LOCAL_ONLY: bool(
                current.get(CONF_WAHA_WEBHOOK_LOCAL_ONLY, True)
            ),
        }
        return await self.async_step_whatsapp_identity_team()

    async def async_step_whatsapp_identity_team(self, user_input=None):
        """Choose the football team for a manual WhatsApp identity mapping."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            self._team_id = user_input["whatsapp_identity_team_id"]
            return await self.async_step_whatsapp_identity_group()

        options = [
            SelectOptionDict(
                value=item.team.team_id,
                label=f"{item.team.name} — {item.team.team_id}",
            )
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="whatsapp_identity_team",
            data_schema=vol.Schema({
                vol.Required("whatsapp_identity_team_id"): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=False, mode="dropdown")
                )
            }),
        )

    def _waha_group_by_id(self, group_id: str):
        for item in self._waha_groups:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if isinstance(raw_id, dict):
                raw_id = raw_id.get("_serialized")
            if str(raw_id or "") == str(group_id):
                return item
            metadata = item.get("groupMetadata") or {}
            meta_id = metadata.get("id") if isinstance(metadata, dict) else None
            if isinstance(meta_id, dict):
                meta_id = meta_id.get("_serialized")
            if str(meta_id or "") == str(group_id):
                return item
        return None

    def _group_participant_ids(self, group_id: str) -> list[str]:
        item = self._waha_group_by_id(group_id) or {}
        participants = item.get("participants")
        if not isinstance(participants, list):
            metadata = item.get("groupMetadata") or {}
            participants = metadata.get("participants") if isinstance(metadata, dict) else []
        result = []
        for participant in participants or []:
            if isinstance(participant, dict):
                raw_id = participant.get("id")
                if isinstance(raw_id, dict):
                    raw_id = raw_id.get("_serialized")
                if raw_id:
                    result.append(str(raw_id))
            elif participant:
                result.append(str(participant))
        return list(dict.fromkeys(result))

    async def _waha_identity_member_options(self, group_id: str):
        """Build contact options from the currently refreshed WAHA group."""
        client = WahaClient(
            async_get_clientsession(self.hass),
            self._waha_temp[CONF_WAHA_BASE_URL],
            self._waha_temp[CONF_WAHA_API_KEY],
            self._waha_temp[CONF_WAHA_SESSION],
        )
        options = []
        for wa_id in self._group_participant_ids(group_id):
            contact_name = ""
            try:
                contact = await client.contact(wa_id)
                contact_name = str(
                    contact.get("name")
                    or contact.get("pushname")
                    or contact.get("shortName")
                    or contact.get("formattedName")
                    or ""
                ).strip()
            except Exception:
                pass
            label = f"{contact_name or 'Onbekende WhatsApp-contact'} — {wa_id}"
            options.append(SelectOptionDict(value=wa_id, label=label))
        return sorted(options, key=lambda x: str(x["label"]).casefold())

    async def async_step_whatsapp_identity_group(self, user_input=None):
        """Choose WhatsApp group and environment, then load its members."""
        group_options = self._waha_group_options()
        if not group_options:
            return self.async_abort(reason="no_waha_groups")

        if user_input is not None:
            self._waha_identity_group_id = str(user_input["whatsapp_identity_group_id"])
            self._waha_identity_members = await self._waha_identity_member_options(
                self._waha_identity_group_id
            )
            if not self._waha_identity_members:
                return self.async_show_form(
                    step_id="whatsapp_identity_group",
                    data_schema=vol.Schema({
                        vol.Required("whatsapp_identity_group_id"): SelectSelector(
                            SelectSelectorConfig(options=group_options, multiple=False, mode="dropdown")
                        ),
                    }),
                    errors={"base": "no_waha_group_members"},
                )
            return await self.async_step_whatsapp_identity_mapping()

        return self.async_show_form(
            step_id="whatsapp_identity_group",
            data_schema=vol.Schema({
                vol.Required("whatsapp_identity_group_id"): SelectSelector(
                    SelectSelectorConfig(options=group_options, multiple=False, mode="dropdown")
                ),
            }),
        )

    async def async_step_whatsapp_identity_mapping(self, user_input=None):
        """Map HA people to WhatsApp contacts for one team/group.

        Production groups keep the full HA-roster editor. Test groups use the
        WhatsApp members as the rows, so a small test group can contain only
        one or two explicitly mapped test people without presenting the full
        squad.
        """
        coordinator = self._coordinator()
        team_data = next(
            (x for x in coordinator.data.teams if x.team.team_id == self._team_id),
            None,
        ) if coordinator else None
        if team_data is None:
            return self.async_abort(reason="team_not_found")

        squad = list(dict.fromkeys(
            list(team_data.selected_players) + list(team_data.manual_players)
        ))
        staff = list(dict.fromkeys(member.name for member in team_data.staff))

        current_waha = dict(
            self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {}
        )
        mappings = list(current_waha.get(CONF_WAHA_IDENTITY_MAPPINGS, []) or [])

        group_name = next(
            (
                str(opt["label"])
                for opt in self._waha_group_options()
                if str(opt["value"]) == str(self._waha_identity_group_id)
            ),
            str(self._waha_identity_group_id),
        )

        # Detect the configured test group for this team.  Test and Production
        # remain independent: saving one group only replaces mappings for that
        # exact team + group.
        team_waha = dict(
            (current_waha.get("teams", {}) or {}).get(str(self._team_id), {}) or {}
        )
        test_group_id = str(team_waha.get("test_group_id") or "")
        is_test_group = bool(
            test_group_id
            and str(self._waha_identity_group_id) == test_group_id
        )

        current_mappings = [
            item for item in mappings
            if str(item.get("team_id")) == str(self._team_id)
            and str(item.get("group_id")) == str(self._waha_identity_group_id)
        ]

        # Build defaults by WhatsApp ID.  This is the natural key for the
        # test-group editor because the test group may contain only 1-2 contacts.
        wa_defaults = {}
        for item in current_mappings:
            wa_id = str(item.get("wa_id") or "").strip()
            if not wa_id:
                continue
            entry = wa_defaults.setdefault(
                wa_id,
                {
                    "persoon": "",
                    "rol": "speler",
                    "production": False,
                    "test": False,
                },
            )
            person = str(item.get("persoon") or "").strip()
            if person:
                entry["persoon"] = person
            role = str(item.get("rol") or "").strip()
            if role:
                entry["rol"] = role
            environment = str(item.get("environment") or "").strip().lower()
            if environment == "production":
                entry["production"] = bool(item.get("enabled", True))
            elif environment == "test":
                entry["test"] = bool(item.get("enabled", True))

        wa_labels = {
            str(opt["value"]): str(opt["label"])
            for opt in self._waha_identity_members
        }

        role_options = [
            SelectOptionDict(value="speler", label="⚽ Speler"),
            SelectOptionDict(value="staf", label="👔 Staf"),
            SelectOptionDict(value="uitsluiten", label="🚫 Uitsluiten"),
        ]

        if is_test_group:
            # TEST: one row per actual WhatsApp member.  This avoids presenting
            # the complete HA roster when the test group contains only 1-2
            # people.  A contact can be explicitly excluded without mapping it.
            rows = [
                ("wa", wa_id)
                for wa_id in sorted(
                    wa_labels,
                    key=lambda value: wa_labels[value].casefold(),
                )
            ]
            if not rows and not current_mappings:
                return self.async_abort(reason="no_whatsapp_members")

            ha_people = list(dict.fromkeys(squad + staff))
            person_options = [
                SelectOptionDict(value="__exclude__", label="🚫 Uitsluiten / geen HA-persoon")
            ] + [
                SelectOptionDict(
                    value=name,
                    label=f"⚽ {name}" if name in squad else f"👔 {name}",
                )
                for name in ha_people
            ]
            wa_options = list(self._waha_identity_members)

            if user_input is not None:
                new_current_mappings = []

                for row_idx, (_, wa_id) in enumerate(rows):
                    display_name = (
                        wa_labels.get(wa_id, wa_id)
                        .split(" — ", 1)[0].strip() or wa_id
                    )
                    suffix = row_idx + 1
                    person = str(
                        user_input.get(
                            f"HA-naam — {display_name} [{suffix}]", ""
                        ) or ""
                    ).strip()
                    role = str(
                        user_input.get(
                            f"Type — {display_name} [{suffix}]", "speler"
                        ) or "speler"
                    ).strip() or "speler"

                    def _form_bool(key):
                        value = user_input.get(key, False)
                        if isinstance(value, str):
                            return value.strip().casefold() in {
                                "1", "true", "yes", "on", "aan"
                            }
                        return bool(value)

                    test = _form_bool(f"Test — {display_name} [{suffix}]")

                    if person == "__exclude__":
                        person = ""

                    if not test:
                        continue

                    if not person:
                        continue

                    base_item = {
                        "team_id": self._team_id,
                        "group_id": self._waha_identity_group_id,
                        "group_name": group_name,
                        "wa_id": wa_id,
                        "whatsapp_name": display_name,
                        "persoon": person,
                        "rol": role,
                        "enabled": True,
                        "environment": "test",
                    }
                    new_current_mappings.append(base_item)

                mappings = [
                    item for item in mappings
                    if not (
                        str(item.get("team_id")) == str(self._team_id)
                        and str(item.get("group_id")) == str(
                            self._waha_identity_group_id
                        )
                    )
                ]
                mappings.extend(new_current_mappings)

                new_waha = dict(current_waha)
                new_waha[CONF_WAHA_IDENTITY_MAPPINGS] = mappings
                new_options = dict(self.config_entry.options)
                new_options[CONF_WAHA_MANAGEMENT] = new_waha
                return self.async_create_entry(title="", data=new_options)

            schema = {}
            for row_idx, (_, wa_id) in enumerate(rows):
                display_name = (
                    wa_labels.get(wa_id, wa_id)
                    .split(" — ", 1)[0].strip() or wa_id
                )
                default = wa_defaults.get(wa_id, {})
                default_person = str(default.get("persoon") or "__exclude__")
                default_role = str(default.get("rol") or "speler")
                default_test = bool(default.get("test", False))
                suffix = row_idx + 1

                schema[vol.Required(
                    f"HA-naam — {display_name} [{suffix}]",
                    default=default_person,
                )] = SelectSelector(
                    SelectSelectorConfig(
                        options=person_options,
                        multiple=False,
                        mode="dropdown",
                    )
                )
                schema[vol.Required(
                    f"WhatsApp-naam — {display_name} [{suffix}]",
                    default=wa_id,
                )] = SelectSelector(
                    SelectSelectorConfig(
                        options=wa_options,
                        multiple=False,
                        mode="dropdown",
                    )
                )
                schema[vol.Required(
                    f"Type — {display_name} [{suffix}]",
                    default=default_role,
                )] = SelectSelector(
                    SelectSelectorConfig(
                        options=role_options,
                        multiple=False,
                        mode="dropdown",
                    )
                )
                schema[vol.Required(
                    f"Test — {display_name} [{suffix}]",
                    default=default_test,
                )] = bool

            return self.async_show_form(
                step_id="whatsapp_identity_mapping",
                data_schema=vol.Schema(schema),
                description_placeholders={
                    "team": team_data.team.name,
                    "group": group_name,
                    "environment": "Test",
                    "members": (
                        f"HA: {len(ha_people)} | WhatsApp: "
                        f"{len(self._waha_identity_members)} | "
                        f"Testmappings: {sum(1 for x in current_mappings if str(x.get('environment')) == 'test')}"
                    ),
                    "ha_count": str(len(ha_people)),
                    "wa_count": str(len(self._waha_identity_members)),
                    "linked_count": str(sum(
                        1 for x in current_mappings
                        if str(x.get("environment")) == "test"
                        and str(x.get("persoon") or "").strip()
                    )),
                    "unlinked_count": str(max(
                        0,
                        len(self._waha_identity_members) - len(current_mappings),
                    )),
                },
            )

        # PRODUCTION: retain the full-roster editor and existing behaviour.
        person_defaults = {}
        for item in current_mappings:
            person = str(item.get("persoon") or "").strip()
            if not person:
                continue
            entry = person_defaults.setdefault(
                person,
                {
                    "wa_id": "",
                    "rol": str(item.get("rol") or "speler"),
                    "production": False,
                    "test": False,
                },
            )
            if item.get("wa_id"):
                entry["wa_id"] = str(item["wa_id"])
            role = str(item.get("rol") or "").strip()
            if role:
                entry["rol"] = role
            environment = str(item.get("environment") or "").strip().lower()
            if environment == "production":
                entry["production"] = bool(item.get("enabled", True))
            elif environment == "test":
                entry["test"] = bool(item.get("enabled", True))

        people = list(dict.fromkeys(
            squad + staff + [p for p in person_defaults if p]
        ))
        if not people and not self._waha_identity_members:
            return self.async_abort(reason="no_team_people")

        mapped_wa_ids = {
            str(item.get("wa_id"))
            for item in current_mappings
            if item.get("wa_id")
            and str(item.get("rol") or "") != "uitsluiten"
            and str(item.get("persoon") or "").strip()
        }

        rows = [("ha", person) for person in people]
        rows.extend(
            ("wa", wa_id)
            for wa_id in sorted(
                wa_labels,
                key=lambda value: wa_labels[value].casefold(),
            )
            if wa_id not in mapped_wa_ids
        )

        wa_options = [
            SelectOptionDict(value="", label="— Niet gekoppeld —")
        ] + list(self._waha_identity_members)

        ha_count = len(people)
        wa_count = len(self._waha_identity_members)
        linked_people = sum(
            1
            for person in people
            if person_defaults.get(person, {}).get("wa_id") in wa_labels
        )
        unlinked_count = max(0, ha_count - linked_people)

        if user_input is not None:
            new_current_mappings = []

            for row_idx, (row_type, row_value) in enumerate(rows):
                display_name = (
                    row_value
                    if row_type == "ha"
                    else wa_labels.get(row_value, row_value)
                    .split(" — ", 1)[0].strip() or row_value
                )
                suffix = row_idx + 1
                person = str(
                    user_input.get(
                        f"HA-naam — {display_name} [{suffix}]", ""
                    ) or ""
                ).strip()
                wa_id = str(
                    user_input.get(
                        f"WhatsApp-naam — {display_name} [{suffix}]", ""
                    ) or ""
                ).strip()
                role = str(
                    user_input.get(
                        f"Type — {display_name} [{suffix}]", "speler"
                    ) or "speler"
                ).strip() or "speler"

                def _form_bool(key):
                    value = user_input.get(key, False)
                    if isinstance(value, str):
                        return value.strip().casefold() in {
                            "1", "true", "yes", "on", "aan"
                        }
                    return bool(value)

                production = _form_bool(
                    f"Productie — {display_name} [{suffix}]"
                )
                test = _form_bool(f"Test — {display_name} [{suffix}]")

                if person in ("", "__exclude__"):
                    person = ""

                if not wa_id:
                    continue

                if role != "uitsluiten" and not person:
                    continue

                whatsapp_name = wa_labels.get(
                    wa_id, wa_id
                ).split(" — ", 1)[0].strip()
                base_item = {
                    "team_id": self._team_id,
                    "group_id": self._waha_identity_group_id,
                    "group_name": group_name,
                    "wa_id": wa_id,
                    "whatsapp_name": whatsapp_name,
                    "persoon": person,
                    "rol": role,
                    "enabled": True,
                }

                if production:
                    item = dict(base_item)
                    item["environment"] = "production"
                    new_current_mappings.append(item)
                if test:
                    item = dict(base_item)
                    item["environment"] = "test"
                    new_current_mappings.append(item)

            mappings = [
                item for item in mappings
                if not (
                    str(item.get("team_id")) == str(self._team_id)
                    and str(item.get("group_id")) == str(
                        self._waha_identity_group_id
                    )
                )
            ]
            mappings.extend(new_current_mappings)

            new_waha = dict(current_waha)
            new_waha[CONF_WAHA_IDENTITY_MAPPINGS] = mappings
            new_options = dict(self.config_entry.options)
            new_options[CONF_WAHA_MANAGEMENT] = new_waha
            return self.async_create_entry(title="", data=new_options)

        schema = {}
        person_options = [
            SelectOptionDict(
                value="__exclude__",
                label="🚫 Uitsluiten / geen HA-persoon",
            )
        ] + [
            SelectOptionDict(
                value=name,
                label=f"⚽ {name}" if name in squad else f"👔 {name}",
            )
            for name in people
        ]

        for row_idx, (row_type, row_value) in enumerate(rows):
            if row_type == "ha":
                display_name = row_value
                default = person_defaults.get(row_value, {})
                default_person = row_value
                default_wa = str(default.get("wa_id") or "")
                default_role = str(
                    default.get("rol")
                    or ("staf" if row_value in staff else "speler")
                )
                default_production = bool(default.get("production", False))
                default_test = bool(default.get("test", False))
            else:
                display_name = (
                    wa_labels.get(row_value, row_value)
                    .split(" — ", 1)[0].strip() or row_value
                )
                default_person = "__exclude__"
                default_wa = row_value
                default_role = "uitsluiten"
                default_production = False
                default_test = False

            suffix = row_idx + 1
            schema[vol.Required(
                f"HA-naam — {display_name} [{suffix}]",
                default=default_person,
            )] = SelectSelector(
                SelectSelectorConfig(
                    options=person_options,
                    multiple=False,
                    mode="dropdown",
                )
            )
            schema[vol.Required(
                f"WhatsApp-naam — {display_name} [{suffix}]",
                default=default_wa,
            )] = SelectSelector(
                SelectSelectorConfig(
                    options=wa_options,
                    multiple=False,
                    mode="dropdown",
                )
            )
            schema[vol.Required(
                f"Type — {display_name} [{suffix}]",
                default=default_role,
            )] = SelectSelector(
                SelectSelectorConfig(
                    options=role_options,
                    multiple=False,
                    mode="dropdown",
                )
            )
            schema[vol.Required(
                f"Productie — {display_name} [{suffix}]",
                default=default_production,
            )] = bool
            schema[vol.Required(
                f"Test — {display_name} [{suffix}]",
                default=default_test,
            )] = bool

        return self.async_show_form(
            step_id="whatsapp_identity_mapping",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "team": team_data.team.name,
                "group": group_name,
                "environment": "Productie + Test",
                "members": (
                    f"HA: {ha_count} | WhatsApp: {wa_count} | "
                    f"Gekoppeld: {linked_people} | Niet gekoppeld: {unlinked_count}"
                ),
                "ha_count": str(ha_count),
                "wa_count": str(wa_count),
                "linked_count": str(linked_people),
                "unlinked_count": str(unlinked_count),
            },
        )

    async def async_step_whatsapp_connection(self, user_input=None):
        """Configure and validate shared WAHA connection settings."""
        current = dict(self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
        errors = {}
        default_base = str(current.get(CONF_WAHA_BASE_URL) or "http://local-waha.local.hass.io:3000")
        default_key = str(current.get(CONF_WAHA_API_KEY) or "")
        default_callback = str(current.get(CONF_WAHA_WEBHOOK_BASE_URL) or "http://homeassistant:8123")
        default_local = bool(current.get(CONF_WAHA_WEBHOOK_LOCAL_ONLY, True))

        if user_input is not None:
            base_url = str(user_input[CONF_WAHA_BASE_URL]).strip().rstrip("/")
            api_key = str(user_input[CONF_WAHA_API_KEY]).strip()
            callback = str(user_input[CONF_WAHA_WEBHOOK_BASE_URL]).strip().rstrip("/")
            local_only = bool(user_input.get(CONF_WAHA_WEBHOOK_LOCAL_ONLY, True))
            if not base_url.startswith(("http://", "https://")):
                errors["base"] = "invalid_waha_url"
            elif not api_key:
                errors["base"] = "missing_waha_api_key"
            elif not callback.startswith(("http://", "https://")):
                errors["base"] = "invalid_webhook_url"
            else:
                client = WahaClient(async_get_clientsession(self.hass), base_url, api_key)
                try:
                    sessions = await client.sessions()
                except Exception:
                    errors["base"] = "cannot_connect_waha"
                else:
                    if not isinstance(sessions, list) or not sessions:
                        errors["base"] = "no_waha_sessions"
                    else:
                        self._waha_temp = {
                            CONF_WAHA_BASE_URL: base_url,
                            CONF_WAHA_API_KEY: api_key,
                            CONF_WAHA_WEBHOOK_BASE_URL: callback,
                            CONF_WAHA_WEBHOOK_LOCAL_ONLY: local_only,
                        }
                        self._waha_sessions = sessions
                        return await self.async_step_whatsapp_session()

        return self.async_show_form(
            step_id="whatsapp_connection",
            data_schema=vol.Schema({
                vol.Required(CONF_WAHA_BASE_URL, default=default_base): str,
                vol.Required(CONF_WAHA_API_KEY, default=default_key): TextSelector(
                    TextSelectorConfig(type="password")
                ),
                vol.Required(CONF_WAHA_WEBHOOK_BASE_URL, default=default_callback): str,
                vol.Optional(CONF_WAHA_WEBHOOK_LOCAL_ONLY, default=default_local): bool,
            }),
            errors=errors,
            description_placeholders={
                "info": "De verbinding wordt eerst getest. Er wordt nog geen WhatsApp-bericht verstuurd."
            },
        )

    async def async_step_whatsapp_session(self, user_input=None):
        """Select active WAHA session and then fetch WhatsApp groups."""
        current = dict(self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
        session_options = []
        for item in self._waha_sessions:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            label = f"{item['name']} — {item.get('status', 'onbekend')}"
            session_options.append(SelectOptionDict(value=str(item["name"]), label=label))
        if not session_options:
            return self.async_abort(reason="no_waha_sessions")

        values = {str(opt["value"]) for opt in session_options}
        suggested = str(current.get(CONF_WAHA_SESSION) or "")
        if suggested not in values:
            suggested = str(session_options[0]["value"])

        if user_input is not None:
            session_name = str(user_input[CONF_WAHA_SESSION])
            self._waha_temp[CONF_WAHA_SESSION] = session_name
            client = WahaClient(
                async_get_clientsession(self.hass),
                self._waha_temp[CONF_WAHA_BASE_URL],
                self._waha_temp[CONF_WAHA_API_KEY],
                session_name,
            )
            try:
                groups = await client.groups()
            except Exception:
                return self.async_show_form(
                    step_id="whatsapp_session",
                    data_schema=vol.Schema({
                        vol.Required(CONF_WAHA_SESSION, default=session_name): SelectSelector(
                            SelectSelectorConfig(options=session_options, multiple=False, mode="dropdown")
                        )
                    }),
                    errors={"base": "cannot_load_waha_groups"},
                )
            self._waha_groups = groups if isinstance(groups, list) else []
            # Persist the validated shared connection immediately. A later group selection
            # can never silently replace these settings.
            new_waha = dict(current)
            new_waha.update(self._waha_temp)
            new_options = dict(self.config_entry.options)
            new_options[CONF_WAHA_MANAGEMENT] = new_waha
            self._pending_waha_options = new_options
            return await self.async_step_whatsapp_team()

        return self.async_show_form(
            step_id="whatsapp_session",
            data_schema=vol.Schema({
                vol.Required(CONF_WAHA_SESSION, default=suggested): SelectSelector(
                    SelectSelectorConfig(options=session_options, multiple=False, mode="dropdown")
                )
            }),
        )

    async def async_step_whatsapp_load_groups(self, user_input=None):
        """Refresh groups using the already stored WAHA connection."""
        current = dict(self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
        base_url = str(current.get(CONF_WAHA_BASE_URL) or "").strip()
        api_key = str(current.get(CONF_WAHA_API_KEY) or "").strip()
        session_name = str(current.get(CONF_WAHA_SESSION) or "default").strip() or "default"
        if not base_url or not api_key:
            return await self.async_step_whatsapp_connection()
        client = WahaClient(async_get_clientsession(self.hass), base_url, api_key, session_name)
        try:
            groups = await client.groups()
        except Exception:
            return self.async_show_form(
                step_id="whatsapp_load_groups",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_load_waha_groups"},
            )
        self._waha_groups = groups if isinstance(groups, list) else []
        self._waha_temp = {
            CONF_WAHA_BASE_URL: base_url,
            CONF_WAHA_API_KEY: api_key,
            CONF_WAHA_WEBHOOK_BASE_URL: str(current.get(CONF_WAHA_WEBHOOK_BASE_URL) or "http://homeassistant:8123"),
            CONF_WAHA_WEBHOOK_LOCAL_ONLY: bool(current.get(CONF_WAHA_WEBHOOK_LOCAL_ONLY, True)),
            CONF_WAHA_SESSION: session_name,
        }
        self._pending_waha_options = dict(self.config_entry.options)
        return await self.async_step_whatsapp_team()

    def _waha_group_options(self):
        """Return WhatsApp groups with human readable names only."""
        options = []
        for item in self._waha_groups:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "Onbekende groep")
            raw_id = item.get("id")
            if isinstance(raw_id, dict):
                group_id = raw_id.get("_serialized")
            else:
                group_id = raw_id
            if group_id and str(group_id).endswith("@g.us"):
                options.append(SelectOptionDict(value=str(group_id), label=name))
        return sorted(options, key=lambda x: str(x["label"]).casefold())

    async def async_step_whatsapp_team(self, user_input=None):
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._team_id = user_input["whatsapp_team_id"]
            return await self.async_step_whatsapp_groups()
        options = [
            SelectOptionDict(value=item.team.team_id, label=f"{item.team.name} — {item.team.team_id}")
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="whatsapp_team",
            data_schema=vol.Schema({
                vol.Required("whatsapp_team_id"): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=False, mode="dropdown")
                )
            }),
        )

    async def async_step_whatsapp_groups(self, user_input=None):
        """Map one football team to explicit WAHA test and production groups."""
        coordinator = self._coordinator()
        team_data = next(
            (x for x in coordinator.data.teams if x.team.team_id == self._team_id), None
        ) if coordinator else None
        if team_data is None:
            return self.async_abort(reason="team_not_found")
        group_options = self._waha_group_options()
        if not group_options:
            return self.async_abort(reason="no_waha_groups")

        current = dict(self.config_entry.options.get(CONF_WAHA_MANAGEMENT, {}) or {})
        # If the shared settings were just validated, use those pending values.
        pending_options = getattr(self, "_pending_waha_options", None)
        if isinstance(pending_options, dict):
            current = dict(pending_options.get(CONF_WAHA_MANAGEMENT, {}) or current)
        current_team = dict((current.get(CONF_WAHA_TEAMS) or {}).get(self._team_id, {}) or {})
        valid_ids = {str(opt["value"]) for opt in group_options}
        label_by_id = {str(opt["value"]): str(opt["label"]) for opt in group_options}

        placeholder = SelectOptionDict(value="__choose_group__", label="— Kies een WhatsApp-groep —")
        selector_options = [placeholder, *group_options]
        errors = {}

        if user_input is not None:
            test_id = str(user_input[CONF_WAHA_TEST_GROUP_ID])
            prod_id = str(user_input[CONF_WAHA_PROD_GROUP_ID])
            if test_id not in valid_ids or prod_id not in valid_ids:
                errors["base"] = "choose_waha_groups"
            elif test_id == prod_id:
                errors["base"] = "waha_groups_must_differ"
            else:
                poll_days = int(user_input[CONF_WAHA_POLL_DAYS_BEFORE])
                reminder_days = int(user_input[CONF_WAHA_REMINDER_DAYS_BEFORE])
                poll_time = str(user_input[CONF_WAHA_POLL_TIME]).strip()
                reminder_time = str(user_input[CONF_WAHA_REMINDER_TIME]).strip()
                matchday_time = str(user_input[CONF_MATCHDAY_MESSAGE_TIME]).strip()
                time_re = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
                if not time_re.fullmatch(poll_time) or not time_re.fullmatch(reminder_time) or not time_re.fullmatch(matchday_time):
                    errors["base"] = "invalid_poll_time"
                elif poll_days < 0 or poll_days > 14 or reminder_days < 0 or reminder_days > 14:
                    errors["base"] = "invalid_poll_days"
                elif reminder_days > poll_days:
                    errors["base"] = "reminder_before_poll"
                elif reminder_days == poll_days and reminder_time <= poll_time:
                    errors["base"] = "reminder_before_poll"
                else:
                    teams_cfg = dict(current.get(CONF_WAHA_TEAMS, {}) or {})
                    updated_team = dict(current_team)
                    updated_team.update({
                        CONF_WAHA_TEST_GROUP_ID: test_id,
                        CONF_WAHA_TEST_GROUP_NAME: label_by_id.get(test_id, test_id),
                        CONF_WAHA_PROD_GROUP_ID: prod_id,
                        CONF_WAHA_PROD_GROUP_NAME: label_by_id.get(prod_id, prod_id),
                        CONF_WAHA_ASSISTANT_NAME: str(user_input.get(CONF_WAHA_ASSISTANT_NAME, "De AI-Stafchef") or "De AI-Stafchef").strip() or "De AI-Stafchef",
                        CONF_WAHA_ATTENDANCE_MODE: str(user_input.get(CONF_WAHA_ATTENDANCE_MODE, DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE),
                        CONF_WAHA_POLL_DAYS_BEFORE: poll_days,
                        CONF_WAHA_POLL_TIME: poll_time,
                        CONF_WAHA_REMINDER_DAYS_BEFORE: reminder_days,
                        CONF_WAHA_REMINDER_TIME: reminder_time,
                        CONF_WAHA_PRODUCTION_ENABLED: bool(user_input.get(CONF_WAHA_PRODUCTION_ENABLED, True)),
                        CONF_MATCHDAY_MESSAGE_ENABLED: bool(user_input.get(CONF_MATCHDAY_MESSAGE_ENABLED, True)),
                        CONF_MATCHDAY_MESSAGE_TIME: matchday_time,
                        CONF_MATCHDAY_WEATHER_ENABLED: bool(user_input.get(CONF_MATCHDAY_WEATHER_ENABLED, True)),
                        CONF_MATCHDAY_COACH_ENABLED: bool(user_input.get(CONF_MATCHDAY_COACH_ENABLED, False)),
                    })
                    teams_cfg[self._team_id] = updated_team
                    new_waha = dict(current)
                    new_waha.update(self._waha_temp)
                    new_waha[CONF_WAHA_TEAMS] = teams_cfg
                    new_options = dict(self.config_entry.options)
                    new_options[CONF_WAHA_MANAGEMENT] = new_waha
                    return self.async_create_entry(title="", data=new_options)

            if not errors:
                # All successful branches return above. This guard only keeps the form open
                # if validation was extended in a future release.
                errors["base"] = "invalid_poll_planning"

            # Keep the current options unchanged when validation fails.
            new_waha = None

        default_test = str(current_team.get(CONF_WAHA_TEST_GROUP_ID) or "")
        if default_test not in valid_ids:
            default_test = "__choose_group__"
        default_prod = str(current_team.get(CONF_WAHA_PROD_GROUP_ID) or "")
        default_assistant_name = str(current_team.get(CONF_WAHA_ASSISTANT_NAME) or "De AI-Stafchef").strip() or "De AI-Stafchef"
        default_attendance_mode = str(current_team.get(CONF_WAHA_ATTENDANCE_MODE, DEFAULT_WAHA_ATTENDANCE_MODE) or DEFAULT_WAHA_ATTENDANCE_MODE)
        if default_prod not in valid_ids:
            default_prod = "__choose_group__"
        default_poll_days = int(current_team.get(CONF_WAHA_POLL_DAYS_BEFORE, DEFAULT_POLL_DAYS_BEFORE))
        default_poll_time = str(current_team.get(CONF_WAHA_POLL_TIME, DEFAULT_POLL_TIME))
        default_reminder_days = int(current_team.get(CONF_WAHA_REMINDER_DAYS_BEFORE, DEFAULT_REMINDER_DAYS_BEFORE))
        default_reminder_time = str(current_team.get(CONF_WAHA_REMINDER_TIME, DEFAULT_REMINDER_TIME))
        default_production_enabled = bool(current_team.get(CONF_WAHA_PRODUCTION_ENABLED, True))
        default_matchday_enabled = bool(current_team.get(CONF_MATCHDAY_MESSAGE_ENABLED, True))
        default_matchday_time = str(current_team.get(CONF_MATCHDAY_MESSAGE_TIME, DEFAULT_MATCHDAY_MESSAGE_TIME))
        default_matchday_weather = bool(current_team.get(CONF_MATCHDAY_WEATHER_ENABLED, True))
        default_matchday_coach = bool(current_team.get(CONF_MATCHDAY_COACH_ENABLED, False))

        return self.async_show_form(
            step_id="whatsapp_groups",
            data_schema=vol.Schema({
                vol.Required(CONF_WAHA_TEST_GROUP_ID, default=default_test): SelectSelector(
                    SelectSelectorConfig(options=selector_options, multiple=False, mode="dropdown")
                ),
                vol.Required(CONF_WAHA_PROD_GROUP_ID, default=default_prod): SelectSelector(
                    SelectSelectorConfig(options=selector_options, multiple=False, mode="dropdown")
                ),
                vol.Required(CONF_WAHA_ASSISTANT_NAME, default=default_assistant_name): str,
                vol.Required(CONF_WAHA_ATTENDANCE_MODE, default=default_attendance_mode): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=WAHA_ATTENDANCE_MODE_POLLS, label="📊 Berichten + polls"),
                            SelectOptionDict(value=WAHA_ATTENDANCE_MODE_MESSAGES, label="💬 Alleen berichten (geen polls)"),
                        ], multiple=False, mode="dropdown"
                    )
                ),
                vol.Required(CONF_WAHA_POLL_DAYS_BEFORE, default=default_poll_days): vol.All(vol.Coerce(int), vol.Range(min=0, max=14)),
                vol.Required(CONF_WAHA_POLL_TIME, default=default_poll_time): str,
                vol.Required(CONF_WAHA_REMINDER_DAYS_BEFORE, default=default_reminder_days): vol.All(vol.Coerce(int), vol.Range(min=0, max=14)),
                vol.Required(CONF_WAHA_REMINDER_TIME, default=default_reminder_time): str,
                vol.Required(CONF_WAHA_PRODUCTION_ENABLED, default=default_production_enabled): bool,
                vol.Required(CONF_MATCHDAY_MESSAGE_ENABLED, default=default_matchday_enabled): bool,
                vol.Required(CONF_MATCHDAY_MESSAGE_TIME, default=default_matchday_time): str,
                vol.Required(CONF_MATCHDAY_WEATHER_ENABLED, default=default_matchday_weather): bool,
                vol.Required(CONF_MATCHDAY_COACH_ENABLED, default=default_matchday_coach): bool,
            }),
            errors=errors,
            description_placeholders={"team": team_data.team.name},
        )

    async def async_step_route(self, user_input=None):
        """Configure the shared openrouteservice API key and choose a team."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            new_options = dict(self.config_entry.options)
            new_options[CONF_ROUTE_API_KEY] = user_input.get(
                CONF_ROUTE_API_KEY, ""
            ).strip()
            self._route_options = new_options
            self._team_id = user_input["route_team_id"]
            return await self.async_step_route_team()

        options = [
            SelectOptionDict(
                value=item.team.team_id,
                label=f"{item.team.name} — {item.team.team_id}",
            )
            for item in coordinator.data.teams
        ]
        return self.async_show_form(
            step_id="route",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ROUTE_API_KEY,
                    description={
                        "suggested_value": self.config_entry.options.get(
                            CONF_ROUTE_API_KEY, ""
                        )
                    },
                ): str,
                vol.Required("route_team_id"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        mode="dropdown",
                    )
                ),
            }),
        )

    async def async_step_route_team(self, user_input=None):
        """Configure the departure point for one team."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        team_data = next(
            (
                item for item in coordinator.data.teams
                if item.team.team_id == self._team_id
            ),
            None,
        )
        if team_data is None:
            return self.async_abort(reason="team_not_found")

        home_match = next(
            (
                match for match in team_data.matches
                if match.is_home is True
                and match.latitude is not None
                and match.longitude is not None
            ),
            None,
        )
        home_name = (
            home_match.accommodation
            if home_match and home_match.accommodation
            else f"Thuisaccommodatie {team_data.team.name}"
        )
        home_lat = home_match.latitude if home_match else None
        home_lon = home_match.longitude if home_match else None

        all_origins = dict(
            self.config_entry.options.get(CONF_ROUTE_TEAM_ORIGINS, {})
        )
        current = dict(all_origins.get(self._team_id, {}))
        current_mode = current.get(CONF_ROUTE_ORIGIN_MODE, ROUTE_ORIGIN_CLUB)

        if user_input is not None:
            mode = user_input[CONF_ROUTE_ORIGIN_MODE]
            if mode == ROUTE_ORIGIN_CUSTOM:
                name = user_input.get(CONF_ROUTE_ORIGIN_NAME, "").strip()
                lat = float(user_input[CONF_ROUTE_ORIGIN_LATITUDE])
                lon = float(user_input[CONF_ROUTE_ORIGIN_LONGITUDE])
                all_origins[self._team_id] = {
                    CONF_ROUTE_ORIGIN_MODE: ROUTE_ORIGIN_CUSTOM,
                    CONF_ROUTE_ORIGIN_NAME: name or "Eigen vertrekpunt",
                    CONF_ROUTE_ORIGIN_LATITUDE: lat,
                    CONF_ROUTE_ORIGIN_LONGITUDE: lon,
                }
            else:
                # Store only the mode. Actual club coordinates remain dynamic
                # and are rediscovered from Voetbal.nl on every refresh.
                all_origins[self._team_id] = {
                    CONF_ROUTE_ORIGIN_MODE: ROUTE_ORIGIN_CLUB,
                }

            new_options = dict(
                getattr(self, "_route_options", self.config_entry.options)
            )
            new_options[CONF_ROUTE_TEAM_ORIGINS] = all_origins
            return self.async_create_entry(title="", data=new_options)

        mode_options = [
            SelectOptionDict(
                value=ROUTE_ORIGIN_CLUB,
                label=f"Thuisaccommodatie — {home_name}",
            ),
            SelectOptionDict(
                value=ROUTE_ORIGIN_CUSTOM,
                label="Eigen vertrekpunt",
            ),
        ]

        schema = {
            vol.Required(
                CONF_ROUTE_ORIGIN_MODE,
                description={"suggested_value": current_mode},
            ): SelectSelector(
                SelectSelectorConfig(
                    options=mode_options,
                    multiple=False,
                    mode="dropdown",
                )
            ),
            vol.Optional(
                CONF_ROUTE_ORIGIN_NAME,
                description={
                    "suggested_value": current.get(
                        CONF_ROUTE_ORIGIN_NAME, ""
                    )
                },
            ): str,
            vol.Optional(
                CONF_ROUTE_ORIGIN_LATITUDE,
                description={
                    "suggested_value": current.get(
                        CONF_ROUTE_ORIGIN_LATITUDE,
                        home_lat if home_lat is not None else self.hass.config.latitude,
                    )
                },
            ): vol.Coerce(float),
            vol.Optional(
                CONF_ROUTE_ORIGIN_LONGITUDE,
                description={
                    "suggested_value": current.get(
                        CONF_ROUTE_ORIGIN_LONGITUDE,
                        home_lon if home_lon is not None else self.hass.config.longitude,
                    )
                },
            ): vol.Coerce(float),
        }

        return self.async_show_form(
            step_id="route_team",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "team": team_data.team.name,
                "home": home_name,
            },
        )

    async def async_step_players(self, user_input=None):
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        team_data = next(
            (item for item in coordinator.data.teams
             if item.team.team_id == self._team_id),
            None,
        )
        if team_data is None:
            return self.async_abort(reason="team_not_found")

        current = dict(self.config_entry.options.get(CONF_PLAYER_MANAGEMENT, {}))
        team_cfg = dict(current.get(self._team_id, {}))
        visible = [player.name for player in team_data.players]
        selected_default = team_cfg.get("selected", visible)
        manual_default = "\n".join(team_cfg.get("manual", []))

        if user_input is not None:
            selected = list(dict.fromkeys(user_input.get("selected_players", [])))
            manual_raw = user_input.get("manual_players", "")
            manual = []
            for line in manual_raw.splitlines():
                name = " ".join(line.split())
                if name and name.casefold() not in {
                    x.casefold() for x in visible + manual
                }:
                    manual.append(name)

            current[self._team_id] = {
                "selected": selected,
                "manual": manual,
            }

            new_options = dict(self.config_entry.options)
            new_options[CONF_PLAYER_MANAGEMENT] = current

            # Correct Home Assistant OptionsFlow completion:
            # return the complete options dict and let HA persist it.
            return self.async_create_entry(
                title="",
                data=new_options,
            )

        player_options = [
            SelectOptionDict(value=name, label=name) for name in visible
        ]
        schema = {
            vol.Optional(
                "selected_players",
                description={"suggested_value": selected_default},
            ): SelectSelector(
                SelectSelectorConfig(
                    options=player_options,
                    multiple=True,
                    mode="dropdown",
                )
            ),
            vol.Optional(
                "manual_players",
                description={"suggested_value": manual_default},
            ): TextSelector(TextSelectorConfig(multiline=True)),
        }
        return self.async_show_form(
            step_id="players",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "team": team_data.team.name,
                "hidden": str(team_data.hidden_players),
            },
        )
