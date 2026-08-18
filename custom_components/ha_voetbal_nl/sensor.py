from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .driving import build_driving_schedule

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SelectedClubSensor(coordinator, entry.entry_id),
        SelectedTeamsSummarySensor(coordinator, entry.entry_id),
    ]

    for team_data in coordinator.data.teams:
        entities.append(
            TeamSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            PlayersSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            ManagedPlayersSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            StaffSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            ProgramSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            NextMatchSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            AttendanceSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            AttendanceControlSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            RoutesSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            DrivingScheduleSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            FlaggingScheduleSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            TrainingScheduleSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            TrainingAttendanceSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            MatchSettingsSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )
        entities.append(
            SeasonOverviewSensor(coordinator, entry.entry_id, team_data.team.team_id)
        )

    async_add_entities(entities)

class BaseTeamEntity(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator)
        self.entry_id = entry_id
        self.team_id = team_id

    @property
    def team_data(self):
        for item in self.coordinator.data.teams:
            if item.team.team_id == self.team_id:
                return item
        return None

class SelectedClubSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "HA Voetbal.nl geselecteerde club"
    _attr_icon = "mdi:shield-outline"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_selected_club"

    @property
    def native_value(self):
        return self.coordinator.data.club.name

    @property
    def extra_state_attributes(self):
        club = self.coordinator.data.club
        return {
            "club_id": club.club_id,
            "plaats": club.city,
        }

class SelectedTeamsSummarySensor(CoordinatorEntity, SensorEntity):
    _attr_name = "HA Voetbal.nl geselecteerde teams"
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_selected_teams"

    @property
    def native_value(self):
        return len(self.coordinator.data.teams)

    @property
    def extra_state_attributes(self):
        return {
            "teams": [
                {
                    "id": item.team.team_id,
                    "naam": item.team.name,
                }
                for item in self.coordinator.data.teams
            ]
        }

class TeamSensor(BaseTeamEntity):
    _attr_icon = "mdi:account-group-outline"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_team"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} team"
            if data
            else f"HA Voetbal.nl {self.team_id} team"
        )

    @property
    def native_value(self):
        data = self.team_data
        return data.team.name if data else None

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        meta = data.metadata
        return {
            "team_id": data.team.team_id,
            "speeldagen": list(meta.days) if meta else [],
            "categorieen": list(meta.categories) if meta else [],
            "competities": list(meta.competitions) if meta else [],
            "subtitles": list(meta.subtitles) if meta else [],
        }

class PlayersSensor(BaseTeamEntity):
    _attr_icon = "mdi:account-multiple"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_players"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} spelers"
            if data
            else f"HA Voetbal.nl {self.team_id} spelers"
        )

    @property
    def native_value(self):
        data = self.team_data
        if not data:
            return None
        return len(data.players) + data.hidden_players

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "zichtbaar": len(data.players),
            "afgeschermd": data.hidden_players,
            "spelers": [player.name for player in data.players],
            "geselecteerd": list(data.selected_players),
            "handmatig": list(data.manual_players),
        }


class ManagedPlayersSensor(BaseTeamEntity):
    """Locally managed squad for automations and later planning."""

    _attr_icon = "mdi:account-edit"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_managed_players"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} spelersbeheer"
            if data else f"HA Voetbal.nl {self.team_id} spelersbeheer"
        )

    @property
    def native_value(self):
        data = self.team_data
        if not data:
            return None
        return len(data.selected_players) + len(data.manual_players)

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        combined = list(dict.fromkeys(
            list(data.selected_players) + list(data.manual_players)
        ))
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "geselecteerd_voetbal_nl": list(data.selected_players),
            "handmatig_toegevoegd": list(data.manual_players),
            "spelers": combined,
            "afgeschermd_voetbal_nl": data.hidden_players,
        }


class StaffSensor(BaseTeamEntity):
    """Staff members for one selected team."""

    _attr_icon = "mdi:account-tie"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_staff"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} staf"
            if data
            else f"HA Voetbal.nl {self.team_id} staf"
        )

    @property
    def native_value(self):
        data = self.team_data
        if not data:
            return None
        return len(data.staff) + data.hidden_staff

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "zichtbaar": len(data.staff),
            "afgeschermd": data.hidden_staff,
            "staf": [member.name for member in data.staff],
        }



def _subtract_minutes(time_value, minutes):
    """Trek minuten af van HH:MM en geef HH:MM terug."""
    if not time_value:
        return None
    try:
        base = datetime.strptime(time_value, "%H:%M")
        return (base - timedelta(minutes=int(minutes))).strftime("%H:%M")
    except (TypeError, ValueError):
        return None


class ProgramSensor(BaseTeamEntity):
    """Compact wedstrijdprogramma for one selected team."""

    _attr_icon = "mdi:calendar-sports"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_programma"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} programma"
            if data else f"HA Voetbal.nl {self.team_id} programma"
        )

    @property
    def native_value(self):
        data = self.team_data
        return len(data.matches) if data else None

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}

        wedstrijden = []
        thuis = 0
        uit = 0
        for match in data.matches:
            if match.is_home is True:
                thuis += 1
            elif match.is_home is False:
                uit += 1
            aanwezig_min = data.match_present_minutes
            reistijd = (
                match.route.reistijd_minuten
                if match.is_home is False else 0
            )
            totaal_vooraf = (
                aanwezig_min + reistijd
                if reistijd is not None else None
            )
            verzameltijd = (
                _subtract_minutes(match.time, totaal_vooraf)
                if totaal_vooraf is not None else None
            )
            try:
                weeknummer = datetime.strptime(
                    match.date_iso, "%Y-%m-%d"
                ).date().isocalendar().week if match.date_iso else None
            except ValueError:
                weeknummer = None

            plan = (
                self.coordinator.driving_plan.status_for_match(data, match)
                if self.coordinator.driving_plan is not None
                else {
                    "vereist": match.is_home is False,
                    "status": "onbekend",
                    "benodigde_autos": data.driving_cars if match.is_home is False else 0,
                    "toegewezen_autos": 0,
                    "chauffeurs": [],
                }
            )
            wedstrijden.append({
                "wedstrijd_id": match.match_id,
                "week": f"W{weeknummer}" if weeknummer else None,
                "weeknummer": weeknummer,
                "datum": match.date_iso,
                "tijd": match.time,
                "thuiswedstrijd": match.is_home,
                "tegenstander": match.opponent,
                "accommodatie": match.accommodation,
                "aanwezig_voor_wedstrijd_minuten": aanwezig_min,
                "reistijd_minuten": reistijd,
                "verzameltijd": verzameltijd,
                "rijschema_verplicht": plan["vereist"],
                "rijschema_status": plan["status"],
                "rijschema_geregeld": (
                    True if plan["status"] == "geregeld"
                    else False if plan["vereist"] else None
                ),
            })

        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "aantal_poulewedstrijden_gevonden": data.program_source_count,
            "aantal_kandidaten_verwerkt": data.program_candidate_count,
            "aantal_wedstrijden": len(wedstrijden),
            "aantal_thuiswedstrijden": thuis,
            "aantal_uitwedstrijden": uit,
            "wedstrijden": wedstrijden,
        }


class NextMatchSensor(BaseTeamEntity):
    """Eerstvolgende nog te spelen wedstrijd van één geselecteerd team."""

    _attr_icon = "mdi:soccer"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_volgende_wedstrijd"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} volgende wedstrijd"
            if data else f"HA Voetbal.nl {self.team_id} volgende wedstrijd"
        )

    def _next_match(self):
        data = self.team_data
        if not data:
            return None

        # De coordinator levert het programma chronologisch. Toch bepalen we
        # expliciet de eerstvolgende wedstrijd, zodat de sensor ook correct
        # blijft als oude wedstrijden nog in data.matches aanwezig zijn.
        now = datetime.now()
        candidates = []
        for match in data.matches:
            if not match.date_iso:
                continue
            try:
                match_dt = datetime.strptime(
                    f"{match.date_iso} {match.time or '23:59'}", "%Y-%m-%d %H:%M"
                )
            except (TypeError, ValueError):
                continue
            if match_dt >= now:
                candidates.append((match_dt, match))

        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    @property
    def native_value(self):
        match = self._next_match()
        if not match:
            return None
        return f"{match.date_iso} {match.time}" if match.time else match.date_iso

    @property
    def extra_state_attributes(self):
        data = self.team_data
        match = self._next_match()
        if not data or not match:
            return {}

        aanwezig_min = data.match_present_minutes
        reistijd = match.route.reistijd_minuten if match.is_home is False else 0
        totaal_vooraf = aanwezig_min + reistijd if reistijd is not None else None
        verzameltijd = (
            _subtract_minutes(match.time, totaal_vooraf)
            if totaal_vooraf is not None else None
        )
        try:
            weeknummer = datetime.strptime(
                match.date_iso, "%Y-%m-%d"
            ).date().isocalendar().week
        except (TypeError, ValueError):
            weeknummer = None

        plan = (
            self.coordinator.driving_plan.status_for_match(data, match)
            if self.coordinator.driving_plan is not None
            else {
                "vereist": match.is_home is False,
                "status": "onbekend",
                "benodigde_autos": data.driving_cars if match.is_home is False else 0,
                "toegewezen_autos": 0,
                "chauffeurs": [],
            }
        )

        if match.is_home is True:
            thuis_uit = "thuis"
            wedstrijd = f"{data.team.name} - {match.opponent}"
        elif match.is_home is False:
            thuis_uit = "uit"
            wedstrijd = f"{match.opponent} - {data.team.name}"
        else:
            thuis_uit = "onbekend"
            wedstrijd = match.opponent

        route = match.route
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "wedstrijd_id": match.match_id,
            "week": f"W{weeknummer}" if weeknummer else None,
            "weeknummer": weeknummer,
            "datum": match.date_iso,
            "tijd": match.time,
            "thuiswedstrijd": match.is_home,
            "thuis_uit": thuis_uit,
            "tegenstander": match.opponent,
            "wedstrijd": wedstrijd,
            "accommodatie": match.accommodation,
            "aanwezig_voor_wedstrijd_minuten": aanwezig_min,
            "reistijd_minuten": reistijd,
            "verzameltijd": verzameltijd,
            "afstand_enkel_km": (
                route.afstand_enkel_km if match.is_home is False else 0
            ),
            "afstand_retour_km": (
                route.afstand_retour_km if match.is_home is False else 0
            ),
            "rijschema_verplicht": plan["vereist"],
            "rijschema_status": plan["status"],
            "rijschema_geregeld": (
                True if plan["status"] == "geregeld"
                else False if plan["vereist"] else None
            ),
            "benodigde_autos": plan.get("benodigde_autos", 0),
            "toegewezen_autos": plan.get("toegewezen_autos", 0),
            "chauffeurs": list(plan.get("chauffeurs", [])),
        }


class AttendanceSensor(BaseTeamEntity):
    """Attendance state derived from the latest WAHA poll for the next match."""

    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_aanwezigheid"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} aanwezigheid"
            if data else f"HA Voetbal.nl {self.team_id} aanwezigheid"
        )

    def _next_match_id(self):
        data = self.team_data
        if not data:
            return None
        now = datetime.now()
        candidates = []
        for match in data.matches:
            if not match.date_iso:
                continue
            try:
                match_dt = datetime.strptime(
                    f"{match.date_iso} {match.time or '23:59'}", "%Y-%m-%d %H:%M"
                )
            except (TypeError, ValueError):
                continue
            if match_dt >= now:
                candidates.append((match_dt, match.match_id))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def _summary(self):
        data = self.team_data
        store = getattr(self.coordinator, "attendance_store", None)
        if not data or store is None:
            return None
        squad = list(dict.fromkeys(
            list(data.selected_players) + list(data.manual_players)
        ))
        staff = list(dict.fromkeys(member.name for member in data.staff))
        return store.summary_for_team(
            data.team.team_id, squad, staff, self._next_match_id()
        )

    @property
    def native_value(self):
        summary = self._summary()
        if not summary or not summary.get("poll_beschikbaar"):
            return "geen_poll"
        return len(summary.get("aanwezig", []))

    @property
    def extra_state_attributes(self):
        data = self.team_data
        summary = self._summary()
        if not data or summary is None:
            return {}
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "poll_beschikbaar": summary.get("poll_beschikbaar", False),
            "poll_id": summary.get("poll_id"),
            "wedstrijd_id": summary.get("wedstrijd_id"),
            "wedstrijd": summary.get("wedstrijd"),
            "datum": summary.get("datum"),
            "tijd": summary.get("tijd"),
            "groep_id": summary.get("groep_id"),
            "groep_naam": summary.get("groep_naam"),
            "testmodus": summary.get("testmodus"),
            "verzonden_op": summary.get("verzonden_op"),
            "poll_status": summary.get("poll_status", "actief"),
            "controle_24u_uitgevoerd": summary.get("controle_24u_uitgevoerd", False),
            "controle_24u_op": summary.get("controle_24u_op"),
            "gesloten": summary.get("gesloten", False),
            "gesloten_op": summary.get("gesloten_op"),
            "aantal_aanwezig": len(summary.get("aanwezig", [])),
            "aantal_afwezig": len(summary.get("afwezig", [])),
            "aantal_geblesseerd": len(summary.get("geblesseerd", [])),
            "aantal_niet_gereageerd": len(summary.get("niet_gereageerd", [])),
            "aanwezig": summary.get("aanwezig", []),
            "afwezig": summary.get("afwezig", []),
            "geblesseerd": summary.get("geblesseerd", []),
            "niet_gereageerd": summary.get("niet_gereageerd", []),
            "aantal_staf_aanwezig": len(summary.get("staf_aanwezig", [])),
            "aantal_staf_afwezig": len(summary.get("staf_afwezig", [])),
            "aantal_staf_geblesseerd": len(summary.get("staf_geblesseerd", [])),
            "aantal_staf_niet_gereageerd": len(summary.get("staf_niet_gereageerd", [])),
            "staf_aanwezig": summary.get("staf_aanwezig", []),
            "staf_afwezig": summary.get("staf_afwezig", []),
            "staf_geblesseerd": summary.get("staf_geblesseerd", []),
            "staf_niet_gereageerd": summary.get("staf_niet_gereageerd", []),
            "onbekende_stemmers": summary.get("onbekende_stemmers", []),
        }


class AttendanceControlSensor(BaseTeamEntity):
    """Read-only control layer: missing votes and immutable driving-plan conflicts."""

    _attr_icon = "mdi:car-alert"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_aanwezigheidscontrole"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} aanwezigheidscontrole"
            if data else f"HA Voetbal.nl {self.team_id} aanwezigheidscontrole"
        )

    def _data(self):
        data = self.team_data
        store = getattr(self.coordinator, "attendance_store", None)
        if not data or store is None:
            return None
        now = datetime.now()
        matches = []
        for match in data.matches:
            if not match.date_iso:
                continue
            try:
                dt = datetime.strptime(
                    f"{match.date_iso} {match.time or '23:59'}", "%Y-%m-%d %H:%M"
                )
            except (TypeError, ValueError):
                continue
            if dt >= now:
                matches.append((dt, match))
        if not matches:
            return None
        _, match = min(matches, key=lambda x: x[0])
        squad = list(dict.fromkeys(list(data.selected_players) + list(data.manual_players)))
        staff = list(dict.fromkeys(member.name for member in data.staff))
        summary = store.summary_for_team(data.team.team_id, squad, staff, match.match_id)
        plan = self.coordinator.driving_plan.status_for_match(data, match) if self.coordinator.driving_plan else {"chauffeurs": []}
        drivers = list(plan.get("chauffeurs", []))
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
            "match": match,
            "summary": summary,
            "chauffeurs": drivers,
            "chauffeurs_zonder_stem": [name for name in drivers if name in missing],
            "chauffeurs_conflict": conflicts,
        }

    @property
    def native_value(self):
        item = self._data()
        if not item or not item["summary"].get("poll_beschikbaar"):
            return "geen_poll"
        if item["summary"].get("gesloten"):
            return "gesloten"
        issues = len(item["chauffeurs_zonder_stem"]) + len(item["chauffeurs_conflict"])
        return "ok" if issues == 0 else f"{issues}_aandachtspunt(en)"

    @property
    def extra_state_attributes(self):
        data = self.team_data
        item = self._data()
        if not data or not item:
            return {}
        summary = item["summary"]
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "wedstrijd_id": summary.get("wedstrijd_id"),
            "wedstrijd": summary.get("wedstrijd"),
            "datum": summary.get("datum"),
            "tijd": summary.get("tijd"),
            "poll_id": summary.get("poll_id"),
            "poll_status": summary.get("poll_status", "actief"),
            "controle_24u_uitgevoerd": summary.get("controle_24u_uitgevoerd", False),
            "chauffeurs": item["chauffeurs"],
            "chauffeurs_zonder_stem": item["chauffeurs_zonder_stem"],
            "chauffeurs_conflict": item["chauffeurs_conflict"],
            "rijschema_aangepast": False,
            "niet_gereageerd": summary.get("niet_gereageerd", []),
            "staf_niet_gereageerd": summary.get("staf_niet_gereageerd", []),
        }



class TrainingAttendanceSensor(BaseTeamEntity):
    """Attendance status for the next concrete training."""
    _attr_icon = "mdi:account-check-outline"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_training_aanwezigheid"

    @property
    def name(self):
        data=self.team_data
        return f"HA Voetbal.nl {data.team.name if data else self.team_id} training aanwezigheid"

    def _item(self):
        data=self.team_data; store=getattr(self.coordinator,"attendance_store",None)
        if not data or store is None: return None,None
        now=datetime.now()
        candidates=[]
        for item in data.training_calendar:
            if item.get("status") != "training": continue
            try: dt=datetime.strptime(f"{item.get('datum')} {item.get('start')}","%d-%m-%Y %H:%M")
            except Exception: continue
            if dt>=now: candidates.append((dt,item))
        if not candidates: return None,None
        _,item=min(candidates,key=lambda x:x[0])
        try: tid="training_"+datetime.strptime(item['datum'],"%d-%m-%Y").strftime("%Y%m%d")+"_"+str(item.get('start') or '0000').replace(':','')
        except Exception: tid=None
        squad=list(dict.fromkeys(list(data.selected_players)+list(data.manual_players)))
        staff=list(dict.fromkeys(m.name for m in data.staff))
        return item,store.summary_for_training(data.team.team_id,tid,squad,staff) if tid else None

    @property
    def native_value(self):
        _,summary=self._item()
        if not summary or not summary.get("poll_beschikbaar"): return "geen_poll"
        return len(summary.get("aanwezig",[]))

    @property
    def extra_state_attributes(self):
        item,summary=self._item(); data=self.team_data
        if not item or not summary or not data: return {}
        return {
            "team_id":data.team.team_id,"team_naam":data.team.name,
            "training_id":summary.get("training_id"),"datum":item.get("datum"),"dag":item.get("dag"),
            "aanwezig_tijd":item.get("verzameltijd"),"starttijd":item.get("start"),"eindtijd":item.get("einde"),"veld":item.get("veld"),
            "poll_beschikbaar":summary.get("poll_beschikbaar",False),"poll_id":summary.get("poll_id"),
            "groep_naam":summary.get("groep_naam"),"testmodus":summary.get("testmodus"),
            "poll_status":summary.get("poll_status","actief"),"gesloten":summary.get("gesloten",False),
            "aantal_aanwezig":len(summary.get("aanwezig",[])),"aantal_afwezig":len(summary.get("afwezig",[])),
            "aantal_geblesseerd":len(summary.get("geblesseerd",[])),"aantal_niet_gereageerd":len(summary.get("niet_gereageerd",[])),
            "aanwezig":summary.get("aanwezig",[]),"afwezig":summary.get("afwezig",[]),"geblesseerd":summary.get("geblesseerd",[]),"niet_gereageerd":summary.get("niet_gereageerd",[]),
            "staf_aanwezig":summary.get("staf_aanwezig",[]),"staf_afwezig":summary.get("staf_afwezig",[]),
            "staf_geblesseerd":summary.get("staf_geblesseerd",[]),"staf_niet_gereageerd":summary.get("staf_niet_gereageerd",[]),
            "onbekende_stemmers":summary.get("onbekende_stemmers",[]),
        }


class TrainingScheduleSensor(BaseTeamEntity):
    """Lokaal ingesteld wekelijks trainingsschema."""

    _attr_icon = "mdi:whistle"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_trainingsschema"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} trainingsschema"
            if data else f"HA Voetbal.nl {self.team_id} trainingsschema"
        )

    @property
    def native_value(self):
        data = self.team_data
        return len(data.training_sessions) if data else None

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        kalender = list(data.training_calendar)
        gepland = sum(1 for item in kalender if item.get("status") == "training")
        vervallen = sum(1 for item in kalender if item.get("status") == "vervallen")
        overrides = sum(
            1
            for item in kalender
            if item.get("reden") == "Toch trainen tijdens schoolvakantie"
        )

        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "seizoen": data.training_season,
            "seizoen_start": data.training_season_start,
            "seizoen_einde": data.training_season_end,
            "aantal_trainingen_per_week": len(data.training_sessions),
            "trainingen": data.training_sessions,
            "schoolvakanties_actief": data.school_holidays_enabled,
            "schoolvakantie_regio": data.school_holiday_region,
            "schoolvakantie_bron": data.school_holiday_source,
            "schoolvakanties": data.school_holidays,
            "toch_trainen_tijdens_schoolvakantie": [
                (
                    datetime.strptime(item["datum"], "%Y-%m-%d").strftime(
                        "%d-%m-%Y"
                    )
                    if item.get("datum")
                    else None
                )
                for item in data.training_exception_dates
                if item.get("datum")
            ],
            "aantal_concrete_trainingsmomenten": len(kalender),
            "aantal_trainingen_doorgaan": gepland,
            "aantal_trainingen_vervallen_vakantie": vervallen,
            "aantal_vakantie_uitzonderingen": overrides,
            "volgende_trainingen": [
                item for item in kalender
                if item.get("status") == "training"
                and item.get("datum")
                and datetime.strptime(item["datum"], "%d-%m-%Y").date()
                    >= datetime.now().date()
            ][:10],
            "volgende_vervallen_trainingen": [
                item for item in kalender
                if item.get("status") == "vervallen"
                and item.get("datum")
                and datetime.strptime(item["datum"], "%d-%m-%Y").date()
                    >= datetime.now().date()
            ][:10],
            "volledige_kalender_intern_beschikbaar": True,
        }


class MatchSettingsSensor(BaseTeamEntity):
    """Wedstrijdinstellingen en verzameltijdbeleid per team."""

    _attr_icon = "mdi:soccer"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_wedstrijdinstellingen"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} wedstrijdinstellingen"
            if data else f"HA Voetbal.nl {self.team_id} wedstrijdinstellingen"
        )

    @property
    def native_value(self):
        data = self.team_data
        return data.match_present_minutes if data else None

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "aanwezig_voor_wedstrijd_minuten": data.match_present_minutes,
            "berekening_thuis": (
                "verzameltijd = wedstrijdtijd - aanwezig_voor_wedstrijd_minuten"
            ),
            "berekening_uit": (
                "verzameltijd = wedstrijdtijd - aanwezig_voor_wedstrijd_minuten "
                "- reistijd_minuten"
            ),
        }


class RoutesSensor(BaseTeamEntity):
    """Compact route summaries for away matches."""

    _attr_icon = "mdi:car-marker"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_routes"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} routes"
            if data else f"HA Voetbal.nl {self.team_id} routes"
        )

    @property
    def native_value(self):
        data = self.team_data
        if not data:
            return None
        return sum(1 for match in data.matches if match.is_home is False)

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}

        routes = []
        for match in data.matches:
            if match.is_home is not False:
                continue
            routes.append({
                "wedstrijd_id": match.match_id,
                "datum": match.date_iso,
                "tijd": match.time,
                "tegenstander": match.opponent,
                "accommodatie": match.accommodation,
                "adres": " ".join(
                    part for part in (match.street, match.postal_city) if part
                ),
                "route_status": match.route.status,
                "route_fout": match.route.fout,
                "vertrek_type": match.route.vertrek_type,
                "vertrek_naam": match.route.vertrek_naam,
                "afstand_enkel_km": match.route.afstand_enkel_km,
                "afstand_retour_km": match.route.afstand_retour_km,
                "reistijd_minuten": match.route.reistijd_minuten,
            })

        vertrek = next(
            (
                {
                    "type": match.route.vertrek_type,
                    "naam": match.route.vertrek_naam,
                    "latitude": match.route.vertrek_latitude,
                    "longitude": match.route.vertrek_longitude,
                }
                for match in data.matches
                if match.is_home is False and match.route.vertrek_naam
            ),
            None,
        )

        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "vertrekpunt": vertrek,
            "aantal_uitwedstrijden": len(routes),
            "aantal_routes_beschikbaar": sum(
                1 for item in routes
                if item["afstand_enkel_km"] is not None
            ),
            "routes": routes,
        }


class DrivingScheduleSensor(BaseTeamEntity):
    _attr_icon = "mdi:car-multiple"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_rijschema"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} rijschema"
            if data else f"HA Voetbal.nl {self.team_id} rijschema"
        )

    @property
    def native_value(self):
        data = self.team_data
        if not data:
            return None
        return sum(1 for m in data.matches if m.is_home is False)

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        plan_store = self.coordinator.driving_plan
        squad = list(dict.fromkeys(
            list(data.selected_players) + list(data.manual_players)
        ))
        excluded = {x.casefold() for x in data.driving_excluded}
        available = [x for x in squad if x.casefold() not in excluded]

        schema = []
        totals = {name: {"ritten": 0, "kilometers": 0.0} for name in available}
        open_count = 0
        incomplete_count = 0

        for match in sorted(
            (m for m in data.matches if m.is_home is False),
            key=lambda m: (m.date_iso or "", m.time or ""),
        ):
            status = plan_store.status_for_match(data, match)
            if status["status"] == "aanvullend_schema_nodig":
                open_count += 1
            elif status["status"] == "niet_compleet":
                incomplete_count += 1
            km = float(match.route.afstand_retour_km or 0.0)
            for name in status["chauffeurs"]:
                if name in totals:
                    totals[name]["ritten"] += 1
                    totals[name]["kilometers"] += km
            try:
                week = datetime.strptime(
                    match.date_iso, "%Y-%m-%d"
                ).date().isocalendar().week if match.date_iso else None
            except ValueError:
                week = None
            schema.append({
                "wedstrijd_id": match.match_id,
                "week": f"W{week}" if week else None,
                "datum": match.date_iso,
                "tijd": match.time,
                "tegenstander": match.opponent,
                "accommodatie": match.accommodation,
                "afstand_retour_km": match.route.afstand_retour_km,
                "reistijd_minuten": match.route.reistijd_minuten,
                "rijschema_status": status["status"],
                "benodigde_autos": status["benodigde_autos"],
                "toegewezen_autos": status["toegewezen_autos"],
                "chauffeurs": status["chauffeurs"],
            })

        verdeling = sorted(
            [
                {
                    "speler": name,
                    "ritten": values["ritten"],
                    "kilometers": round(values["kilometers"], 1),
                }
                for name, values in totals.items()
            ],
            key=lambda x: (x["ritten"], x["kilometers"], x["speler"].casefold()),
        )

        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "autos_per_uitwedstrijd": data.driving_cars,
            "aantal_spelers": len(squad),
            "aantal_beschikbare_chauffeurs": len(available),
            "beschikbare_chauffeurs": available,
            "uitgesloten_chauffeurs": list(data.driving_excluded),
            "aantal_uitwedstrijden": len(schema),
            "aantal_rijschemas_geregeld": sum(
                1 for x in schema if x["rijschema_status"] == "geregeld"
            ),
            "aantal_aanvullend_schema_nodig": open_count,
            "aantal_niet_complete_rijschemas": incomplete_count,
            "schema": schema,
            "verdeling": verdeling,
            "waarschuwingen": [],
        }



class FlaggingScheduleSensor(BaseTeamEntity):
    """Per-team assistant-referee/flagger plan, independent from polls."""
    _attr_icon = "mdi:flag-variant"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_vlagger"

    @property
    def name(self):
        data=self.team_data
        return f"HA Voetbal.nl {data.team.name} vlagger" if data else f"HA Voetbal.nl {self.team_id} vlagger"

    @property
    def native_value(self):
        data=self.team_data
        if not data or not data.flagging_enabled: return 0
        return sum(1 for m in data.matches if self.coordinator.flagging_plan and self.coordinator.flagging_plan.status_for_match(data,m,self.coordinator.driving_plan).get("status")=="geregeld")

    @property
    def extra_state_attributes(self):
        data=self.team_data
        if not data: return {}
        store=self.coordinator.flagging_plan
        rows=[]; warnings=[]
        if store is not None:
            for match in sorted(data.matches,key=lambda m:(m.date_iso or "",m.time or "")):
                st=store.status_for_match(data,match,self.coordinator.driving_plan)
                if st["status"] in {"niet_geregeld","conflict"}: warnings.append({"wedstrijd_id":match.match_id,"status":st["status"],"vlagger":st.get("vlagger","")})
                rows.append({"wedstrijd_id":match.match_id,"datum":match.date_iso,"tijd":match.time,"thuiswedstrijd":match.is_home,"tegenstander":match.opponent,"vlagger":st.get("vlagger",""),"vlagger_status":st.get("status"),"vlaggen_verplicht":st.get("vereist")})
        return {"team_id":data.team.team_id,"team_naam":data.team.name,"vlaggen_ingeschakeld":data.flagging_enabled,"uitgesloten_vlaggers":list(data.flagging_excluded),"extra_vlaggers":list(data.flagging_extra),"aantal_wedstrijden":len(rows),"aantal_vlaggers_geregeld":sum(1 for x in rows if x["vlagger_status"]=="geregeld"),"aantal_vlaggers_niet_geregeld":sum(1 for x in rows if x["vlagger_status"] in {"niet_geregeld","conflict"}),"schema":rows,"waarschuwingen":warnings}


class SeasonOverviewSensor(BaseTeamEntity):
    """Compact PDF/export-ready season overview."""

    _attr_icon = "mdi:file-table-outline"

    def __init__(self, coordinator, entry_id, team_id):
        super().__init__(coordinator, entry_id, team_id)
        self._attr_unique_id = f"{entry_id}_{team_id}_seizoensoverzicht"

    @property
    def name(self):
        data = self.team_data
        return (
            f"HA Voetbal.nl {data.team.name} seizoensoverzicht"
            if data else f"HA Voetbal.nl {self.team_id} seizoensoverzicht"
        )

    @property
    def native_value(self):
        data = self.team_data
        return len(data.matches) if data else None

    @property
    def extra_state_attributes(self):
        data = self.team_data
        if not data:
            return {}
        export = data.season_export_data or {}
        matches = export.get("wedstrijden", [])
        return {
            "team_id": data.team.team_id,
            "team_naam": data.team.name,
            "seizoen": export.get("seizoen"),
            "aantal_wedstrijden": len(matches),
            "aantal_uitwedstrijden": sum(
                1 for x in matches if x.get("thuiswedstrijd") is False
            ),
            "aantal_uitwedstrijden_rijschema_geregeld": sum(
                1 for x in matches
                if x.get("thuiswedstrijd") is False
                and x.get("rijschema", {}).get("status") == "geregeld"
            ),
            "aantal_uitwedstrijden_aanvullend_schema_nodig": sum(
                1 for x in matches
                if x.get("thuiswedstrijd") is False
                and x.get("rijschema", {}).get("status")
                    == "aanvullend_schema_nodig"
            ),
            "rijschema_per_persoon": export.get("rijschema_per_persoon", []),
            "aantal_trainingsmomenten_seizoen": len(
                export.get("trainingskalender", [])
            ),
            "pdf_datamodel_beschikbaar": True,
            "laatste_pdf": export.get("laatste_pdf"),
        }
