import json
import re

from sqlmodel import select

from backend import analytics
from backend.db import get_session
from backend.models import User
from tests.helpers import (
    log_bodyweight,
    log_climb,
    log_max_test,
    register,
    save_work_set,
)


def chart_payload(client):
    """Parse /dashboard's `#volume-trend-data` JSON-in-DOM payload."""
    page = client.get("/dashboard").text
    match = re.search(
        r'<script type="application/json" id="volume-trend-data">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert match, "no volume-trend-data payload on the dashboard"
    return json.loads(match.group(1))


def volume_points(client):
    """Parse /dashboard into {combo: [(date, volume), ...]} in page order."""
    page = client.get("/dashboard").text
    points = {}
    for combo, date, volume in re.findall(
        r'class="volume-point" data-combo="([^"]+)" data-date="([\d-]+)" '
        r'data-volume="([\d.]+)"',
        page,
    ):
        points.setdefault(combo, []).append((date, float(volume)))
    return points


def plateau_flags(client):
    page = client.get("/dashboard").text
    return set(re.findall(r'class="pill plateau-flag" data-combo="([^"]+)"', page))


def test_plateau_flag_on_stalled_but_not_growing_history(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    log_max_test(client, "left", "open hand", 10, "2026-05-01", "30")

    # Stalled: recent sessions never beat the earlier best (420).
    for day, volume in enumerate([400, 410, 420, 420, 415, 410, 420]):
        save_work_set(client, "left", 1, str(volume), "1",
                      date=f"2026-06-{day + 1:02d}")

    # Growing: volume keeps setting new highs.
    for day, volume in enumerate([300, 310, 320, 330, 340, 355]):
        save_work_set(client, "left", 1, str(volume), "1",
                      date=f"2026-06-{day + 1:02d}",
                      grip="open hand", edge_mm=10)

    assert plateau_flags(client) == {"left|half crimp|20"}


def test_plateau_flag_ignores_deload_sessions(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")

    # Stalled pattern (should be a plateau):
    for day, volume in enumerate([400, 410, 420, 420, 415, 410, 420]):
        save_work_set(client, "left", 1, str(volume), "1", date=f"2026-06-{day + 1:02d}")
    
    assert plateau_flags(client) == {"left|half crimp|20"}

    # Now mark the latest session as a deload
    client.post(
        "/session/update",
        data={
            "date": "2026-06-07",
            "is_deload": "on",
        },
        headers={"HX-Request": "true"}
    )
    
    # The 7th session (420) is ignored. The remaining 6 sessions are:
    # 400, 410, 420, 420, 415, 410
    # The 4 recent sessions are [420, 420, 415, 410]. Their max is 420.
    # The earlier sessions are [400, 410]. Their max is 410.
    # Since 420 is NOT <= 410, there is NO plateau detected when ignoring the deload!
    assert plateau_flags(client) == set()

def overtraining_flags(client):
    page = client.get("/dashboard").text
    return set(
        re.findall(r'class="pill overtraining-flag" data-combo="([^"]+)"', page)
    )


def test_overtraining_needs_both_volume_spike_and_short_rest(client):
    register(client)
    for grip, edge in (("half crimp", 20), ("half crimp", 10),
                       ("open hand", 20), ("open hand", 10)):
        log_max_test(client, "left", grip, edge, "2026-05-01", "40")

    def sessions(grip, edge, final_date, final_volume):
        # Steady baseline: 400 volume every 7 days...
        for date in ("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"):
            save_work_set(client, "left", 1, "400", "1", date=date,
                          grip=grip, edge_mm=edge)
        # ...then the final session under test.
        save_work_set(client, "left", 1, str(final_volume), "1",
                      date=final_date, grip=grip, edge_mm=edge)

    # spike (550 >= 1.25x400) + short rest (2 days vs typical 7) -> warning
    sessions("half crimp", 20, "2026-06-24", 550)
    # spike + normal rest -> no warning
    sessions("half crimp", 10, "2026-06-29", 550)
    # normal volume + short rest -> no warning
    sessions("open hand", 20, "2026-06-24", 410)
    # normal volume + normal rest -> no warning
    sessions("open hand", 10, "2026-06-29", 400)

    assert overtraining_flags(client) == {"left|half crimp|20"}


def test_dashboard_ships_the_full_ordered_volume_series_per_combo(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-06-03")
    save_work_set(client, "left", 1, "42.5", "5", date="2026-06-10")

    payload = chart_payload(client)
    assert payload == [
        {
            "combo": "left|half crimp|20",
            "dates": ["2026-06-03", "2026-06-10"],
            "volumes": [200.0, 212.5],
        }
    ]

    # The old server-rendered SVG route is gone.
    resp = client.get(
        "/dashboard/volume.svg?hand=left&grip_type_id=1&edge_mm=20"
    )
    assert resp.status_code == 404


def test_dashboard_shows_training_volume_per_session_per_combo(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")
    log_max_test(client, "left", "open hand", 10, "2026-06-01", "30")

    # Session 1: 40x5 + 40x5 = 400
    save_work_set(client, "left", 1, "40", "5", date="2026-06-03")
    save_work_set(client, "left", 2, "40", "5", date="2026-06-03")
    # Session 2: 42.5x5 + 40x5 = 412.5
    save_work_set(client, "left", 1, "42.5", "5", date="2026-06-10")
    save_work_set(client, "left", 2, "40", "5", date="2026-06-10")
    # A different combo trains the same day - kept separate.
    save_work_set(client, "left", 1, "30", "5", date="2026-06-10",
                  grip="open hand", edge_mm=10)

    points = volume_points(client)

    assert points["left|half crimp|20"] == [
        ("2026-06-03", 400.0),
        ("2026-06-10", 412.5),
    ]
    assert points["left|open hand|10"] == [("2026-06-10", 150.0)]


def db_session_and_user(client):
    session = next(client.app.dependency_overrides[get_session]())
    user = session.exec(select(User)).first()
    return session, user


def test_dashboard_view_empty_state(client):
    register(client)
    session, user = db_session_and_user(client)

    view = analytics.dashboard_view(session, user)

    assert view == {
        "combos": [],
        "chart_data": [],
        "correlation": {"points": [], "n": 0, "r": None},
    }


def test_dashboard_view_aggregation_encapsulation(client):
    register(client)
    # Set up user data:
    # Combo 1: stalled volume (plateau)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    for day, volume in enumerate([400, 410, 420, 420, 415, 410, 420]):
        save_work_set(
            client, "left", 1, str(volume), "1", date=f"2026-06-{day + 1:02d}"
        )

    # Combo 2: volume spike + short rest (overtraining warning)
    log_max_test(client, "left", "open hand", 10, "2026-05-01", "30")
    for date in ("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"):
        save_work_set(
            client, "left", 1, "400", "1", date=date, grip="open hand", edge_mm=10
        )
    save_work_set(
        client, "left", 1, "550", "1", date="2026-06-24", grip="open hand", edge_mm=10
    )

    # Climb + bodyweight for correlation
    log_bodyweight(client, "2026-06-01", "70")
    log_climb(client, "2026-06-05", "V4")

    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)

    assert "combos" in view
    assert "chart_data" in view
    assert "correlation" in view

    assert len(view["combos"]) == 2
    combo_map = {c["combo_key"]: c for c in view["combos"]}

    c1 = combo_map["left|half crimp|20"]
    assert c1["hand"] == "left"
    assert c1["grip_name"] == "half crimp"
    assert c1["edge_mm"] == 20
    assert c1["plateau"] is True
    assert c1["overtraining"] is False
    assert len(c1["trend"]) == 7

    c2 = combo_map["left|open hand|10"]
    assert c2["hand"] == "left"
    assert c2["grip_name"] == "open hand"
    assert c2["edge_mm"] == 10
    assert c2["plateau"] is False
    assert c2["overtraining"] is True
    assert len(c2["trend"]) == 5

    # Check chart_data format
    chart_map = {cd["combo"]: cd for cd in view["chart_data"]}
    assert "left|half crimp|20" in chart_map
    assert "left|open hand|10" in chart_map

    cd1 = chart_map["left|half crimp|20"]
    assert cd1["dates"] == [f"2026-06-{day + 1:02d}" for day in range(7)]
    assert cd1["volumes"] == [400.0, 410.0, 420.0, 420.0, 415.0, 410.0, 420.0]

    cd2 = chart_map["left|open hand|10"]
    assert cd2["dates"] == [
        "2026-06-01",
        "2026-06-08",
        "2026-06-15",
        "2026-06-22",
        "2026-06-24",
    ]
    assert cd2["volumes"] == [400.0, 400.0, 400.0, 400.0, 550.0]

    # Check correlation
    assert view["correlation"]["n"] == 1
    assert len(view["correlation"]["points"]) == 1
    assert view["correlation"]["points"][0]["grade"] == "V4"


def test_dashboard_view_excludes_combos_without_training_volume(client):
    register(client)
    # A max test recorded, but no training sessions/work sets logged for this combo.
    log_max_test(client, "left", "pinch", 45, "2026-05-01", "30")

    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)

    assert view["combos"] == []
    assert view["chart_data"] == []
