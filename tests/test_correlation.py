import re

from tests.helpers import log_bodyweight, log_climb, log_max_test, register


def correlation_stat(client):
    page = client.get("/dashboard").text
    match = re.search(r'class="corr-r" data-r="([-\d.]+)" data-n="(\d+)"', page)
    return (float(match.group(1)), int(match.group(2))) if match else None


def correlation_points(client):
    page = client.get("/dashboard").text
    return {
        date: (float(pct), float(grade))
        for date, pct, grade in re.findall(
            r'class="corr-point" data-date="([\d-]+)" data-pct="([\d.]+)" '
            r'data-grade="([\d.]+)"',
            page,
        )
    }


def seed_progression(client, count=8):
    """Strength and boulder grade rising together; one unparseable-grade
    climb as noise (issue #55 — excluded from the correlation, not silently
    but with loud feedback at logging time and a history badge)."""
    register(client)
    log_bodyweight(client, "2026-06-01", "70")

    # The n >= 8 floor needs eight parseable points; ties exercise
    # Spearman's average-rank handling.
    points = [
        ("2026-06-01", "35", "2026-06-02", "V1"),
        ("2026-06-10", "38", "2026-06-12", "V2"),
        ("2026-06-15", "42", "2026-06-16", "V3"),
        ("2026-06-20", "44", "2026-06-21", "V4"),
        ("2026-06-25", "46", "2026-06-26", "V4"),  # tie in grades
        ("2026-06-28", "46", "2026-06-29", "V5"),  # tie in strength
        ("2026-07-02", "48", "2026-07-03", "V6"),
        ("2026-07-10", "50", "2026-07-12", "V7"),
    ]
    for strength_date, weight, climb_date, grade in points[:count]:
        log_max_test(client, "left", "half crimp", 20, strength_date, weight)
        log_climb(client, climb_date, grade)

    if count >= 8:
        log_climb(client, "2026-06-15", "hard")  # unparseable grade, excluded


def test_rising_strength_and_grades_correlate_positively(client):
    seed_progression(client)

    stat = correlation_stat(client)
    assert stat is not None, "no correlation stat on the dashboard"
    r, n = stat
    assert n == 8  # the unparseable-grade climb is excluded
    assert r > 0.95


def test_each_climb_uses_the_closest_bodyweight_at_or_before_it(client):
    seed_progression(client)
    # Weight gained just before the last climb: 50/75, not 50/70.
    log_bodyweight(client, "2026-07-11", "75")

    points = correlation_points(client)

    assert points["2026-06-02"] == (0.5, 1.0)     # 35/70, V1
    assert points["2026-07-12"] == (round(50/75, 3), 7.0)


def test_too_few_boulder_climbs_shows_no_correlation(client):
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_climb(client, "2026-06-02", "V2")

    assert correlation_stat(client) is None


def test_correlation_floor_boundary_at_seven_points_shows_no_correlation(client):
    """The n >= 8 floor: exactly 7 points must still yield no correlation."""
    seed_progression(client, count=7)

    assert correlation_stat(client) is None
