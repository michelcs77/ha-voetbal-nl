from __future__ import annotations

from datetime import datetime
import itertools

from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1


class DrivingPlanStore:
    """Persist stable driver assignments per team and match."""

    def __init__(self, hass, entry_id):
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"ha_voetbal_nl.driving_plan.{entry_id}",
        )
        self._data = {"teams": {}}

    async def async_load(self):
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._data = stored
        self._data.setdefault("teams", {})

    async def async_save(self):
        await self._store.async_save(self._data)

    def team_plan(self, team_id):
        return self._data.setdefault("teams", {}).setdefault(
            team_id,
            {"matches": {}, "initialized": False},
        )

    def assignments(self, team_id):
        return self.team_plan(team_id).setdefault("matches", {})

    def is_initialized(self, team_id):
        return bool(self.team_plan(team_id).get("initialized"))

    def set_initialized(self, team_id, value=True):
        self.team_plan(team_id)["initialized"] = bool(value)

    def clear_team(self, team_id):
        self._data.setdefault("teams", {})[team_id] = {"matches": {}, "initialized": False}

    def set_assignment(self, team_id, match_id, drivers, cars, source="basis"):
        self.assignments(team_id)[match_id] = {
            "chauffeurs": list(drivers),
            "benodigde_autos": int(cars),
            "bron": source,
            "aangemaakt": datetime.now().isoformat(timespec="seconds"),
        }

    def get_assignment(self, team_id, match_id):
        return self.assignments(team_id).get(match_id)

    def status_for_match(self, team_data, match):
        if match.is_home is not False:
            return {
                "vereist": False,
                "status": "niet_van_toepassing",
                "benodigde_autos": 0,
                "toegewezen_autos": 0,
                "chauffeurs": [],
            }

        needed = max(1, int(team_data.driving_cars or 1))
        assignment = self.get_assignment(team_data.team.team_id, match.match_id)
        if not assignment:
            return {
                "vereist": True,
                "status": "aanvullend_schema_nodig",
                "benodigde_autos": needed,
                "toegewezen_autos": 0,
                "chauffeurs": [],
            }

        excluded = {x.casefold() for x in team_data.driving_excluded}
        eligible_drivers = [
            name for name in assignment.get("chauffeurs", [])
            if name.casefold() not in excluded
        ]
        assigned = len(eligible_drivers)
        status = "geregeld" if assigned >= needed else "niet_compleet"
        return {
            "vereist": True,
            "status": status,
            "benodigde_autos": needed,
            "toegewezen_autos": assigned,
            "chauffeurs": eligible_drivers,
        }


def _squad(team_data):
    seen = set()
    out = []
    excluded = {x.casefold() for x in team_data.driving_excluded}
    for raw in list(team_data.selected_players) + list(team_data.manual_players):
        name = " ".join(str(raw).split())
        key = name.casefold()
        if name and key not in seen and key not in excluded:
            seen.add(key)
            out.append(name)
    return out


def _current_stats(team_data, store):
    names = _squad(team_data)
    stats = {n: {"ritten": 0, "kilometers": 0.0, "laatste": ""} for n in names}
    match_by_id = {m.match_id: m for m in team_data.matches}

    for match_id, item in store.assignments(team_data.team.team_id).items():
        match = match_by_id.get(match_id)
        if not match or match.is_home is not False:
            continue
        km = float(match.route.afstand_retour_km or 0.0)
        for name in item.get("chauffeurs", []):
            if name not in stats:
                continue
            stats[name]["ritten"] += 1
            stats[name]["kilometers"] += km
            stats[name]["laatste"] = match.date_iso or ""
    return names, stats


def _choose_supplemental(team_data, store, matches):
    names, stats = _current_stats(team_data, store)
    cars = max(1, int(team_data.driving_cars or 1))
    output = {}

    for match in sorted(matches, key=lambda m: (m.date_iso or "", m.time or "")):
        needed = min(cars, len(names))
        km = float(match.route.afstand_retour_km or 0.0)
        best = None
        best_score = None
        for combo in itertools.combinations(names, needed):
            projected = []
            for name in names:
                trips = stats[name]["ritten"] + (1 if name in combo else 0)
                kms = stats[name]["kilometers"] + (km if name in combo else 0.0)
                projected.append((name, trips, kms))
            trip_values = [x[1] for x in projected]
            km_values = [x[2] for x in projected]
            trip_spread = max(trip_values) - min(trip_values) if trip_values else 0
            km_spread = max(km_values) - min(km_values) if km_values else 0.0
            repeated = sum(
                1 for name in combo
                if stats[name]["laatste"] == (match.date_iso or "")
            )
            score = (
                trip_spread,
                round(km_spread, 3),
                repeated,
                tuple(x.casefold() for x in combo),
            )
            if best_score is None or score < best_score:
                best_score = score
                best = list(combo)

        drivers = best or names[:needed]
        output[match.match_id] = drivers
        for name in drivers:
            stats[name]["ritten"] += 1
            stats[name]["kilometers"] += km
            stats[name]["laatste"] = match.date_iso or ""
    return output
