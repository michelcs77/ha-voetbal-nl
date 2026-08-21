import asyncio
from http.cookies import SimpleCookie
from html import unescape
import json
import re
from urllib.parse import quote, urlsplit

from aiohttp import ClientSession, FormData

from .const import BASE_URL, LOGIN_PATH, USER_AGENT
from .models import Club, ClubData, MultiTeamData, PlayerDebug, SelectedTeamData, StaffMember, Team
from .parser import inspect_player_page, parse_club_teams, parse_team_metadata, parse_team_people, parse_program_match_ids, parse_program_match_ids_for_team, parse_program_match_hints_for_team, parse_match_detail

class VoetbalNlError(Exception):
    pass

class VoetbalNlAuthError(VoetbalNlError):
    pass

class VoetbalNlConnectionError(VoetbalNlError):
    pass

class VoetbalNlClient:
    def __init__(self, session: ClientSession, email: str, password: str):
        self._session = session
        self._email = email
        self._password = password
        self._session_cookie_name = None
        self._session_cookie_value = None

    @property
    def _headers(self):
        return {
            "User-Agent": USER_AGENT,
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.7",
            "Accept": "*/*",
        }

    def _cookie_header(self):
        if self._session_cookie_name and self._session_cookie_value:
            return {"Cookie": f"{self._session_cookie_name}={self._session_cookie_value}"}
        return {}

    def _save_cookie(self, response):
        for name, morsel in response.cookies.items():
            if name.startswith("SESS") or name.startswith("SSESS"):
                self._session_cookie_name = name
                self._session_cookie_value = morsel.value
                return
        for raw in response.headers.getall("Set-Cookie", []):
            simple = SimpleCookie()
            try:
                simple.load(raw)
            except Exception:
                pass
            for name, morsel in simple.items():
                if name.startswith("SESS") or name.startswith("SSESS"):
                    self._session_cookie_name = name
                    self._session_cookie_value = morsel.value
                    return
            m = re.search(r"\b(S?SESS[0-9A-Za-z]+)=([^;]+)", raw)
            if m:
                self._session_cookie_name = m.group(1)
                self._session_cookie_value = m.group(2)
                return

    async def _already_logged_in(self):
        try:
            async with self._session.get(
                f"{BASE_URL}/profiel/overzicht",
                headers=self._headers | self._cookie_header(),
                allow_redirects=True,
            ) as response:
                return response.status == 200 and "/inloggen" not in response.url.path
        except Exception:
            return False

    async def async_login(self):
        if await self._already_logged_in():
            return

        async with self._session.get(
            f"{BASE_URL}{LOGIN_PATH}",
            headers=self._headers,
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                raise VoetbalNlConnectionError(f"Loginpagina gaf HTTP {response.status}")
            if "/inloggen" not in response.url.path:
                return
            login_html = await response.text()

        m = re.search(r'name="form_build_id"[^>]*value="([^"]+)"', login_html, re.I)
        if not m:
            m = re.search(r'value="([^"]+)"[^>]*name="form_build_id"', login_html, re.I)
        if not m:
            raise VoetbalNlAuthError("form_build_id niet gevonden")

        form = FormData()
        form.add_field("email", self._email)
        form.add_field("password", self._password)
        form.add_field("form_build_id", m.group(1))
        form.add_field("form_id", "login_form")

        async with self._session.post(
            f"{BASE_URL}{LOGIN_PATH}",
            data=form,
            headers=self._headers,
            allow_redirects=False,
        ) as response:
            if response.status not in (302, 303):
                body = await response.text()
                if "inloggen" in body.lower():
                    raise VoetbalNlAuthError("Voetbal.nl heeft de login geweigerd")
                raise VoetbalNlAuthError(f"Onverwachte loginstatus HTTP {response.status}")
            self._save_cookie(response)

        if not await self._already_logged_in():
            raise VoetbalNlAuthError("Sessie is niet geldig")

    async def async_get_authenticated(self, path, retry=True):
        if not self._session_cookie_name and not await self._already_logged_in():
            await self.async_login()

        headers = dict(self._headers)
        headers.update(self._cookie_header())

        async with self._session.get(
            f"{BASE_URL}{path}",
            headers=headers,
            allow_redirects=True,
        ) as response:
            text = await response.text()
            if "/inloggen" in response.url.path:
                if retry:
                    self._session_cookie_name = None
                    self._session_cookie_value = None
                    await self.async_login()
                    return await self.async_get_authenticated(path, retry=False)
                raise VoetbalNlAuthError("Voetbal.nl sessie is niet geldig")
            if response.status != 200:
                raise VoetbalNlConnectionError(f"{path} gaf HTTP {response.status}")
            return text

    async def async_search_clubs(self, query):
        """Use Voetbal.nl's own live club search endpoint."""
        await self.async_login()
        path = f"/club/clubID/{quote(query.strip())}"
        text = await self.async_get_authenticated(path)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as err:
            raise VoetbalNlConnectionError("Clubzoeker gaf geen geldige JSON") from err

        if not isinstance(payload, list):
            raise VoetbalNlConnectionError("Onverwachte response van clubzoeker")

        clubs = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            club_id = str(item.get("clubid") or "").strip()
            name = str(item.get("name") or "").strip()
            city = str(item.get("city") or "").strip()
            if club_id and name:
                clubs.append(Club(club_id=club_id, name=name, city=city))
        return clubs


    async def async_get_team_metadata(self, team):
        """Fetch authenticated overview metadata for one team."""
        html = await self.async_get_authenticated(
            f"/team/{team.team_id}/overzicht"
        )
        return parse_team_metadata(html, team.team_id, team.name)


    async def async_get_team_players(self, team):
        """Fetch the selected team's player page and diagnostics."""
        html = await self.async_get_authenticated(
            f"/team/{team.team_id}/team"
        )

        debug_info = inspect_player_page(html)
        people = parse_team_people(html)

        from .models import Player

        players = [
            Player(name=name, visible=True)
            for name in people["players"]
        ]
        staff = [
            StaffMember(name=name, visible=True)
            for name in people["staff"]
        ]

        debug = PlayerDebug(
            http_ok=True,
            html_lengte=debug_info["html_lengte"],
            spelers_sectie_lengte=debug_info["spelers_sectie_lengte"],
            teammembers_gevonden=debug_info["teammembers_gevonden"],
            spelers_label_gevonden=debug_info["spelers_label_gevonden"],
            afgeschermd_gevonden=debug_info["afgeschermd_gevonden"],
            zichtbare_kandidaten_gevonden=debug_info["zichtbare_kandidaten_gevonden"],
            loginpagina=debug_info["loginpagina"],
        )

        return (
            players,
            people["hidden_players"],
            staff,
            people["hidden_staff"],
            debug,
        )

    async def async_get_team_program(self, team):
        """Fetch the complete team programme, including chained ScheduleResults data.

        Voetbal.nl does not always put the full season in the initial team page.
        A ScheduleResults block can load a second block through AJAX, and that
        response can itself contain another URL.  Following only the URLs from
        the first page therefore truncates some programmes after one phase.
        """
        html = await self.async_get_authenticated(
            f"/team/{team.team_id}/programma"
        )

        def _normalise_program_path(value):
            """Return a safe same-site program path or None."""
            value = unescape(str(value or "")).strip().replace("\\/", "/")
            if not value:
                return None

            # data-options can contain an absolute voetbal.nl URL.  Convert it
            # back to a path because async_get_authenticated prefixes BASE_URL.
            if value.startswith("http://") or value.startswith("https://"):
                parsed = urlsplit(value)
                base = urlsplit(BASE_URL)
                if parsed.netloc.casefold() != base.netloc.casefold():
                    return None
                value = parsed.path or "/"
                if parsed.query:
                    value += f"?{parsed.query}"

            if not value.startswith("/"):
                return None

            # Only crawl team ScheduleResults AJAX endpoints. Never treat
            # ordinary team pages or /wedstrijd/M.../programma detail links as
            # pagination endpoints: doing so fans out into unrelated fixtures.
            path_only = value.split("?", 1)[0]
            if not re.fullmatch(r"/team/ajax/[^/]+/programma(?:/[^/]+)?", path_only, re.I):
                return None
            return value

        def _discover_program_paths(source):
            """Discover program AJAX paths from HTML/JSON component markup."""
            paths = []
            decoded_source = unescape(source or "")

            # Primary source: component data-options JSON.  Support both normal
            # quotes and HTML-escaped JSON values.
            for attr in re.findall(
                r'data-options\s*=\s*["\']([^"\']+)["\']',
                source or "",
                re.I | re.S,
            ):
                decoded = unescape(attr)
                options = None
                try:
                    options = json.loads(decoded)
                except json.JSONDecodeError:
                    # Be tolerant of a slightly changed serializer; extracting
                    # just the URL is enough for ScheduleResults pagination.
                    match = re.search(
                        r'["\']?url["\']?\s*:\s*["\']([^"\']+)',
                        decoded,
                        re.I,
                    )
                    if match:
                        options = {"url": match.group(1)}
                if isinstance(options, dict):
                    path = _normalise_program_path(options.get("url"))
                    if path and path not in paths:
                        paths.append(path)

            # Fallback for JSON or changed component markup where the URL is no
            # longer inside a data-options attribute.  Look only at URL-valued
            # fields/attributes; ordinary fixture hrefs also contain /programma
            # and must never be treated as pagination endpoints.
            url_patterns = (
                r'["\']url["\']\s*:\s*["\']([^"\']+)["\']',
                r'data-(?:url|endpoint)\s*=\s*["\']([^"\']+)["\']',
                # Voetbal.nl also renders programme tabs as ordinary href/action
                # attributes.  v0.11.1 missed those and therefore saw only the
                # beker ScheduleResults block for some teams.
                r'(?:href|action)\s*=\s*["\']([^"\']+)["\']',
                # Last-resort: pick up an escaped/raw same-team AJAX programme
                # path wherever it occurs in component markup or inline JSON.
                r'((?:https?://[^"\'\s<>]+)?/team/ajax/[^"\'\s<>]+/programma/[^"\'\s<>?#]+)',
            )
            for pattern in url_patterns:
                for match in re.finditer(pattern, decoded_source, re.I | re.S):
                    path = _normalise_program_path(match.group(1))
                    if path and path not in paths:
                        paths.append(path)

            return paths

        html_parts = [html]

        # Breadth-first crawl of chained ScheduleResults responses.  The cap is
        # defensive only; a normal team program needs just a handful of blocks.
        discovered_initial_paths = _discover_program_paths(html)
        queue = list(discovered_initial_paths)

        # Some Voetbal.nl team pages expose only the active phase in the HTML
        # (for example /beker) while the regular competition is available on a
        # sibling ScheduleResults endpoint. Probe that canonical sibling too.
        # A missing endpoint is harmless: async_get_authenticated raises and the
        # crawler simply continues. This prevents a season from stopping at the
        # end of the cup phase.
        competition_path = f"/team/ajax/{team.team_id}/programma/competitie"
        if competition_path not in queue:
            queue.append(competition_path)

        seen_paths = set()
        failed_paths = []
        max_program_requests = 40

        while queue and len(seen_paths) < max_program_requests:
            ajax_path = queue.pop(0)
            if ajax_path in seen_paths:
                continue
            seen_paths.add(ajax_path)

            try:
                ajax_text = await self.async_get_authenticated(ajax_path)
            except VoetbalNlError:
                # Keep all other program blocks usable if one optional block is
                # temporarily unavailable.
                failed_paths.append(ajax_path)
                continue

            ajax_html = ajax_text
            try:
                payload = json.loads(ajax_text)
                if isinstance(payload, dict) and isinstance(payload.get("html"), str):
                    ajax_html = payload["html"]
            except json.JSONDecodeError:
                pass

            if ajax_html:
                html_parts.append(ajax_html)

            # Critical v0.11.0 fix: also inspect every fetched response for the
            # next ScheduleResults URL instead of stopping after the first page.
            for candidate in _discover_program_paths(ajax_text):
                if candidate not in seen_paths and candidate not in queue:
                    queue.append(candidate)
            if ajax_html != ajax_text:
                for candidate in _discover_program_paths(ajax_html):
                    if candidate not in seen_paths and candidate not in queue:
                        queue.append(candidate)

        combined_html = "\n".join(html_parts)
        all_program_ids = []
        for found_id in re.findall(r'/wedstrijd/(M\d+)(?:/|["\'])', combined_html, re.I):
            found_id = found_id.upper()
            if found_id not in all_program_ids:
                all_program_ids.append(found_id)
        match_ids, source_count, program_hints = parse_program_match_hints_for_team(
            combined_html, team.name
        )
        program_debug = {}

        semaphore = asyncio.Semaphore(8)

        async def _load_match(match_id):
            async with semaphore:
                try:
                    detail_html = await self.async_get_authenticated(
                        f"/wedstrijd/{match_id}/programma"
                    )
                except VoetbalNlError:
                    return None
                match = parse_match_detail(
                    detail_html,
                    match_id,
                    team.team_id,
                    team.name,
                )
                # MatchDetail remains authoritative. If Voetbal.nl renders a
                # different detail layout and home/away cannot be recognised,
                # fall back to the already authenticated team program row. This
                # prevents valid fixtures from silently disappearing.
                if match.is_home is None:
                    hint = program_hints.get(match_id) or {}
                    hinted_is_home = hint.get("is_home")
                    if hinted_is_home is None:
                        return None
                    match.is_home = hinted_is_home
                    if not match.home_team:
                        match.home_team = hint.get("home_team") or ""
                    if not match.away_team:
                        match.away_team = hint.get("away_team") or ""
                    if not match.opponent:
                        match.opponent = hint.get("opponent") or (
                            match.away_team if match.is_home else match.home_team
                        )
                    if not match.date_iso:
                        match.date_iso = hint.get("date_iso")
                    if not match.date_text:
                        match.date_text = hint.get("date_text") or ""
                    if not match.time:
                        match.time = hint.get("time")
                return match

        results = await asyncio.gather(
            *(_load_match(match_id) for match_id in match_ids)
        )
        matches = [match for match in results if match is not None]
        matches.sort(key=lambda item: (
            item.date_iso or "9999-99-99",
            item.time or "99:99",
            item.match_id,
        ))
        return matches, source_count, len(match_ids), program_debug

    async def async_get_selected_team_data(self, club, team):
        """Fetch metadata and player list for one selected team."""
        metadata = await self.async_get_team_metadata(team)
        players, hidden_count, staff, hidden_staff, player_debug = (
            await self.async_get_team_players(team)
        )
        matches, source_count, candidate_count, program_debug = await self.async_get_team_program(team)
        return SelectedTeamData(
            club=club,
            team=team,
            metadata=metadata,
            players=players,
            hidden_players=hidden_count,
            staff=staff,
            hidden_staff=hidden_staff,
            player_debug=player_debug,
            matches=matches,
            program_source_count=source_count,
            program_candidate_count=candidate_count,
            program_debug=program_debug,
        )


    async def async_get_multi_team_data(self, club, teams):
        """Fetch metadata and players for multiple selected teams."""
        results = []
        for team in teams:
            results.append(
                await self.async_get_selected_team_data(club, team)
            )
        return MultiTeamData(club=club, teams=results)

    async def async_get_club_data(self, club: Club):
        """Fetch all team links from the authenticated club teams page."""
        await self.async_login()
        html = await self.async_get_authenticated(f"/club/{club.club_id}/teams")
        teams = parse_club_teams(html, club.name)
        return ClubData(club=club, teams=teams)
