from __future__ import annotations

from datetime import datetime, timedelta


def _week_number(iso_date):
    if not iso_date:
        return None
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d").date()
        return dt.isocalendar().week
    except ValueError:
        return None


def _display_date(iso_date):
    if not iso_date:
        return None
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return iso_date



def _subtract_minutes(time_value, minutes):
    if not time_value or minutes is None:
        return None
    try:
        base = datetime.strptime(str(time_value), "%H:%M")
        return (base - timedelta(minutes=int(minutes))).strftime("%H:%M")
    except (TypeError, ValueError):
        return None


def build_season_export(team_data, driving_plan):
    """Canonical season structure for future PDF/export functionality."""
    matches = []
    per_person = {}

    for match in sorted(
        team_data.matches,
        key=lambda m: (m.date_iso or "9999-99-99", m.time or "99:99"),
    ):
        plan = driving_plan.status_for_match(team_data, match)
        week = _week_number(match.date_iso)
        match_label = f"{match.home_team} - {match.away_team}".strip(" -")
        reistijd = match.route.reistijd_minuten if match.is_home is False else 0
        totaal_vooraf = (team_data.match_present_minutes + reistijd) if reistijd is not None else None
        verzameltijd = _subtract_minutes(match.time, totaal_vooraf)
        row = {
            "week": f"W{week}" if week is not None else None,
            "weeknummer": week,
            "datum": _display_date(match.date_iso),
            "datum_iso": match.date_iso,
            "tijd": match.time,
            "wedstrijd": match_label,
            "thuiswedstrijd": match.is_home,
            "thuisteam": match.home_team,
            "uitteam": match.away_team,
            "thuis_logo_url": match.home_logo_url,
            "uit_logo_url": match.away_logo_url,
            "tegenstander": match.opponent,
            "tegenstander_logo_url": (
                match.away_logo_url if match.is_home is True
                else match.home_logo_url if match.is_home is False
                else None
            ),
            "accommodatie": match.accommodation,
            "aanwezig_voor_wedstrijd_minuten": team_data.match_present_minutes,
            "reistijd_minuten": reistijd,
            "verzameltijd": verzameltijd,
            "afstand_enkel_km": match.route.afstand_enkel_km if match.is_home is False else 0,
            "afstand_retour_km": match.route.afstand_retour_km if match.is_home is False else 0,
            "rijschema": plan,
        }
        matches.append(row)

        if match.is_home is False:
            for person in plan.get("chauffeurs", []):
                per_person.setdefault(person, []).append({
                    "week": row["week"],
                    "weeknummer": week,
                    "datum": row["datum"],
                    "datum_iso": match.date_iso,
                    "wedstrijd": match_label,
                    "tegenstander": match.opponent,
                    "tegenstander_logo_url": row.get("tegenstander_logo_url"),
                    "afstand_enkel_km": match.route.afstand_enkel_km or 0,
                    "afstand_retour_km": match.route.afstand_retour_km or 0,
                })

    people = [
        {
            "speler": name,
            "ritten": rows,
            "aantal_ritten": len(rows),
            "kilometers_enkel": round(sum(float(r.get("afstand_enkel_km") or 0) for r in rows), 1),
            "kilometers_retour": round(sum(float(r.get("afstand_retour_km") or 0) for r in rows), 1),
        }
        for name, rows in sorted(per_person.items(), key=lambda item: item[0].casefold())
    ]

    team_logo_url = team_data.team.logo_url
    if not team_logo_url:
        for match in team_data.matches:
            if match.is_home is True and match.home_logo_url:
                team_logo_url = match.home_logo_url
                break
            if match.is_home is False and match.away_logo_url:
                team_logo_url = match.away_logo_url
                break

    return {
        "team_id": team_data.team.team_id,
        "team_naam": team_data.team.name,
        "team_logo_url": team_logo_url,
        "seizoen": team_data.training_season,
        "wedstrijden": matches,
        "rijschema_per_persoon": people,
        # Full training calendar intentionally remains internal; this is exactly
        # what the later PDF generator can consume without Home Assistant's
        # 16KB state-attribute limitation.
        "trainingskalender": list(team_data.training_calendar),
    }
