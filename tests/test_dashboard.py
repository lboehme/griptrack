import json
import re
from datetime import date as date_type

from sqlmodel import select

from backend import analytics
from backend.db import get_session
from backend.models import User
from tests.helpers import (
    log_bodyweight,
    log_climb,
    log_max_test,
    login,
    register,
    register_second_user,
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


def asymmetry_chart_payload(client):
    """Parse /dashboard's `#asymmetry-chart-data` JSON-in-DOM payload."""
    page = client.get("/dashboard").text
    match = re.search(
        r'<script type="application/json" id="asymmetry-chart-data">(.*?)</script>',
        page,
        re.DOTALL,
    )
    return json.loads(match.group(1)) if match else None


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


def _asymmetry_points(client, series):
    """Parse /dashboard into {combo: [(date, gap), ...]} for the given
    asymmetry series ("strength" or "load"), in page order."""
    page = client.get("/dashboard").text
    points = {}
    for combo, date, gap in re.findall(
        r'class="asymmetry-point"[^>]*data-combo="([^"]+)"[^>]*data-series="'
        + series
        + r'"[^>]*data-date="([\d-]+)" '
        r'data-gap="([-\d.]+)"',
        page,
    ):
        points.setdefault(combo, []).append((date, float(gap)))
    return points


def strength_asymmetry_points(client):
    """Parse /dashboard into {combo: [(date, gap), ...]} for strength series."""
    return _asymmetry_points(client, "strength")


def load_asymmetry_points(client):
    """Parse /dashboard into {combo: [(date, gap), ...]} for load series."""
    return _asymmetry_points(client, "load")


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


def asymmetry_warning_flags(client):
    page = client.get("/dashboard").text
    return set(
        re.findall(
            r'class="pill asymmetry-warning-flag" data-combo="([^"]+)"', page
        )
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


def test_dashboard_ships_the_full_ordered_volume_and_intensity_series_per_combo(client):
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
            "intensity_dates": ["2026-06-03", "2026-06-10"],
            "intensities": [1.0, 1.0],
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
        "asymmetry_pairs": [],
        "asymmetry_chart_data": [],
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
    assert "asymmetry_pairs" in view
    assert "asymmetry_chart_data" in view

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
    assert view["asymmetry_pairs"] == []
    assert view["asymmetry_chart_data"] == []


def test_strength_gap_trend_signed_calculation_in_both_directions(client):
    register(client)
    # L > R (positive %): L=50, R=40 -> (50 - 40)/50 * 100 = +20.0%
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "50")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40")

    # Equal (0%): Right logs a 50kg WorkSet on 2026-05-10 -> L=50, R=50 -> 0.0%
    save_work_set(client, "right", 1, "50", "5", date="2026-05-10")

    # R > L (negative %): Right logs a 62.5kg WorkSet on 2026-05-20 -> L=50, R=62.5 -> (50 - 62.5)/62.5 * 100 = -20.0%
    save_work_set(client, "right", 1, "62.5", "5", date="2026-05-20")

    session, user = db_session_and_user(client)
    trend = analytics.strength_gap_trend(session, user, 1, 20)
    assert trend == [
        (date_type(2026, 5, 1), 20.0),
        (date_type(2026, 5, 10), 0.0),
        (date_type(2026, 5, 20), -20.0),
    ]

    # HTTP seam
    payload = asymmetry_chart_payload(client)
    assert payload == [
        {
            "combo": "asymmetry|half crimp|20",
            "grip_name": "half crimp",
            "edge_mm": 20,
            "strength_dates": ["2026-05-01", "2026-05-10", "2026-05-20"],
            "strength_gaps": [20.0, 0.0, -20.0],
            "load_dates": [],
            "load_gaps": [],
        }
    ]

    pts = strength_asymmetry_points(client)
    assert pts["asymmetry|half crimp|20"] == [
        ("2026-05-01", 20.0),
        ("2026-05-10", 0.0),
        ("2026-05-20", -20.0),
    ]


def test_asymmetry_omits_dates_where_either_hand_lacks_current_max(client):
    register(client)
    # 2026-04-01: only left tested -> no asymmetry point
    log_max_test(client, "left", "half crimp", 20, "2026-04-01", "40")

    # 2026-04-10: only left trained -> right still lacks CurrentMax -> no asymmetry point
    save_work_set(client, "left", 1, "45", "5", date="2026-04-10")

    # 2026-04-20: right tested -> now BOTH hands have CurrentMax (L=45, R=50) -> point produced!
    log_max_test(client, "right", "half crimp", 20, "2026-04-20", "50")

    # 2026-04-25: right trained -> L=45, R=55 -> point produced!
    save_work_set(client, "right", 1, "55", "5", date="2026-04-25")

    session, user = db_session_and_user(client)
    trend = analytics.strength_gap_trend(session, user, 1, 20)
    assert len(trend) == 2
    assert trend[0] == (date_type(2026, 4, 20), (45.0 - 50.0) / 50.0 * 100.0)
    assert trend[1] == (date_type(2026, 4, 25), (45.0 - 55.0) / 55.0 * 100.0)

    payload = asymmetry_chart_payload(client)
    assert payload is not None
    assert payload[0]["strength_dates"] == ["2026-04-20", "2026-04-25"]


def test_asymmetry_omits_combo_tested_on_only_one_hand(client):
    register(client)
    # Combo 1: tested on both hands
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40")

    # Combo 2: tested ONLY on left hand
    log_max_test(client, "left", "open hand", 10, "2026-05-01", "30")

    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)

    asym_keys = [p["combo_key"] for p in view["asymmetry_pairs"]]
    assert asym_keys == ["asymmetry|half crimp|20"]
    assert "asymmetry|open hand|10" not in asym_keys

    payload = asymmetry_chart_payload(client)
    assert payload is not None
    assert len(payload) == 1
    assert payload[0]["combo"] == "asymmetry|half crimp|20"


def test_dashboard_omits_asymmetry_section_when_no_paired_data(client):
    register(client)
    # Completely empty user
    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)
    assert view["asymmetry_pairs"] == []
    assert view["asymmetry_chart_data"] == []

    page = client.get("/dashboard").text
    assert "asymmetry-card" not in page
    assert asymmetry_chart_payload(client) is None

    # User with single-hand test only
    log_max_test(client, "left", "pinch", 45, "2026-05-01", "30")
    view = analytics.dashboard_view(session, user)
    assert view["asymmetry_pairs"] == []
    assert view["asymmetry_chart_data"] == []

    page = client.get("/dashboard").text
    assert "asymmetry-card" not in page
    assert asymmetry_chart_payload(client) is None


def test_asymmetry_per_user_data_isolation(client):
    register(client, email="userA@example.com")
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "50")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40")

    register_second_user(client, email="userB@example.com")
    # User B has no data yet
    assert asymmetry_chart_payload(client) is None

    # User B logs their own data on a different combo
    log_max_test(client, "left", "open hand", 10, "2026-05-05", "30")
    log_max_test(client, "right", "open hand", 10, "2026-05-05", "36")

    user_b_payload = asymmetry_chart_payload(client)
    assert user_b_payload == [
        {
            "combo": "asymmetry|open hand|10",
            "grip_name": "open hand",
            "edge_mm": 10,
            "strength_dates": ["2026-05-05"],
            "strength_gaps": [-16.666666666666664],
            "load_dates": [],
            "load_gaps": [],
        }
    ]

    # Switch back to User A
    login(client, "userA@example.com", "test-pw-1234")
    user_a_payload = asymmetry_chart_payload(client)
    assert user_a_payload == [
        {
            "combo": "asymmetry|half crimp|20",
            "grip_name": "half crimp",
            "edge_mm": 20,
            "strength_dates": ["2026-05-01"],
            "strength_gaps": [20.0],
            "load_dates": [],
            "load_gaps": [],
        }
    ]


def test_asymmetry_ignores_voided_max_tests(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-05-01", "40")

    # Verify asymmetry exists
    assert asymmetry_chart_payload(client) is not None

    # Void all max tests
    page = client.get("/max-tests").text
    void_actions = re.findall(r'action="/max-tests/(\d+)/void"', page)
    for test_id in void_actions:
        client.post(f"/max-tests/{test_id}/void", follow_redirects=True)

    # Now tests are voided -> no asymmetry data
    assert asymmetry_chart_payload(client) is None


def test_load_gap_trend_signed_calculation_in_both_directions(client):
    register(client)
    # Session 1 (2026-06-01): L > R (+20.0%)
    # Left: 50kg x 5 = 250; Right: 40kg x 5 = 200 -> (250 - 200) / 250 * 100 = +20.0%
    save_work_set(client, "left", 1, "50", "5", date="2026-06-01")
    save_work_set(client, "right", 1, "40", "5", date="2026-06-01")

    # Session 2 (2026-06-05): Equal (0.0%)
    # Left: 40kg x 5 = 200; Right: 40kg x 5 = 200 -> (200 - 200) / 200 * 100 = 0.0%
    save_work_set(client, "left", 1, "40", "5", date="2026-06-05")
    save_work_set(client, "right", 1, "40", "5", date="2026-06-05")

    # Session 3 (2026-06-10): R > L (-20.0%)
    # Left: 40kg x 5 = 200; Right: 50kg x 5 = 250 -> (200 - 250) / 250 * 100 = -20.0%
    save_work_set(client, "left", 1, "40", "5", date="2026-06-10")
    save_work_set(client, "right", 1, "50", "5", date="2026-06-10")

    session, user = db_session_and_user(client)
    trend = analytics.load_gap_trend(session, user, 1, 20)
    assert trend == [
        (date_type(2026, 6, 1), 20.0),
        (date_type(2026, 6, 5), 0.0),
        (date_type(2026, 6, 10), -20.0),
    ]

    # HTTP seam: verify JSON payload and list elements
    payload = asymmetry_chart_payload(client)
    assert payload == [
        {
            "combo": "asymmetry|half crimp|20",
            "grip_name": "half crimp",
            "edge_mm": 20,
            "strength_dates": [],
            "strength_gaps": [],
            "load_dates": ["2026-06-01", "2026-06-05", "2026-06-10"],
            "load_gaps": [20.0, 0.0, -20.0],
        }
    ]

    load_pts = load_asymmetry_points(client)
    assert load_pts["asymmetry|half crimp|20"] == [
        ("2026-06-01", 20.0),
        ("2026-06-05", 0.0),
        ("2026-06-10", -20.0),
    ]


def test_load_gap_trend_omits_sessions_where_only_one_hand_trained(client):
    register(client)
    # Session 1: only left logged work sets -> no load gap point
    save_work_set(client, "left", 1, "40", "5", date="2026-06-01")

    # Session 2: both hands logged work sets -> point produced
    save_work_set(client, "left", 1, "50", "5", date="2026-06-05")
    save_work_set(client, "right", 1, "40", "5", date="2026-06-05")

    # Session 3: only right logged work sets -> no load gap point
    save_work_set(client, "right", 1, "40", "5", date="2026-06-10")

    # Session 4: deload session where both hands logged work sets -> excluded from trend
    save_work_set(client, "left", 1, "30", "5", date="2026-06-15")
    save_work_set(client, "right", 1, "30", "5", date="2026-06-15")
    client.post(
        "/session/update",
        data={"date": "2026-06-15", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )

    session, user = db_session_and_user(client)
    trend = analytics.load_gap_trend(session, user, 1, 20)
    assert trend == [(date_type(2026, 6, 5), 20.0)]

    payload = asymmetry_chart_payload(client)
    assert payload is not None
    assert payload[0]["load_dates"] == ["2026-06-05"]
    assert payload[0]["load_gaps"] == [20.0]


def test_combos_with_only_session_estimate_renders_load_gap_series_and_appears_on_dashboard(client):
    register(client)
    # Bilateral work sets without any MaxWeightTest (trained under SessionMaxEstimate)
    save_work_set(client, "left", 1, "35", "5", date="2026-06-01")
    save_work_set(client, "right", 1, "30", "5", date="2026-06-01")

    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)

    assert len(view["asymmetry_pairs"]) == 1
    pair = view["asymmetry_pairs"][0]
    assert pair["combo_key"] == "asymmetry|half crimp|20"
    assert pair["strength_trend"] == []
    assert len(pair["load_trend"]) == 1
    assert pair["load_trend"][0] == (date_type(2026, 6, 1), (175.0 - 150.0) / 175.0 * 100.0)

    # HTTP seam
    page = client.get("/dashboard").text
    assert "asymmetry-card" in page
    assert "Training Load Gap" in page
    assert "Strength Max Gap" not in page

    payload = asymmetry_chart_payload(client)
    assert payload == [
        {
            "combo": "asymmetry|half crimp|20",
            "grip_name": "half crimp",
            "edge_mm": 20,
            "strength_dates": [],
            "strength_gaps": [],
            "load_dates": ["2026-06-01"],
            "load_gaps": [(175.0 - 150.0) / 175.0 * 100.0],
        }
    ]


def test_combos_with_only_max_weight_tests_renders_strength_gap_series_only(client):
    register(client)
    # Bilateral MaxWeightTests without any WorkSets
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "45")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "40")

    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)

    assert len(view["asymmetry_pairs"]) == 1
    pair = view["asymmetry_pairs"][0]
    assert pair["combo_key"] == "asymmetry|half crimp|20"
    assert pair["load_trend"] == []
    assert len(pair["strength_trend"]) == 1

    # HTTP seam
    page = client.get("/dashboard").text
    assert "asymmetry-card" in page
    assert "Strength Max Gap" in page
    assert "Training Load Gap" not in page

    payload = asymmetry_chart_payload(client)
    assert payload == [
        {
            "combo": "asymmetry|half crimp|20",
            "grip_name": "half crimp",
            "edge_mm": 20,
            "strength_dates": ["2026-06-01"],
            "strength_gaps": [(45.0 - 40.0) / 45.0 * 100.0],
            "load_dates": [],
            "load_gaps": [],
        }
    ]


def test_dashboard_omits_asymmetry_section_only_when_both_series_are_empty(client):
    register(client)
    # 1. Completely empty
    page = client.get("/dashboard").text
    assert "asymmetry-card" not in page

    # 2. Single hand test and single hand work sets
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-06-02")
    page = client.get("/dashboard").text
    assert "asymmetry-card" not in page

    # 3. Both hands on different combos (unpaired)
    log_max_test(client, "right", "open hand", 10, "2026-06-01", "30")
    save_work_set(client, "right", 1, "30", "5", date="2026-06-02", grip="open hand", edge_mm=10)
    page = client.get("/dashboard").text
    assert "asymmetry-card" not in page

    # 4. Bilateral combo with only deload session (no max test, so both series empty)
    save_work_set(client, "left", 1, "20", "5", date="2026-06-05", grip="pinch", edge_mm=45)
    save_work_set(client, "right", 1, "20", "5", date="2026-06-05", grip="pinch", edge_mm=45)
    client.post(
        "/session/update",
        data={"date": "2026-06-05", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )
    session, user = db_session_and_user(client)
    pinch_strength = analytics.strength_gap_trend(session, user, 2, 45)
    pinch_load = analytics.load_gap_trend(session, user, 2, 45)
    assert pinch_strength == []
    assert pinch_load == []

    page = client.get("/dashboard").text
    assert "asymmetry-card" not in page


def test_load_gap_per_user_data_isolation_at_http_seam(client):
    register(client, email="userA@example.com")
    # User A: bilateral work sets on half crimp 20mm
    save_work_set(client, "left", 1, "50", "5", date="2026-06-01")
    save_work_set(client, "right", 1, "40", "5", date="2026-06-01")

    register_second_user(client, email="userB@example.com")
    # User B has no data yet
    assert asymmetry_chart_payload(client) is None

    # User B logs bilateral work sets on open hand 10mm
    save_work_set(client, "left", 1, "30", "5", date="2026-06-05", grip="open hand", edge_mm=10)
    save_work_set(client, "right", 1, "36", "5", date="2026-06-05", grip="open hand", edge_mm=10)

    user_b_payload = asymmetry_chart_payload(client)
    assert user_b_payload == [
        {
            "combo": "asymmetry|open hand|10",
            "grip_name": "open hand",
            "edge_mm": 10,
            "strength_dates": [],
            "strength_gaps": [],
            "load_dates": ["2026-06-05"],
            "load_gaps": [-16.666666666666664],
        }
    ]

    # Switch back to User A
    login(client, "userA@example.com", "test-pw-1234")
    user_a_payload = asymmetry_chart_payload(client)
    assert user_a_payload == [
        {
            "combo": "asymmetry|half crimp|20",
            "grip_name": "half crimp",
            "edge_mm": 20,
            "strength_dates": [],
            "strength_gaps": [],
            "load_dates": ["2026-06-01"],
            "load_gaps": [20.0],
        }
    ]


def test_asymmetry_warning_silent_below_data_minimum():
    # Fewer than 6 sessions (ASYM_RECENT_SESSIONS + ASYM_MIN_BASELINE_SESSIONS = 3 + 3)
    # Even if recent gap is high (e.g. 20%), thin data gates BOTH arms.
    trend = [
        (date_type(2026, 6, 1), 2.0),
        (date_type(2026, 6, 2), 2.0),
        (date_type(2026, 6, 3), 20.0),
        (date_type(2026, 6, 4), 20.0),
        (date_type(2026, 6, 5), 20.0),
    ]
    assert len(trend) == 5
    assert analytics.asymmetry_warning(trend) is False

    # Empty trend
    assert analytics.asymmetry_warning([]) is False


def test_asymmetry_warning_fires_on_drift_gte_5_pp():
    # 6 points: baseline [2.0, 2.0, 2.0] (avg 2.0), recent [7.0, 7.0, 7.0] (avg 7.0)
    # 7.0 - 2.0 = 5.0 pp drift (>= 5.0) -> fires
    trend = [
        (date_type(2026, 6, 1), 2.0),
        (date_type(2026, 6, 2), 2.0),
        (date_type(2026, 6, 3), 2.0),
        (date_type(2026, 6, 4), 7.0),
        (date_type(2026, 6, 5), 7.0),
        (date_type(2026, 6, 6), 7.0),
    ]
    assert analytics.asymmetry_warning(trend) is True

    # Signed drift in negative direction (Right hand higher load)
    # baseline [-2.0, -2.0, -2.0] -> abs [2.0, 2.0, 2.0]
    # recent [-8.0, -8.0, -8.0] -> abs [8.0, 8.0, 8.0]
    # 8.0 - 2.0 = 6.0 >= 5.0 -> fires
    trend_signed = [
        (date_type(2026, 6, 1), -2.0),
        (date_type(2026, 6, 2), -2.0),
        (date_type(2026, 6, 3), -2.0),
        (date_type(2026, 6, 4), -8.0),
        (date_type(2026, 6, 5), -8.0),
        (date_type(2026, 6, 6), -8.0),
    ]
    assert analytics.asymmetry_warning(trend_signed) is True

    # 9 points with full 6-session baseline window
    # baseline [1.0, 1.0, 2.0, 2.0, 1.0, 2.0] (avg 1.5)
    # recent [7.0, 7.0, 7.0] (avg 7.0)
    # 7.0 - 1.5 = 5.5 >= 5.0 -> fires
    trend_9 = [
        (date_type(2026, 6, 1), 1.0),
        (date_type(2026, 6, 2), 1.0),
        (date_type(2026, 6, 3), 2.0),
        (date_type(2026, 6, 4), 2.0),
        (date_type(2026, 6, 5), 1.0),
        (date_type(2026, 6, 6), 2.0),
        (date_type(2026, 6, 7), 7.0),
        (date_type(2026, 6, 8), 7.0),
        (date_type(2026, 6, 9), 7.0),
    ]
    assert analytics.asymmetry_warning(trend_9) is True


def test_asymmetry_warning_silent_on_stable_gap():
    # Stable 8% gap: drift = 0 < 5.0, recent = 8.0 < 15.0 -> silent
    trend_8 = [(date_type(2026, 6, i), 8.0) for i in range(1, 8)]
    assert analytics.asymmetry_warning(trend_8) is False

    # Stable 10% gap (natural dominance): drift = 0 < 5.0, recent = 10.0 < 15.0 -> silent
    trend_10 = [(date_type(2026, 6, i), 10.0) for i in range(1, 8)]
    assert analytics.asymmetry_warning(trend_10) is False

    # Small drift under 5 pp threshold: baseline 3.0, recent 6.5 -> drift 3.5 < 5.0 -> silent
    trend_small_drift = [
        (date_type(2026, 6, 1), 3.0),
        (date_type(2026, 6, 2), 3.0),
        (date_type(2026, 6, 3), 3.0),
        (date_type(2026, 6, 4), 6.5),
        (date_type(2026, 6, 5), 6.5),
        (date_type(2026, 6, 6), 6.5),
    ]
    assert analytics.asymmetry_warning(trend_small_drift) is False


def test_asymmetry_warning_fires_on_sustained_gte_15_pct_backstop():
    # Stable 15.0% gap: drift = 0.0, but recent = 15.0 >= 15.0 -> backstop arm fires
    trend_15 = [(date_type(2026, 6, i), 15.0) for i in range(1, 7)]
    assert analytics.asymmetry_warning(trend_15) is True

    # Stable 18.0% gap: recent = 18.0 >= 15.0 -> backstop arm fires
    trend_18 = [(date_type(2026, 6, i), 18.0) for i in range(1, 8)]
    assert analytics.asymmetry_warning(trend_18) is True


def test_asymmetry_warning_silent_on_narrowing_gap():
    # Narrowing gap (e.g. baseline 12.0%, recent 4.0%):
    # recent - baseline = -8.0 < 5.0, recent = 4.0 < 15.0 -> never warns
    trend_narrowing = [
        (date_type(2026, 6, 1), 12.0),
        (date_type(2026, 6, 2), 12.0),
        (date_type(2026, 6, 3), 12.0),
        (date_type(2026, 6, 4), 4.0),
        (date_type(2026, 6, 5), 4.0),
        (date_type(2026, 6, 6), 4.0),
    ]
    assert analytics.asymmetry_warning(trend_narrowing) is False

    # Narrowing gap above 15% backstop (e.g. baseline 20.0%, recent 16.0%):
    # Gap narrowed, so it must not warn despite recent >= 15.0%
    trend_narrowing_above_backstop = [
        (date_type(2026, 6, 1), 20.0),
        (date_type(2026, 6, 2), 20.0),
        (date_type(2026, 6, 3), 20.0),
        (date_type(2026, 6, 4), 16.0),
        (date_type(2026, 6, 5), 16.0),
        (date_type(2026, 6, 6), 16.0),
    ]
    assert analytics.asymmetry_warning(trend_narrowing_above_backstop) is False


def test_dashboard_asymmetry_warning_renders_when_warning_fires_and_absent_when_false(client):
    register(client)
    # Combo 1: Half crimp 20mm has 6 bilateral sessions with widening gap >= 5 pp (drifting from 0% to 20%)
    # Sessions 1-3: Left 50kg x 5 = 250, Right 50kg x 5 = 250 -> 0.0% gap
    for day in range(1, 4):
        save_work_set(client, "left", 1, "50", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "50", "5", date=f"2026-06-0{day}")

    # Sessions 4-6: Left 50kg x 5 = 250, Right 40kg x 5 = 200 -> +20.0% gap
    for day in range(4, 7):
        save_work_set(client, "left", 1, "50", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "40", "5", date=f"2026-06-0{day}")

    # Combo 2: Open hand 10mm has 6 bilateral sessions with stable ~5% gap (Left 40, Right 38 -> gap ~5%)
    for day in range(1, 7):
        save_work_set(client, "left", 1, "40", "5", date=f"2026-06-0{day}", grip="open hand", edge_mm=10)
        save_work_set(client, "right", 1, "38", "5", date=f"2026-06-0{day}", grip="open hand", edge_mm=10)

    session, user = db_session_and_user(client)
    view = analytics.dashboard_view(session, user)

    pairs_by_key = {p["combo_key"]: p for p in view["asymmetry_pairs"]}
    assert "asymmetry|half crimp|20" in pairs_by_key
    assert "asymmetry|open hand|10" in pairs_by_key
    assert pairs_by_key["asymmetry|half crimp|20"]["asymmetry_warning"] is True
    assert pairs_by_key["asymmetry|open hand|10"]["asymmetry_warning"] is False

    # HTTP seam
    page = client.get("/dashboard").text
    assert "⚠ asymmetry drift" in page

    flags = asymmetry_warning_flags(client)
    assert flags == {"asymmetry|half crimp|20"}


def test_asymmetry_warning_per_user_data_isolation_at_http_seam(client):
    register(client, email="userA@example.com")
    # User A: 6 sessions on half crimp 20mm with widening gap
    for day in range(1, 4):
        save_work_set(client, "left", 1, "50", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "50", "5", date=f"2026-06-0{day}")
    for day in range(4, 7):
        save_work_set(client, "left", 1, "50", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "40", "5", date=f"2026-06-0{day}")

    # User A has warning flag
    assert asymmetry_warning_flags(client) == {"asymmetry|half crimp|20"}

    # User B registers: 6 sessions on half crimp 20mm with balanced loads (0% gap)
    register_second_user(client, email="userB@example.com")
    for day in range(1, 7):
        save_work_set(client, "left", 1, "40", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "40", "5", date=f"2026-06-0{day}")

    # User B has no warning flag
    assert asymmetry_warning_flags(client) == set()

    # User A logs in again: still has warning flag
    login(client, "userA@example.com", "test-pw-1234")
    assert asymmetry_warning_flags(client) == {"asymmetry|half crimp|20"}


def test_mean_intensity_trend_multi_set_mean(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "50")
    # Session 2026-06-03: 3 sets with weights 40, 42.5, 45.
    # CurrentMax as of 2026-06-03 is 50.0.
    # Intensity per set: 40/50 = 0.8, 42.5/50 = 0.85, 45/50 = 0.9.
    # Mean intensity = (0.8 + 0.85 + 0.9) / 3 = 0.85.
    save_work_set(client, "left", 1, "40", "5", date="2026-06-03")
    save_work_set(client, "left", 2, "42.5", "5", date="2026-06-03")
    save_work_set(client, "left", 3, "45", "5", date="2026-06-03")

    session, user = db_session_and_user(client)
    trend = analytics.mean_intensity_trend(session, user, "left", 1, 20)
    assert trend == [(date_type(2026, 6, 3), 0.85)]

    # HTTP seam
    payload = chart_payload(client)
    assert payload == [
        {
            "combo": "left|half crimp|20",
            "dates": ["2026-06-03"],
            "volumes": [637.5],
            "intensity_dates": ["2026-06-03"],
            "intensities": [0.85],
        }
    ]


def test_mean_intensity_trend_as_of_date_current_max_denominator(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")
    # Session 1 on 2026-06-03: 36kg -> CurrentMax as of 2026-06-03 is 40.0 -> intensity = 36/40 = 0.9
    save_work_set(client, "left", 1, "36", "5", date="2026-06-03")

    # Higher max test on 2026-06-08: 50kg
    log_max_test(client, "left", "half crimp", 20, "2026-06-08", "50")
    # Session 2 on 2026-06-10: 40kg -> CurrentMax as of 2026-06-10 is 50.0 -> intensity = 40/50 = 0.8
    save_work_set(client, "left", 1, "40", "5", date="2026-06-10")

    session, user = db_session_and_user(client)
    trend = analytics.mean_intensity_trend(session, user, "left", 1, 20)
    assert trend == [
        (date_type(2026, 6, 3), 0.9),
        (date_type(2026, 6, 10), 0.8),
    ]

    payload = chart_payload(client)
    assert payload == [
        {
            "combo": "left|half crimp|20",
            "dates": ["2026-06-03", "2026-06-10"],
            "volumes": [180.0, 200.0],
            "intensity_dates": ["2026-06-03", "2026-06-10"],
            "intensities": [0.9, 0.8],
        }
    ]


def test_mean_intensity_trend_skips_sessions_where_current_max_is_none(client):
    register(client)
    # Session 1 on 2026-06-01: trained under estimate/untested -> CurrentMax is None
    save_work_set(client, "left", 1, "30", "5", date="2026-06-01")

    # Max test logged on 2026-06-05: 40kg
    log_max_test(client, "left", "half crimp", 20, "2026-06-05", "40")

    # Session 2 on 2026-06-06: 36kg -> CurrentMax is 40.0 -> intensity = 36/40 = 0.9
    save_work_set(client, "left", 1, "36", "5", date="2026-06-06")

    session, user = db_session_and_user(client)
    # Volume trend includes both sessions
    vol_trend = analytics.training_volume_trend(session, user, "left", 1, 20)
    assert vol_trend == [
        (date_type(2026, 6, 1), 150.0),
        (date_type(2026, 6, 6), 180.0),
    ]

    # Intensity trend skips the first session
    int_trend = analytics.mean_intensity_trend(session, user, "left", 1, 20)
    assert int_trend == [
        (date_type(2026, 6, 6), 0.9),
    ]

    # HTTP seam
    payload = chart_payload(client)
    assert payload == [
        {
            "combo": "left|half crimp|20",
            "dates": ["2026-06-01", "2026-06-06"],
            "volumes": [150.0, 180.0],
            "intensity_dates": ["2026-06-06"],
            "intensities": [0.9],
        }
    ]


def test_mean_intensity_trend_ignores_deload_sessions(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")

    # Session 1: normal
    save_work_set(client, "left", 1, "40", "5", date="2026-06-03")

    # Session 2: deload
    save_work_set(client, "left", 1, "20", "5", date="2026-06-07")
    client.post(
        "/session/update",
        data={"date": "2026-06-07", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )

    # Session 3: normal
    save_work_set(client, "left", 1, "40", "5", date="2026-06-10")

    session, user = db_session_and_user(client)
    trend = analytics.mean_intensity_trend(session, user, "left", 1, 20)
    assert trend == [
        (date_type(2026, 6, 3), 1.0),
        (date_type(2026, 6, 10), 1.0),
    ]

