from __future__ import annotations

from datetime import datetime
import itertools
from homeassistant.helpers.storage import Store
from .driving import can_drive_on_date

STORAGE_VERSION = 1

class FlaggingPlanStore:
    """Persist one assistant-referee/flagger per match and team."""
    def __init__(self, hass, entry_id):
        self._store = Store(hass, STORAGE_VERSION, f"ha_voetbal_nl.flagging_plan.{entry_id}")
        self._data = {"teams": {}}

    async def async_load(self):
        stored = await self._store.async_load()
        if isinstance(stored, dict): self._data = stored
        self._data.setdefault("teams", {})

    async def async_save(self):
        await self._store.async_save(self._data)

    def team_plan(self, team_id):
        return self._data.setdefault("teams", {}).setdefault(team_id, {"matches": {}, "initialized": False})

    def assignments(self, team_id): return self.team_plan(team_id).setdefault("matches", {})
    def is_initialized(self, team_id): return bool(self.team_plan(team_id).get("initialized"))
    def set_initialized(self, team_id, value=True): self.team_plan(team_id)["initialized"] = bool(value)
    def clear_team(self, team_id): self._data.setdefault("teams", {})[team_id] = {"matches": {}, "initialized": False}
    def set_assignment(self, team_id, match_id, flagger, source="basis"):
        self.assignments(team_id)[match_id] = {"vlagger": flagger or "", "bron": source, "aangemaakt": datetime.now().isoformat(timespec="seconds")}
    def get_assignment(self, team_id, match_id): return self.assignments(team_id).get(match_id)

    def status_for_match(self, team_data, match, driving_plan=None):
        if not getattr(team_data, "flagging_enabled", False):
            return {"vereist": False, "status": "niet_van_toepassing", "vlagger": "", "kandidaten": []}
        assignment = self.get_assignment(team_data.team.team_id, match.match_id)
        candidates = eligible_flaggers(team_data, match, driving_plan)
        if not assignment or not assignment.get("vlagger"):
            return {"vereist": True, "status": "niet_geregeld", "vlagger": "", "kandidaten": candidates}
        name = assignment.get("vlagger", "")
        if name.casefold() not in {x.casefold() for x in candidates}:
            return {"vereist": True, "status": "conflict", "vlagger": name, "kandidaten": candidates}
        return {"vereist": True, "status": "geregeld", "vlagger": name, "kandidaten": candidates}

def _all_people(team_data):
    names = list(team_data.selected_players) + list(team_data.manual_players) + list(getattr(team_data, "flagging_extra", []))
    seen=set(); out=[]
    for raw in names:
        name=" ".join(str(raw).split()); key=name.casefold()
        if name and key not in seen: seen.add(key); out.append(name)
    return out

def eligible_flaggers(team_data, match, driving_plan=None):
    allowed={str(x).strip().casefold() for x in getattr(team_data,"flagging_allowed",[]) if str(x).strip()}
    extra={str(x).strip().casefold() for x in getattr(team_data,"flagging_extra",[]) if str(x).strip()}
    people=[n for n in _all_people(team_data) if n.casefold() in (allowed | extra)]

    # Driving availability is the base eligibility for flagging. A person
    # who is permanently excluded from driving or temporarily unavailable
    # on this match date must never be scheduled as a flagger either.
    people=[
        n for n in people
        if can_drive_on_date(team_data, n, match.date_iso or "")
    ]

    # For away matches, the selected flagger must also be one of the drivers
    # actually assigned to that specific match. Home matches do not require
    # an assigned driver.
    if match.is_home is False and driving_plan is not None:
        drivers=driving_plan.status_for_match(team_data, match).get("chauffeurs",[])
        d={x.casefold() for x in drivers}
        people=[n for n in people if n.casefold() in d]
    return people

def rebuild_flagging_schedule(team_data, driving_plan=None):
    matches=sorted(team_data.matches,key=lambda m:(m.date_iso or "9999-99-99",m.time or "99:99",m.match_id))
    allowed = {x.casefold() for x in getattr(team_data, "flagging_allowed", [])}
    extra = {x.casefold() for x in getattr(team_data, "flagging_extra", [])}
    counts={n:0 for n in _all_people(team_data) if n.casefold() in (allowed | extra)}
    output={}; warnings=[]
    for match in matches:
        candidates=eligible_flaggers(team_data,match,driving_plan)
        if not candidates:
            output[match.match_id]=""; warnings.append(f"{match.date_iso or match.date_text}: geen geschikte vlagger beschikbaar")
            continue
        best=min(candidates,key=lambda n:(counts.get(n,0),n.casefold()))
        output[match.match_id]=best; counts[best]=counts.get(best,0)+1
    return output,warnings
