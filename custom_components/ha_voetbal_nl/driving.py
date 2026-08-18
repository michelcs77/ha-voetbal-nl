from __future__ import annotations

import math


def _unique_names(names):
    out = []
    seen = set()
    for raw in names:
        name = " ".join(str(raw).split())
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _objective(stats, eligible, min_target, max_target):
    """Lexicographic objective: trip fairness first, then km spread, then variance."""
    trips = [stats[name]["ritten"] for name in eligible]
    kms = [stats[name]["kilometers"] for name in eligible]

    trip_range = max(trips) - min(trips) if trips else 0
    km_range = max(kms) - min(kms) if kms else 0.0
    km_mean = sum(kms) / len(kms) if kms else 0.0
    km_variance = (
        sum((km - km_mean) ** 2 for km in kms) / len(kms)
        if kms else 0.0
    )

    # Hard penalty if we ever exceed the theoretical fair trip bounds.
    bounds_penalty = 0
    for trip_count in trips:
        if trip_count < min_target:
            bounds_penalty += min_target - trip_count
        if trip_count > max_target:
            bounds_penalty += trip_count - max_target

    return (
        bounds_penalty,
        trip_range,
        round(km_range, 4),
        round(km_variance, 4),
    )


def _choose_drivers_for_match(
    eligible,
    stats,
    needed,
    distance_value,
    match_index,
    min_target,
    max_target,
):
    """Pick the best driver combination for one match using global fairness scoring."""
    # Candidate pre-sort keeps the combinatorial search small while still
    # considering the people who are most useful for balancing.
    ranked = sorted(
        eligible,
        key=lambda name: (
            stats[name]["ritten"],
            stats[name]["kilometers"],
            stats[name]["laatste"],
            name.casefold(),
        ),
    )

    # Search all combinations when the pool is modest. With 15 players and
    # 4 cars this is only 1365 combinations.
    pool = ranked

    best_combo = None
    best_score = None

    import itertools
    for combo in itertools.combinations(pool, needed):
        # Simulate assignment.
        for name in combo:
            stats[name]["ritten"] += 1
            stats[name]["kilometers"] += distance_value

        score = _objective(stats, eligible, min_target, max_target)

        # Prefer not to schedule the same driver again too soon when fairness
        # and kilometre balance are otherwise equal.
        recency_penalty = sum(
            1
            for name in combo
            if match_index - stats[name]["laatste"] <= 1
        )

        combo_score = score + (recency_penalty, tuple(n.casefold() for n in combo))

        for name in combo:
            stats[name]["ritten"] -= 1
            stats[name]["kilometers"] -= distance_value

        if best_score is None or combo_score < best_score:
            best_score = combo_score
            best_combo = combo

    return list(best_combo or ranked[:needed])


def _improve_by_swaps(schedule, stats, eligible, min_target, max_target, team_data):
    """Local improvement pass: swap drivers between matches to reduce km spread."""
    improved = True
    iterations = 0

    while improved and iterations < 300:
        iterations += 1
        improved = False
        current_score = _objective(stats, eligible, min_target, max_target)

        for i, match_a in enumerate(schedule):
            km_a = float(match_a["afstand_retour_km"] or 0.0)
            drivers_a = match_a["chauffeurs"]

            for j in range(i + 1, len(schedule)):
                match_b = schedule[j]
                km_b = float(match_b["afstand_retour_km"] or 0.0)
                if abs(km_a - km_b) < 0.01:
                    continue
                drivers_b = match_b["chauffeurs"]

                for a in list(drivers_a):
                    for b in list(drivers_b):
                        if a == b:
                            continue
                        # Never swap a driver onto a date on which they are
                        # temporarily unavailable.
                        if _is_temporarily_unavailable(team_data, b, match_a.get("datum", "")):
                            continue
                        if _is_temporarily_unavailable(team_data, a, match_b.get("datum", "")):
                            continue
                        if b in drivers_a or a in drivers_b:
                            continue

                        # Swap keeps trip counts identical, only km changes.
                        stats[a]["kilometers"] += km_b - km_a
                        stats[b]["kilometers"] += km_a - km_b

                        new_score = _objective(
                            stats, eligible, min_target, max_target
                        )

                        if new_score < current_score:
                            ai = drivers_a.index(a)
                            bi = drivers_b.index(b)
                            drivers_a[ai] = b
                            drivers_b[bi] = a
                            improved = True
                            current_score = new_score
                            break

                        # Undo.
                        stats[a]["kilometers"] += km_a - km_b
                        stats[b]["kilometers"] += km_b - km_a

                    if improved:
                        break
                if improved:
                    break
            if improved:
                break



def _temporary_unavailability(team_data):
    out = {}
    for item in getattr(team_data, "driving_unavailable_dates", []) or []:
        if isinstance(item, dict):
            name = " ".join(str(item.get("name", "")).split())
            date_iso = str(item.get("date", "")).strip()
            if name and date_iso:
                out.setdefault(name.casefold(), set()).add(date_iso)
    return out


def _is_temporarily_unavailable(team_data, name, date_iso):
    return date_iso in _temporary_unavailability(team_data).get(name.casefold(), set())

def can_drive_on_date(team_data, name, date_iso):
    """Return whether *name* is eligible to drive for the team on a date.

    Driving availability is the base availability for flagging as well: a
    person who cannot drive on a particular match date must not be selected
    as a flagger on that date either.
    """
    normalized = " ".join(str(name).split())
    if not normalized:
        return False

    squad = _unique_names(
        list(team_data.selected_players)
        + list(team_data.manual_players)
        + list(getattr(team_data, "driving_extra", []))
    )
    key = normalized.casefold()
    if key not in {n.casefold() for n in squad}:
        return False

    excluded = {
        " ".join(str(value).split()).casefold()
        for value in getattr(team_data, "driving_excluded", []) or []
        if str(value).strip()
    }
    if key in excluded:
        return False

    return not _is_temporarily_unavailable(team_data, normalized, date_iso or "")

def build_driving_schedule(team_data):
    """Build a deterministic season-wide fair driving schedule.

    Priorities:
    1. keep trip counts at the theoretical minimum/maximum;
    2. minimize kilometre spread across drivers;
    3. avoid consecutive assignments when possible.
    """
    squad = _unique_names(
        list(team_data.selected_players) + list(team_data.manual_players) + list(getattr(team_data, "driving_extra", []))
    )
    excluded_keys = {
        " ".join(str(name).split()).casefold()
        for name in team_data.driving_excluded
        if str(name).strip()
    }
    eligible = [n for n in squad if n.casefold() not in excluded_keys]
    excluded = [n for n in squad if n.casefold() in excluded_keys]
    cars = max(1, int(team_data.driving_cars or 1))
    unavailable = _temporary_unavailability(team_data)

    matches = sorted(
        (m for m in team_data.matches if m.is_home is False),
        key=lambda m: (
            m.date_iso or "9999-99-99",
            m.time or "99:99",
            m.match_id,
        ),
    )

    total_assignments = len(matches) * min(cars, len(eligible))
    min_target = total_assignments // len(eligible) if eligible else 0
    max_target = math.ceil(total_assignments / len(eligible)) if eligible else 0

    stats = {
        n: {
            "speler": n,
            "ritten": 0,
            "kilometers": 0.0,
            "laatste": -9999,
        }
        for n in eligible
    }

    schedule = []
    warnings = []

    for idx, match in enumerate(matches):
        match_eligible = [
            n for n in eligible
            if match.date_iso not in unavailable.get(n.casefold(), set())
        ]
        needed = min(cars, len(match_eligible))

        if len(match_eligible) < cars:
            warnings.append(
                f"{match.date_iso or match.date_text}: {cars} auto's gevraagd, "
                f"maar slechts {len(match_eligible)} beschikbare chauffeurs op deze datum."
            )

        km = float(match.route.afstand_retour_km or 0.0)

        drivers = _choose_drivers_for_match(
            match_eligible,
            stats,
            needed,
            km,
            idx,
            min_target,
            max_target,
        )

        for name in drivers:
            stats[name]["ritten"] += 1
            stats[name]["kilometers"] += km
            stats[name]["laatste"] = idx

        schedule.append({
            "wedstrijd_id": match.match_id,
            "datum": match.date_iso,
            "tijd": match.time,
            "tegenstander": match.opponent,
            "accommodatie": match.accommodation,
            "afstand_retour_km": match.route.afstand_retour_km,
            "reistijd_minuten": match.route.reistijd_minuten,
            "chauffeurs": drivers,
        })

    # Improve kilometre balance without changing anyone's number of trips.
    if eligible and schedule:
        _improve_by_swaps(
            schedule,
            stats,
            eligible,
            min_target,
            max_target,
            team_data,
        )

    kms = [stats[name]["kilometers"] for name in eligible]
    avg_km = sum(kms) / len(kms) if kms else 0.0
    spread_km = (max(kms) - min(kms)) if kms else 0.0

    verdeling = sorted(
        ({
            "speler": v["speler"],
            "ritten": v["ritten"],
            "kilometers": round(v["kilometers"], 1),
            "verschil_van_gemiddelde_km": round(
                v["kilometers"] - avg_km, 1
            ),
        } for v in stats.values()),
        key=lambda x: (
            x["ritten"],
            x["kilometers"],
            x["speler"].casefold(),
        ),
    )

    return {
        "spelers": squad,
        "beschikbare_chauffeurs": eligible,
        "uitgesloten_chauffeurs": excluded,
        "tijdelijke_rijbeperkingen": [dict(x) for x in (getattr(team_data, "driving_unavailable_dates", []) or [])],
        "autos_per_uitwedstrijd": cars,
        "schema": schedule,
        "verdeling": verdeling,
        "waarschuwingen": warnings,
        "doel_min_ritten": min_target,
        "doel_max_ritten": max_target,
        "gemiddelde_km_per_chauffeur": round(avg_km, 1),
        "kilometer_spreiding": round(spread_km, 1),
    }
