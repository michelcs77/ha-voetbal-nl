from html import unescape
from html.parser import HTMLParser
import re

from .models import Team


def _clean(value):
    value = unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _norm(value):
    value = _clean(value).casefold()
    value = value.replace(".", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


class TeamLinkParser(HTMLParser):
    """Collect anchors that point at /team/T.../... including their visible text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs_d = {str(k).lower(): (v or "") for k, v in attrs}
        if tag.lower() == "img" and self.current is not None:
            src = attrs_d.get("src") or attrs_d.get("data-src") or ""
            if src and not self.current.get("logo_url"):
                self.current["logo_url"] = src
            return
        if tag.lower() != "a":
            return
        href = attrs_d.get("href", "")
        m = re.search(r"/team/(T[0-9A-Za-z]+)/", href, re.I)
        if not m:
            return
        self.current = {
            "team_id": m.group(1),
            "href": href,
            "text": [],
            "title": attrs_d.get("title", ""),
            "logo_url": None,
        }

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            self.items.append(self.current)
            self.current = None


def parse_club_teams(html, club_name=None):
    """Parse the real teams belonging to the selected club.

    Voetbal.nl renders account/favorite team links in the same HTML document.
    Those links can have names such as 'zat 1', 'VR30+1' or 'zat MO17-2'.
    The club team list itself uses the full club name in the visible label.
    Therefore, when club_name is known, only labels that start with that club
    name are accepted.

    Team IDs remain the unique key. We deliberately do NOT merge equal names:
    Voetbal.nl can expose multiple official T-IDs with the same display name.
    """
    parser = TeamLinkParser()
    parser.feed(html)

    club_norm = _norm(club_name) if club_name else ""
    found = {}

    for item in parser.items:
        team_id = item["team_id"]
        text = _clean(" ".join(item["text"]))
        title = _clean(item.get("title"))
        name = text or title or team_id
        name_norm = _norm(name)

        if club_norm:
            # Real club-list labels are e.g. "v.v. Cuijk 3".
            # Favorites/profile navigation like "zat 1" is excluded.
            if not (name_norm == club_norm or name_norm.startswith(club_norm + " ")):
                continue

        old = found.get(team_id)
        candidate = Team(team_id=team_id, name=name, href=item["href"], logo_url=item.get("logo_url"))

        # Prefer a human-readable label over a bare ID if the same T-ID
        # occurs multiple times in the club page.
        if old is None or old.name == old.team_id:
            found[team_id] = candidate

    return sorted(found.values(), key=lambda x: (x.name.casefold(), x.team_id))


def parse_team_metadata(html, team_id, team_name):
    """Extract diagnostic metadata from an authenticated team overview.

    We intentionally collect evidence instead of guessing whether duplicate
    display names mean Saturday/Sunday. MatchDetail title/subtitle pairs are
    the strongest signals currently visible on Voetbal.nl.
    """
    from .models import TeamMetadata

    days = set()
    categories = set()
    competitions = set()
    subtitles = []

    # MatchDetail-title normally contains e.g. "Zaterdag 3 oktober".
    for title in re.findall(
        r'<h3[^>]*class="[^"]*MatchDetail-title[^"]*"[^>]*>(.*?)</h3>',
        html,
        re.I | re.S,
    ):
        value = _clean(title)
        m = re.match(
            r"(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\b",
            value,
            re.I,
        )
        if m:
            days.add(m.group(1).capitalize())

    # Subtitles contain data such as "Mannen, 3, 6e klasse 15".
    for subtitle in re.findall(
        r'<p[^>]*class="[^"]*MatchDetail-subTitle[^"]*"[^>]*>(.*?)</p>',
        html,
        re.I | re.S,
    ):
        value = _clean(subtitle)
        if not value:
            continue
        subtitles.append(value)
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if parts:
            categories.add(parts[0])
        if len(parts) >= 3:
            competitions.add(", ".join(parts[2:]))
        elif len(parts) >= 2:
            competitions.add(parts[-1])

    # Some overview pages expose schedule rows rather than MatchDetail.
    # Scan visible text for explicit weekday names as a secondary signal.
    visible = _clean(html)
    for day in (
        "Maandag", "Dinsdag", "Woensdag", "Donderdag",
        "Vrijdag", "Zaterdag", "Zondag"
    ):
        if re.search(rf"\b{day}\b", visible, re.I):
            days.add(day)

    return TeamMetadata(
        team_id=team_id,
        name=team_name,
        days=tuple(sorted(days)),
        categories=tuple(sorted(categories)),
        competitions=tuple(sorted(competitions)),
        subtitles=tuple(dict.fromkeys(subtitles)),
    )


def _strip_tags(value):
    value = re.sub(r'<script\b.*?</script>', ' ', value, flags=re.I | re.S)
    value = re.sub(r'<style\b.*?</style>', ' ', value, flags=re.I | re.S)
    value = re.sub(r'<[^>]+>', ' ', value)
    return _clean(value)


def _extract_player_section(html):
    """Extract a conservative window after the actual 'Spelers' label.

    v0.4.4 intentionally avoids depending on CSS class names. We locate the
    last useful 'Spelers' heading and then cut at a later 'Staf' heading only
    if that leaves player-like content. If no safe Staf boundary is found,
    use a bounded HTML window.
    """
    matches = list(re.finditer(r'>\s*Spelers\s*<', html, re.I | re.S))
    if not matches:
        return ""

    # Prefer the occurrence followed by privacy/name data.
    chosen = matches[-1]
    for m in matches:
        probe = html[m.end():m.end() + 30000]
        if re.search(r'\bAfgeschermd\b', probe, re.I):
            chosen = m
            break

    tail = html[chosen.end():]
    # Bound the scope so we don't count unrelated page content.
    tail = tail[:50000]

    # Stop at a Staf heading only after at least one player marker/name area.
    for staff in re.finditer(r'>\s*Staf\s*<', tail, re.I | re.S):
        candidate = tail[:staff.start()]
        if re.search(r'\bAfgeschermd\b', candidate, re.I) or len(candidate) > 1000:
            return candidate

    return tail


def _candidate_player_names_from_section(section):
    """Extract literal visible player names from several Voetbal.nl markups.

    The site has used both nested spans and generic row/card markup. We only
    accept text that is actually present in the HTML; nothing is inferred.
    """
    candidates = []

    # 1. Historical/current name classes (including TeamMembers-name).
    for m in re.finditer(
        r'<(?P<tag>span|div|p|a)[^>]*class=["\'][^"\']*'
        r'(?:TeamMembers-name|player[^"\']*name|name[^"\']*player|member[^"\']*name)'
        r'[^"\']*["\'][^>]*>(?P<body>.*?)</(?P=tag)>',
        section,
        re.I | re.S,
    ):
        value = _strip_tags(m.group("body"))
        if value:
            candidates.append(value)

    # 2. A common Voetbal.nl pattern is first name as text plus surname in a
    # nested span. Flatten every short span/div and later apply strict filters.
    for m in re.finditer(
        r'<(?P<tag>span|div)[^>]*>(?P<body>.*?)</(?P=tag)>',
        section,
        re.I | re.S,
    ):
        body = m.group("body")
        value = _strip_tags(body)
        if value and len(value) <= 80:
            candidates.append(value)

    # 3. Extract adjacent text chunks around nested spans. This catches markup
    # like: <span>Isa<span> Willems </span></span>.
    for m in re.finditer(
        r'>([^<>]{1,40})<span[^>]*>\s*([^<>]{1,50})\s*</span>',
        section,
        re.I | re.S,
    ):
        value = _clean(f"{m.group(1)} {m.group(2)}")
        if value:
            candidates.append(value)

    return candidates


def _looks_like_player_name(value):
    value = _clean(value)
    folded = value.casefold()

    if not value or len(value) < 3 or len(value) > 70:
        return False
    if folded == "afgeschermd" or "afgeschermd" in folded:
        return False

    blocked_exact = {
        "spelers", "staf", "toon meer", "meer tonen", "team",
        "programma", "uitslagen", "stand", "indeling", "overzicht",
    }
    if folded in blocked_exact:
        return False

    blocked_contains = (
        "voetbal.nl", "wedstrijd", "bekijk ", "privacy", "cookie",
        "inloggen", "uitloggen", "sportpark", "zaterdag", "zondag",
        "klasse", "competitie",
    )
    if any(token in folded for token in blocked_contains):
        return False

    # Names need at least two alphabetic words. Apostrophes, hyphens and
    # particles such as van/de/den are allowed naturally by this expression.
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]*", value)
    if len(words) < 2 or len(words) > 7:
        return False

    # Reject obvious UI sentences/labels. Real player names are compact.
    if len(value.split()) > 7:
        return False
    if any(ch in value for ch in (":", "/", "\\", "{", "}", "[", "]", "=")):
        return False

    return True


def parse_team_players(html):
    """Parse visible and hidden players from the verified Spelers section.

    v0.4.5 keeps the v0.4.4 hidden-player count and broadens only the literal
    visible-name extraction.
    """
    section = _extract_player_section(html)
    if not section:
        return [], 0

    # Preserve the verified v0.4.4 behaviour.
    hidden = len(re.findall(r'\bAfgeschermd\b', section, re.I))

    candidates = _candidate_player_names_from_section(section)

    visible = []
    seen = set()
    for raw in candidates:
        value = _clean(raw)
        if not _looks_like_player_name(value):
            continue

        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        visible.append(value)

    return visible, hidden

def _extract_playerlist_groups(html):
    """Parse Voetbal.nl Playerlist groups from the observed live markup.

    Expected structure:
      Playerlist-groupTitle -> Spelers / Staf
      Playerlist-item
      Playercopy-firstname
      Playercopy-lastname
    """
    result = {
        "spelers": {"visible": [], "hidden": 0},
        "staf": {"visible": [], "hidden": 0},
    }

    # Locate every group title and scope each group until the next group title.
    title_matches = list(re.finditer(
        r'<span[^>]*class=["\'][^"\']*Playerlist-groupTitle[^"\']*["\'][^>]*>'
        r'\s*(Spelers|Staf)\s*</span>',
        html,
        re.I | re.S,
    ))

    for pos, title_match in enumerate(title_matches):
        group_name = _clean(title_match.group(1)).casefold()
        if group_name not in result:
            continue

        group_start = title_match.end()
        group_end = title_matches[pos + 1].start() if pos + 1 < len(title_matches) else len(html)
        group_html = html[group_start:group_end]

        # Parse complete list items so firstname and lastname stay paired.
        for item in re.finditer(
            r'<li[^>]*class=["\'][^"\']*Playerlist-item[^"\']*["\'][^>]*>'
            r'(?P<body>.*?)</li>',
            group_html,
            re.I | re.S,
        ):
            body = item.group("body")

            first_match = re.search(
                r'<span[^>]*class=["\'][^"\']*Playercopy-firstname[^"\']*["\'][^>]*>'
                r'(?P<value>.*?)</span>',
                body,
                re.I | re.S,
            )
            last_match = re.search(
                r'<span[^>]*class=["\'][^"\']*Playercopy-lastname[^"\']*["\'][^>]*>'
                r'(?P<value>.*?)</span>',
                body,
                re.I | re.S,
            )

            first = _strip_tags(first_match.group("value")) if first_match else ""
            last = _strip_tags(last_match.group("value")) if last_match else ""

            if last.casefold() == "afgeschermd" or first.casefold() == "afgeschermd":
                result[group_name]["hidden"] += 1
                continue

            full_name = _clean(f"{first} {last}")
            if not full_name:
                continue

            # Literal de-duplication only.
            if full_name.casefold() not in {
                name.casefold() for name in result[group_name]["visible"]
            }:
                result[group_name]["visible"].append(full_name)

    return result


def parse_team_people(html):
    """Return players and staff separately from the same team page."""
    groups = _extract_playerlist_groups(html)
    return {
        "players": groups["spelers"]["visible"],
        "hidden_players": groups["spelers"]["hidden"],
        "staff": groups["staf"]["visible"],
        "hidden_staff": groups["staf"]["hidden"],
    }


def parse_team_players(html):
    """Backward-compatible player parser using the exact Playerlist markup."""
    people = parse_team_people(html)
    return people["players"], people["hidden_players"]

def inspect_player_page(html):
    """Return player-page diagnostics without making assumptions.

    The purpose is to distinguish:
    - wrong endpoint
    - lost authentication/session
    - HTML structure mismatch
    - parser mismatch
    """
    html_cf = html.casefold()

    teammembers_gevonden = (
        "teammembers" in html_cf
        or 'data-component="teammembers"' in html_cf
        or "teammembers-" in html_cf
    )

    spelers_label_gevonden = bool(
        re.search(
            r'>\s*spelers\s*<',
            html,
            re.I | re.S,
        )
        or re.search(
            r'TeamMembers-headerLabel[^>]*>\s*Spelers\s*<',
            html,
            re.I | re.S,
        )
    )

    player_section = _extract_player_section(html)
    afgeschermd_gevonden = len(
        re.findall(r'\bAfgeschermd\b', player_section or html, re.I)
    )
    zichtbare_kandidaten_gevonden = len(
        _candidate_player_names_from_section(player_section)
        if player_section else []
    )

    loginpagina = bool(
        "/inloggen" in html_cf
        or "<title>inloggen" in html_cf
        or "redirecting to /inloggen" in html_cf
        or 'name="form_id" value="login_form"' in html_cf
    )

    return {
        "html_lengte": len(html),
        "spelers_sectie_lengte": len(player_section),
        "teammembers_gevonden": teammembers_gevonden,
        "spelers_label_gevonden": spelers_label_gevonden,
        "afgeschermd_gevonden": afgeschermd_gevonden,
        "zichtbare_kandidaten_gevonden": zichtbare_kandidaten_gevonden,
        "loginpagina": loginpagina,
    }


_DUTCH_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}

def parse_program_match_ids(html):
    """Return unique match IDs in page order from a team program page."""
    ids = []
    for match_id in re.findall(r'/wedstrijd/(M\d+)(?:/|["\'])', html, re.I):
        match_id = match_id.upper()
        if match_id not in ids:
            ids.append(match_id)
    return ids



def _program_fixture_block(html, match_id):
    """Return the rendered fixture anchor for one match when available."""
    pattern = (
        rf'<a\b[^>]*href=["\']/wedstrijd/{re.escape(match_id)}(?:/programma)?["\'][^>]*>'
        rf'(.*?)</a>'
    )
    m = re.search(pattern, html, re.I | re.S)
    return m.group(0) if m else ""


def _program_fixture_hint(block, team_name):
    """Extract best-effort home/away/date/time data from a program fixture row."""
    if not block:
        return {}

    team_names = []
    for m in re.finditer(
        r'<div[^>]*class=["\'][^"\']*\bteam\b[^"\']*["\'][^>]*>(.*?)</div>',
        block, re.I | re.S,
    ):
        value = _strip_tags(m.group(1))
        if value and value not in team_names:
            team_names.append(value)
        if len(team_names) >= 2:
            break

    home = team_names[0] if len(team_names) >= 1 else ""
    away = team_names[1] if len(team_names) >= 2 else ""
    wanted = _norm(team_name)
    is_home = None
    if home and away:
        if _norm(home) == wanted:
            is_home = True
        elif _norm(away) == wanted:
            is_home = False

    # Some rendered rows mark the selected team on the home/away value even
    # when the nested team labels changed. Use that only as a directional hint.
    if is_home is None:
        if re.search(r'class=["\'][^"\']*\bvalue\b[^"\']*\bhome\b[^"\']*\bmy-team\b', block, re.I):
            is_home = True
        elif re.search(r'class=["\'][^"\']*\bvalue\b[^"\']*\baway\b[^"\']*\bmy-team\b', block, re.I):
            is_home = False

    text = _strip_tags(block)
    time_m = re.search(r'\b(\d{1,2}:\d{2})\b', text)
    date_iso = _infer_match_date(text)
    opponent = ""
    if is_home is True and away:
        opponent = away
    elif is_home is False and home:
        opponent = home

    return {
        "home_team": home,
        "away_team": away,
        "is_home": is_home,
        "opponent": opponent,
        "date_text": text,
        "date_iso": date_iso,
        "time": time_m.group(1) if time_m else None,
    }


def parse_program_match_hints_for_team(html, team_name):
    """Return candidate IDs plus fixture-row fallbacks for a selected team.

    The program page is used only as a fallback. Authenticated MatchDetail
    pages remain authoritative whenever they can identify both teams.
    """
    all_ids = parse_program_match_ids(html)
    if not all_ids:
        return [], 0, {}

    wanted = _norm(team_name)
    candidates = []
    seen = set()
    hints = {}

    for match in re.finditer(r'/wedstrijd/(M\d+)(?:/|["\'])', html, re.I):
        match_id = match.group(1).upper()
        if match_id in seen:
            continue
        seen.add(match_id)

        block = _program_fixture_block(html, match_id)
        hint = _program_fixture_hint(block, team_name)
        if hint:
            hints[match_id] = hint

        # Prefer the complete fixture row. Keep the historic local-context
        # heuristic as fallback for changed markup.
        row_context = _norm(block) if block else ""
        start = max(0, match.start() - 1800)
        end = min(len(html), match.end() + 1800)
        local_context = _norm(html[start:end])
        if wanted and (wanted in row_context or wanted in local_context):
            candidates.append(match_id)

    if len(candidates) < 2:
        candidates = all_ids
        for match_id in candidates:
            if match_id not in hints:
                block = _program_fixture_block(html, match_id)
                hint = _program_fixture_hint(block, team_name)
                if hint:
                    hints[match_id] = hint

    return candidates, len(all_ids), hints


def parse_program_match_ids_for_team(html, team_name):
    """Backward-compatible candidate-ID API."""
    candidates, source_count, _ = parse_program_match_hints_for_team(html, team_name)
    return candidates, source_count

def _infer_match_date(date_text, now=None):
    """Infer ISO date for a Dutch day/month label, preferring a future date."""
    from datetime import date
    now = now or date.today()
    text = _clean(date_text).casefold()
    m = re.search(
        r'\b(?:maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)?\s*'
        r'(\d{1,2})\s+(' + "|".join(_DUTCH_MONTHS) + r')\b',
        text,
        re.I,
    )
    if not m:
        return None
    day = int(m.group(1))
    month = _DUTCH_MONTHS[m.group(2).casefold()]
    candidates = []
    for year in (now.year - 1, now.year, now.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        delta = (d - now).days
        candidates.append((d, delta))
    future = [item for item in candidates if -31 <= item[1] <= 370]
    if not future:
        return None
    # Prefer upcoming/current dates; allow recent matches for program completeness.
    upcoming = [item for item in future if item[1] >= 0]
    chosen = min(upcoming, key=lambda x: x[1]) if upcoming else max(future, key=lambda x: x[1])
    return chosen[0].isoformat()


def _team_logo_urls(html, home_team, away_team):
    """Return logo URLs found in img tags for the two MatchDetail teams."""
    result = {"home": None, "away": None}
    home_norm = _norm(home_team)
    away_norm = _norm(away_team)
    for tag in re.findall(r"<img\b[^>]*>", html, re.I | re.S):
        attrs = {}
        for key, quoted, bare in re.findall(
            r"([:\w-]+)\s*=\s*(?:[\"']([^\"']*)[\"']|([^\s>]+))",
            tag, re.I | re.S,
        ):
            attrs[key.casefold()] = unescape(quoted or bare or "")
        alt_norm = _norm(attrs.get("alt", ""))
        src = attrs.get("src") or attrs.get("data-src") or ""
        if not src:
            continue
        if home_norm and alt_norm == home_norm and not result["home"]:
            result["home"] = src
        elif away_norm and alt_norm == away_norm and not result["away"]:
            result["away"] = src
    return result["home"], result["away"]


def parse_match_detail(html, match_id, team_id, team_name):
    """Parse one authenticated Voetbal.nl MatchDetail page."""
    from .models import Match

    title_m = re.search(
        r'<h3[^>]*class="[^"]*MatchDetail-title[^"]*"[^>]*>(.*?)</h3>',
        html, re.I | re.S
    )
    date_text = _strip_tags(title_m.group(1)) if title_m else ""

    time_m = re.search(
        r'MatchDetail-separatorLineText[^>]*>\s*(\d{1,2}:\d{2})\s*<',
        html, re.I | re.S
    )
    match_time = time_m.group(1) if time_m else None

    # Team names occur in the two MatchDetail-teamName containers.
    team_names = []
    for m in re.finditer(
        r'<div[^>]*class="[^"]*MatchDetail-teamName[^"]*"[^>]*>(.*?)</div>',
        html, re.I | re.S
    ):
        value = _strip_tags(m.group(1))
        if value and value not in team_names:
            team_names.append(value)
        if len(team_names) >= 2:
            break

    home = team_names[0] if len(team_names) >= 1 else ""
    away = team_names[1] if len(team_names) >= 2 else ""
    home_logo_url, away_logo_url = _team_logo_urls(html, home, away)

    norm_team = _norm(team_name)
    is_home = None
    if home and away:
        if _norm(home) == norm_team:
            is_home = True
        elif _norm(away) == norm_team:
            is_home = False

    opponent = ""
    if is_home is True:
        opponent = away
    elif is_home is False:
        opponent = home

    field_m = re.search(
        r'<span>\s*Veld\s*</span>.*?MatchDetail-values[^>]*>\s*<span>\s*([^<]+)\s*</span>',
        html, re.I | re.S
    )
    field_value = _clean(field_m.group(1)) if field_m else None

    def loc(cls):
        m = re.search(
            rf'<span[^>]*class="[^"]*{re.escape(cls)}[^"]*"[^>]*>(.*?)</span>',
            html, re.I | re.S
        )
        return _strip_tags(m.group(1)) if m else None

    accommodation = loc("LocationDetails-infoPark")
    street = loc("LocationDetails-infoStreet")
    postal_city = loc("LocationDetails-infoZip")

    lat = lon = None
    coord_m = re.search(
        r'google\.com/maps/embed/v1/place\?q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)',
        html, re.I
    )
    if coord_m:
        lat = float(coord_m.group(1))
        lon = float(coord_m.group(2))

    return Match(
        match_id=match_id,
        team_id=team_id,
        team_name=team_name,
        date_text=date_text,
        date_iso=_infer_match_date(date_text),
        time=match_time,
        home_team=home,
        away_team=away,
        is_home=is_home,
        opponent=opponent,
        field_name=field_value,
        accommodation=accommodation,
        street=street,
        postal_city=postal_city,
        latitude=lat,
        longitude=lon,
        home_logo_url=home_logo_url,
        away_logo_url=away_logo_url,
    )
