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


def seed_progression(client):
    """Strength and boulder grade rising together; one sport climb as noise."""
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_climb(client, "2026-06-02", "V2")
    log_max_test(client, "left", "half crimp", 20, "2026-06-10", "42")
    log_climb(client, "2026-06-12", "6B")          # Font for V4
    log_max_test(client, "left", "half crimp", 20, "2026-06-20", "49")
    log_climb(client, "2026-06-22", "V6")
    log_climb(client, "2026-06-15", "7a+", discipline="sport")  # excluded


def test_rising_strength_and_grades_correlate_positively(client):
    seed_progression(client)

    stat = correlation_stat(client)
    assert stat is not None, "no correlation stat on the dashboard"
    r, n = stat
    assert n == 3  # the sport climb is excluded
    assert r > 0.9


def test_each_climb_uses_the_closest_bodyweight_at_or_before_it(client):
    seed_progression(client)
    # Weight gained just before the last climb: 49/75, not 49/70.
    log_bodyweight(client, "2026-06-21", "75")

    points = correlation_points(client)

    assert points["2026-06-02"] == (0.5, 2.0)     # 35/70, V2
    assert points["2026-06-12"] == (0.6, 4.0)     # 42/70, Font 6B -> V4
    assert points["2026-06-22"] == (0.653, 6.0)   # 49/75, V6


def test_too_few_boulder_climbs_shows_no_correlation(client):
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_climb(client, "2026-06-02", "V2")

    assert correlation_stat(client) is None
