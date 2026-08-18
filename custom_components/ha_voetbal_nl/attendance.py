"""Persistent attendance/poll storage for HA Voetbal.nl."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


class AttendanceStore:
    """Store polls, votes and durable WhatsApp-to-person mappings."""

    def __init__(self, hass, entry_id: str):
        self._store = Store(hass, STORAGE_VERSION, f"ha_voetbal_nl_attendance_{entry_id}")
        self.data = {"polls": {}, "votes": {}, "mappings": {}, "conflict_notices": {}, "messages": {}}

    async def async_load(self):
        loaded = await self._store.async_load()
        if isinstance(loaded, dict):
            self.data.update(loaded)

    async def async_save(self):
        await self._store.async_save(self.data)

    def add_poll(self, poll_id: str, meta: dict):
        self.data.setdefault("polls", {})[poll_id] = dict(meta)

    def poll(self, poll_id: str):
        return self.data.get("polls", {}).get(poll_id)


    def polls_for_match(self, team_id: str, match_id: str, test_mode: bool | None = None):
        """Return polls for a team/match, optionally filtered by test/production mode."""
        items = []
        for poll_id, meta in self.data.get("polls", {}).items():
            if meta.get("team_id") != team_id or meta.get("wedstrijd_id") != match_id:
                continue
            if test_mode is not None and bool(meta.get("testmodus")) != bool(test_mode):
                continue
            items.append((poll_id, meta))
        return sorted(items, key=lambda x: int(x[1].get("verzonden_timestamp") or 0))

    def latest_poll(self, team_id: str, match_id: str, test_mode: bool | None = None):
        items = self.polls_for_match(team_id, match_id, test_mode)
        return items[-1] if items else (None, None)


    def polls_for_training(self, team_id: str, training_id: str, test_mode: bool | None = None):
        """Return polls for one concrete training."""
        items = []
        for poll_id, meta in self.data.get("polls", {}).items():
            if meta.get("team_id") != team_id or meta.get("training_id") != training_id:
                continue
            if test_mode is not None and bool(meta.get("testmodus")) != bool(test_mode):
                continue
            items.append((poll_id, meta))
        return sorted(items, key=lambda x: int(x[1].get("verzonden_timestamp") or 0))

    def latest_training_poll(self, team_id: str, training_id: str, test_mode: bool | None = None):
        items = self.polls_for_training(team_id, training_id, test_mode)
        return items[-1] if items else (None, None)

    def summary_for_training(
        self,
        team_id: str,
        training_id: str,
        squad: list[str],
        staff: list[str] | None = None,
        test_mode: bool = False,
    ):
        """Build attendance summary for one training poll."""
        staff = list(staff or [])
        poll_id, meta = self.latest_training_poll(team_id, training_id, test_mode)
        if not poll_id or not meta:
            return {
                "poll_beschikbaar": False, "poll_id": None, "training_id": training_id,
                "aanwezig": [], "afwezig": [], "geblesseerd": [], "niet_gereageerd": list(squad),
                "staf_aanwezig": [], "staf_afwezig": [], "staf_geblesseerd": [],
                "staf_niet_gereageerd": list(staff), "onbekende_stemmers": [],
            }
        # A poll stores the exact eligible participant set at creation time.
        # This makes production/test matching authoritative for reminders,
        # dashboards and historical summaries alike.
        if isinstance(meta.get("eligible_players"), list):
            squad = list(dict.fromkeys(str(x) for x in meta.get("eligible_players", []) if str(x).strip()))
        if isinstance(meta.get("eligible_staff"), list):
            staff = list(dict.fromkeys(str(x) for x in meta.get("eligible_staff", []) if str(x).strip()))
        player_status = {name: "niet_gereageerd" for name in squad}
        staff_status = {name: "niet_gereageerd" for name in staff}
        unknown = []
        for vote in self.votes_for_poll(poll_id):
            person, role, answer = vote.get("persoon") or vote.get("speler"), vote.get("rol"), vote.get("status")
            if answer not in {"aanwezig", "afwezig", "geblesseerd"}:
                continue
            if role == "speler" and person in player_status:
                player_status[person] = answer
            elif role == "staf" and person in staff_status:
                staff_status[person] = answer
            elif person in player_status:
                player_status[person] = answer
            else:
                unknown.append({"naam": vote.get("contact_naam"), "whatsapp_id": vote.get("wa_id") or vote.get("voter_id"), "keuze": vote.get("keuze")})
        out = dict(meta)
        out.update({
            "poll_beschikbaar": True, "poll_id": poll_id, "training_id": training_id,
            "aanwezig": [n for n,v in player_status.items() if v == "aanwezig"],
            "afwezig": [n for n,v in player_status.items() if v == "afwezig"],
            "geblesseerd": [n for n,v in player_status.items() if v == "geblesseerd"],
            "niet_gereageerd": [n for n,v in player_status.items() if v == "niet_gereageerd"],
            "staf_aanwezig": [n for n,v in staff_status.items() if v == "aanwezig"],
            "staf_afwezig": [n for n,v in staff_status.items() if v == "afwezig"],
            "staf_geblesseerd": [n for n,v in staff_status.items() if v == "geblesseerd"],
            "staf_niet_gereageerd": [n for n,v in staff_status.items() if v == "niet_gereageerd"],
            "onbekende_stemmers": unknown,
        })
        return out

    def update_poll(self, poll_id: str, **changes):
        meta = self.data.setdefault("polls", {}).get(poll_id)
        if not isinstance(meta, dict):
            return False
        meta.update(changes)
        return True

    def message_sent(self, key: str) -> bool:
        return bool(self.data.setdefault("messages", {}).get(key))

    def mark_message_sent(self, key: str, value: str | None = None):
        self.data.setdefault("messages", {})[key] = value or now_iso()

    def conflict_notice_sent(self, poll_id: str, person: str, status: str) -> bool:
        key = f"{poll_id}|{_norm_name(person)}|{status}"
        return bool(self.data.setdefault("conflict_notices", {}).get(key))

    def mark_conflict_notice(self, poll_id: str, person: str, status: str):
        key = f"{poll_id}|{_norm_name(person)}|{status}"
        self.data.setdefault("conflict_notices", {})[key] = now_iso()

    def votes_for_poll(self, poll_id: str):
        return [dict(v) for k, v in self.data.get("votes", {}).items() if k.startswith(f"{poll_id}|")]

    def mapping(self, wa_id: str) -> dict | None:
        item = self.data.get("mappings", {}).get(wa_id)
        return dict(item) if isinstance(item, dict) else None

    def add_mapping(
        self,
        wa_id: str,
        contact_name: str,
        person: str | None,
        role: str | None,
    ):
        """Persist a resolved WhatsApp identity for reuse on later votes."""
        self.data.setdefault("mappings", {})[wa_id] = {
            "contact_naam": contact_name,
            "persoon": person,
            "rol": role,
        }

    def _exact_match(self, contact_name: str, names: list[str]) -> str | None:
        needle = _norm_name(contact_name)
        if not needle:
            return None
        exact = [name for name in names if _norm_name(name) == needle]
        return exact[0] if len(exact) == 1 else None

    @staticmethod
    def _match_words(value: str) -> list[str]:
        """Return normalized name words, ignoring common WhatsApp labels."""
        words = re.findall(r"[a-z0-9]+", (value or "").casefold())
        ignored = {"jvc", "new"}
        return [word for word in words if word not in ignored]

    def _clean_full_match(self, contact_name: str, names: list[str]) -> str | None:
        contact_words = self._match_words(contact_name)
        if not contact_words:
            return None
        needle = "".join(contact_words)
        matches = []
        for name in names:
            candidate = "".join(self._match_words(name))
            if candidate and candidate == needle:
                matches.append(name)
        return matches[0] if len(matches) == 1 else None

    def match_person(
        self, contact_name: str, squad: list[str], staff: list[str]
    ) -> tuple[str | None, str | None]:
        """Safely resolve a WhatsApp contact to one unique player or staff member."""
        # 1. Exact match remains authoritative.
        player = self._exact_match(contact_name, squad)
        staff_member = self._exact_match(contact_name, staff)
        if player and staff_member:
            return None, None
        if player:
            return player, "speler"
        if staff_member:
            return staff_member, "staf"

        # 2. Ignore harmless WhatsApp labels such as JVC and New.
        player = self._clean_full_match(contact_name, squad)
        staff_member = self._clean_full_match(contact_name, staff)
        if player and staff_member:
            return None, None
        if player:
            return player, "speler"
        if staff_member:
            return staff_member, "staf"

        # 3. Unique first-name fallback. Check players and staff together
        # so an ambiguous first name is never guessed.
        words = self._match_words(contact_name)
        if not words:
            return None, None
        first = words[0]
        candidates = []
        for name in squad:
            person_words = self._match_words(name)
            if person_words and person_words[0] == first:
                candidates.append((name, "speler"))
        for name in staff:
            person_words = self._match_words(name)
            if person_words and person_words[0] == first:
                candidates.append((name, "staf"))
        return candidates[0] if len(candidates) == 1 else (None, None)

    def record_vote(self, poll_id: str, voter_id: str, payload: dict):
        key = f"{poll_id}|{voter_id}"
        old = self.data.setdefault("votes", {}).get(key)
        new_ts = int(payload.get("timestamp") or 0)
        old_ts = int((old or {}).get("timestamp") or 0)
        if old and old_ts > new_ts:
            return False
        self.data["votes"][key] = dict(payload)
        return True

    def summary_for_team(
        self,
        team_id: str,
        squad: list[str],
        staff: list[str] | None = None,
        next_match_id: str | None = None,
        test_mode: bool = False,
    ):
        staff = list(staff or [])
        polls = [
            (pid, meta)
            for pid, meta in self.data.get("polls", {}).items()
            if meta.get("team_id") == team_id
            and (next_match_id is None or meta.get("wedstrijd_id") == next_match_id)
            and bool(meta.get("testmodus")) == bool(test_mode)
        ]
        if not polls:
            return {
                "poll_beschikbaar": False,
                "poll_id": None,
                "wedstrijd_id": next_match_id,
                "aanwezig": [],
                "afwezig": [],
                "geblesseerd": [],
                "niet_gereageerd": list(squad),
                "staf_aanwezig": [],
                "staf_afwezig": [],
                "staf_geblesseerd": [],
                "staf_niet_gereageerd": list(staff),
                "onbekende_stemmers": [],
            }

        poll_id, meta = sorted(
            polls, key=lambda x: int(x[1].get("verzonden_timestamp") or 0)
        )[-1]
        # A poll stores the exact eligible participant set at creation time.
        # This makes production/test matching authoritative for reminders,
        # dashboards and historical summaries alike.
        if isinstance(meta.get("eligible_players"), list):
            squad = list(dict.fromkeys(str(x) for x in meta.get("eligible_players", []) if str(x).strip()))
        if isinstance(meta.get("eligible_staff"), list):
            staff = list(dict.fromkeys(str(x) for x in meta.get("eligible_staff", []) if str(x).strip()))
        player_status = {name: "niet_gereageerd" for name in squad}
        staff_status = {name: "niet_gereageerd" for name in staff}
        unknown = []
        for key, vote in self.data.get("votes", {}).items():
            if not key.startswith(f"{poll_id}|"):
                continue
            person = vote.get("persoon") or vote.get("speler")
            role = vote.get("rol")
            answer = vote.get("status")
            if answer not in {"aanwezig", "afwezig", "geblesseerd"}:
                continue
            if role == "speler" and person in player_status:
                player_status[person] = answer
            elif role == "staf" and person in staff_status:
                staff_status[person] = answer
            elif person in player_status:  # backwards compatibility with v0.9.15 votes
                player_status[person] = answer
            elif vote.get("contact_naam") or vote.get("voter_id"):
                unknown.append({
                    "naam": vote.get("contact_naam"),
                    "whatsapp_id": vote.get("wa_id") or vote.get("voter_id"),
                    "keuze": vote.get("keuze"),
                })

        return {
            "poll_beschikbaar": True,
            "poll_id": poll_id,
            "wedstrijd_id": meta.get("wedstrijd_id"),
            "wedstrijd": meta.get("wedstrijd"),
            "datum": meta.get("datum"),
            "tijd": meta.get("tijd"),
            "groep_id": meta.get("groep_id"),
            "groep_naam": meta.get("groep_naam"),
            "testmodus": bool(meta.get("testmodus")),
            "verzonden_op": meta.get("verzonden_op"),
            "poll_status": meta.get("poll_status", "actief"),
            "controle_24u_uitgevoerd": bool(meta.get("controle_24u_uitgevoerd")),
            "controle_24u_op": meta.get("controle_24u_op"),
            "gesloten": bool(meta.get("gesloten")),
            "gesloten_op": meta.get("gesloten_op"),
            "aanwezig": [n for n, v in player_status.items() if v == "aanwezig"],
            "afwezig": [n for n, v in player_status.items() if v == "afwezig"],
            "geblesseerd": [n for n, v in player_status.items() if v == "geblesseerd"],
            "niet_gereageerd": [n for n, v in player_status.items() if v == "niet_gereageerd"],
            "staf_aanwezig": [n for n, v in staff_status.items() if v == "aanwezig"],
            "staf_afwezig": [n for n, v in staff_status.items() if v == "afwezig"],
            "staf_geblesseerd": [n for n, v in staff_status.items() if v == "geblesseerd"],
            "staf_niet_gereageerd": [n for n, v in staff_status.items() if v == "niet_gereageerd"],
            "onbekende_stemmers": unknown,
        }


def now_iso():
    return datetime.now(timezone.utc).isoformat()
