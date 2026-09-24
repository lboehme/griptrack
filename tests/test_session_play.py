"""HTTP-seam tests for /session/play (#146, docs/adr/0014): the server
derives which step (warmup rung, work set, rest, summary) to render from
persisted state, and every action answers with either the next step's htmx
fragment or a 303 back to /session/play for a plain form post."""

import re
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend import training_log
from backend.db import configure_sqlite_pragmas, get_session
from backend.models import (
    STARTER_GRIP_TYPES,
    GripType,
    TrainingProtocol,
    TrainingSession,
    User,
    WorkSet,
)
from tests.helpers import (
    checked_steps,
    complete_warmup,
    completed_detail,
    current_maxes,
    current_set_field,
    delete_focus_set,
    get_session_page,
    grip_type_id,
    log_max_test,
    play_step_title,
    register,
    register_second_user,
    restore_focus_set,
    save_focus_set,
    save_work_set,
    workset_step,
)


def setup_tested_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")


def play_page(client, grip="half crimp", edge_mm=20, date="2026-07-04", **params):
    all_params = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
        **params,
    }
    return get_session_page(client, "/session/play", all_params)


def rest_ends_at(page_text):
    m = re.search(r'data-rest-ends-at="([^"]*)"', page_text)
    return m.group(1) if m and m.group(1) else None


def step_kind(page_text):
    m = re.search(r'id="play-step" data-step="(\w+)"', page_text)
    return m.group(1) if m else None


# ---------- step derivation: warmup -> work set -> rest -> work set -> summary ----------


def test_new_session_starts_on_the_first_warmup_rung(client):
    setup_tested_user(client)
    page = play_page(client)

    assert page.status_code == 200
    assert step_kind(page.text) == "warmup"
    assert "50%" in page.text


def test_rung_done_advances_to_the_next_rung(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")

    r = client.post(
        "/session/rung-done",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "step_index": 0},
        follow_redirects=True,
    )
    assert step_kind(r.text) == "warmup"
    assert "65%" in r.text


def test_completing_every_rung_reaches_the_first_work_set(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    page = complete_warmup(client, gid, 20)

    assert step_kind(page.text) == "workset"
    assert "hand-card" in page.text


def test_a_non_final_set_commit_moves_to_the_rest_step(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)

    response = save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    assert step_kind(response.text) == "rest"
    assert rest_ends_at(response.text) is not None


def test_skip_rest_moves_straight_to_the_next_set(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))

    response = client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )
    assert step_kind(response.text) == "workset"
    assert rest_ends_at(response.text) is None


def test_plus_30_seconds_moves_rest_ends_at_by_exactly_30(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    page = save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    before = datetime.fromisoformat(rest_ends_at(page.text))

    response = client.post(
        "/session/rest/extend",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        headers={"HX-Request": "true"},
    )
    after = datetime.fromisoformat(rest_ends_at(response.text))

    assert (after - before).total_seconds() == 30


def test_the_final_sets_commit_skips_rest_and_reaches_the_summary(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)

    # Default protocol: 3 work sets.
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )
    save_focus_set(client, 2, left=(30, 5, 7), right=(28, 5, 7))
    client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )
    response = save_focus_set(client, 3, left=(30, 5, 7), right=(28, 5, 7))

    assert step_kind(response.text) == "summary"
    assert "Session done" in response.text
    assert rest_ends_at(response.text) is None


def test_editing_a_completed_set_does_not_touch_rest(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )

    response = client.post(
        "/session/set",
        data={
            "grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04",
            "set_number": 1, "editing": "true",
            "left_weight": 31, "left_reps": 5, "left_rpe": 7,
            "right_weight": 28, "right_reps": 5, "right_rpe": 7,
        },
        follow_redirects=True,
    )
    assert rest_ends_at(response.text) is None
    assert step_kind(response.text) == "workset"


# ---------- resume after a "reload" ----------


def test_resume_after_reload_lands_on_the_same_rung(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    client.post(
        "/session/rung-done",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "step_index": 0},
        follow_redirects=True,
    )

    page = play_page(client)
    assert step_kind(page.text) == "warmup"
    assert "65%" in page.text


def test_resume_after_reload_during_rest_keeps_the_same_set_number_and_lands_on_rest(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))

    page = play_page(client)
    assert step_kind(page.text) == "rest"
    assert "set 2 of 3" in page.text.lower()


def test_resume_after_reload_on_a_work_set_lands_on_the_right_set_number(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )

    page = play_page(client)
    assert step_kind(page.text) == "workset"
    assert 'name="set_number" value="2"' in page.text


# ---------- htmx fragment vs no-JS 303, on every POST ----------


def test_rung_done_answers_303_without_htmx_and_a_fragment_with_it(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    data = {"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "step_index": 0}

    plain = client.post("/session/rung-done", data=data, follow_redirects=False)
    assert plain.status_code == 303
    assert plain.headers["location"].startswith("/session/play?")

    htmx = client.post("/session/rung-done", data=data, headers={"HX-Request": "true"})
    assert htmx.status_code == 200
    assert "<html" not in htmx.text


def test_set_commit_answers_303_without_htmx_and_a_fragment_with_it(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    data = {
        "grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "set_number": 1,
        "left_weight": 30, "left_reps": 5, "right_weight": 28, "right_reps": 5,
    }

    plain = client.post("/session/set", data=data, follow_redirects=False)
    assert plain.status_code == 303
    assert plain.headers["location"].startswith("/session/play?")

    # Re-post the same (now non-final) set with HX-Request -- upsert in place.
    htmx = client.post("/session/set", data=data, headers={"HX-Request": "true"})
    assert htmx.status_code == 200
    assert "<html" not in htmx.text
    assert step_kind(htmx.text) == "rest"


def test_rest_end_answers_303_without_htmx_and_a_fragment_with_it(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    data = {"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"}

    htmx = client.post("/session/rest/end", data=data, headers={"HX-Request": "true"})
    assert htmx.status_code == 200
    assert "<html" not in htmx.text
    assert step_kind(htmx.text) == "workset"


# ---------- redirects preserve every query parameter ----------


def test_legacy_warmup_redirects_to_play_preserving_params(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")

    response = client.get(
        "/session/warmup",
        params={
            "grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04",
            "hand": "left", "session_number": 1,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/session/play?")
    for fragment in (
        f"grip_type_id={gid}", "edge_mm=20", "date=2026-07-04",
        "hand=left", "session_number=1",
    ):
        assert fragment in location


def test_legacy_worksets_redirects_to_play_preserving_sets_and_edit(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")

    response = client.get(
        "/session/worksets",
        params={
            "grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04",
            "sets": 5, "edit": 2,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/session/play?")
    assert "sets=5" in location
    assert "edit=2" in location


# ---------- isolation and bounds ----------


def test_user_b_cannot_reach_or_mutate_user_as_session_through_play(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))

    register_second_user(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    # User B's own /session/play for the same combo/date starts fresh, on
    # warmup -- it never sees user A's rest state or committed set.
    page = play_page(client, gid=gid)
    assert step_kind(page.text) == "warmup"

    # User B's delete/restore/rest actions against that (date, combo) can
    # only ever touch user B's own (non-existent) session.
    delete_response = delete_focus_set(client, 1, date="2026-07-04")
    assert delete_response.status_code == 200
    restore_response = restore_focus_set(client, 1, date="2026-07-04", left=(99, 9, None))
    assert restore_response.status_code == 200

    rest_response = client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )
    assert rest_response.status_code == 200

    # Back to user A: their session is untouched by any of the above.
    client.post("/logout")
    from tests.helpers import login

    login(client, "lifter@example.com", "test-pw-1234")
    page = play_page(client)
    assert step_kind(page.text) == "rest"


def test_rest_extend_out_of_range_seconds_are_rejected_at_the_boundary(client):
    """No numeric input on the rest endpoints is user-controlled (extend is
    a fixed +30s), but step_index and set_number still carry the app's usual
    upper bounds (backend.limits) -- an absurd step_index is rejected."""
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")

    response = client.post(
        "/session/rung-done",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "step_index": 99999},
        follow_redirects=False,
    )
    assert response.status_code == 422


def test_edge_mm_out_of_range_is_rejected_on_play(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")

    response = client.get(
        "/session/play",
        params={"grip_type_id": gid, "edge_mm": 999999, "date": "2026-07-04"},
    )
    assert response.status_code == 422


def test_unknown_grip_type_on_play_is_rejected(client):
    register(client)

    response = client.get(
        "/session/play",
        params={"grip_type_id": 999999, "edge_mm": 20, "date": "2026-07-04"},
    )
    assert response.status_code == 404


# ---------- rest_ends_at model/derivation edge cases ----------


def test_rest_step_shows_pull_once_the_stored_end_time_has_passed(client):
    """rest_ends_at in the past still derives to the rest step (not
    silently skipped) -- the ring just shows 0:00/"Pull" until the user
    acts (docs/adr/0014 orchestrator decision 1)."""
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))

    # Force rest_ends_at into the past directly (simulating time passing) --
    # same idiom as tests/test_climbs.py and friends.
    session = next(client.app.dependency_overrides[get_session]())
    ts = session.exec(select(TrainingSession)).first()
    ts.rest_ends_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    session.add(ts)
    session.commit()

    page = play_page(client)
    assert step_kind(page.text) == "rest"
    assert "Pull" in page.text
    assert "Start set 2" in page.text


# ---------- POST /session/set (Set commit, docs/adr/0007) -- unchanged behavior ----------


def test_set_commit_writes_both_hands_in_one_atomic_request(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)

    response = save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    assert response.status_code == 200
    assert step_kind(response.text) == "rest"  # a non-final set starts rest

    # Both hands landed atomically -- visible once back on the work-set step.
    back = client.post(
        "/session/rest/end",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"},
        follow_redirects=True,
    )
    assert "42.5" in back.text and "40.0" in back.text


def test_invalid_partial_payload_writes_nothing_at_all(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)

    response = client.post(
        "/session/set",
        data={
            "grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "set_number": 1,
            "left_weight": 42.5,  # missing left_reps
        },
        follow_redirects=True,
    )
    assert response.status_code == 400

    page = play_page(client)
    assert "hand-card" in page.text  # still on the same in-progress set 1


def test_bad_rpe_is_rejected_and_writes_nothing(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)

    response = client.post(
        "/session/set",
        data={
            "grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "set_number": 1,
            "left_weight": 40, "left_reps": 5, "left_rpe": 7.3,
        },
        follow_redirects=True,
    )
    assert response.status_code == 400


def test_unknown_grip_type_is_rejected_on_set_commit(client):
    register(client)
    response = client.post(
        "/session/set",
        data={
            "grip_type_id": 999999, "edge_mm": 20, "date": "2026-07-04", "set_number": 1,
            "left_weight": 40, "left_reps": 5,
        },
    )
    assert response.status_code == 404


def test_delete_set_renumbers_remaining_sets_without_gaps(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=(40, 5, 7))
    client.post("/session/rest/end", data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"})
    save_focus_set(client, 2, left=(45, 5, 8))

    response = delete_focus_set(client, 1, date="2026-07-04")
    assert response.status_code == 200
    # The old set 2 is now set 1.
    assert "45.0" in response.text or "45" in response.text


# ---------- unit-level (training_log) -- ported from the pre-#146 suite ----------


def make_test_db() -> tuple[Session, User, int]:
    engine = configure_sqlite_pragmas(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    for name in STARTER_GRIP_TYPES:
        dimension = "block width" if name == "pinch" else "edge depth"
        session.add(GripType(name=name, dimension_name=dimension))
    session.add(TrainingProtocol(user_id=None))
    user = User(email="test@example.com", hashed_password="pw")
    session.add(user)
    session.commit()
    session.refresh(user)
    grip = session.exec(select(GripType).where(GripType.name == "half crimp")).one()
    assert grip.id is not None
    return session, user, grip.id


def test_parse_hands_payload_valid_two_hands():
    result = training_log.parse_hands_payload(
        left_weight=42.5, left_reps=5, left_rpe=8.0,
        right_weight=40.0, right_reps=5, right_rpe=7.5,
    )
    assert result == {"left": (42.5, 5, 8.0), "right": (40.0, 5, 7.5)}


def test_parse_hands_payload_single_hand_sequential():
    result = training_log.parse_hands_payload(left_weight=42.5, left_reps=5, left_rpe=None)
    assert result == {"left": (42.5, 5, None)}


def test_parse_hands_payload_rejects_missing_reps():
    with pytest.raises(training_log.SetValidationError, match="left hand needs both weight and reps"):
        training_log.parse_hands_payload(left_weight=42.5, left_reps=None)


def test_parse_hands_payload_rejects_out_of_range_values():
    with pytest.raises(training_log.SetValidationError, match="Weight out of range"):
        training_log.parse_hands_payload(left_weight=-5.0, left_reps=5)
    with pytest.raises(training_log.SetValidationError, match="Reps out of range"):
        training_log.parse_hands_payload(left_weight=40.0, left_reps=0)
    with pytest.raises(training_log.SetValidationError, match="RPE must be between 1 and 10 in 0.5 steps"):
        training_log.parse_hands_payload(left_weight=40.0, left_reps=5, left_rpe=7.3)


def test_parse_hands_payload_rejects_empty():
    with pytest.raises(training_log.SetValidationError, match="At least one hand's weight and reps are required"):
        training_log.parse_hands_payload()


def test_commit_focus_set_stages_and_commits_atomically():
    session, user, gid = make_test_db()
    date = date_type(2026, 7, 4)
    payload = {"left": (42.5, 5, 8.0), "right": (40.0, 5, 7.5)}
    ts = training_log.commit_focus_set(session, user, gid, 20, date, 1, None, payload)
    assert ts is not None
    assert ts.session_number == 1
    assert ts.date == date

    worksets = session.exec(
        select(WorkSet).where(WorkSet.training_session_id == ts.id).order_by(WorkSet.hand)
    ).all()
    assert len(worksets) == 2
    assert worksets[0].hand == "left" and worksets[0].weight == 42.5
    assert worksets[1].hand == "right" and worksets[1].weight == 40.0


def test_commit_focus_set_rejects_unknown_grip_type():
    session, user, _ = make_test_db()
    date = date_type(2026, 7, 4)
    with pytest.raises(training_log.UnknownGripTypeError):
        training_log.commit_focus_set(session, user, 999999, 20, date, 1, None, {"left": (42.5, 5, 8.0)})


def test_commit_focus_set_starts_rest_only_on_a_non_final_normal_commit():
    session, user, gid = make_test_db()
    date = date_type(2026, 7, 4)

    ts = training_log.commit_focus_set(session, user, gid, 20, date, 1, None, {"left": (40.0, 5, 7.0)})
    assert ts.rest_ends_at is not None  # set 1 of 3 (protocol default) -- not final

    ts = training_log.commit_focus_set(session, user, gid, 20, date, 1, None, {"left": (41.0, 5, 7.0)}, editing=True)
    assert ts.rest_ends_at is not None  # unchanged by an edit-mode Save

    ts = training_log.commit_focus_set(session, user, gid, 20, date, 2, None, {"left": (40.0, 5, 7.0)})
    ts = training_log.commit_focus_set(session, user, gid, 20, date, 3, None, {"left": (40.0, 5, 7.0)})
    assert ts.rest_ends_at is None  # the final set never starts a rest


def test_restore_focus_set_shifts_higher_sets_and_inserts():
    session, user, gid = make_test_db()
    date = date_type(2026, 7, 4)
    training_log.commit_focus_set(session, user, gid, 20, date, 1, None, {"left": (40.0, 5, 7.0)})
    ts = training_log.commit_focus_set(session, user, gid, 20, date, 2, None, {"left": (45.0, 5, 9.0)})
    training_log.restore_focus_set(session, user, gid, 20, date, 2, None, {"left": (42.5, 5, 8.0)})

    worksets = session.exec(
        select(WorkSet).where(WorkSet.training_session_id == ts.id).order_by(WorkSet.set_number)
    ).all()
    assert len(worksets) == 3
    assert worksets[0].set_number == 1 and worksets[0].weight == 40.0
    assert worksets[1].set_number == 2 and worksets[1].weight == 42.5
    assert worksets[2].set_number == 3 and worksets[2].weight == 45.0


def test_restore_focus_set_rejects_unknown_grip_type():
    session, user, _ = make_test_db()
    date = date_type(2026, 7, 4)
    with pytest.raises(training_log.UnknownGripTypeError):
        training_log.restore_focus_set(session, user, 999999, 20, date, 1, None, {"left": (42.5, 5, 8.0)})


# ============================================================
# Ported from the pre-#146 tests/test_warmup.py and tests/test_worksets.py
# (see the final report for the full per-test disposition list: ported vs.
# dropped-with-reason). All go through /session/play; workset_step() and
# complete_warmup() (tests/helpers.py) stand in for the old direct
# GET /session/warmup / GET /session/worksets calls, advancing through any
# unticked rungs and a pending rest first, since session play (#146) now
# gates the work-set step behind them.
# ============================================================


def rung_weights(page_text):
    """The current rung's weight per hand (one rung shown at a time, #146)."""
    result = {}
    for hnd, weight in re.findall(
        r'rung-tile[^"]*"\s*data-hand="(\w+)">.*?<div class="rung-tile-weight">([\d.]+)',
        page_text,
        re.DOTALL,
    ):
        result[hnd] = float(weight)
    return result


def rung_done(client, grip_id, step_index, hand=None, date="2026-07-04"):
    data = {"grip_type_id": grip_id, "edge_mm": 20, "date": date, "step_index": step_index}
    if hand:
        data["hand"] = hand
    return client.post("/session/rung-done", data=data, follow_redirects=True)


# ---------- warmup ramp values (ported from test_warmup.py) ----------


def test_ramp_values_step_through_each_rung_rounded_down_to_loadable(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    expected = [
        {"left": 21.25, "right": 20.0},
        {"left": 27.5, "right": 26.0},
        {"left": 33.75, "right": 31.75},
        {"left": 38.0, "right": 36.0},
    ]
    for i, exp in enumerate(expected):
        page = play_page(client)
        assert rung_weights(page.text) == exp
        rung_done(client, gid, i)


def clear_inventory(client):
    rows = re.findall(r'class="plate-weight">([^<]+)<', client.get("/settings/plates").text)
    for weight in rows:
        client.post("/plates", data={"weight": weight, "count": "0"})


def test_empty_plate_inventory_suggests_zero_for_every_rung(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    clear_inventory(client)
    for i in range(4):
        page = play_page(client)
        assert set(rung_weights(page.text).values()) == {0.0}
        rung_done(client, gid, i)


def test_sequential_hand_order_shows_one_rung_tile_at_a_time(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    page = play_page(client)
    assert set(rung_weights(page.text)) == {"left"}


def test_checking_a_rung_tick_autosaves_and_advances_once_both_hands_are_done(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    today = date_type.today().isoformat()

    before = play_page(client, date=today)
    assert checked_steps(before.text) == set()

    client.post(
        "/session/check",
        data={"grip_type_id": gid, "edge_mm": 20, "date": today, "hand": "left", "step_index": 0},
        follow_redirects=True,
    )
    after = play_page(client, date=today)
    assert checked_steps(after.text) == {("left", 0)}  # still on rung 0

    client.post(
        "/session/check",
        data={"grip_type_id": gid, "edge_mm": 20, "date": today, "hand": "right", "step_index": 0},
        follow_redirects=True,
    )
    advanced = play_page(client, date=today)
    # Both hands ticked for rung 0 -> derivation moves on to rung 1.
    assert "65%" in advanced.text
    assert checked_steps(advanced.text) == set()  # rung 1's own (unticked) tile


def test_unchecking_a_rung_tick_persists_too(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")

    client.post(
        "/session/check",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "hand": "left", "step_index": 0},
        follow_redirects=True,
    )
    assert checked_steps(play_page(client).text) == {("left", 0)}

    # The same action on a checked step unchecks it (accidental tap).
    client.post(
        "/session/check",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "hand": "left", "step_index": 0},
        follow_redirects=True,
    )
    assert checked_steps(play_page(client).text) == set()


def test_one_untested_hand_still_renders_the_tested_hands_rung(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")

    page = play_page(client)

    assert page.status_code == 200
    grip_id = grip_type_id(client, "half crimp")
    assert (
        f'href="/max-tests/guided?grip_type_id={grip_id}&amp;edge_mm=20'
        f'&amp;date=2026-07-04&amp;hand=right"' in page.text
    )
    assert 'class="estimate-form" data-hand="right"' in page.text
    assert set(rung_weights(page.text)) == {"left"}


def test_started_session_is_listed_in_history(client):
    # The session-start page's "Previous sessions" card went with
    # /session/new (#149); the list itself lives on /history.
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    rung_done(client, gid, 0)  # starts the session

    page = client.get("/progress/timeline").text
    assert 'class="history-session" data-date="2026-07-04"' in page


def test_session_start_form_defaults_to_the_last_used_combination(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "left", "open hand", 10, "2026-07-02", "35")

    page = client.get("/today/change")

    assert page.status_code == 200
    grip_id = grip_type_id(client, "open hand")
    assert f'value="{grip_id}" selected' in page.text
    assert 'name="edge_mm" value="10"' in page.text


# ---------- work-set step rendering (ported from test_worksets.py) ----------


def test_worksets_step_renders_hand_cards_ladder_and_prefills(client):
    setup_tested_user(client)
    page = workset_step(client)
    assert play_step_title(page.text) == "Work set 1 of 3"
    assert page.text.count('class="progress-segment') == 4 + 3  # 4 rungs + 3 sets
    assert 'data-hand="left"' in page.text and 'data-hand="right"' in page.text
    assert 'id="ladder-data"' in page.text
    assert current_set_field(page.text, "left", "weight") == "42.5"
    assert current_set_field(page.text, "right", "weight") == "40.0"
    assert current_set_field(page.text, "left", "reps") == "5"


def test_caption_shows_the_users_own_unit(client):
    register(client, unit_pref="lbs")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "90")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "85")

    page = workset_step(client)
    assert "lbs · plate-loadable" in page.text
    assert "kg · plate-loadable" not in page.text


def test_add_a_set_extends_the_denominator(client):
    setup_tested_user(client)
    page = workset_step(client)
    assert play_step_title(page.text) == "Work set 1 of 3"

    add_link = re.search(r'href="([^"]*sets=4[^"]*)"', page.text).group(1)
    extended = client.get(add_link.replace("&amp;", "&")).text
    assert play_step_title(extended) == "Work set 1 of 4"


def test_sequential_hand_order_shows_one_card_and_commits_one_hand(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    page = workset_step(client)
    assert page.text.count('<div class="hand-card ') == 1
    assert 'data-hand="left"' in page.text
    assert 'data-hand="right"' not in page.text

    response = save_focus_set(client, 1, left=("42.5", "5", "8"))
    assert response.status_code == 200

    page = workset_step(client)
    assert completed_detail(page.text, 1) == "42.5 kg × 5 @ 8.0"

    right = workset_step(client, hand="right")
    assert 'data-hand="right"' in right.text
    assert 'data-hand="left"' not in right.text


def test_worksets_step_defaults_to_three_sets_with_protocol_prefills(client):
    setup_tested_user(client)
    page = workset_step(client)
    assert play_step_title(page.text) == "Work set 1 of 3"
    assert current_set_field(page.text, "left", "weight") == "42.5"
    assert current_set_field(page.text, "left", "reps") == "5"
    assert current_set_field(page.text, "right", "weight") == "40.0"


# ---------- session-level fields: notes/deload/pain (unchanged endpoints) ----------


def summary_step(client, date="2026-07-04"):
    """The summary step's page (#147), where notes/deload/tweaks now live:
    Finish pins a session with logged sets to its summary on resume, so
    this reaches it without committing every planned set first."""
    client.post("/session/finish", data={"date": date})
    return play_page(client, date=date)


def test_session_notes_over_the_length_ceiling_are_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    response = client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "x" * 2001},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422


def test_pain_report_note_over_the_length_ceiling_is_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    response = client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "2", "note": "x" * 2001},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422


def test_pain_report_with_an_invalid_hand_is_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    response = client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left'; DROP TABLE users;--", "severity": "2"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code in (400, 422)


def test_session_notes_and_deload_autosave(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    response = client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "Felt tired today.", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204

    page = summary_step(client)
    assert step_kind(page.text) == "summary"
    assert "Felt tired today." in page.text
    assert re.search(r'name="is_deload"[^>]*checked', page.text)


def test_pain_report_autosaves_and_displays(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    response = client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "2", "note": "Tweaked a pulley"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204

    page = summary_step(client)
    assert "Tweaked a pulley" in page.text
    assert re.search(r'id="tweak-hand-left"[^>]*checked', page.text)
    assert re.search(r'id="tweak-left-severity-2"[^>]*checked', page.text)


def test_pain_report_save_is_an_upsert_keyed_on_hand(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "2"},
        headers={"HX-Request": "true"},
    )
    response = client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "2", "note": "Tweaked a pulley"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204

    page = summary_step(client)
    assert page.text.count("Tweaked a pulley") == 1
    assert re.search(r'id="tweak-left-severity-2"[^>]*checked', page.text)

    client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "right", "severity": "1"},
        headers={"HX-Request": "true"},
    )
    page = summary_step(client)
    assert re.search(r'id="tweak-left-severity-2"[^>]*checked', page.text)
    assert re.search(r'id="tweak-right-severity-1"[^>]*checked', page.text)


def test_pain_reports_and_session_meta_are_isolated_per_user(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "2", "note": "User A pulley tweak"},
        headers={"HX-Request": "true"},
    )
    client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "User A notes", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )

    register_second_user(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "35")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "35")
    save_work_set(client, "left", 1, "35", "5", date="2026-07-04")
    client.post(
        "/session/pain-report",
        data={"date": "2026-07-04", "hand": "left", "severity": "3", "note": "User B own tweak"},
        headers={"HX-Request": "true"},
    )
    client.post(
        "/session/update",
        data={"date": "2026-07-04", "notes": "User B notes"},
        headers={"HX-Request": "true"},
    )
    b_page = summary_step(client).text
    assert "User B own tweak" in b_page
    assert "User A pulley tweak" not in b_page
    assert "User A notes" not in b_page

    from tests.helpers import login

    login(client, "lifter@example.com", "test-pw-1234")
    a_page = summary_step(client).text
    assert "User A pulley tweak" in a_page
    assert "User A notes" in a_page
    assert re.search(r'name="is_deload"[^>]*checked', a_page)
    assert "User B own tweak" not in a_page
    assert "User B notes" not in a_page


def test_pain_report_severity_out_of_bounds_is_rejected(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    for severity in ("0", "4", "-1"):
        response = client.post(
            "/session/pain-report",
            data={"date": "2026-07-04", "hand": "left", "severity": severity},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 422, f"severity {severity} was accepted"


# ---------- notes/deload/tweaks live on the summary step (#147) ----------


def test_summary_holds_notes_deload_and_tweaks_below_the_stats(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")

    page = summary_step(client).text

    stats_idx = page.index('class="summary-stats"')
    assert page.index('id="session-rpe-form"') > stats_idx
    assert page.index('class="summary-tweaks"') > stats_idx
    assert page.index('id="session-update-form"') > stats_idx
    assert 'name="is_deload"' in page
    assert 'name="notes"' in page
    assert 'name="severity"' in page
    assert "How did it feel?" not in page


def test_tweak_hand_uses_a_segmented_none_left_right_group(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "40", "5", date="2026-07-04")
    page = summary_step(client).text
    assert 'select name="hand"' not in page
    for choice in ("none", "left", "right"):
        assert re.search(
            rf'<input type="radio" id="tweak-hand-{choice}" name="tweak_hand" value="{choice}"',
            page,
        )


def test_switch_hand_link_absent_for_alternating_hand_order(client):
    setup_tested_user(client)
    page = workset_step(client)
    assert "Switch to" not in page.text


def test_switch_hand_link_present_for_sequential_hand_order(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    page = workset_step(client)
    assert "Switch to Right hand" in page.text
    assert "hand=right" in page.text


def _finish_three_sets(client, **hands):
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    combo = {"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04"}
    for n in (1, 2):
        save_focus_set(client, n, **hands)
        client.post("/session/rest/end", data=combo, follow_redirects=True)
    return save_focus_set(client, 3, **hands)


def test_sequential_summary_offers_the_other_hand(client):
    """Sequential order runs one hand's whole flow; finishing the left
    hand's sets must lead on to the right hand, not dead-end at summary."""
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    page = _finish_three_sets(client, left=(30, 5, 7))
    assert step_kind(page.text) == "summary"
    assert "Start Right hand" in page.text
    assert "hand=right" in page.text


def test_sequential_summary_on_the_right_hand_offers_left(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20, hand="right")
    combo = {"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "hand": "right"}
    for n in (1, 2, 3):
        save_focus_set(client, n, right=(28, 5, 7))
        client.post("/session/rest/end", data=combo, follow_redirects=True)
    page = play_page(client, hand="right")
    assert step_kind(page.text) == "summary"
    assert "Start Left hand" in page.text


def test_alternating_summary_has_no_other_hand_button(client):
    setup_tested_user(client)
    page = _finish_three_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    assert step_kind(page.text) == "summary"
    assert "Start Right hand" not in page.text
    assert "Start Left hand" not in page.text


def test_no_new_write_route_is_added_beyond_play_and_its_actions(client):
    """Pins the /session/* route surface after #146 -- every write still
    goes through an endpoint that existed before, plus the new play-step
    actions this issue adds (and #148's Rest sound toggle)."""
    from backend.main import create_app

    def all_paths(routes):
        for route in routes:
            path = getattr(route, "path", None)
            if path is not None:
                yield path
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from all_paths(nested.routes)

    app = create_app()
    session_paths = {path for path in all_paths(app.routes) if path.startswith("/session/")}
    assert session_paths == {
        "/session/create",
        "/session/new",
        "/session/play",
        "/session/warmup",
        "/session/worksets",
        "/session/workset",
        "/session/workset/delete",
        "/session/set",
        "/session/set/delete",
        "/session/set/restore",
        "/session/estimate",
        "/session/check",
        "/session/rung-done",
        "/session/rest/extend",
        "/session/rest/end",
        # #148 (native rest bridge): the Rest sound toggle on the rest step.
        "/session/rest/sound",
        "/session/update",
        "/session/pain-report",
        # Summary step (#147).
        "/session/rpe",
        "/session/finish",
    }


# ---------- Edit mode (ported from test_worksets.py issue #80 section) ----------


def test_edit_param_prefills_the_cards_with_that_sets_saved_values(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    workset_step(client)  # skip past rest
    save_focus_set(client, 2, left=("45.0", "5", "9"), right=("41.0", "5", "8"))

    page = workset_step(client, edit=1)

    assert play_step_title(page.text) == "Editing set 1"
    assert current_set_field(page.text, "left", "weight") == "42.5"
    assert current_set_field(page.text, "left", "reps") == "5"
    assert current_set_field(page.text, "left", "rpe") == "8.0"
    assert current_set_field(page.text, "right", "weight") == "40.0"
    assert 'name="set_number" value="1" id="set-number-field"' in page.text
    assert re.search(r'class="set-done-btn">Save</button>', page.text)
    assert re.search(r'set-cancel-btn" href="[^"]*">Cancel</a>', page.text)


def test_saving_an_edited_set_updates_in_place_with_no_duplicate(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    workset_step(client)
    save_focus_set(client, 2, left=("45.0", "5", "9"), right=("41.0", "5", "8"))

    edit_page = workset_step(client, edit=1)
    assert play_step_title(edit_page.text) == "Editing set 1"

    response = save_focus_set(client, 1, left=("40.0", "4", "9"))
    assert response.status_code == 200

    history = client.get("/progress/timeline").text
    assert history.count('data-hand="left" data-set="1"') == 1
    assert history.count('data-hand="right" data-set="1"') == 1
    assert history.count('data-hand="left" data-set="2"') == 1

    detail = completed_detail(workset_step(client).text, 1)
    assert "L 40.0 × 4 @ 9" in detail


def test_saving_an_edited_set_returns_to_the_prior_in_progress_set(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    workset_step(client)
    save_focus_set(client, 2, left=("45.0", "5", "9"), right=("41.0", "5", "8"))
    assert play_step_title(workset_step(client).text) == "Work set 3 of 3"

    workset_step(client, edit=1)
    save_focus_set(client, 1, left=("40.0", "4", "9"))

    assert play_step_title(workset_step(client).text) == "Work set 3 of 3"


def test_cancel_writes_nothing_and_returns_to_the_prior_set(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    workset_step(client)
    save_focus_set(client, 2, left=("45.0", "5", "9"), right=("41.0", "5", "8"))

    edit_page = workset_step(client, edit=1)
    assert play_step_title(edit_page.text) == "Editing set 1"

    # Cancel (no-JS) is just a plain link back -- no write happens.
    normal_page = workset_step(client)
    assert play_step_title(normal_page.text) == "Work set 3 of 3"
    assert "L 42.5 × 5 @ 8" in completed_detail(normal_page.text, 1)


def test_completed_row_href_degrades_to_the_edit_param_no_js(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    workset_step(client)
    save_focus_set(client, 2, left=("45.0", "5", "9"), right=("41.0", "5", "8"))

    page = workset_step(client)
    match = re.search(r'<a class="completed-row[^"]*" data-set="1" href="([^"]*)"', page.text)
    assert match, "no href found on the set-1 completed row"
    href = match.group(1).replace("&amp;", "&")
    assert "edit=1" in href

    followed = client.get(href, follow_redirects=True).text
    assert play_step_title(followed) == "Editing set 1"
    assert current_set_field(followed, "left", "weight") == "42.5"


def test_sequential_hand_order_edit_scopes_to_one_hand(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    save_focus_set(client, 1, left=("42.5", "5", "8"))

    page = workset_step(client, edit=1)

    assert play_step_title(page.text) == "Editing set 1"
    assert page.text.count('<div class="hand-card ') == 1
    assert 'data-hand="left"' in page.text
    assert 'data-hand="right"' not in page.text
    assert current_set_field(page.text, "left", "weight") == "42.5"


def test_editing_a_set_that_was_never_saved_falls_back_to_the_normal_view(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))

    page = workset_step(client, edit=99)
    assert play_step_title(page.text) == "Work set 2 of 3"


def test_edit_mode_still_works_once_every_default_set_is_logged(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    workset_step(client)
    save_focus_set(client, 2, left=("43.0", "5", "8"), right=("40.5", "5", "8"))
    workset_step(client)
    save_focus_set(client, 3, left=("44.0", "5", "8"), right=("41.0", "5", "8"))

    all_done_page = workset_step(client)
    # All 3 default sets logged and the final commit skips rest, so this
    # actually lands on the summary step -- not "focus-all-done" (that
    # fallback only fires when editing an out-of-range set on a page that
    # still has a form). Confirm the summary instead.
    assert step_kind(all_done_page.text) == "summary"

    page = workset_step(client, edit=2)
    assert play_step_title(page.text) == "Editing set 2"
    assert current_set_field(page.text, "left", "weight") == "43.0"

    response = save_focus_set(client, 2, left=("46.0", "4", "9"))
    assert response.status_code == 200
    detail = completed_detail(workset_step(client, edit=2).text, 2)
    assert "L 46.0 × 4 @ 9" in detail


# ---------- RPE stepper defaults and carry-down (ported, issue #114) ----------


def test_rpe_stepper_defaults_to_greyed_7_and_blank_raw_input(client):
    setup_tested_user(client)
    page = workset_step(client)
    assert current_set_field(page.text, "left", "rpe") == ""
    assert current_set_field(page.text, "right", "rpe") == ""
    assert re.search(
        r'<span class="mini-value rpe-inactive" data-role="rpe-display" data-hand="left">\s*7\s*</span>',
        page.text,
    )


def test_rpe_carries_down_from_prior_committed_set(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))

    page = workset_step(client)
    assert play_step_title(page.text) == "Work set 2 of 3"
    assert current_set_field(page.text, "left", "rpe") == "8.0"
    assert current_set_field(page.text, "right", "rpe") == "7.5"


def test_rpe_stays_unset_when_prior_set_had_no_rpe(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", None), right=("40.0", "5", None))

    page = workset_step(client)
    assert play_step_title(page.text) == "Work set 2 of 3"
    assert current_set_field(page.text, "left", "rpe") == ""


# ---------- delete/restore renumbering (ported, issue #115) ----------


def test_delete_set_renumbers_remaining_sets_without_gaps_ported(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("40.0", "5", "7"), right=("38.0", "5", "7"))
    workset_step(client)
    save_focus_set(client, 2, left=("42.5", "5", "8"), right=("40.0", "5", "8"))
    workset_step(client)
    save_focus_set(client, 3, left=("45.0", "5", "9"), right=("42.0", "5", "9"))

    response = delete_focus_set(client, 2)
    assert response.status_code == 200

    page = workset_step(client)
    assert completed_detail(page.text, 1) == "L 40.0 × 5 @ 7.0 · R 38.0 × 5 @ 7.0 kg"
    assert completed_detail(page.text, 2) == "L 45.0 × 5 @ 9.0 · R 42.0 × 5 @ 9.0 kg"
    assert completed_detail(page.text, 3) is None

    history = client.get("/progress/timeline").text
    assert history.count('data-hand="left" data-set="1"') == 1
    assert history.count('data-hand="left" data-set="2"') == 1
    assert history.count('data-hand="left" data-set="3"') == 0


def test_restore_set_inserts_and_shifts_higher_sets_back_up_ported(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("40.0", "5", "7"), right=("38.0", "5", "7"))
    workset_step(client)
    save_focus_set(client, 2, left=("42.5", "5", "8"), right=("40.0", "5", "8"))
    workset_step(client)
    save_focus_set(client, 3, left=("45.0", "5", "9"), right=("42.0", "5", "9"))

    delete_focus_set(client, 2)
    response = restore_focus_set(client, 2, left=("42.5", "5", "8"), right=("40.0", "5", "8"))
    assert response.status_code == 200

    # All 3 default sets are filled again -- the step is now "summary", so
    # view the completed list through edit= (see
    # test_edit_mode_still_works_once_every_default_set_is_logged).
    page = workset_step(client, edit=1)
    assert completed_detail(page.text, 1) == "L 40.0 × 5 @ 7.0 · R 38.0 × 5 @ 7.0 kg"
    assert completed_detail(page.text, 2) == "L 42.5 × 5 @ 8.0 · R 40.0 × 5 @ 8.0 kg"
    assert completed_detail(page.text, 3) == "L 45.0 × 5 @ 9.0 · R 42.0 × 5 @ 9.0 kg"


def test_delete_only_remaining_set_leaves_combo_empty_cleanly(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("40.0", "5", "7"), right=("38.0", "5", "7"))

    response = delete_focus_set(client, 1)
    assert response.status_code == 200

    page = workset_step(client)
    assert completed_detail(page.text, 1) is None
    assert play_step_title(page.text) == "Work set 1 of 3"
    assert current_set_field(page.text, "left", "weight") == "42.5"


def test_sequential_hand_delete_and_restore(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    save_focus_set(client, 1, left=("40.0", "5", "7"))
    workset_step(client)
    save_focus_set(client, 2, left=("42.5", "5", "8"))
    workset_step(client)
    save_focus_set(client, 3, left=("45.0", "5", "9"))

    delete_focus_set(client, 2)

    page = workset_step(client)
    assert completed_detail(page.text, 1) == "40.0 kg × 5 @ 7.0"
    assert completed_detail(page.text, 2) == "45.0 kg × 5 @ 9.0"
    assert completed_detail(page.text, 3) is None

    restore_focus_set(client, 2, left=("42.5", "5", "8"))
    # All 3 default sets are filled again -- step is "summary"; view via edit=.
    restored_page = workset_step(client, edit=1)
    assert completed_detail(restored_page.text, 1) == "40.0 kg × 5 @ 7.0"
    assert completed_detail(restored_page.text, 2) == "42.5 kg × 5 @ 8.0"
    assert completed_detail(restored_page.text, 3) == "45.0 kg × 5 @ 9.0"


# ---------- current_max / /session/workset legacy endpoint (ported) ----------


def test_current_max_rises_with_a_heavier_work_set_since_the_last_test(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "45", "3", date="2026-07-04")

    combo = ("left", "half crimp", 20)
    assert current_maxes(client)[combo] == 45.0
    assert current_maxes(client)[("right", "half crimp", 20)] == 40.0

    log_max_test(client, "left", "half crimp", 20, "2026-07-05", "41")
    assert current_maxes(client)[combo] == 41.0


def test_session_start_defaults_prefer_the_last_trained_combination(client):
    setup_tested_user(client)
    log_max_test(client, "left", "open hand", 10, "2026-07-02", "35")
    save_work_set(client, "left", 1, "42.5", "5", date="2026-07-03")

    page = client.get("/today/change")
    grip_id = grip_type_id(client, "half crimp")
    assert f'value="{grip_id}" selected' in page.text
    assert 'name="edge_mm" value="20"' in page.text


def test_per_hand_workset_endpoint_still_upserts_in_place(client):
    setup_tested_user(client)
    save_work_set(client, "left", 1, "42.5", "5", rpe="8.5")

    page = workset_step(client)
    assert current_set_field(page.text, "left", "weight") == "42.5"
    assert current_set_field(page.text, "left", "reps") == "5"
    assert current_set_field(page.text, "left", "rpe") == "8.5"

    save_work_set(client, "left", 1, "40.0", "4", rpe="9.0")
    page = workset_step(client)
    assert current_set_field(page.text, "left", "weight") == "40.0"


def test_unknown_grip_type_is_rejected_and_writes_nothing_on_workset(client):
    setup_tested_user(client)
    response = client.post(
        "/session/workset",
        data={
            "grip_type_id": 999999, "edge_mm": 20, "date": "2026-07-04",
            "hand": "left", "set_number": 1, "weight": "42.5", "reps": 5,
        },
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert completed_detail(workset_step(client).text, 1) is None


def test_an_accidentally_added_set_can_be_deleted_via_legacy_endpoint(client):
    setup_tested_user(client)
    save_work_set(client, "left", 3, "42.5", "5")
    save_work_set(client, "left", 4, "30", "2")

    response = client.post(
        "/session/workset/delete",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"), "edge_mm": 20,
            "date": "2026-07-04", "hand": "left", "set_number": 4,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    history = client.get("/progress/timeline").text
    assert 'data-set="3"' in history
    assert 'data-set="4"' not in history


# ---------- undo after delete (review item 2) ----------


def test_undo_after_delete_restores_the_set_via_303_no_js(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=("40.0", "5", "7"), right=("38.0", "5", "7"))

    response = delete_focus_set(client, 1)
    assert response.status_code == 200
    assert "undo-banner" in response.text
    assert 'action="/session/set/restore"' in response.text
    assert 'name="left_weight" value="40.0"' in response.text
    assert 'name="right_weight" value="38.0"' in response.text

    # Following the undo form's own values restores the set.
    restored = restore_focus_set(client, 1, left=("40.0", "5", "7.0"), right=("38.0", "5", "7.0"))
    assert restored.status_code == 200
    detail = completed_detail(workset_step(client).text, 1)
    assert "L 40.0 × 5 @ 7" in detail


def test_undo_banner_appears_on_the_htmx_fragment_too(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=("40.0", "5", "7"), right=("38.0", "5", "7"))

    response = client.post(
        "/session/set/delete",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "set_number": 1},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "<html" not in response.text
    assert "undo-banner" in response.text


def test_undo_banner_does_not_appear_on_a_later_unrelated_visit(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=("40.0", "5", "7"), right=("38.0", "5", "7"))
    delete_focus_set(client, 1)

    # A plain revisit with no undo_* query params never shows the banner --
    # it's a one-shot affordance carried in that one redirect only.
    page = workset_step(client)
    assert "undo-banner" not in page.text


# ---------- plate breakdown (review item 3) ----------


def test_plate_breakdown_renders_on_the_warmup_rung(client):
    setup_tested_user(client)
    page = play_page(client)
    assert "Pin + 20 + 1.25" in page.text  # 21.25 kg, left hand's first rung


def test_plate_breakdown_renders_on_the_work_set_card(client):
    setup_tested_user(client)
    page = workset_step(client)
    assert 'data-role="plate-breakdown" data-hand="left"' in page.text
    assert "Pin + 20 + 10 + 10" in page.text  # 40.0 kg default seed, kg starter inventory


def test_plate_breakdown_shows_nothing_for_an_off_ladder_weight(client):
    setup_tested_user(client)
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    save_focus_set(client, 1, left=("42.55", "5", None))  # off-ladder value
    page = workset_step(client, edit=1)
    left_card = page.text[page.text.index('data-hand="left"'):]
    left_card = left_card[: left_card.index("reps-rpe-grid")]
    assert "plate-breakdown" not in left_card


# ---------- a few more direct ports (batch 2) ----------


def test_rpe_blank_persists_as_null(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", None), right=("40.0", "5", None))
    detail = completed_detail(workset_step(client).text, 1)
    assert "@" not in detail


def test_reposting_the_same_session_hand_set_updates_in_place(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"))
    save_focus_set(client, 1, left=("40.0", "4", "9"))

    page = workset_step(client)
    assert current_set_field(page.text, "left", "weight") == "40.0"
    assert current_set_field(page.text, "left", "reps") == "4"
    assert current_set_field(page.text, "left", "rpe") == "9.0"

    history = client.get("/progress/timeline").text
    assert history.count('data-set="1"') == 1


def test_user_b_cannot_write_into_user_as_session_via_set_commit(client):
    setup_tested_user(client)
    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7"))

    register_second_user(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "30")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "30")
    save_focus_set(client, 1, left=("30.0", "5", "6"))

    from tests.helpers import login

    login(client, "lifter@example.com", "test-pw-1234")
    detail = completed_detail(workset_step(client).text, 1)
    assert "L 42.5" in detail
    assert "L 30.0" not in detail


def test_rest_countdown_renders_configured_default_rest_seconds_on_workset(client):
    register(client, "timeruser@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    client.post(
        "/profile/protocol",
        data={"base_work_set_reps": "5", "default_rest_seconds": "150"},
        follow_redirects=True,
    )

    page = workset_step(client)
    assert 'data-rest-seconds="150"' in page.text


def test_up_next_row_renders_singular_and_range_labels(client):
    setup_tested_user(client)
    page = workset_step(client, date="2026-07-04")
    assert "Sets 2–3 up next · same load carries down" in page.text

    save_focus_set(client, 1, left=("42.5", "5", "8"), right=("40.0", "5", "7.5"))
    page = workset_step(client, date="2026-07-04")
    assert "Set 3 up next · same load carries down" in page.text
    assert "Sets 3–3" not in page.text
