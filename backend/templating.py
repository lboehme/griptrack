from pathlib import Path

from fastapi.templating import Jinja2Templates

from backend.analytics import parse_boulder_grade

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Badging unparsed boulder grades in _climb_list.html needs the same parser
# the correlation uses, so history/climbs stay in lockstep with analytics.py
# instead of duplicating the V/Font regex.
templates.env.globals["parse_boulder_grade"] = parse_boulder_grade
