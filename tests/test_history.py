import re

from tests.helpers import (
    log_climb,
    log_max_test,
    register,
    register_second_user,
    save_work_set,
)


def history_sessions(client):
    """Parse /history into {date: [(hand, set_number, weight, reps), ...]}."""
    page = client.get("/history").text
    sessions = {}
    for date, block in re.findall(
        r'class="history-session" data-date="([\d-]+)"(.*?)</details>',
        page,
        re.DOTALL,
    ):
        sessions[date] = re.findall(
            r'class="history-set" data-hand="(\w+)" data-set="(\d+)" '
            r'data-weight="([\d.]+)" data-reps="(\d+)"',
            block,
        )
    return sessions


def history_climbs(client):
    page = client.get("/history").text
    return re.findall(
        r'class="climb" data-discipline="(\w+)" data-grade="([^"]+)" '
        r'data-style="(\w+)" data-date="([\d-]+)"',
        page,
    )


def test_history_lists_own_climbs(client):
    register(client)
    client.post(
        "/climbs",
        data={"date": "2026-07-03", "discipline": "boulder", "grade": "V5",
              "style": "flash"},
    )

    assert ("boulder", "V5", "flash", "2026-07-03") in history_climbs(client)


def test_history_never_shows_another_users_data(client):
    register(client, email="founder@example.com")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-04")
    log_climb(client, date="2026-07-03", grade="V5")

    register_second_user(client)

    # Logged in as friend: founder's history is invisible.
    assert history_sessions(client) == {}
    assert history_climbs(client) == []


def test_history_lists_own_sessions_expandable_to_work_sets(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-04")
    save_work_set(client, "right", 1, "40", "5", date="2026-07-04")
    save_work_set(client, "left", 1, "43.75", "5", date="2026-07-07")

    sessions = history_sessions(client)

    assert set(sessions) == {"2026-07-04", "2026-07-07"}
    assert ("left", "1", "42.5", "5") in sessions["2026-07-04"]
    assert ("right", "1", "40.0", "5") in sessions["2026-07-04"]
    assert sessions["2026-07-07"] == [("left", "1", "43.75", "5")]
