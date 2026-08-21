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


def build_season_export(team_data, driving_plan, flagging_plan=None):
    """Canonical season structure for future PDF/export functionality."""
    matches = []
    per_person = {}

    for match in sorted(
        team_data.matches,
        key=lambda m: (m.date_iso or "9999-99-99", m.time or "99:99"),
    ):
        plan = driving_plan.status_for_match(team_data, match)
        flag = (
            flagging_plan.status_for_match(team_data, match, driving_plan)
            if flagging_plan is not None
            else {"vereist": False, "status": "niet_van_toepassing", "vlagger": "", "kandidaten": []}
        )
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
            "vlagger": flag.get("vlagger", ""),
            "vlagger_status": flag.get("status", "niet_van_toepassing"),
            "vlaggen_verplicht": flag.get("vereist", False),
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

    vlagger_per_persoon = {}
    if flagging_plan is not None and getattr(team_data, "flagging_enabled", False):
        # Start with every configured flagger so the PDF also shows people
        # who are configured as available but currently have zero assignments.
        configured_flaggers = []
        seen_flaggers = set()
        for raw in list(getattr(team_data, "flagging_allowed", [])) + list(getattr(team_data, "flagging_extra", [])):
            name = " ".join(str(raw).split())
            key = name.casefold()
            if name and key not in seen_flaggers:
                seen_flaggers.add(key)
                configured_flaggers.append(name)
                vlagger_per_persoon[name] = []

        for row in matches:
            name = str(row.get("vlagger") or "").strip()
            if not name or row.get("vlagger_status") != "geregeld":
                continue
            # Preserve the configured spelling when possible.
            canonical = next((n for n in configured_flaggers if n.casefold() == name.casefold()), name)
            vlagger_per_persoon.setdefault(canonical, []).append({
                "week": row.get("week"),
                "weeknummer": row.get("weeknummer"),
                "datum": row.get("datum"),
                "datum_iso": row.get("datum_iso"),
                "tijd": row.get("tijd"),
                "wedstrijd": row.get("wedstrijd"),
                "tegenstander": row.get("tegenstander"),
                "thuiswedstrijd": row.get("thuiswedstrijd"),
                "tegenstander_logo_url": row.get("tegenstander_logo_url"),
            })

    vlaggers = [
        {"speler": name, "wedstrijden": rows, "aantal_wedstrijden": len(rows)}
        for name, rows in sorted(vlagger_per_persoon.items(), key=lambda item: item[0].casefold())
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

    # Date-specific driver unavailability for the PDF/export. Group entries by
    # date so the document stays compact and also show restrictions entered
    # for home matches (useful as a complete configuration overview).
    match_by_date = {}
    for row in matches:
        if row.get("datum_iso"):
            match_by_date.setdefault(row["datum_iso"], row)

    unavailable_by_date = {}
    for item in list(getattr(team_data, "driving_unavailable_dates", []) or []):
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        date_iso = str(item.get("date") or "").strip()
        if not name or not date_iso:
            continue
        names = unavailable_by_date.setdefault(date_iso, [])
        if name.casefold() not in {x.casefold() for x in names}:
            names.append(name)

    driver_unavailability = []
    for date_iso in sorted(unavailable_by_date):
        match_row = match_by_date.get(date_iso, {})
        week = match_row.get("weeknummer") or _week_number(date_iso)
        driver_unavailability.append({
            "week": f"W{week}" if week is not None else None,
            "weeknummer": week,
            "datum": _display_date(date_iso),
            "datum_iso": date_iso,
            "wedstrijd": match_row.get("wedstrijd") or "-",
            "thuiswedstrijd": match_row.get("thuiswedstrijd"),
            "chauffeurs": unavailable_by_date[date_iso],
        })

    return {
        "team_id": team_data.team.team_id,
        "team_naam": team_data.team.name,
        "team_logo_url": team_logo_url,
        "seizoen": team_data.training_season,
        "wedstrijden": matches,
        "rijschema_per_persoon": people,
        "chauffeurs_niet_beschikbaar": driver_unavailability,
        "vlagger_per_persoon": vlaggers,
        "vlaggen_ingeschakeld": bool(getattr(team_data, "flagging_enabled", False)),
        # Full training calendar intentionally remains internal; this is exactly
        # what the later PDF generator can consume without Home Assistant's
        # 16KB state-attribute limitation.
        "trainingskalender": list(team_data.training_calendar),
    }
