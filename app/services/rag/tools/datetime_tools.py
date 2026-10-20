import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool

WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def app_timezone_name() -> str:
    return os.getenv("APP_TIMEZONE", "UTC")


def current_weekday() -> str:
    now = datetime.now(ZoneInfo(app_timezone_name()))
    return WEEKDAY_NAMES[now.weekday()]


def make_datetime_tools():
    timezone_name = app_timezone_name()

    async def get_current_date() -> str:
        """Return today's date and day of week in the app timezone."""
        now = datetime.now(ZoneInfo(timezone_name))
        day_of_week = WEEKDAY_NAMES[now.weekday()]
        return json.dumps(
            {
                "date": now.date().isoformat(),
                "day_of_week": day_of_week,
                "day_of_week_label": day_of_week.capitalize(),
                "timezone": timezone_name,
            }
        )

    return [
        StructuredTool.from_function(
            coroutine=get_current_date,
            name="get_current_date",
            description=(
                "Get today's date and day of week. "
                "Use before answering questions about 'today', 'tomorrow', or this week's workout. "
                "Workout days in the database use lowercase names (e.g. tuesday)."
            ),
        ),
    ]
