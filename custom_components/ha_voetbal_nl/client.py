import asyncio
from http.cookies import SimpleCookie
from html import unescape
import json
import re
from urllib.parse import quote

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
        """Fetch the complete team programme, including ScheduleResults AJAX data."""
        html = await self.async_get_authenticated(
            f"/team/{team.team_id}/programma"
        )

        # Voetbal.nl can render only the first programme block in the main page
        # and expose later rounds through one or more ScheduleResults AJAX URLs.
        # Discover those URLs from data-options instead of hardcoding competition
        # names, so this works for every club/team and competition phase.
        ajax_paths = []
        for attr in re.findall(r'data-options=["\']([^"\']+)["\']', html, re.I):
            decoded = unescape(attr)
            try:
                options = json.loads(decoded)
            except json.JSONDecodeError:
                continue
            ajax_path = str(options.get("url") or "").strip()
            if (
                ajax_path
                and ajax_path.startswith("/")
                and "/programma/" in ajax_path
                and ajax_path not in ajax_paths
            ):
                ajax_paths.append(ajax_path)

        html_parts = [html]
        for ajax_path in ajax_paths:
            try:
                ajax_text = await self.async_get_authenticated(ajax_path)
            except VoetbalNlError:
                # Keep the main programme available if an optional AJAX block
                # is temporarily unavailable.
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

        combined_html = "\n".join(html_parts)
        match_ids, source_count, program_hints = parse_program_match_hints_for_team(
            combined_html, team.name
        )

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
        return matches, source_count, len(match_ids)

    async def async_get_selected_team_data(self, club, team):
        """Fetch metadata and player list for one selected team."""
        metadata = await self.async_get_team_metadata(team)
        players, hidden_count, staff, hidden_staff, player_debug = (
            await self.async_get_team_players(team)
        )
        matches, source_count, candidate_count = await self.async_get_team_program(team)
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
