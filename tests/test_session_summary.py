"""HTTP-seam tests for the session play Summary step (#147, docs/adr/0014):
Session RPE chips, tweaks (pain reports), notes/deload moved here from the
old "How did it feel?" card, Finish (stamps finished_at once), resume after
Finish, the export/import round trip of the two new columns, and the
derived session_load helper."""

import csv
import io
import re
import zipfile
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

import pytest

from backend import analytics
from backend.models import TrainingSession
from backend.templating import human_date
from tests.helpers import (
    complete_warmup,
    export_archive,
    generate_invite,
    grip_type_id,
    import_archive,
    log_max_test,
    login,
    register,
    register_second_user,
    save_focus_set,
    workset_step,
)

DATE = "2026-07-04"


def setup_tested_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")


def combo(client, hand=None):
    data = {"grip_type_id": grip_type_id(client, "half crimp"), "edge_mm": 20, "date": DATE}
    if hand:
        data["hand"] = hand
    return data


def finish_sets(client, hand=None, count=3, **hands):
    """Warm up, then commit `count` sets (skipping rest in between) --
    the default protocol's 3 sets land on the summary step."""
    params = combo(client, hand)
    complete_warmup(client, params["grip_type_id"], 20, date=DATE, hand=hand)
    response = None
    for n in range(1, count + 1):
        response = save_focus_set(client, n, date=DATE, **hands)
        client.post("/session/rest/end", data=params, follow_redirects=True)
    return response


def play(client, hand=None, **extra):
    return client.get("/session/play", params={**combo(client, hand), **extra})


def step_kind(text):
    m = re.search(r'id="play-step" data-step="(\w+)"', text)
    return m.group(1) if m else None


def export_sessions(client) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        text = z.read("TrainingSession.csv").decode()
    return list(csv.DictReader(io.StringIO(text)))


def selected_rpe(text):
    m = re.search(r'class="[^"]*rpe-chip[^"]*\bon\b[^"]*"[^>]*value="(\d+)"', text)
    return m.group(1) if m else None


# ---------- rendering ----------


def test_summary_shows_headline_date_combo_and_stat_tiles(client):
    setup_tested_user(client)
    page = finish_sets(client, left=(30, 5, 7), right=(28, 5, 8))

    assert step_kind(page.text) == "summary"
    assert "Session done" in page.text
    assert human_date(date_type(2026, 7, 4)) in page.text
    assert "Half crimp" in page.text
    # TrainingVolume: 3 × (30×5 + 28×5) = 870
    assert re.search(r'data-stat="volume"[^>]*>\s*870\b', page.text)
    assert re.search(r'data-stat="sets-per-hand"[^>]*>\s*3\b', page.text)
    assert re.search(r'data-stat="avg-rpe"[^>]*>\s*7\.5\b', page.text)
    assert "min" in page.text  # the duration-so-far readout


def test_summary_average_rpe_is_a_dash_when_no_set_had_an_rpe(client):
    setup_tested_user(client)
    page = finish_sets(client, left=(30, 5, None), right=(28, 5, None))
    assert re.search(r'data-stat="avg-rpe"[^>]*>\s*–', page.text)


def test_summary_offers_five_session_rpe_chips_and_tweak_chips(client):
    setup_tested_user(client)
    page = finish_sets(client, left=(30, 5, 7), right=(28, 5, 7)).text

    for value, label in ((3, "Easy"), (5, "Moderate"), (7, "Hard"), (9, "Very hard"), (10, "Max")):
        assert re.search(rf'name="session_rpe" value="{value}"', page)
        assert label in page
    assert selected_rpe(page) is None
    for choice in ("none", "left", "right"):
        assert f'value="{choice}"' in page
    assert 'name="notes"' in page
    assert 'name="is_deload"' in page
    assert "Finish" in page


def test_how_it_felt_card_is_gone_from_the_work_set_step(client):
    setup_tested_user(client)
    save_focus_set(client, 1, date=DATE, left=(30, 5, 7), right=(28, 5, 7))
    page = workset_step(client, date=DATE).text
    assert 'id="how-it-felt"' not in page
    assert "How did it feel?" not in page
    assert 'name="notes"' not in page


# ---------- Session RPE chips ----------


def test_session_rpe_chip_without_js_saves_and_redirects_back_to_play(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))

    response = client.post(
        "/session/rpe", data={**combo(client), "session_rpe": "7"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/session/play?")

    page = play(client).text
    assert step_kind(page) == "summary"
    assert selected_rpe(page) == "7"
    assert export_sessions(client)[0]["session_rpe"] == "7"


def test_session_rpe_chip_with_htmx_answers_the_summary_fragment(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))

    response = client.post(
        "/session/rpe",
        data={**combo(client), "session_rpe": "9"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert step_kind(response.text) == "summary"
    assert selected_rpe(response.text) == "9"
    assert "<html" not in response.text


def test_session_rpe_can_be_changed_by_tapping_another_chip(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/rpe", data={**combo(client), "session_rpe": "3"})
    client.post("/session/rpe", data={**combo(client), "session_rpe": "10"})
    assert export_sessions(client)[0]["session_rpe"] == "10"


@pytest.mark.parametrize("bad", ["0", "11", "-3", "abc", "7.5", ""])
def test_session_rpe_out_of_range_or_non_numeric_is_rejected(client, bad):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    response = client.post(
        "/session/rpe", data={**combo(client), "session_rpe": bad}, follow_redirects=False
    )
    assert response.status_code == 422
    assert export_sessions(client)[0]["session_rpe"] == ""


# ---------- Finish ----------


def test_finish_stamps_finished_at_and_redirects_home(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    assert export_sessions(client)[0]["finished_at"] == ""

    response = client.post("/session/finish", data=combo(client), follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert export_sessions(client)[0]["finished_at"] != ""


def test_finish_is_idempotent(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/finish", data=combo(client))
    first = export_sessions(client)[0]["finished_at"]

    again = client.post("/session/finish", data=combo(client), follow_redirects=False)
    assert again.status_code == 303
    assert export_sessions(client)[0]["finished_at"] == first


def test_finish_with_htmx_redirects_via_hx_redirect(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    response = client.post(
        "/session/finish", data=combo(client), headers={"HX-Request": "true"}
    )
    assert response.headers.get("HX-Redirect") == "/"


def test_after_finish_play_resumes_on_the_editable_summary(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/finish", data=combo(client))

    page = play(client).text
    assert step_kind(page) == "summary"
    assert "Session done" in page

    client.post("/session/rpe", data={**combo(client), "session_rpe": "5"})
    assert selected_rpe(play(client).text) == "5"


def test_after_finish_a_deleted_set_still_resumes_on_the_summary(client):
    """finished_at wins over the planned-set count: a set removed after
    Finish must not drag the session back to the work-set step."""
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/finish", data=combo(client))
    client.post("/session/set/delete", data={**combo(client), "set_number": 3})

    assert step_kind(play(client).text) == "summary"


def test_after_finish_adding_a_set_from_the_menu_shows_the_work_set_step(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/finish", data=combo(client))

    page = play(client, sets=4).text
    assert step_kind(page) == "workset"
    assert "Work set 4 of 4" in page


def test_finish_is_the_primary_action_when_no_other_hand_is_left(client):
    setup_tested_user(client)
    page = finish_sets(client, left=(30, 5, 7), right=(28, 5, 7)).text
    assert re.search(r'class="[^"]*summary-finish-btn[^"]*btn-primary', page) or re.search(
        r'class="btn summary-finish-btn"', page
    )
    assert "Start Right hand" not in page and "Start Left hand" not in page


def test_sequential_summary_keeps_the_other_hand_primary_and_finish_secondary(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    page = finish_sets(client, left=(30, 5, 7)).text
    assert step_kind(page) == "summary"
    assert "Start Right hand" in page
    assert re.search(r'class="btn btn-secondary summary-finish-btn"', page)


def test_sequential_finish_then_other_hand_still_starts_that_hand(client):
    setup_tested_user(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})
    finish_sets(client, left=(30, 5, 7))
    client.post("/session/finish", data=combo(client, "left"))

    page = play(client, hand="right").text
    assert step_kind(page) in ("warmup", "workset")


# ---------- tweaks (pain reports) ----------


def test_tweak_saves_through_pain_report_and_redirects_back_to_play_no_js(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    c = combo(client)

    response = client.post(
        "/session/pain-report",
        data={
            "grip_type_id": c["grip_type_id"], "edge_mm": 20, "date": DATE,
            "hand": "left", "severity": "2", "note": "pulley twinge",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/session/play?")

    page = play(client).text
    assert "pulley twinge" in page
    assert re.search(r'id="tweak-hand-left"[^>]*checked', page)
    assert re.search(r'id="tweak-left-severity-2"[^>]*checked', page)


def test_tweak_is_at_most_one_report_per_hand(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    c = combo(client)
    for severity, note in (("1", "first"), ("3", "second")):
        client.post(
            "/session/pain-report",
            data={"grip_type_id": c["grip_type_id"], "edge_mm": 20, "date": DATE,
                  "hand": "right", "severity": severity, "note": note},
            headers={"HX-Request": "true"},
        )
    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        rows = list(csv.DictReader(io.StringIO(z.read("PainReport.csv").decode())))
    assert len(rows) == 1
    assert rows[0]["severity"] == "3" and rows[0]["note"] == "second"

    page = play(client).text
    assert re.search(r'id="tweak-hand-right"[^>]*checked', page)
    assert re.search(r'id="tweak-right-severity-3"[^>]*checked', page)


def test_no_tweaks_leaves_none_selected(client):
    setup_tested_user(client)
    page = finish_sets(client, left=(30, 5, 7), right=(28, 5, 7)).text
    assert re.search(r'id="tweak-hand-none"[^>]*checked', page)


# ---------- notes + deload on the summary ----------


def test_notes_and_deload_autosave_and_render_on_the_summary(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    response = client.post(
        "/session/update",
        data={"date": DATE, "notes": "Felt tired today.", "is_deload": "on"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204

    page = play(client).text
    assert "Felt tired today." in page
    assert re.search(r'name="is_deload"[^>]*checked', page)


def test_notes_without_js_redirect_back_to_play_when_the_combo_is_posted(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    response = client.post(
        "/session/update",
        data={**combo(client), "notes": "no-js notes"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/session/play?")
    assert "no-js notes" in play(client).text


# ---------- per-user isolation ----------


def test_user_b_cannot_set_user_as_session_rpe_or_finish_it(client):
    setup_tested_user(client)
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    c = combo(client)

    register_second_user(client)
    rpe = client.post("/session/rpe", data={**c, "session_rpe": "10"}, follow_redirects=False)
    assert rpe.status_code == 303
    fin = client.post("/session/finish", data=c, follow_redirects=False)
    assert fin.status_code == 303
    # User B never gets a session of their own out of it either.
    assert export_sessions(client) == []

    login(client, "lifter@example.com", "test-pw-1234")
    row = export_sessions(client)[0]
    assert row["session_rpe"] == ""
    assert row["finished_at"] == ""


# ---------- export / import ----------


def test_export_import_round_trips_session_rpe_and_finished_at(client):
    register(client, "founder@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    finish_sets(client, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/rpe", data={**combo(client), "session_rpe": "9"})
    client.post("/session/finish", data=combo(client))
    original = export_sessions(client)[0]
    assert original["session_rpe"] == "9" and original["finished_at"]

    archive = export_archive(client)
    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    assert import_archive(client, archive).status_code == 303

    restored = export_sessions(client)[0]
    assert restored["session_rpe"] == "9"
    assert restored["finished_at"] == original["finished_at"]


def _strip_columns(csv_text: str, columns: set[str]) -> str:
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    reader = csv.reader(io.StringIO(csv_text))
    header = [h for h in next(reader) if h not in columns]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue()


@pytest.mark.parametrize(
    "dropped",
    [
        {"session_rpe", "finished_at"},
        # A pre-#146 archive also predates rest_ends_at.
        {"session_rpe", "finished_at", "rest_ends_at"},
        # A pre-PR-#154-review archive has no play state columns (D2).
        {"planned_sets", "play_grip_type_id", "play_edge_mm"},
    ],
)
def test_an_older_archive_without_the_new_columns_still_imports(client, dropped):
    register(client, "founder@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    save_focus_set(client, 1, date=DATE, left=(30, 5, 7), right=(28, 5, 7))
    client.post("/session/update", data={"date": DATE, "notes": "old notes"})

    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["TrainingSession.csv"] = _strip_columns(
        members["TrainingSession.csv"].decode(), dropped
    ).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    response = import_archive(client, out.getvalue())
    assert response.status_code == 303

    restored = export_sessions(client)
    assert len(restored) == 1
    assert restored[0]["notes"] == "old notes"
    if "session_rpe" in dropped:
        assert restored[0]["session_rpe"] == ""
        assert restored[0]["finished_at"] == ""
    assert restored[0]["planned_sets"] == ""


def _archive_with_session_cell(client, column: str, value: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        members = {n: z.read(n) for n in z.namelist()}
    rows = list(csv.DictReader(io.StringIO(members["TrainingSession.csv"].decode())))
    rows[0][column] = value
    out_csv = io.StringIO()
    writer = csv.DictWriter(out_csv, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    members["TrainingSession.csv"] = out_csv.getvalue().encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize("bad_rpe", ["0", "11", "99", "-3"])
def test_import_rejects_a_session_rpe_outside_1_to_10(client, bad_rpe):
    register(client, "founder@example.com", "test-pw-1234")
    save_focus_set(client, 1, date=DATE, left=(30, 5, 7), right=(28, 5, 7))
    archive = _archive_with_session_cell(client, "session_rpe", bad_rpe)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    response = import_archive(client, archive)

    assert response.status_code == 400
    assert "session_rpe" in response.text
    assert export_sessions(client) == []


@pytest.mark.usefixtures("session_date_is_today")
def test_import_does_not_restore_a_pending_rest(client):
    """rest_ends_at is transient play state: a restored session must never
    reopen on a stale rest step (PR #154 review)."""
    register(client, "founder@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    save_focus_set(client, 1, date=DATE, left=(30, 5, 7), right=(28, 5, 7))
    assert export_sessions(client)[0]["rest_ends_at"] != ""
    archive = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    assert import_archive(client, archive).status_code == 303

    assert export_sessions(client)[0]["rest_ends_at"] == ""
    assert step_kind(play(client).text) != "rest"


def test_an_archive_with_an_unknown_extra_column_is_still_rejected(client):
    register(client, "founder@example.com", "test-pw-1234")
    save_focus_set(client, 1, date=DATE, left=(30, 5, 7), right=(28, 5, 7))
    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        members = {n: z.read(n) for n in z.namelist()}
    text = members["TrainingSession.csv"].decode()
    lines = text.splitlines()
    lines[0] += ",bogus"
    lines[1:] = [line + ",x" for line in lines[1:]]
    members["TrainingSession.csv"] = ("\n".join(lines) + "\n").encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    assert import_archive(client, out.getvalue()).status_code == 400


# ---------- session_load (derived, analytics) ----------

UTC = timezone.utc
START = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)


def _ts(rpe=None, started=START, finished=None):
    return TrainingSession(
        user_id=1, date=date_type(2026, 7, 4), session_rpe=rpe,
        started_at=started, finished_at=finished,
    )


def test_session_load_is_rpe_times_duration_minutes():
    ts = _ts(rpe=7, finished=START + timedelta(minutes=30))
    assert analytics.session_load(ts) == pytest.approx(210.0)


def test_session_load_counts_partial_minutes():
    ts = _ts(rpe=5, finished=START + timedelta(minutes=10, seconds=30))
    assert analytics.session_load(ts) == pytest.approx(52.5)


def test_session_load_is_none_without_finished_at():
    assert analytics.session_load(_ts(rpe=7, finished=None)) is None


def test_session_load_is_none_without_started_at():
    ts = _ts(rpe=7, started=None, finished=START + timedelta(minutes=30))
    assert analytics.session_load(ts) is None


def test_session_load_is_none_without_session_rpe():
    assert analytics.session_load(_ts(rpe=None, finished=START + timedelta(minutes=30))) is None


def test_session_load_is_zero_for_a_zero_duration():
    assert analytics.session_load(_ts(rpe=9, finished=START)) == 0.0


def test_session_load_never_goes_negative_on_clock_skew():
    assert analytics.session_load(_ts(rpe=9, finished=START - timedelta(minutes=5))) == 0.0


def test_session_load_mixes_naive_and_aware_datetimes_as_utc():
    """SQLite drops tzinfo on the round trip, so one side can come back
    naive while the other is still aware -- both are UTC."""
    naive_start = START.replace(tzinfo=None)
    ts = _ts(rpe=4, started=naive_start, finished=START + timedelta(minutes=20))
    assert analytics.session_load(ts) == pytest.approx(80.0)
    ts2 = _ts(rpe=4, started=START, finished=(START + timedelta(minutes=20)).replace(tzinfo=None))
    assert analytics.session_load(ts2) == pytest.approx(80.0)

