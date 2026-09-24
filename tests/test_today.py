"""Today (#149): the coach home at `/` -- plan selection, Go lighter, the
rest-day suggestion, resume / done states, the week strip, the bodyweight
prompt, the Change picker, and the new tab bar / redirects.

Everything here runs against the server's own `date.today()` because Today
is always today; history is seeded relative to it."""

import html
import re
from datetime import date as date_type
from datetime import timedelta

from sqlmodel import select

from backend.db import get_session
from backend.models import TrainingSession, User
from tests.conftest import WEBVIEW_DEVICE_TOKEN
from tests.helpers import (
    grip_type_id,
    log_bodyweight,
    log_climb,
    log_max_test,
    register,
    register_second_user,
    save_focus_set,
    save_work_set,
)

TODAY = date_type.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def tested_user(client, weight="40"):
    register(client)
    log_max_test(client, "left", "half crimp", 20, day(-60), weight)
    log_max_test(client, "right", "half crimp", 20, day(-60), weight)


def today_page(client, **params):
    response = client.get("/", params=params)
    assert response.status_code == 200
    return response.text


def state(page):
    return re.search(r'id="today-root" class="today" data-state="(\w+)"', page).group(1)


def plan_attr(page, name):
    match = re.search(rf'class="card glass strong today-card today-plan"[^>]*data-{name}="([^"]*)"', page)
    return match.group(1) if match else None


def hand_plan(page, hand):
    match = re.search(
        rf'class="today-hand" data-hand="{hand}" data-weight="([^"]*)" data-source="([^"]*)"',
        page,
    )
    return (match.group(1), match.group(2)) if match else None


def reason(page):
    match = re.search(r'data-reason="([^"]*)"', page)
    return html.unescape(match.group(1)) if match else None


def db_session(client):
    return next(client.app.dependency_overrides[get_session]())


def todays_session(client, email="lifter@example.com"):
    session = db_session(client)
    user = session.exec(select(User).where(User.email == email)).one()
    row = session.exec(
        select(TrainingSession)
        .where(TrainingSession.user_id == user.id)
        .where(TrainingSession.date == TODAY)
    ).first()
    session.close()
    return row


def full_session(client, date, weight=40.0, reps=5, rpe=None, sets=3, grip="half crimp"):
    for n in range(1, sets + 1):
        save_focus_set(
            client, n, date=date, grip=grip,
            left=(weight, reps, rpe), right=(weight, reps, rpe),
        )


# ---------- plan selection ----------


def test_plan_uses_the_last_trained_combination(client):
    tested_user(client)
    log_max_test(client, "left", "open hand", 10, day(-50), "30")
    save_work_set(client, "left", 1, "40", "5", date=day(-20))  # half crimp trained last

    page = today_page(client)

    assert state(page) == "plan"
    assert plan_attr(page, "grip-type-id") == grip_type_id(client, "half crimp")
    assert plan_attr(page, "edge-mm") == "20"
    assert "Half crimp · 20 mm" in page


def test_plan_falls_back_to_current_max_with_no_session_history(client):
    tested_user(client, weight="40")

    page = today_page(client)

    assert hand_plan(page, "left") == ("40.0", "max")
    assert hand_plan(page, "right") == ("40.0", "max")
    assert reason(page) == "Built from your current max"
    # Sets × reps from the protocol (3 work sets) and progression path (5).
    assert plan_attr(page, "sets") == "3"
    assert plan_attr(page, "reps") == "5"
    assert "3 × 5" in page


def test_plan_falls_back_to_the_last_sessions_weights(client):
    tested_user(client)
    # No RPE logged -> autoregulation is ineligible, so last session wins.
    full_session(client, day(-5), weight=37.5)

    page = today_page(client)

    assert hand_plan(page, "left") == ("37.5", "last")
    assert hand_plan(page, "right") == ("37.5", "last")
    assert reason(page) == "Same as last session"


def test_plan_uses_the_autoregulation_suggestion_and_says_why(client):
    tested_user(client)
    # Two non-deload sessions at target reps and RPE 7 -> "ready": the
    # Weight path suggests the next loadable rung above 40 (40.5 kg with
    # the default kg plates).
    full_session(client, day(-8), weight=40.0, rpe=7.0)
    full_session(client, day(-5), weight=40.0, rpe=7.0)

    page = today_page(client)

    assert hand_plan(page, "left") == ("40.5", "suggestion")
    assert hand_plan(page, "right") == ("40.5", "suggestion")
    assert reason(page) == "+0.5 kg: last session felt easy (RPE 7)"


def test_set_progression_plans_one_more_set(client):
    tested_user(client)
    client.post(
        "/profile/progression",
        data={"path": "set", "rep_min": 5, "rep_max": 5, "max_sets": 6},
    )
    full_session(client, day(-8), weight=40.0, rpe=7.0)
    full_session(client, day(-5), weight=40.0, rpe=7.0)

    page = today_page(client)

    assert plan_attr(page, "sets") == "4"
    assert reason(page) == "+1 set: last session felt easy (RPE 7)"
    # Start carries the extra set to /session/play.
    assert 'name="sets" value="4"' in page


def test_start_goes_to_session_play_with_the_combo(client):
    tested_user(client)

    page = today_page(client)

    form = re.search(
        r'<form method="get" action="/session/play" class="today-start-form">(.*?)</form>', page, re.DOTALL
    )
    assert form is not None
    body = form.group(1)
    assert f'name="grip_type_id" value="{grip_type_id(client, "half crimp")}"' in body
    assert 'name="edge_mm" value="20"' in body
    # Client-local date: client-date.js rewrites the server's default.
    assert f'name="date" value="{TODAY.isoformat()}" class="local-date-default"' in body
    assert "Start session" in body


def test_no_data_yet_prompts_for_the_guided_max_test(client):
    register(client)

    page = today_page(client)

    assert state(page) == "no_data"
    assert 'href="/progress/maxes"' in page
    assert "today-start-form" not in page
    assert "today-plan" not in page


# ---------- Change picker ----------


def test_change_picker_preselects_the_plan_and_rerenders_today_for_a_choice(client):
    tested_user(client)
    log_max_test(client, "left", "open hand", 10, day(-70), "30")

    picker = client.get("/today/change").text
    half = grip_type_id(client, "half crimp")
    assert f'value="{half}" selected' in picker
    assert 'name="edge_mm" value="20"' in picker
    # The picker never pushes history (Android Back): no hx-push-url anywhere.
    assert "hx-push-url" not in picker

    open_hand = grip_type_id(client, "open hand")
    page = today_page(client, grip_type_id=open_hand, edge_mm=10)
    assert plan_attr(page, "grip-type-id") == open_hand
    assert hand_plan(page, "left") == ("30.0", "max")
    assert hand_plan(page, "right") == ("", "")


def test_change_picker_renders_server_side_without_js(client):
    tested_user(client)

    page = today_page(client, change=1)

    assert 'id="today-picker"' in page


def test_change_picker_rejects_an_unknown_grip(client):
    tested_user(client)

    assert client.get("/", params={"grip_type_id": 9999, "edge_mm": 20}).status_code == 404
    assert client.get("/today/change", params={"grip_type_id": 9999, "edge_mm": 20}).status_code == 404


def test_voided_test_no_longer_drives_the_plan_combo(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, day(-10), "42.5")
    log_max_test(client, "left", "open hand", 10, day(-9), "35")
    assert plan_attr(today_page(client), "grip-type-id") == grip_type_id(client, "open hand")

    max_tests = client.get("/progress/maxes").text
    newest_id = max(int(i) for i in re.findall(r'action="/max-tests/(\d+)/void"', max_tests))
    client.post(f"/max-tests/{newest_id}/void")

    assert plan_attr(today_page(client), "grip-type-id") == grip_type_id(client, "half crimp")


# ---------- Go lighter ----------


def test_go_lighter_is_not_offered_without_a_reason(client):
    tested_user(client)

    assert "go-lighter-btn" not in today_page(client)


def test_go_lighter_is_offered_after_a_recent_pain_report(client):
    tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date=day(-3))
    client.post(
        "/session/pain-report",
        data={"date": day(-3), "hand": "left", "severity": 1},
    )

    page = today_page(client)

    assert "go-lighter-btn" in page
    assert "Left hand: niggle logged" in page


def test_a_pain_report_older_than_a_week_does_not_offer_go_lighter(client):
    tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date=day(-9))
    client.post("/session/pain-report", data={"date": day(-9), "hand": "left", "severity": 2})

    assert "go-lighter-btn" not in today_page(client)


def test_go_lighter_marks_the_session_deload_and_scales_to_85_percent_rounded_down(client):
    tested_user(client, weight="40")

    response = client.post(
        "/today/lighter", data={"date": TODAY.isoformat(), "on": "1"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    assert todays_session(client).is_deload is True
    page = today_page(client)
    # 85% of 40 is 34, which the default kg plates can't make on one pin:
    # rounded DOWN to the next loadable rung, 33.75 -- never up.
    assert hand_plan(page, "left") == ("33.75", "max")
    assert hand_plan(page, "right") == ("33.75", "max")
    assert "data-deload" in page
    assert reason(page) == "Go lighter: 85% of today's plan"
    # Still offered (so it can be undone), and the empty session it created
    # doesn't turn Start into Resume.
    assert "Undo lighter" in page
    assert state(page) == "plan"

    client.post("/today/lighter", data={"date": TODAY.isoformat(), "on": "0"})

    assert todays_session(client).is_deload is False
    page = today_page(client)
    assert hand_plan(page, "left") == ("40.0", "max")
    assert "data-deload" not in page


def test_go_lighter_keeps_the_picked_combo(client):
    tested_user(client)
    gid = grip_type_id(client, "half crimp")

    response = client.post(
        "/today/lighter",
        data={"date": TODAY.isoformat(), "on": "1", "grip_type_id": gid, "edge_mm": 20},
        follow_redirects=False,
    )

    assert response.headers["location"] == f"/?grip_type_id={gid}&edge_mm=20"


def test_go_lighter_refuses_to_create_a_past_session(client):
    tested_user(client)

    response = client.post("/today/lighter", data={"date": day(-3), "on": "1"})

    assert response.status_code == 400


# ---------- rest-day suggestion ----------


def test_two_consecutive_training_days_suggest_a_rest_day_without_blocking(client):
    tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date=day(-2))
    save_work_set(client, "left", 1, "40", "5", date=day(-1))

    page = today_page(client)

    assert state(page) == "rest"
    assert "Rest day" in page
    # Start drops to a secondary button but is still there.
    assert re.search(r'<button type="submit" class="today-start btn-secondary">Train anyway</button>', page)


def test_one_training_day_is_not_a_rest_day(client):
    tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date=day(-1))
    save_work_set(client, "left", 1, "40", "5", date=day(-3))

    page = today_page(client)

    assert state(page) == "plan"
    assert "Pull day" in page


def test_overtraining_warning_suggests_a_rest_day(client):
    tested_user(client)
    # Four evenly spaced sessions, then a volume spike after a short rest:
    # the OvertrainingWarning heuristic (spike AND short rest).
    for offset in (-41, -31, -21, -11):
        save_work_set(client, "left", 1, "40", "5", date=day(offset))
    save_work_set(client, "left", 1, "40", "5", date=day(-9))
    save_work_set(client, "left", 2, "40", "5", date=day(-9))

    page = today_page(client)

    assert state(page) == "rest"
    assert "spiked" in page
    assert "go-lighter-btn" in page


# ---------- resume and done ----------


def test_an_in_progress_session_turns_start_into_resume(client):
    tested_user(client)
    save_focus_set(client, 1, date=TODAY.isoformat(), left=(40, 5, None), right=(40, 5, None))

    page = today_page(client)

    assert state(page) == "resume"
    assert "Resume · set 2 of 3" in page
    gid = grip_type_id(client, "half crimp")
    assert (
        f'href="/session/play?grip_type_id={gid}&amp;edge_mm=20&amp;date={TODAY.isoformat()}'
        f'&amp;session_number=1"'
    ) in page


def test_warmup_ticks_alone_already_count_as_in_progress(client):
    tested_user(client)
    gid = grip_type_id(client, "half crimp")
    client.post(
        "/session/rung-done",
        data={"grip_type_id": gid, "edge_mm": 20, "date": TODAY.isoformat(), "step_index": 0},
    )

    page = today_page(client)

    assert state(page) == "resume"
    assert "Resume · set 1 of 3" in page


def test_a_finished_session_shows_the_recap_and_log_a_climb(client):
    tested_user(client)
    full_session(client, TODAY.isoformat(), weight=40.0, reps=5)

    page = today_page(client)

    assert state(page) == "done"
    assert "Done for today." in page
    assert 'data-recap-sets="3"' in page
    # 3 sets × 2 hands × 40 kg × 5 reps
    assert 'data-recap-volume="1200.0"' in page
    assert re.search(r'class="btn today-primary"[^>]*>Log a climb</a>', page)
    assert "today-start-form" not in page


def test_finishing_early_counts_as_done(client):
    """Finish on the summary (#147) ends the session even with planned sets
    left: Today shows the recap, not "Resume"."""
    tested_user(client)
    today = TODAY.isoformat()
    save_focus_set(client, 1, date=today, left=("40", "5", "8"), right=("40", "5", "8"))
    assert state(today_page(client)) == "resume"

    gid = grip_type_id(client, "half crimp")
    client.post("/session/finish", data={"grip_type_id": gid, "edge_mm": 20, "date": today})

    assert state(today_page(client)) == "done"


def test_the_recap_shows_session_rpe_once_rated(client):
    tested_user(client)
    today = TODAY.isoformat()
    full_session(client, today)
    assert "data-recap-rpe" not in today_page(client)

    gid = grip_type_id(client, "half crimp")
    client.post(
        "/session/rpe",
        data={"grip_type_id": gid, "edge_mm": 20, "date": today, "session_rpe": "7"},
    )

    assert 'data-recap-rpe="7"' in today_page(client)


def test_training_again_after_done_plans_a_second_session(client):
    tested_user(client)
    full_session(client, TODAY.isoformat())
    gid = grip_type_id(client, "half crimp")

    page = today_page(client, grip_type_id=gid, edge_mm=20)

    assert state(page) == "plan"
    assert 'name="session_number" value="2"' in page
    picker = client.get("/today/change").text
    assert "start-second-session" in picker
    assert 'name="session_number" value="2"' in picker


def test_second_session_affordance_only_once_today_has_a_session(client):
    tested_user(client)

    assert "start-second-session" not in client.get("/today/change").text


# ---------- bodyweight prompt and week ----------


def test_stale_or_missing_bodyweight_prompts_a_weigh_in(client):
    tested_user(client)
    assert "today-bodyweight" in today_page(client)

    log_bodyweight(client, day(-29), "70")
    assert "today-bodyweight" in today_page(client)

    log_bodyweight(client, day(-3), "70.4")
    assert "today-bodyweight" not in today_page(client)


def test_bodyweight_prompt_opens_the_sheet_on_the_bodyweight_tab(client):
    tested_user(client)

    page = today_page(client)

    assert 'href="/?log=bodyweight" hx-get="/log/sheet?tab=bodyweight"' in page


def test_this_week_counts_sessions_climbs_and_the_best_send(client):
    tested_user(client)
    week_start = TODAY - timedelta(days=TODAY.weekday())
    save_work_set(client, "left", 1, "40", "5", date=week_start.isoformat())
    save_work_set(client, "left", 1, "40", "5", date=(week_start - timedelta(days=1)).isoformat())
    log_climb(client, date=week_start.isoformat(), grade="7A", style="flash")
    log_climb(client, date=week_start.isoformat(), grade="7B", style="attempt")
    log_climb(client, date=TODAY.isoformat(), grade="6C", style="redpoint")
    log_climb(client, date=(week_start - timedelta(days=1)).isoformat(), grade="8A", style="flash")

    page = today_page(client)

    assert 'data-week-sessions="1"' in page
    assert 'data-week-climbs="3"' in page
    # An attempt isn't a send, and last week's 8A doesn't count.
    assert 'data-best-send="7A"' in page
    assert "--dot: var(--grade-7a)" in page


def test_week_strip_has_no_best_send_without_sends(client):
    tested_user(client)

    assert 'data-best-send=""' in today_page(client)


# ---------- isolation ----------


def test_today_is_scoped_to_the_logged_in_user(client):
    register(client, email="founder@example.com")
    log_max_test(client, "left", "half crimp", 20, day(-60), "40")
    save_focus_set(client, 1, date=TODAY.isoformat(), left=(40, 5, None))
    log_climb(client, date=TODAY.isoformat(), grade="7A")

    register_second_user(client)
    page = today_page(client)

    assert state(page) == "no_data"
    assert 'data-week-climbs="0"' in page
    assert 'data-week-sessions="0"' in page


def test_go_lighter_only_touches_the_callers_session(client):
    register(client, email="founder@example.com")
    log_max_test(client, "left", "half crimp", 20, day(-60), "40")
    save_work_set(client, "left", 1, "40", "5", date=TODAY.isoformat())

    register_second_user(client)
    client.post("/today/lighter", data={"date": TODAY.isoformat(), "on": "1"})

    assert todays_session(client, "founder@example.com").is_deload is False
    assert todays_session(client, "friend@example.com").is_deload is True


# ---------- headline / identity ----------


def test_headline_greets_by_name(client):
    register(client, name="Lukas")
    log_max_test(client, "left", "half crimp", 20, day(-60), "40")

    assert "Pull day, Lukas." in today_page(client)


def test_today_never_shows_the_device_placeholder_email(webview_client):
    webview_client.post("/device-login", data={"token": WEBVIEW_DEVICE_TOKEN})
    webview_client.post("/welcome", data={"unit_pref": "kg", "hand_order_pref": "alternating"})

    page = webview_client.get("/").text

    assert "device-owner" not in page
    assert "griptrack.local" not in page
    assert "Logged in as" not in page
    assert 'data-greeting-name=""' in page


# ---------- navigation ----------


def test_tab_bar_has_today_progress_log_and_settings(client):
    register(client)

    page = today_page(client)
    nav = re.search(r'<nav class="tabbar[^"]*"[^>]*>(.*?)</nav>', page, re.DOTALL).group(1)

    assert 'href="/"' in nav
    assert 'href="/progress"' in nav
    assert 'href="/settings"' in nav
    # ＋ Log opens the sheet in place (no history entry), plain link without JS.
    assert 'href="/?log=climb" hx-get="/log/sheet?tab=climb" hx-target="#log-sheet-slot"' in nav
    assert "hx-push-url" not in page
    for gone in ('href="/session/new"', 'href="/climbs"', 'href="/dashboard"', 'href="/profile"'):
        assert gone not in nav


def test_tab_bar_is_hidden_during_session_play(client):
    tested_user(client)
    gid = grip_type_id(client, "half crimp")

    page = client.get(
        "/session/play", params={"grip_type_id": gid, "edge_mm": 20, "date": TODAY.isoformat()}
    ).text

    assert 'class="tabbar' not in page


def test_tab_bar_is_hidden_on_first_run_screens(webview_client):
    webview_client.post("/device-login", data={"token": WEBVIEW_DEVICE_TOKEN})
    assert 'class="tabbar' not in webview_client.get("/welcome").text
    webview_client.post("/welcome", data={"unit_pref": "kg", "hand_order_pref": "alternating"})

    assert 'class="tabbar' not in webview_client.get("/welcome/plates").text
    assert 'class="tabbar' not in webview_client.get("/welcome/test").text
    assert 'class="tabbar' in webview_client.get("/").text


def test_progress_is_a_real_page_and_settings_aliases_profile(client):
    register(client)

    # Progress shipped (#150): a page of its own, no longer a 303 alias.
    progress = client.get("/progress", follow_redirects=False)
    settings = client.get("/settings", follow_redirects=False)

    assert progress.status_code == 200
    assert 'id="progress-root"' in progress.text
    assert (settings.status_code, settings.headers["location"]) == (303, "/profile")


def test_old_session_new_and_climbs_pages_redirect(client):
    register(client)

    new = client.get("/session/new", follow_redirects=False)
    climbs = client.get("/climbs", follow_redirects=False)

    assert (new.status_code, new.headers["location"]) == (303, "/")
    assert (climbs.status_code, climbs.headers["location"]) == (303, "/?log=climb")


def test_tab_pages_require_login(client):
    for path in ("/progress", "/settings", "/today/change", "/session/new", "/climbs"):
        assert client.get(path, follow_redirects=False).status_code == 401
