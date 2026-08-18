DOMAIN = "ha_voetbal_nl"
BASE_URL = "https://www.voetbal.nl"
LOGIN_PATH = "/inloggen"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_CLUB_QUERY = "club_query"
CONF_CLUB_ID = "club_id"
CONF_CLUB_NAME = "club_name"
CONF_CLUB_CITY = "club_city"
CONF_TEAM_IDS = "team_ids"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 Chrome/151.0 Safari/537.36"
)

PLATFORMS = ["sensor"]

CONF_PLAYER_MANAGEMENT = "player_management"

CONF_ROUTE_API_KEY = "route_api_key"
CONF_ROUTE_TEAM_ORIGINS = "route_team_origins"
CONF_ROUTE_ORIGIN_MODE = "mode"
CONF_ROUTE_ORIGIN_NAME = "name"
CONF_ROUTE_ORIGIN_LATITUDE = "latitude"
CONF_ROUTE_ORIGIN_LONGITUDE = "longitude"
ROUTE_ORIGIN_CLUB = "club"
ROUTE_ORIGIN_CUSTOM = "custom"
# v0.7.3: no program match limit; kept out of runtime use.

CONF_DRIVING_MANAGEMENT = "driving_management"
CONF_DRIVING_CARS = "cars_per_away_match"
CONF_DRIVING_EXCLUDED = "excluded_drivers"
DEFAULT_DRIVING_CARS = 4

# v0.9.0: trainingsschema en verzameltijd wedstrijden
CONF_TRAINING_MANAGEMENT = "training_management"
CONF_MATCH_PRESENT_MINUTES = "match_present_minutes"
DEFAULT_MATCH_PRESENT_MINUTES = 45

SCHOOL_HOLIDAY_API = "https://opendata.rijksoverheid.nl/v1/infotypes/schoolholidays"
DEFAULT_SCHOOL_HOLIDAY_REGION = "auto"

CONF_MATCH_MANAGEMENT = "match_management"

CONF_DRIVING_ADD_SUPPLEMENT = "add_supplemental_schedule"
CONF_DRIVING_EXTRA_DRIVERS = "extra_drivers"
CONF_DRIVING_EXTRA_MANUAL = "extra_drivers_manual"
# v0.10.3: per-match temporary driver unavailability
CONF_DRIVING_UNAVAILABLE = "temporary_driver_unavailability"

# v0.10.0: optional assistant-referee/flagger planning per team
CONF_FLAGGING_MANAGEMENT = "flagging_management"
CONF_FLAGGING_ENABLED = "enabled"
CONF_FLAGGING_ALLOWED = "flaggers"
CONF_FLAGGING_EXTRA = "extra_flaggers"
CONF_FLAGGING_EXTRA_MANUAL = "extra_flaggers_manual"
CONF_FLAGGING_REBUILD = "rebuild_match_tasks"

# v0.9.7: PDF season export
SERVICE_GENERATE_SEASON_PDF = "genereer_seizoens_pdf"
SERVICE_SEND_SEASON_PDF = "stuur_seizoens_pdf"
SERVICE_SEND_SEASON_PDF_DASHBOARD = "verstuur_seizoens_pdf"
ATTR_TEAM_ID = "team_id"
ATTR_FILENAME = "bestandsnaam"

# v0.9.14: WhatsApp/WAHA attendance polls
CONF_WAHA_MANAGEMENT = "waha_management"
CONF_WAHA_BASE_URL = "base_url"
CONF_WAHA_API_KEY = "api_key"
CONF_WAHA_SESSION = "session"
CONF_WAHA_WEBHOOK_BASE_URL = "webhook_base_url"
CONF_WAHA_WEBHOOK_LOCAL_ONLY = "webhook_local_only"
CONF_WAHA_TEAMS = "teams"
CONF_WAHA_TEST_GROUP_ID = "test_group_id"
CONF_WAHA_TEST_GROUP_NAME = "test_group_name"
CONF_WAHA_PROD_GROUP_ID = "prod_group_id"
CONF_WAHA_PROD_GROUP_NAME = "prod_group_name"
CONF_WAHA_ASSISTANT_NAME = "assistant_name"
CONF_WAHA_IDENTITY_MAPPINGS = "identity_mappings"
# v0.10.9: per-team WhatsApp attendance communication mode
CONF_WAHA_ATTENDANCE_MODE = "attendance_mode"
WAHA_ATTENDANCE_MODE_POLLS = "polls"
WAHA_ATTENDANCE_MODE_MESSAGES = "messages"
DEFAULT_WAHA_ATTENDANCE_MODE = WAHA_ATTENDANCE_MODE_POLLS

SERVICE_SEND_ATTENDANCE_POLL = "verstuur_aanwezigheidspoll"
ATTR_TEST_MODE = "testmodus"
ATTR_MATCH_ID = "wedstrijd_id"

# v0.9.17: lifecycle and reminder control around attendance polls
SERVICE_CHECK_ATTENDANCE = "controleer_aanwezigheid"
SERVICE_SIMULATE_ATTENDANCE = "simuleer_aanwezigheidsstatus"
SERVICE_SIMULATE_SCHEDULER = "simuleer_scheduler"
SERVICE_SHOW_ATTENDANCE_STATUS = "toon_aanwezigheidsstatus"
ATTR_PERSON = "persoon"
ATTR_STATUS = "status"
ATTR_SCHEDULER_PHASE = "fase"
# v0.9.20: per-team configurable poll/reminder planning
CONF_WAHA_POLL_DAYS_BEFORE = "poll_days_before"
CONF_WAHA_POLL_TIME = "poll_time"
CONF_WAHA_REMINDER_DAYS_BEFORE = "reminder_days_before"
CONF_WAHA_REMINDER_TIME = "reminder_time"
CONF_WAHA_PRODUCTION_ENABLED = "production_enabled"
DEFAULT_POLL_DAYS_BEFORE = 3
DEFAULT_POLL_TIME = "19:00"
DEFAULT_REMINDER_DAYS_BEFORE = 1
DEFAULT_REMINDER_TIME = "19:00"
POLL_SCHEDULER_INTERVAL_MINUTES = 5

ATTENDANCE_PRESENT = "aanwezig"
ATTENDANCE_ABSENT = "afwezig"
ATTENDANCE_INJURED = "geblesseerd"
ATTENDANCE_UNKNOWN = "niet_gereageerd"

# v0.9.24: training attendance polls and configurable training scheduler
CONF_TRAINING_POLL_DAYS_BEFORE = "poll_days_before"
CONF_TRAINING_POLL_TIME = "poll_time"
CONF_TRAINING_REMINDER_DAYS_BEFORE = "reminder_days_before"
CONF_TRAINING_REMINDER_TIME = "reminder_time"
CONF_TRAINING_PRODUCTION_ENABLED = "production_enabled"
DEFAULT_TRAINING_POLL_DAYS_BEFORE = 2
DEFAULT_TRAINING_POLL_TIME = "19:00"
DEFAULT_TRAINING_REMINDER_DAYS_BEFORE = 1
DEFAULT_TRAINING_REMINDER_TIME = "19:00"
SERVICE_SEND_TRAINING_POLL = "verstuur_trainingspoll"
SERVICE_CHECK_TRAINING_ATTENDANCE = "controleer_training_aanwezigheid"
SERVICE_SIMULATE_TRAINING_SCHEDULER = "simuleer_training_scheduler"
SERVICE_SHOW_TRAINING_ATTENDANCE_STATUS = "toon_training_aanwezigheidsstatus"
ATTR_TRAINING_ID = "training_id"

# v0.9.28: matchday and training-day WhatsApp information messages
CONF_MATCHDAY_MESSAGE_ENABLED = "matchday_message_enabled"
CONF_MATCHDAY_MESSAGE_TIME = "matchday_message_time"
CONF_MATCHDAY_WEATHER_ENABLED = "matchday_weather_enabled"
DEFAULT_MATCHDAY_MESSAGE_TIME = "09:00"
CONF_TRAINING_INFO_ENABLED = "training_info_enabled"
CONF_TRAINING_INFO_HOURS_BEFORE = "training_info_hours_before"
CONF_TRAINING_WEATHER_ENABLED = "training_weather_enabled"
CONF_TRAINING_ATTENDANCE_SUMMARY_ENABLED = "training_attendance_summary_enabled"
DEFAULT_TRAINING_INFO_HOURS_BEFORE = 2
SERVICE_SEND_MATCHDAY_INFO = "verstuur_wedstrijddagbericht"
SERVICE_SEND_TRAINING_INFO = "verstuur_trainingsdagbericht"

# v0.9.30: optional Gemini-generated coach messages
CONF_GEMINI_API_KEY = "gemini_api_key"
CONF_GEMINI_MODEL = "gemini_model"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
CONF_MATCHDAY_COACH_ENABLED = "matchday_coach_enabled"
CONF_TRAINING_COACH_ENABLED = "training_coach_enabled"
