"""The ＋ Log sheet (#149): Climb / Bodyweight / Tweak tabs, htmx-driven,
with `/?log=<tab>` as the server-side (no-JS) way in."""

import re
from datetime import date as date_type
from datetime import timedelta

from sqlmodel import select

from backend.db import get_session
from backend.models import BodyWeightLog, Climb, PainReport, TrainingSession, User
from tests.helpers import log_climb, register, register_second_user, save_work_set

TODAY = date_type.today()
HX = {"HX-Request": "true"}


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def db_rows(client, model, email="lifter@example.com"):
    session = next(client.app.dependency_overrides[get_session]())
    user = session.exec(select(User).where(User.email == email)).one()
    if model is PainReport:
        rows = session.exec(
            select(PainReport, TrainingSession)
            .join(TrainingSession, PainReport.training_session_id == TrainingSession.id)
            .where(TrainingSession.user_id == user.id)
        ).all()
    else:
        rows = session.exec(select(model).where(model.user_id == user.id)).all()
    session.close()
    return rows


def primary_grades(page):
    block = re.search(
        r'<div class="grade-chips"[^>]*>(.*?)</div>\s*<div class="grade-chips-more"', page, re.DOTALL
    ).group(1)
    return re.findall(r'name="grade" value="([^"]+)"', block)


def more_grades(page):
    block = re.search(r'<div class="grade-chips-more"[^>]*>(.*?)</div>', page, re.DOTALL).group(1)
    return re.findall(r'name="grade" value="([^"]+)"', block)


def checked_style(page):
    return re.search(r'name="style" value="(\w+)" class="chip-radio" checked', page).group(1)


def post_climb(client, headers=None, **fields):
    data = {"grade": "7A", "style": "flash", "when": "today", "today": TODAY.isoformat()}
    data.update(fields)
    return client.post("/log/climb", data=data, headers=headers, follow_redirects=False)


# ---------- opening the sheet ----------


def test_sheet_fragment_renders_each_tab(client):
    register(client)

    for tab, marker in (("climb", "sheet-climb"), ("bodyweight", "sheet-bodyweight"), ("tweak", "sheet-tweak")):
        fragment = client.get("/log/sheet", params={"tab": tab}, headers=HX).text
        assert marker in fragment
        assert 'class="log-sheet"' in fragment
        # Opening a tab never adds a history entry for Android Back.
        assert "hx-push-url" not in fragment


def test_unknown_tab_falls_back_to_climb(client):
    register(client)

    assert "sheet-climb" in client.get("/log/sheet", params={"tab": "nope"}).text


def test_log_query_opens_the_sheet_server_side(client):
    register(client)

    page = client.get("/", params={"log": "bodyweight"}).text

    assert 'class="log-sheet"' in page
    assert "sheet-bodyweight" in page
    assert 'class="log-sheet"' not in client.get("/", params={"log": "bogus"}).text
    assert 'class="log-sheet"' not in client.get("/").text


def test_climbs_redirect_lands_on_the_open_climb_sheet(client):
    register(client)

    page = client.get("/climbs").text

    assert "sheet-climb" in page


# ---------- Climb tab ----------


def test_grade_chips_default_to_6a_through_7b_plus_with_colour_dots(client):
    register(client)

    page = client.get("/log/sheet?tab=climb").text

    assert primary_grades(page) == ["6A", "6A+", "6B", "6B+", "6C", "6C+", "7A", "7A+", "7B", "7B+"]
    assert more_grades(page) == ["5", "5+", "7C", "7C+", "8A", "8A+", "__other__"]
    assert "--dot: var(--grade-6a)" in page
    assert "--dot: var(--grade-7b)" in page


def test_grade_chips_center_on_recent_grades(client):
    register(client)
    for offset in range(3):
        log_climb(client, date=day(-offset), grade="7C", style="redpoint")

    page = client.get("/log/sheet?tab=climb").text

    primary = primary_grades(page)
    assert len(primary) == 10
    assert "7C" in primary and "8A" in primary
    assert "6A" not in primary
    # Style defaults to the last used one.
    assert checked_style(page) == "redpoint"


def test_style_chips_default_to_flash_and_read_send_for_redpoint(client):
    register(client)

    page = client.get("/log/sheet?tab=climb").text

    assert checked_style(page) == "flash"
    assert re.search(r'value="redpoint" class="chip-radio"><span class="chip-face">Send<', page)


def test_logging_a_climb_via_htmx_returns_a_toast_and_refresh_trigger(client):
    register(client)

    response = post_climb(client, headers=HX, grade="7A", style="flash")

    assert response.status_code == 200
    assert "Climb logged" in response.text
    assert 'class="toast"' in response.text
    assert response.headers["HX-Trigger"] == "griptrack-logged"
    climbs = db_rows(client, Climb)
    assert [(c.grade, c.style, c.date, c.discipline) for c in climbs] == [("7A", "flash", TODAY, "boulder")]


def test_logging_a_climb_without_js_redirects_to_today_with_a_toast(client):
    register(client)

    response = post_climb(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/?saved=climb"
    assert "Climb logged" in client.get(response.headers["location"]).text


def test_when_chips_resolve_yesterday_and_a_picked_date(client):
    register(client)

    post_climb(client, when="yesterday", today="2026-07-10")
    post_climb(client, when="date", today="2026-07-10", pick_date="2026-06-01")

    dates = sorted(c.date for c in db_rows(client, Climb))
    assert dates == [date_type(2026, 6, 1), date_type(2026, 7, 9)]


def test_picked_date_is_required_for_when_date(client):
    register(client)

    assert post_climb(client, when="date").status_code == 400
    assert post_climb(client, when="later").status_code == 400
    assert db_rows(client, Climb) == []


def test_other_grade_takes_the_typed_text_and_keeps_the_unrecognised_warning(client):
    register(client)

    response = post_climb(client, headers=HX, grade="__other__", grade_other="  V5  ")
    assert response.status_code == 200
    assert "recognized" not in response.text.lower()

    unrecognised = post_climb(client, headers=HX, grade="__other__", grade_other="proj")
    assert "recognized" in unrecognised.text.lower()
    assert "correlation" in unrecognised.text.lower()

    assert sorted(c.grade for c in db_rows(client, Climb)) == ["V5", "proj"]


def test_unrecognised_grade_warning_rides_the_no_js_redirect_as_a_flag(client):
    register(client)

    response = post_climb(client, grade="__other__", grade_other="hard")

    assert response.headers["location"] == "/?saved=climb&grade_warning=1"
    followed = client.get(response.headers["location"]).text
    assert "recognized" in followed.lower()
    assert "grade-warning" not in client.get("/").text


def test_other_grade_needs_text(client):
    register(client)

    assert post_climb(client, grade="__other__", grade_other="   ").status_code == 400
    assert db_rows(client, Climb) == []


def test_invalid_climb_style_is_rejected(client):
    register(client)

    assert post_climb(client, style="dogged").status_code == 400
    assert db_rows(client, Climb) == []


def test_climb_logging_takes_three_taps_worth_of_fields(client):
    """The sheet's defaults (style, When=Today, client-local today) mean a
    grade is the only thing to pick -- ＋, grade chip, Log."""
    register(client)

    page = client.get("/log/sheet?tab=climb").text

    assert re.search(r'name="when" value="today" class="chip-radio" checked', page)
    assert f'name="today" value="{TODAY.isoformat()}" class="local-date-default"' in page


# ---------- Bodyweight tab ----------


def test_bodyweight_tab_reuses_the_hold_to_repeat_steppers(client):
    register(client)

    page = client.get("/log/sheet?tab=bodyweight").text

    assert 'class="stepper-btn stepper-minus" data-step="-0.1" data-target="bw-weight"' in page
    assert 'class="stepper-btn stepper-plus" data-step="0.1" data-target="bw-weight"' in page
    # Default when nothing is logged yet (kg account).
    assert 'name="weight" value="70.0"' in page


def test_bodyweight_tab_prefills_the_last_logged_weight(client):
    register(client)
    client.post("/log/bodyweight", data={"date": day(-10), "weight": "71.3"})

    page = client.get("/log/sheet?tab=bodyweight").text

    assert 'name="weight" value="71.3"' in page


def test_saving_bodyweight(client):
    register(client)

    response = client.post(
        "/log/bodyweight", data={"date": TODAY.isoformat(), "weight": "72.4"}, headers=HX
    )

    assert response.status_code == 200
    assert "Bodyweight logged" in response.text
    assert [(b.date, b.weight) for b in db_rows(client, BodyWeightLog)] == [(TODAY, 72.4)]
    # The stale-bodyweight prompt on Today goes away.
    assert "today-bodyweight" not in client.get("/").text


def test_bodyweight_must_be_positive_and_bounded(client):
    register(client)

    assert client.post("/log/bodyweight", data={"date": TODAY.isoformat(), "weight": "0"}).status_code == 422
    assert client.post("/log/bodyweight", data={"date": TODAY.isoformat(), "weight": "1000.1"}).status_code == 422
    assert db_rows(client, BodyWeightLog) == []


# ---------- Tweak tab ----------


def test_tweak_tab_offers_hand_and_severity_with_descriptions(client):
    register(client)

    page = client.get("/log/sheet?tab=tweak").text

    for hand in ("left", "right", "both"):
        assert f'name="hand" value="{hand}"' in page
    for severity, label in ((1, "Niggle"), (2, "Tweak"), (3, "Injury")):
        assert f'name="severity" value="{severity}"' in page
        assert f"<strong>{label}</strong><small>" in page


def test_tweak_creates_todays_session_when_needed(client):
    register(client)

    response = client.post(
        "/log/tweak",
        data={"date": TODAY.isoformat(), "hand": "left", "severity": 2, "note": "pulley"},
        headers=HX,
    )

    assert response.status_code == 200
    assert "Tweak noted" in response.text
    [(report, training_session)] = db_rows(client, PainReport)
    assert (report.hand, report.severity, report.note) == ("left", 2, "pulley")
    assert training_session.date == TODAY


def test_tweak_upserts_one_row_per_hand_on_the_existing_session(client):
    register(client)
    save_work_set(client, "left", 1, "40", "5", date=TODAY.isoformat())

    client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "right", "severity": 1})
    client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "right", "severity": 3})

    rows = db_rows(client, PainReport)
    assert [(r.hand, r.severity) for r, _ in rows] == [("right", 3)]
    assert len({ts.id for _, ts in rows}) == 1


def test_tweak_on_a_past_date_needs_an_existing_session(client):
    register(client)

    refused = client.post("/log/tweak", data={"date": day(-3), "hand": "left", "severity": 1})
    assert refused.status_code == 400
    assert db_rows(client, PainReport) == []

    save_work_set(client, "left", 1, "40", "5", date=day(-3))
    ok = client.post(
        "/log/tweak", data={"date": day(-3), "hand": "left", "severity": 1}, follow_redirects=False
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/?saved=tweak"


def test_tweak_validates_hand_and_severity(client):
    register(client)

    assert client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "foot", "severity": 1}).status_code == 400
    assert client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "left", "severity": 4}).status_code == 422
    assert client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "left", "severity": 0}).status_code == 422
    assert db_rows(client, PainReport) == []


# ---------- auth and isolation ----------


def test_sheet_routes_require_login(client):
    assert client.get("/log/sheet").status_code == 401
    assert post_climb(client).status_code == 401
    assert client.post("/log/bodyweight", data={"date": TODAY.isoformat(), "weight": "70"}).status_code == 401
    assert client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "left", "severity": 1}).status_code == 401


def test_sheet_saves_are_scoped_to_the_logged_in_user(client):
    register(client, email="founder@example.com")
    log_climb(client, date=day(-1), grade="7C", style="redpoint")

    register_second_user(client)
    post_climb(client, grade="6A")
    client.post("/log/bodyweight", data={"date": TODAY.isoformat(), "weight": "60"})
    client.post("/log/tweak", data={"date": TODAY.isoformat(), "hand": "left", "severity": 1})

    # The friend's sheet defaults don't come from the founder's climbs.
    page = client.get("/log/sheet?tab=climb").text
    assert checked_style(page) == "flash"
    assert [c.grade for c in db_rows(client, Climb, "founder@example.com")] == ["7C"]
    assert db_rows(client, BodyWeightLog, "founder@example.com") == []
    assert db_rows(client, PainReport, "founder@example.com") == []
    assert [c.grade for c in db_rows(client, Climb, "friend@example.com")] == ["6A"]


# ---------- PR #154 review: blank grades and future dates ----------


def test_a_grade_that_is_blank_after_stripping_is_rejected(client):
    register(client)

    for blank in ("   ", "\t"):
        assert post_climb(client, grade=blank).status_code == 400
    assert db_rows(client, Climb) == []


def test_a_tweak_on_a_future_date_is_rejected(client):
    register(client)

    for future in ("9999-12-31", day(2)):
        response = client.post("/log/tweak", data={"date": future, "hand": "left", "severity": "1"})
        assert response.status_code == 400
    assert db_rows(client, PainReport) == []
    assert db_rows(client, TrainingSession) == []


def test_a_tweak_tomorrow_is_within_the_timezone_tolerance(client):
    register(client)

    response = client.post(
        "/log/tweak", data={"date": day(1), "hand": "left", "severity": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_go_lighter_on_a_future_date_is_rejected(client):
    register(client)

    for future in ("9999-12-31", day(2)):
        response = client.post("/today/lighter", data={"date": future, "on": "1"})
        assert response.status_code == 400
    assert db_rows(client, TrainingSession) == []
