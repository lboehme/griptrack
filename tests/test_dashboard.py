import re

from tests.helpers import grip_type_id, log_max_test, register


def save_work_set(client, hand, set_number, weight, reps, date,
                  grip="half crimp", edge_mm=20):
    return client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "hand": hand,
            "set_number": set_number,
            "weight": weight,
            "reps": reps,
        },
        follow_redirects=True,
    )


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


def test_dashboard_renders_a_server_side_chart_per_combo(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-06-03")
    save_work_set(client, "left", 1, "42.5", "5", date="2026-06-10")

    page = client.get("/dashboard").text
    src = re.search(r'<img class="trend-chart"[^>]*src="([^"]+)"', page)
    assert src, "no chart image on the dashboard"

    svg = client.get(src.group(1).replace("&amp;", "&"))
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg")
    assert "<svg" in svg.text


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
