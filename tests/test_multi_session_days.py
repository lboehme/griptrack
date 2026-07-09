"""Multi-session days (issue #51): session_number lets a (user, date) hold
more than one TrainingSession — a morning and evening pull stay
independent instead of silently merging."""

import re
from datetime import date as date_type
from datetime import timedelta

from tests.helpers import (
<<<<<<< HEAD
    get_session_page,
=======
>>>>>>> origin/main
    grip_type_id,
    log_max_test,
    register,
    save_work_set,
)


def setup_tested_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")


def workset_rows(page_text):
    rows = {}
    for hand, set_number, block in re.findall(
        r'<td class="workset-cell" data-hand="(\w+)" data-set="(\d+)">(.*?)</td>',
        page_text,
        re.DOTALL,
    ):
        weight = re.search(r'name="weight" value="([^"]*)"', block).group(1)
        rows[(hand, int(set_number))] = weight
    return rows


def volume_points(client):
    page = client.get("/dashboard").text
    points = {}
    for combo, date, volume in re.findall(
        r'class="volume-point" data-combo="([^"]+)" data-date="([\d-]+)" '
        r'data-volume="([\d.]+)"',
        page,
    ):
        points.setdefault(combo, []).append((date, float(volume)))
    return points


def test_two_sessions_same_date_have_independent_work_sets(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")

    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-04")

    # A second session, same date, explicit session_number=2.
    client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id,
            "edge_mm": 20,
            "date": "2026-07-04",
            "hand": "left",
            "set_number": 1,
            "weight": "30",
            "reps": "8",
            "session_number": 2,
        },
    )

    page1 = client.get(
        "/session/worksets",
        params={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "session_number": 1,
        },
    ).text
    page2 = client.get(
        "/session/worksets",
        params={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "session_number": 2,
        },
    ).text

    assert workset_rows(page1)[("left", 1)] == "42.5"
    assert workset_rows(page2)[("left", 1)] == "30.0"


def test_two_sessions_same_date_have_independent_volume(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")

    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")  # session 1: 200
    client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "hand": "left", "set_number": 1, "weight": "35", "reps": "5",
            "session_number": 2,
        },
    )  # session 2: 175

    points = volume_points(client)["left|half crimp|20"]

    assert ("2026-07-04", 200.0) in points
    assert ("2026-07-04", 175.0) in points
    assert len(points) == 2


def test_default_flows_land_on_the_days_latest_session(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")

    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "hand": "left", "set_number": 1, "weight": "50", "reps": "3",
            "session_number": 2,
        },
    )

    # No session_number given -> resolves to session 2 (the latest).
    page = client.get(
        "/session/worksets",
        params={"grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04"},
    ).text

    assert workset_rows(page)[("left", 1)] == "50.0"


def test_second_session_affordance_only_appears_once_today_has_one(client):
    setup_tested_user(client)
    today = date_type.today().isoformat()

    before = client.get("/session/new").text
    assert "start-second-session" not in before

    grip_id = grip_type_id(client, "half crimp")
    client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id, "edge_mm": 20, "date": today,
            "hand": "left", "set_number": 1, "weight": "40", "reps": "5",
        },
    )

    after = client.get("/session/new").text
    assert "start-second-session" in after
<<<<<<< HEAD
    assert f'name="session_number" value="2"' in after
=======
    assert 'name="session_number" value="2"' in after
>>>>>>> origin/main


def test_starting_a_second_session_today_gets_its_own_session_number(client):
    setup_tested_user(client)
    today = date_type.today().isoformat()
    grip_id = grip_type_id(client, "half crimp")

    save_work_set(client, "left", 1, "40", "5", date=today)

    # Explicitly requesting session_number=2 for today (no gate — today is
    # never past) creates a second, independent session.
    client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id, "edge_mm": 20, "date": today,
            "hand": "left", "set_number": 1, "weight": "20", "reps": "10",
            "session_number": 2,
        },
    )

    page1 = client.get(
        "/session/worksets",
        params={
            "grip_type_id": grip_id, "edge_mm": 20, "date": today,
            "session_number": 1,
        },
    ).text
    page2 = client.get(
        "/session/worksets",
        params={
            "grip_type_id": grip_id, "edge_mm": 20, "date": today,
            "session_number": 2,
        },
    ).text
    assert workset_rows(page1)[("left", 1)] == "40.0"
    assert workset_rows(page2)[("left", 1)] == "20.0"


def test_past_date_with_no_session_shows_confirm_prompt_and_creates_nothing(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")
    past_date = "2020-01-15"

    page = client.get(
        "/session/warmup",
        params={"grip_type_id": grip_id, "edge_mm": 20, "date": past_date},
    )

    assert page.status_code == 200
    assert "session-confirm-card" in page.text
    assert 'class="ramp-weight"' not in page.text

    # Still nothing in history for that date.
    history = client.get("/history").text
    assert f'data-date="{past_date}"' not in history


def test_past_date_confirmation_creates_the_session_then_proceeds(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")
    past_date = "2020-01-15"

    client.post(
        "/session/create",
        data={
            "page": "warmup", "grip_type_id": grip_id, "edge_mm": 20,
            "date": past_date,
        },
        follow_redirects=True,
    )

    # Now the plain GET renders the real warmup page, no more prompt.
    page = client.get(
        "/session/warmup",
        params={"grip_type_id": grip_id, "edge_mm": 20, "date": past_date},
    )
    assert "session-confirm-card" not in page.text
    assert 'class="ramp-weight"' in page.text


def test_past_date_worksets_page_also_gates_creation(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")
    past_date = "2020-01-15"

    page = client.get(
        "/session/worksets",
        params={"grip_type_id": grip_id, "edge_mm": 20, "date": past_date},
    )

    assert "session-confirm-card" in page.text
    assert 'class="workset-cell"' not in page.text


def test_today_still_creates_implicitly_with_no_confirmation_needed(client):
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")
    today = date_type.today().isoformat()

    page = client.get(
        "/session/warmup",
        params={"grip_type_id": grip_id, "edge_mm": 20, "date": today},
    )

    assert "session-confirm-card" not in page.text
    assert 'class="ramp-weight"' in page.text


def test_yesterday_with_a_recent_session_needs_no_confirmation(client):
    """The gate only fires when there is genuinely no session yet — an
    existing past session (retro-logging) is editable in one step."""
    setup_tested_user(client)
    grip_id = grip_type_id(client, "half crimp")
    yesterday = (date_type.today() - timedelta(days=1)).isoformat()

    save_work_set(client, "left", 1, "40", "5", date=yesterday)

    page = client.get(
        "/session/warmup",
        params={"grip_type_id": grip_id, "edge_mm": 20, "date": yesterday},
    )
    assert "session-confirm-card" not in page.text
    assert 'class="ramp-weight"' in page.text


def test_existing_migration_data_lands_on_session_number_one(client):
    """Sessions created before this slice (i.e. with no explicit
    session_number) default to 1 — the migration's backfill value."""
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    grip_id = grip_type_id(client, "half crimp")
    page = client.get(
        "/session/worksets",
        params={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "session_number": 1,
        },
    ).text
    assert workset_rows(page)[("left", 1)] == "40.0"
