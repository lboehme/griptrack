from datetime import date as date_type

from sqlmodel import Session, select

from backend.analytics import parse_boulder_grade
from backend.models import CLIMB_STYLES, Climb, User

# New climbs are always logged as boulder (sport-climb logging was dropped —
# see issue #55; the discipline column and existing sport rows are untouched
# so history keeps rendering them).
NEW_CLIMB_DISCIPLINE = "boulder"


class InvalidStyleError(ValueError):
    """Raised when an unrecognized climb style is provided."""


def log_climb(
    session: Session,
    user: User,
    date: date_type,
    grade: str,
    style: str,
    notes: str | None = None,
) -> tuple[Climb, bool]:
    """Log a new climb for the user.

    Returns the persisted Climb and a boolean indicating whether the grade was
    recognized as a valid boulder grade for analytics.
    """
    if style not in CLIMB_STYLES:
        raise InvalidStyleError("Style must be one of: " + ", ".join(CLIMB_STYLES))

    climb = Climb(
        user_id=user.id,
        date=date,
        discipline=NEW_CLIMB_DISCIPLINE,
        grade=grade,
        style=style,
        notes=notes,
    )
    session.add(climb)
    session.commit()
    session.refresh(climb)

    recognized_grade = parse_boulder_grade(grade) is not None
    return climb, recognized_grade


def climbs_newest_first(session: Session, user: User) -> list[Climb]:
    """A user's climbs, newest first — the one query both the climbs page
    and the history page render from, so their ordering can't drift."""
    return list(
        session.exec(
            select(Climb)
            .where(Climb.user_id == user.id)
            .order_by(Climb.date.desc(), Climb.id.desc())
        ).all()
    )


climb_history = climbs_newest_first
