import json
import re

from tests.helpers import log_max_test, register, save_work_set


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
