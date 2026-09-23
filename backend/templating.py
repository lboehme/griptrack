import datetime
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from backend.analytics import parse_boulder_grade

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def human_date(val: Any) -> str:
    """Format date for user display:
    'Tue 22 Sep' for current year, '22 Sep 2025' for other years.
    Handles date, datetime, or ISO string gracefully.
    """
    if val is None:
        return ""
    d: datetime.date
    if isinstance(val, datetime.datetime):
        d = val.date()
    elif isinstance(val, datetime.date):
        d = val
    elif isinstance(val, str):
        trimmed = val.strip()
        if not trimmed:
            return ""
        try:
            d = datetime.date.fromisoformat(trimmed[:10])
        except ValueError:
            return val
    else:
        return str(val)

    now = datetime.date.today()
    month_name = _MONTHS[d.month]
    if d.year == now.year:
        weekday_name = _WEEKDAYS[d.weekday()]
        return f"{weekday_name} {d.day} {month_name}"
    return f"{d.day} {month_name} {d.year}"


def display_name(val: Any) -> str:
    """Format enums and snake_case / lower-case values for user display:
    'left' -> 'Left', 'half_crimp' -> 'Half crimp', 'redpoint' -> 'Redpoint', etc.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    cleaned = s.replace("_", " ")
    return cleaned[:1].upper() + cleaned[1:]


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Badging unparsed boulder grades in _climb_list.html needs the same parser
# the correlation uses, so history/climbs stay in lockstep with analytics.py
# instead of duplicating the V/Font regex.
templates.env.globals["parse_boulder_grade"] = parse_boulder_grade
templates.env.globals["human_date"] = human_date
templates.env.filters["human_date"] = human_date
templates.env.globals["display_name"] = display_name
templates.env.filters["display_name"] = display_name
