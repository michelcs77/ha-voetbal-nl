from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class Club:
    club_id: str
    name: str
    city: str = ""

@dataclass(frozen=True, slots=True)
class Team:
    team_id: str
    name: str
    href: str | None = None
    logo_url: str | None = None

@dataclass(frozen=True, slots=True)
class TeamMetadata:
    team_id: str
    name: str
    days: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    competitions: tuple[str, ...] = ()
    subtitles: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class Player:
    name: str
    visible: bool = True

@dataclass(frozen=True, slots=True)
class StaffMember:
    name: str
    visible: bool = True

@dataclass(frozen=True, slots=True)
class PlayerDebug:
    http_ok: bool
    html_lengte: int
    spelers_sectie_lengte: int
    teammembers_gevonden: bool
    spelers_label_gevonden: bool
    afgeschermd_gevonden: int
    zichtbare_kandidaten_gevonden: int
    loginpagina: bool


@dataclass(slots=True)
class MatchRoute:
    status: str = "niet_berekend"
    fout: str | None = None
    vertrek_type: str | None = None
    vertrek_naam: str | None = None
    vertrek_latitude: float | None = None
    vertrek_longitude: float | None = None
    afstand_enkel_km: float | None = None
    afstand_retour_km: float | None = None
    reistijd_minuten: int | None = None

@dataclass(slots=True)
class Match:
    match_id: str
    team_id: str
    team_name: str
    date_text: str = ""
    date_iso: str | None = None
    time: str | None = None
    home_team: str = ""
    away_team: str = ""
    is_home: bool | None = None
    opponent: str = ""
    field_name: str | None = None
    accommodation: str | None = None
    street: str | None = None
    postal_city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    home_logo_url: str | None = None
    away_logo_url: str | None = None
    route: MatchRoute = field(default_factory=MatchRoute)

@dataclass(slots=True)
class ClubData:
    club: Club
    teams: list[Team] = field(default_factory=list)

@dataclass(slots=True)
class SelectedTeamData:
    club: Club
    team: Team
    metadata: TeamMetadata | None = None
    players: list[Player] = field(default_factory=list)
    hidden_players: int = 0
    staff: list[StaffMember] = field(default_factory=list)
    hidden_staff: int = 0
    player_debug: PlayerDebug | None = None
    selected_players: list[str] = field(default_factory=list)
    manual_players: list[str] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    program_source_count: int = 0
    program_candidate_count: int = 0
    program_debug: dict = field(default_factory=dict)
    driving_excluded: list[str] = field(default_factory=list)
    driving_extra: list[str] = field(default_factory=list)
    driving_unavailable_dates: list[dict] = field(default_factory=list)
    driving_cars: int = 4
    flagging_enabled: bool = False
    flagging_allowed: list[str] = field(default_factory=list)
    flagging_extra: list[str] = field(default_factory=list)
    training_sessions: list[dict] = field(default_factory=list)
    match_present_minutes: int = 45
    school_holidays_enabled: bool = False
    school_holiday_region: str = "auto"
    training_exception_dates: list[dict] = field(default_factory=list)
    training_calendar: list[dict] = field(default_factory=list)
    training_season: str = ""
    training_season_start: str = ""
    training_season_end: str = ""
    school_holiday_source: str = ""
    school_holidays: list[dict] = field(default_factory=list)
    season_export_data: dict = field(default_factory=dict)

@dataclass(slots=True)
class MultiTeamData:
    club: Club
    teams: list[SelectedTeamData] = field(default_factory=list)
