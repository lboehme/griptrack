"""Persisted session-play state (PR #154 review, D2): the planned set count
and the in-progress combo live on the TrainingSession, so the step
derivation never depends on a URL hint surviving every round trip.

- MUST-FIX 1: Today's "+1 set" / ⋯ Add a set used to be a `sets=` URL hint
  that the first Set commit dropped ("set 4 of 3", or set 4 silently lost).
- MUST-FIX 6: Today's Resume fell back to the last-trained combo when the
  session had warmup ticks but no set yet.
- Nice-to-have: a pending rest leaked onto another combo's play page."""

import re
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

import pytest

from sqlmodel import select

from backend.db import get_session
from backend.models import TrainingSession
from tests.helpers import (
    complete_warmup,
    export_archive,
    generate_invite,
    import_archive,
    get_session_page,
    grip_type_id,
    log_max_test,
    play_step_title,
    register,
    register_second_user,
    save_focus_set,
)

DATE = "2026-07-04"
TODAY = date_type.today().isoformat()


def setup_tested_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")


def combo(client, grip="half crimp", edge_mm=20, date=DATE, **extra):
    return {"grip_type_id": grip_type_id(client, grip), "edge_mm": edge_mm, "date": date, **extra}


def play(client, **params):
    # get_session_page confirms the past-date creation gate on first use.
    return get_session_page(client, "/session/play", params)


def step_kind(text):
    m = re.search(r'id="play-step" data-step="(\w+)"', text)
    return m.group(1) if m else None


def rest_next_line(text):
    m = re.search(r'class="rest-next-line">([^<]*)<', text)
    return m.group(1).strip() if m else None


def sessions(client):
    session = next(client.app.dependency_overrides[get_session]())
    rows = session.exec(select(TrainingSession).order_by(TrainingSession.id)).all()
    session.close()
    return rows


def warm_up_with_hint(client, sets, **combo_params):
    """What the rendered warmup forms post: every rung-done carries the
    page's one-time `sets` initialiser."""
    params = {**combo_params}
    page = play(client, **params, sets=sets)
    assert f'name="sets" value="{sets}"' in page.text
    for step_index in range(8):
        if "rung-tile" not in page.text:
            return page
        client.post(
            "/session/rung-done",
            data={**params, "step_index": step_index, "sets": sets},
            follow_redirects=True,
        )
        page = play(client, **params)
    return page


# ---------- MUST-FIX 1: the planned set count is persisted ----------


def test_a_get_with_a_sets_hint_never_writes_state(client):
    setup_tested_user(client)
    page = client.get("/session/play", params={**combo(client, date=TODAY), "sets": 4})

    assert play_step_title(page.text) == "Warmup"
    assert sessions(client) == []


@pytest.mark.usefixtures("session_date_is_today")
def test_todays_extra_set_survives_every_set_commit_and_a_bare_reload(client):
    setup_tested_user(client)
    params = combo(client)
    warm_up_with_hint(client, 4, **params)

    for n in (1, 2, 3):
        response = save_focus_set(client, n, left=(30, 5, 7), right=(28, 5, 7))
        assert step_kind(response.text) == "rest"
        assert rest_next_line(response.text) == f"Next · set {n + 1} of 4 · same load"
        client.post("/session/rest/end", data=params, follow_redirects=True)

    # A bare /session/play reload (no sets= anywhere) is still on set 4.
    page = play(client, **params)
    assert step_kind(page.text) == "workset"
    assert play_step_title(page.text) == "Work set 4 of 4"
    assert sessions(client)[0].planned_sets == 4


@pytest.mark.usefixtures("session_date_is_today")
def test_the_rest_step_and_native_bridge_title_name_the_persisted_count(client):
    setup_tested_user(client)
    params = combo(client)
    warm_up_with_hint(client, 4, **params)

    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    page = play(client, **params).text

    assert step_kind(page) == "rest"
    assert 'data-rest-title="Rest · set 2 of 4 next"' in page
    assert 'data-total-sets="4"' in page


def test_a_set_commit_carrying_the_initialiser_persists_it(client):
    """No warmup ticks first (e.g. the warmup was already done on another
    path): the Set commit itself persists the page's `sets` initialiser."""
    setup_tested_user(client)
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)

    client.post(
        "/session/set",
        data={**params, "set_number": 1, "sets": 5, "left_weight": 30, "left_reps": 5,
              "right_weight": 28, "right_reps": 5},
    )

    assert play_step_title(play(client, **params).text) in ("Rest", "Work set 2 of 5")
    assert sessions(client)[0].planned_sets == 5


@pytest.mark.usefixtures("session_date_is_today")
def test_add_a_set_is_a_post_that_persists_and_remove_takes_it_back(client):
    setup_tested_user(client)
    params = combo(client)
    page = complete_warmup(client, params["grip_type_id"], 20)
    # The ⋯ menu no longer carries a GET sets= link.
    assert not re.search(r'href="[^"]*sets=', page.text)
    assert 'action="/session/sets"' in page.text

    response = client.post("/session/sets", data={**params, "sets": 4}, follow_redirects=False)
    assert response.status_code == 303
    assert "sets=" not in response.headers["location"]
    assert play_step_title(play(client, **params).text) == "Work set 1 of 4"

    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    assert rest_next_line(play(client, **params).text) == "Next · set 2 of 4 · same load"

    client.post("/session/sets", data={**params, "sets": 3})
    client.post("/session/rest/end", data=params)
    assert play_step_title(play(client, **params).text) == "Work set 2 of 3"


def test_add_a_set_answers_htmx_with_the_play_fragment(client):
    setup_tested_user(client)
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)

    response = client.post(
        "/session/sets", data={**params, "sets": 4}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'data-step-title="Work set 1 of 4"' in response.text


def test_add_a_set_after_finish_reopens_the_session_for_that_set(client):
    setup_tested_user(client)
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)
    for n in (1, 2, 3):
        save_focus_set(client, n, left=(30, 5, 7), right=(28, 5, 7))
        client.post("/session/rest/end", data=params)
    client.post("/session/finish", data=params)
    assert step_kind(play(client, **params).text) == "summary"

    client.post("/session/sets", data={**params, "sets": 4})

    # Survives a reload (no hint in the URL), then set 4 lands on the summary.
    page = play(client, **params).text
    assert step_kind(page) == "workset"
    assert play_step_title(page) == "Work set 4 of 4"
    response = save_focus_set(client, 4, left=(30, 5, 7), right=(28, 5, 7))
    assert step_kind(response.text) == "summary"


def test_planned_sets_is_bounded(client):
    setup_tested_user(client)
    params = combo(client)
    for bad in ("0", "101", "99999999999999999999"):
        response = client.post("/session/sets", data={**params, "sets": bad})
        assert response.status_code == 422


def test_add_a_set_only_touches_the_callers_session(client):
    setup_tested_user(client)
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)
    register_second_user(client)
    client.post("/session/sets", data={**params, "sets": 6})

    owner, intruder = sessions(client)
    assert owner.planned_sets is None
    assert intruder.planned_sets == 6
    assert owner.user_id != intruder.user_id


# ---------- MUST-FIX 6: Resume opens the combo play is actually on ----------


def test_resume_opens_the_combo_whose_warmup_was_started(client):
    register(client)
    for hand in ("left", "right"):
        log_max_test(client, hand, "half crimp", 20, "2026-07-01", "40")
        log_max_test(client, hand, "open hand", 10, "2026-07-01", "30")
    save_focus_set(client, 1, date="2026-07-02", left=(30, 5, 7), right=(30, 5, 7))

    open_hand = combo(client, grip="open hand", edge_mm=10, date=TODAY)
    client.post("/session/rung-done", data={**open_hand, "step_index": 0})

    page = client.get("/").text
    assert 'data-state="resume"' in page
    href = re.search(r'class="btn today-primary today-resume-btn" href="([^"]*)"', page).group(1)
    assert f"grip_type_id={open_hand['grip_type_id']}" in href
    assert "edge_mm=10" in href


def test_a_bare_get_never_stamps_the_play_combo(client):
    setup_tested_user(client)
    open_hand = combo(client, grip="open hand", edge_mm=10)
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)

    play(client, **open_hand)

    row = sessions(client)[0]
    assert (row.play_grip_type_id, row.play_edge_mm) == (int(params["grip_type_id"]), 20)


# ---------- nice-to-have: a pending rest belongs to the play combo ----------


@pytest.mark.usefixtures("session_date_is_today")
def test_a_pending_rest_does_not_leak_onto_another_combo(client):
    setup_tested_user(client)
    log_max_test(client, "left", "open hand", 10, "2026-07-01", "30")
    log_max_test(client, "right", "open hand", 10, "2026-07-01", "30")
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    assert step_kind(play(client, **params).text) == "rest"

    other = play(client, **combo(client, grip="open hand", edge_mm=10)).text
    assert step_kind(other) != "rest"
    assert 'id="rest-step"' not in other
    # ...and the original combo still shows its rest.
    assert step_kind(play(client, **params).text) == "rest"


def test_export_import_round_trips_the_play_state(client):
    setup_tested_user(client)
    params = combo(client)
    complete_warmup(client, params["grip_type_id"], 20)
    client.post("/session/sets", data={**params, "sets": 5})
    archive = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    assert import_archive(client, archive).status_code == 303

    restored = sessions(client)[-1]
    assert restored.planned_sets == 5
    assert (restored.play_grip_type_id, restored.play_edge_mm) == (int(params["grip_type_id"]), 20)


# ---------- nice-to-have: retro-logging never starts a real rest ----------


def test_a_set_committed_on_a_past_date_starts_no_rest(client):
    setup_tested_user(client)
    params = combo(client, date="2026-07-04")
    complete_warmup(client, params["grip_type_id"], 20, date="2026-07-04")

    response = save_focus_set(client, 1, date="2026-07-04", left=(30, 5, 7), right=(28, 5, 7))

    assert step_kind(response.text) == "workset"
    assert play_step_title(response.text) == "Work set 2 of 3"
    assert 'id="rest-step"' not in response.text
    assert sessions(client)[0].rest_ends_at is None


def test_a_set_committed_today_still_starts_the_rest(client):
    setup_tested_user(client)
    params = combo(client, date=TODAY)
    complete_warmup(client, params["grip_type_id"], 20, date=TODAY)

    response = save_focus_set(client, 1, date=TODAY, left=(30, 5, 7), right=(28, 5, 7))

    assert step_kind(response.text) == "rest"



# ---------- nice-to-have: session load runs from the first real activity ----------


@pytest.mark.parametrize("create", ["tweak", "lighter"])
def test_a_row_created_before_training_has_no_start_until_play_begins(client, create):
    setup_tested_user(client)
    if create == "tweak":
        client.post("/log/tweak", data={"date": TODAY, "hand": "left", "severity": "1"})
    else:
        client.post("/today/lighter", data={"date": TODAY, "on": "1"})
    assert sessions(client)[0].started_at is None

    before = datetime.now(timezone.utc).replace(tzinfo=None)
    params = combo(client, date=TODAY)
    client.post("/session/rung-done", data={**params, "step_index": 0})

    started = sessions(client)[0].started_at
    assert started is not None
    assert started.replace(tzinfo=None) >= before - timedelta(seconds=1)
