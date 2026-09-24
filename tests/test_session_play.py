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
    complete_warmup,
    delete_focus_set,
    get_session_page,
    grip_type_id,
    log_max_test,
    register,
    register_second_user,
    restore_focus_set,
    save_focus_set,
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
    assert "All sets done" in response.text
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
