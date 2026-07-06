import re

from tests.helpers import log_climb, register, register_second_user


def climb_rows(client):
    """Parse the climbs page into (date, discipline, grade, style) tuples."""
    page = client.get("/climbs").text
    return re.findall(
        r'class="climb" data-discipline="(\w+)" data-grade="([^"]+)" '
        r'data-style="(\w+)" data-date="([\d-]+)"',
        page,
    )


def test_user_can_log_climbs_of_both_disciplines(client):
    register(client)

    log_climb(client, grade="V5", discipline="boulder", style="flash")
    log_climb(client, grade="7a+", discipline="sport", style="redpoint",
              date="2026-07-02", notes="second go after rest")

    rows = climb_rows(client)
    assert ("boulder", "V5", "flash", "2026-07-04") in rows
    assert ("sport", "7a+", "redpoint", "2026-07-02") in rows


def test_invalid_discipline_or_style_is_rejected(client):
    register(client)

    assert log_climb(client, discipline="trad").status_code == 400
    assert log_climb(client, style="dogged").status_code == 400
    assert climb_rows(client) == []


def test_climbs_are_scoped_to_the_logged_in_user(client):
    register(client, email="founder@example.com")
    log_climb(client, grade="V5")

    register_second_user(client)

    assert climb_rows(client) == []
