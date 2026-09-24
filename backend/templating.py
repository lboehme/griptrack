import datetime
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from backend.analytics import parse_boulder_grade
from backend.plates import plate_breakdown

# V-scale floor for each gym-circuit grade colour band (V2 of
# docs/ui-review-2026-09.md): 6A/6A+ = V3 ... 7B and up = V8+. Below V3
# (below 6A) has no band in the spec, so it renders with no colour.
_GRADE_COLOR_BANDS: list[tuple[float, str]] = [
    (8.0, "var(--grade-7b)"),
    (6.0, "var(--grade-7a)"),
    (5.0, "var(--grade-6c)"),
    (4.0, "var(--grade-6b)"),
    (3.0, "var(--grade-6a)"),
]

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


def grade_color(grade: Any) -> str:
    """CSS var() reference for a boulder grade's gym-circuit colour band
    (V2), or "" when the grade doesn't parse or falls below the lowest
    banded grade (6A) — callers treat "" as "no colour"."""
    v = parse_boulder_grade(str(grade)) if grade is not None else None
    if v is None:
        return ""
    for floor, color in _GRADE_COLOR_BANDS:
        if v >= floor:
            return color
    return ""


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Badging unparsed boulder grades in _climb_list.html needs the same parser
# the correlation uses, so history/climbs stay in lockstep with analytics.py
# instead of duplicating the V/Font regex.
templates.env.globals["parse_boulder_grade"] = parse_boulder_grade
templates.env.globals["human_date"] = human_date
templates.env.filters["human_date"] = human_date
templates.env.globals["display_name"] = display_name
templates.env.filters["display_name"] = display_name
templates.env.filters["grade_color"] = grade_color
templates.env.globals["plate_breakdown"] = plate_breakdown
templates.env.filters["num_trim"] = lambda v: f"{v:g}"
