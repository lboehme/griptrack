"""Progress (#150): the headline %BW chart, story sentences, Go deeper
pages, the timeline, and the redirects from the pages it absorbed. All at
the HTTP seam: the chart series is read back from its JSON-in-DOM payload."""

import html
import json
import re
from datetime import date as date_type
from datetime import timedelta

from sqlmodel import select

from backend.db import get_session
from backend.models import MaxWeightTest
from tests.helpers import (
    grip_type_id,
    log_bodyweight,
    log_climb,
    log_max_test,
    register,
    register_second_user,
    save_work_set,
)
from tests.test_correlation import seed_progression

TODAY = date_type.today()


def progress_page(client, **params):
    response = client.get("/progress", params=params)
    assert response.status_code == 200
    return response.text


def chart_payload(page):
    match = re.search(
        r'<script type="application/json" id="progress-chart-data">(.*?)</script>',
        page,
        re.DOTALL,
    )
    assert match, "no progress-chart-data payload"
    return json.loads(match.group(1))


def hand_series(page, hand):
    data = chart_payload(page)["hands"][hand]
    return list(zip(data["dates"], data["values"], strict=True))


def sentences(page):
    """[(kind, hand, claim, advice)] in page order."""
    return [
        (kind, hand or None, html.unescape(claim), html.unescape(advice))
        for kind, hand, claim, advice in re.findall(
            r'class="story-sentence" data-kind="(\w+)"(?: data-hand="(\w+)")?>.*?'
            r"<strong>(.*?)</strong>(?: <span class=\"muted\">(.*?)</span>)?</p>",
            page,
            re.DOTALL,
        )
    ]


def kinds(page):
    return [(kind, hand) for kind, hand, _, _ in sentences(page)]


def void_test(client, weight):
    session = next(client.app.dependency_overrides[get_session]())
    test = session.exec(select(MaxWeightTest).where(MaxWeightTest.weight == weight)).one()
    response = client.post(f"/max-tests/{test.id}/void", follow_redirects=False)
    assert response.status_code == 303
    session.close()


# ---------------------------------------------------------------- chart


def test_headline_series_is_current_max_over_bodyweight_as_of_each_date(client):
    register(client)
    # Before any bodyweight: a test and a session whose dates must be skipped.
    log_max_test(client, "left", "half crimp", 20, "2026-05-15", "30")
    save_work_set(client, "left", 1, "30", "5", date="2026-05-20")

    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "28")
    # A heavier work set overtakes the test: CurrentMax 36 from here on.
    save_work_set(client, "left", 1, "36", "5", date="2026-06-03")
    save_work_set(client, "right", 1, "28", "5", date="2026-06-03")
    # A 50 kg test, voided: it must never count (nor add its date).
    log_max_test(client, "left", "half crimp", 20, "2026-06-05", "50")
    void_test(client, 50.0)
    save_work_set(client, "left", 1, "35", "5", date="2026-06-08")
    # New bodyweight before the last session.
    log_bodyweight(client, "2026-06-10", "75")
    save_work_set(client, "left", 1, "37", "5", date="2026-06-12")

    page = progress_page(client, range="all")

    assert hand_series(page, "left") == [
        ("2026-06-01", 35 / 70),
        ("2026-06-03", 36 / 70),
        ("2026-06-08", 36 / 70),  # not 50/70: the voided test is ignored
        ("2026-06-12", 37 / 75),
    ]
    assert hand_series(page, "right") == [
        ("2026-06-01", 28 / 70),
        ("2026-06-03", 28 / 70),
        ("2026-06-08", 28 / 70),
        ("2026-06-12", 28 / 75),
    ]
    # Legend shows the latest value per hand; the chart has an ARIA title.
    assert 'data-hand="left" data-latest="0.4933"' in page
    assert "49.3%" in page
    assert (
        'role="img" aria-label="Strength as % of bodyweight, Half crimp 20 mm, '
        'all time: Left 49.3%, Right 37.3%.'
    ) in page


def test_untested_hand_has_no_series(client):
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    # Right trains without a test (estimate-only): no CurrentMax, no points.
    save_work_set(client, "right", 1, "30", "5", date="2026-06-03")

    page = progress_page(client, range="all")

    assert hand_series(page, "left") == [("2026-06-01", 0.5), ("2026-06-03", 0.5)]
    assert hand_series(page, "right") == []


def test_sends_are_parsed_boulder_grades_with_their_colour_band(client):
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_climb(client, "2026-06-02", "7A")
    log_climb(client, "2026-06-03", "6B+")
    log_climb(client, "2026-06-04", "hard")  # unparsed: not on the chart

    payload = chart_payload(progress_page(client, range="all"))

    assert payload["sends"] == [
        {"date": "2026-06-02", "grade": "7A", "value": 6.0, "token": "--grade-7a"},
        {"date": "2026-06-03", "grade": "6B+", "value": 4.0, "token": "--grade-6b"},
    ]


def test_range_limits_the_series_and_sends(client):
    register(client)
    old = (TODAY - timedelta(days=60)).isoformat()
    recent = (TODAY - timedelta(days=10)).isoformat()
    log_bodyweight(client, old, "70")
    log_max_test(client, "left", "half crimp", 20, old, "35")
    save_work_set(client, "left", 1, "38.5", "5", date=recent)
    log_climb(client, old, "6A")
    log_climb(client, recent, "6C")

    six_weeks = chart_payload(progress_page(client, range="6w"))
    three_months = chart_payload(progress_page(client, range="3m"))

    assert six_weeks["hands"]["left"]["dates"] == [recent]
    assert [s["grade"] for s in six_weeks["sends"]] == ["6C"]
    assert six_weeks["since"] == (TODAY - timedelta(days=42)).isoformat()
    assert three_months["hands"]["left"]["dates"] == [old, recent]
    assert [s["grade"] for s in three_months["sends"]] == ["6A", "6C"]
    # 6W is the default.
    assert chart_payload(progress_page(client)) == six_weeks


def test_combo_picker_appears_with_two_combos_and_defaults_to_last_trained(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")

    assert "progress-combos" not in progress_page(client)

    log_max_test(client, "left", "open hand", 10, "2026-06-02", "30")
    save_work_set(client, "left", 1, "36", "5", date="2026-06-03")  # half crimp 20

    page = progress_page(client, range="all")
    assert "progress-combos" in page
    crimp = grip_type_id(client, "half crimp")
    open_hand = grip_type_id(client, "open hand")
    assert f'data-grip-type-id="{crimp}" data-edge-mm="20" aria-current="true"' in page

    picked = progress_page(client, grip_type_id=open_hand, edge_mm=10, range="all")
    assert f'data-grip-type-id="{open_hand}" data-edge-mm="10" aria-current="true"' in picked
    # The picker links are plain hrefs (no-JS) upgraded by htmx.
    assert f'href="/progress?grip_type_id={crimp}&amp;edge_mm=20&amp;range=all"' in picked


def test_htmx_picker_request_returns_only_the_progress_root(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")

    response = client.get("/progress", params={"range": "3m"}, headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert '<div id="progress-root"' in response.text
    assert "<html" not in response.text
    assert 'data-range="3m"' in response.text


def test_progress_never_shows_another_users_data(client):
    register(client, email="founder@example.com")
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_climb(client, "2026-06-02", "7A")

    register_second_user(client)
    page = progress_page(client, range="all")
    payload = chart_payload(page)

    assert payload["hands"] == {
        "left": {"dates": [], "values": []},
        "right": {"dates": [], "values": []},
    }
    assert payload["sends"] == []
    assert kinds(page) == [("missing", None)]


def test_go_deeper_rows_link_every_detail_page(client):
    register(client)
    page = progress_page(client)
    for href in (
        "/progress/volume",
        "/progress/balance",
        "/progress/grade",
        "/progress/maxes",
        "/progress/timeline",
    ):
        assert f'href="{href}"' in page
        assert client.get(href).status_code == 200


def test_raw_data_lists_sit_behind_closed_disclosures(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-06-03")
    save_work_set(client, "right", 1, "40", "5", date="2026-06-03")

    for path, marker in (
        ("/progress/volume", "volume-list"),
        ("/progress/balance", "asymmetry-list"),
        ("/progress/maxes", "Test history"),
    ):
        page = client.get(path).text
        assert '<details class="show-data">' in page
        assert "<details class=\"show-data\" open" not in page
        assert page.index('<details class="show-data">') < page.index(marker)


# ---------------------------------------------------------------- story


def test_change_sentence_only_for_a_hand_that_moved(client):
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    log_max_test(client, "right", "half crimp", 20, "2026-06-01", "30")
    save_work_set(client, "left", 1, "37", "5", date="2026-06-08")
    save_work_set(client, "right", 1, "30", "5", date="2026-06-08")

    found = sentences(progress_page(client, range="all"))

    # (37/70 - 35/70) / (35/70) = +5.7% -> "up 6%"; Right didn't move.
    changes = [s for s in found if s[0] == "change"]
    assert len(changes) == 1
    kind, hand, claim, advice = changes[0]
    assert hand == "left"
    assert claim.startswith("Left up 6% since ")
    assert advice == "52.9% of bodyweight now."


def test_change_sentence_names_the_range_span(client):
    register(client)
    start = (TODAY - timedelta(days=30)).isoformat()
    log_bodyweight(client, start, "70")
    log_max_test(client, "left", "half crimp", 20, start, "40")
    save_work_set(client, "left", 1, "36", "5", date=(TODAY - timedelta(days=3)).isoformat())
    # A new, lower test: a deliberate reset, so Left goes down.
    log_max_test(client, "left", "half crimp", 20, (TODAY - timedelta(days=2)).isoformat(), "36")

    found = sentences(progress_page(client, range="6w"))

    assert ("change", "left", "Left down 10% in 6 weeks.", "51.4% of bodyweight now.") in found


def test_plateau_sentence_follows_the_plateau_flag(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    log_max_test(client, "left", "open hand", 10, "2026-05-01", "30")
    # Stalled half crimp (the dashboard's plateau fixture), weekly.
    for week, volume in enumerate([400, 410, 420, 420, 415, 410, 420]):
        save_work_set(client, "left", 1, str(volume), "1",
                      date=(date_type(2026, 6, 1) + timedelta(weeks=week)).isoformat())
    # Growing open hand: no plateau.
    for day, volume in enumerate([300, 310, 320, 330, 340, 355]):
        save_work_set(client, "left", 1, str(volume), "1",
                      date=f"2026-06-{day + 1:02d}", grip="open hand", edge_mm=10)

    crimp = grip_type_id(client, "half crimp")
    open_hand = grip_type_id(client, "open hand")
    stalled = sentences(progress_page(client, grip_type_id=crimp, edge_mm=20, range="all"))
    growing = sentences(progress_page(client, grip_type_id=open_hand, edge_mm=10, range="all"))

    # Best earlier volume (420) was week 3; the last session is week 7.
    assert ("plateau", "left", "Left has held for 4 weeks.",
            "A deload or a retest could break it.") in stalled
    assert "plateau" not in [s[0] for s in growing]
    # Same answer as the volume page's plateau pill.
    volume_page = client.get("/progress/volume").text
    assert 'class="pill plateau-flag" data-combo="left|half crimp|20"' in volume_page
    assert 'class="pill plateau-flag" data-combo="left|open hand|10"' not in volume_page


def test_plateau_over_less_than_two_weeks_counts_sessions(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    for day, volume in enumerate([400, 410, 420, 420, 415, 410, 420]):
        save_work_set(client, "left", 1, str(volume), "1", date=f"2026-06-{day + 1:02d}")

    found = sentences(progress_page(client, range="all"))

    assert ("plateau", "left", "Left has held for 4 sessions.",
            "A deload or a retest could break it.") in found


def test_overtraining_sentence_needs_spike_and_short_rest(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-05-01", "40")
    log_max_test(client, "left", "open hand", 10, "2026-05-01", "40")
    for date in ("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"):
        save_work_set(client, "left", 1, "400", "1", date=date)
        save_work_set(client, "left", 1, "400", "1", date=date, grip="open hand", edge_mm=10)
    save_work_set(client, "left", 1, "550", "1", date="2026-06-24")  # spike + short rest
    save_work_set(client, "left", 1, "550", "1", date="2026-06-29",  # spike, normal rest
                  grip="open hand", edge_mm=10)

    crimp = grip_type_id(client, "half crimp")
    open_hand = grip_type_id(client, "open hand")
    warned = kinds(progress_page(client, grip_type_id=crimp, edge_mm=20, range="all"))
    calm = kinds(progress_page(client, grip_type_id=open_hand, edge_mm=10, range="all"))

    assert ("overtraining", "left") in warned
    assert ("overtraining", "left") not in calm


def test_asymmetry_sentence_follows_the_asymmetry_warning(client):
    register(client)
    # Half crimp: gap drifts 0% -> 20% (warns); open hand: stable ~5%.
    for day in range(1, 4):
        save_work_set(client, "left", 1, "50", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "50", "5", date=f"2026-06-0{day}")
    for day in range(4, 7):
        save_work_set(client, "left", 1, "50", "5", date=f"2026-06-0{day}")
        save_work_set(client, "right", 1, "40", "5", date=f"2026-06-0{day}")
    for day in range(1, 7):
        save_work_set(client, "left", 1, "40", "5", date=f"2026-06-0{day}", grip="open hand", edge_mm=10)
        save_work_set(client, "right", 1, "38", "5", date=f"2026-06-0{day}", grip="open hand", edge_mm=10)

    crimp = grip_type_id(client, "half crimp")
    open_hand = grip_type_id(client, "open hand")
    drifting = sentences(progress_page(client, grip_type_id=crimp, edge_mm=20, range="all"))
    stable = sentences(progress_page(client, grip_type_id=open_hand, edge_mm=10, range="all"))

    assert ("asymmetry", None, "Your hands are drifting apart.",
            "Left is carrying more load than your usual balance.") in drifting
    assert "asymmetry" not in [s[0] for s in stable]


def test_correlation_sentence_puts_rho_into_words(client):
    seed_progression(client)  # rho > 0.95 across 8 sends

    found = sentences(progress_page(client, range="all"))
    correlation = [s for s in found if s[0] == "correlation"]

    assert correlation == [(
        "correlation", None, "Your sends are following.",
        "Across 8 boulder sends, harder grades came with a stronger pull (strong link).",
    )]
    assert "missing" not in [s[0] for s in found]


def test_below_the_floor_shows_the_missing_sends_line_not_a_correlation(client):
    seed_progression(client, count=7)

    found = sentences(progress_page(client, range="all"))

    assert "correlation" not in [s[0] for s in found]
    assert ("missing", None, "Log 1 more boulder send", "to see how strength tracks grade.") in found


def test_missing_line_never_counts_negative_when_variance_is_zero(client):
    register(client)
    log_bodyweight(client, "2026-06-01", "70")
    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    for i, grade in enumerate(["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9"], start=2):
        log_climb(client, f"2026-06-{i:02d}", grade)

    page = progress_page(client, range="all")

    assert "correlation" not in [kind for kind, _ in kinds(page)]
    assert "more boulder send" not in page
    assert "-1" not in "".join(claim for _, _, claim, _ in sentences(page))


def test_missing_line_asks_for_a_test_then_bodyweight(client):
    register(client)
    assert sentences(progress_page(client)) == [
        ("missing", None, "Nothing to chart yet.", "Run a max test to start your strength line."),
    ]

    log_max_test(client, "left", "half crimp", 20, "2026-06-01", "35")
    assert sentences(progress_page(client)) == [
        ("missing", None, "Log your bodyweight", "to see strength as a share of it."),
    ]


def test_at_most_three_sentences_in_priority_order(client):
    register(client)
    log_bodyweight(client, "2026-05-01", "70")
    for hand in ("left", "right"):
        log_max_test(client, hand, "half crimp", 20, "2026-05-01", "300")
    # Both hands: CurrentMax rises (a change sentence each) and volume
    # stalls (a plateau each) -- four signals, three slots.
    for week, volume in enumerate([400, 410, 420, 420, 415, 410, 420]):
        date = (date_type(2026, 6, 1) + timedelta(weeks=week)).isoformat()
        for hand in ("left", "right"):
            save_work_set(client, hand, 1, str(volume), "1", date=date)

    assert kinds(progress_page(client, range="all")) == [
        ("change", "left"), ("change", "right"), ("plateau", "left"),
    ]


# ---------------------------------------------------------------- timeline


def timeline(client, **params):
    response = client.get("/progress/timeline", params=params)
    assert response.status_code == 200
    return response.text


def session_row(page, date, session_number=1):
    match = re.search(
        rf'<li class="history-session" data-date="{date}" data-session-number="{session_number}">(.*?)</details>',
        page,
        re.DOTALL,
    )
    assert match, f"no timeline row for {date}"
    return match.group(1)


def test_timeline_session_row_shows_combo_top_set_volume_rpe_and_deload(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "left", "open hand", 10, "2026-07-01", "30")
    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-04")
    save_work_set(client, "left", 2, "45", "3", date="2026-07-04")
    save_work_set(client, "left", 3, "30", "5", date="2026-07-04", grip="open hand", edge_mm=10)
    crimp = grip_type_id(client, "half crimp")
    client.post("/session/rpe", data={"grip_type_id": crimp, "edge_mm": 20,
                                      "date": "2026-07-04", "session_rpe": 7})
    client.post("/session/update", data={"date": "2026-07-04", "is_deload": "on"},
                headers={"HX-Request": "true"})

    row = session_row(timeline(client), "2026-07-04")

    assert "Half crimp · 20 mm" in row
    assert '<span class="muted">+1</span>' in row  # a second combo that session
    assert 'data-top-weight="45.0"' in row and "× 3" in row
    assert 'data-volume="497.5"' in row  # 42.5x5 + 45x3 + 30x5
    assert 'data-session-rpe="7"' in row
    assert "deload-tag" in row
    # Links its first combo (by set number) into session play.
    assert (
        f'href="/session/play?grip_type_id={crimp}&amp;edge_mm=20&amp;date=2026-07-04&amp;session_number=1"'
        in row
    )


def test_timeline_link_reopens_a_finished_session_on_its_summary(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    save_work_set(client, "right", 1, "40", "5", date="2026-07-04")
    client.post("/session/finish", data={"date": "2026-07-04"})

    href = re.search(r'class="timeline-row" href="([^"]+)"', timeline(client)).group(1)
    play = client.get(html.unescape(href))

    assert play.status_code == 200
    assert "summary-step" in play.text


def test_second_session_of_a_day_links_its_own_session_number(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04", session_number=1)
    save_work_set(client, "left", 1, "41", "5", date="2026-07-04", session_number=2)

    page = timeline(client)

    assert "session_number=2" in session_row(page, "2026-07-04", 2)
    # Latest session_number first within a date.
    assert page.index('data-session-number="2"') < page.index('data-session-number="1"')


def test_timeline_groups_by_week_newest_first_and_mixes_climbs(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-07-01")  # Wed, week of 29 Jun
    log_climb(client, "2026-07-02", "6C", style="flash")
    save_work_set(client, "left", 1, "40", "5", date="2026-07-08")  # Wed, week of 6 Jul

    page = timeline(client)

    weeks = re.findall(r'class="timeline-week" data-week="([\d-]+)"', page)
    assert weeks == ["2026-07-06", "2026-06-29"]
    first_week = page.split('data-week="2026-06-29"')[1]
    assert 'class="climb" data-discipline="boulder" data-grade="6C" data-style="flash"' in first_week
    assert "grade-dot" in first_week
    assert first_week.index('data-grade="6C"') < first_week.index('data-date="2026-07-01"')


def test_climbs_only_filter_hides_sessions(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    log_climb(client, "2026-07-03", "7A")

    page = timeline(client, show="climbs")

    assert "history-session" not in page
    assert 'data-grade="7A"' in page
    assert 'aria-current="page">Climbs only' in page


# ---------------------------------------------------------------- redirects


def test_old_pages_redirect_into_progress_preserving_the_query(client):
    register(client)
    cases = {
        "/dashboard": "/progress",
        "/dashboard?range=all": "/progress?range=all",
        "/history": "/progress/timeline",
        "/history?show=climbs": "/progress/timeline?show=climbs",
        "/max-tests": "/progress/maxes",
    }
    for old, new in cases.items():
        response = client.get(old, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, new)


def test_max_test_posts_land_on_the_maxes_page(client):
    register(client)
    logged = client.post(
        "/max-tests",
        data={"hand": "left", "grip_type_id": grip_type_id(client, "half crimp"),
              "edge_mm": 20, "date": "2026-07-01", "weight": "40"},
        follow_redirects=False,
    )
    assert (logged.status_code, logged.headers["location"]) == (303, "/progress/maxes")

    test_id = re.search(r'action="/max-tests/(\d+)/void"', client.get("/progress/maxes").text).group(1)
    voided = client.post(f"/max-tests/{test_id}/void", follow_redirects=False)
    assert (voided.status_code, voided.headers["location"]) == (303, "/progress/maxes")


def test_maxes_page_offers_the_guided_test(client):
    register(client)
    page = client.get("/progress/maxes").text
    assert 'action="/max-tests/guided"' in page
    assert 'action="/max-tests"' in page
