"""Constants for the unofficial eBichelchen integration."""

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "ebichelchen"
NAME = "eBichelchen"
BASE_URL = "https://ssl.education.lu/ebichelchen/app"
API_URL = BASE_URL + "/api"
SCHOOL_TZ = ZoneInfo("Europe/Luxembourg")
CONF_STUDENTS = "students"
CONF_REFRESH = "refresh_minutes"
DEFAULT_REFRESH = 30
LOOKAHEAD = timedelta(days=28)
ALLOWED_HOSTS = frozenset({"ssl.education.lu", "auth.education.lu", "iam.auth.education.lu"})
