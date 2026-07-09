import re
from datetime import date as date_type

from sqlmodel import select

from backend.db import get_session
from backend.models import Climb, User
from tests.helpers import log_climb, register, register_second_user


def climb_rows(client):
    """Parse the climbs page into (date, discipline, grade, style) tuples."""
    page = client.get("/climbs").text
    return re.findall(
        r'class="climb" data-discipline="(\w+)" data-grade="([^"]+)" '
        r'data-style="(\w+)" data-date="([\d-]+)"',
        page,
    )


def history_climb_rows(client):
    page = client.get("/history").text
    return re.findall(
        r'class="climb" data-discipline="(\w+)" data-grade="([^"]+)" '
        r'data-style="(\w+)" data-date="([\d-]+)"',
        page,
    )


def _seed_legacy_sport_climb(client, email="lifter@example.com", **fields):
    """Directly insert a discipline='sport' climb. The HTTP seam can no
    longer create these (issue #55 dropped the discipline picker — new
    climbs are always boulder), so this stands in for pre-existing
    production rows that must keep rendering unchanged."""
    session = next(client.app.dependency_overrides[get_session]())
    user = session.exec(select(User).where(User.email == email)).one()
    date_value = fields.get("date", "2026-07-02")
    if isinstance(date_value, str):
        date_value = date_type.fromisoformat(date_value)
    session.add(
        Climb(
            user_id=user.id,
            date=date_value,
            discipline="sport",
            grade=fields.get("grade", "7a+"),
            style=fields.get("style", "redpoint"),
            notes=fields.get("notes"),
        )
    )
    session.commit()
    session.close()


def test_logged_climbs_are_always_boulder(client):
    register(client)

    log_climb(client, grade="V5", style="flash")

    rows = climb_rows(client)
    assert ("boulder", "V5", "flash", "2026-07-04") in rows


def test_submitted_discipline_is_ignored_new_climbs_stay_boulder(client):
    register(client)

    # An attacker (or stale client) posting discipline=sport must not be
    # able to create a sport climb — the route hardcodes boulder.
    response = log_climb(client, grade="V5", discipline="sport")
    assert response.status_code == 200

    rows = climb_rows(client)
    assert ("boulder", "V5", "flash", "2026-07-04") in rows
    assert not any(row[0] == "sport" for row in rows)


def test_invalid_style_is_rejected(client):
    register(client)

    assert log_climb(client, style="dogged").status_code == 400
    assert climb_rows(client) == []


def test_climbs_are_scoped_to_the_logged_in_user(client):
    register(client, email="founder@example.com")
    log_climb(client, grade="V5")

    register_second_user(client)

    assert climb_rows(client) == []


def test_unparseable_grade_shows_immediate_feedback_and_is_still_saved(client):
    register(client)

    response = log_climb(
        client, grade="hard", style="flash", follow_redirects=False
    )

    # No redirect for the warning case — the warning is rendered directly.
    assert response.status_code == 200
    assert "grade" in response.text.lower()
    assert "recognized" in response.text.lower()
    assert "correlation" in response.text.lower()

    rows = climb_rows(client)
    assert ("boulder", "hard", "flash", "2026-07-04") in rows


def test_unparseable_grade_is_badged_in_history(client):
    register(client)
    log_climb(client, grade="hard", style="flash")

    page = client.get("/history").text
    assert "grade-unparsed" in page
    assert "not recognized" in page.lower()


def test_parseable_v_and_font_grades_show_no_warning_or_badge(client):
    register(client)

    v_response = log_climb(client, grade="V5", style="flash", date="2026-07-04")
    assert v_response.status_code in (200, 303)

    font_response = log_climb(
        client, grade="7A+", style="flash", date="2026-07-05"
    )
    assert font_response.status_code in (200, 303)

    climbs_page = client.get("/climbs").text
    assert "grade-unparsed" not in climbs_page
    assert "recognized" not in climbs_page.lower()

    history_page = client.get("/history").text
    assert "grade-unparsed" not in history_page


def test_existing_sport_rows_still_render_in_history_unchanged(client):
    register(client)
    log_climb(client, grade="V5", style="flash")
    _seed_legacy_sport_climb(client, grade="7a+", style="redpoint", date="2026-07-02")

    rows = history_climb_rows(client)
    assert ("boulder", "V5", "flash", "2026-07-04") in rows
    assert ("sport", "7a+", "redpoint", "2026-07-02") in rows

    page = client.get("/history").text
    # Legacy sport rows aren't badged as "unparsed" — they're excluded from
    # the correlation by discipline, not by a grade-parse failure.
    sport_li = re.search(r'<li class="climb"[^>]*data-discipline="sport"[^>]*>.*?</li>', page, re.DOTALL)
    assert sport_li is not None
    assert "grade-unparsed" not in sport_li.group(0)
