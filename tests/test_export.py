"""CSV export: the session-data half (join-scoped via TrainingSession)
and the export endpoint's auth gate. The directly-user-scoped files
(BodyWeightLog/Climb/MaxWeightTest) are covered in test_profile.py."""

import io
import zipfile

from tests.helpers import (
    grip_type_id,
    log_climb,
    log_max_test,
    register,
    register_second_user,
    save_work_set,
)


def _export_zip(client):
    response = client.get("/profile/export")
    assert response.status_code == 200
    return zipfile.ZipFile(io.BytesIO(response.content))


def _rows(z, name):
    return z.read(name).decode().splitlines()


def _train_full_session(client, date, workset_weight, pain_note, estimate_weight):
    """One session with every kind of session-scoped row the export dumps."""
    save_work_set(client, "left", 1, workset_weight, "5", date=date)
    client.post(
        "/session/check",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": 20,
            "date": date,
            "hand": "left",
            "step_index": 0,
        },
        headers={"HX-Request": "true"},
    )
    client.post(
        "/session/pain-report",
        data={"date": date, "hand": "left", "severity": "2", "note": pain_note},
        headers={"HX-Request": "true"},
    )
    # Estimate goes to a combo the user has never tested.
    client.post(
        "/session/estimate",
        data={
            "grip_type_id": grip_type_id(client, "open hand"),
            "edge_mm": 20,
            "date": date,
            "hand": "right",
            "weight": estimate_weight,
        },
        headers={"HX-Request": "true"},
    )


def test_export_includes_session_data_scoped_to_the_exporting_user(client):
    # User A trains on the same date with distinctive values...
    register(client, "founder@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "50")
    _train_full_session(client, "2026-07-04", "33", "A tweaked pulley", "61")

    # ...so that any cross-user leak in the join-scoped queries would
    # surface as extra rows or A's values in B's export.
    register_second_user(client, "friend@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    _train_full_session(client, "2026-07-04", "44", "B sore finger", "62")

    with _export_zip(client) as z:
        names = z.namelist()
        for expected in (
            "TrainingSession.csv",
            "WorkSet.csv",
            "PainReport.csv",
            "WarmupStepCheck.csv",
            "SessionMaxEstimate.csv",
        ):
            assert expected in names

        sessions = _rows(z, "TrainingSession.csv")
        assert len(sessions) == 2  # header + B's single session

        worksets = _rows(z, "WorkSet.csv")
        assert len(worksets) == 2
        assert "44" in worksets[1] and "33" not in worksets[1]

        pain = _rows(z, "PainReport.csv")
        assert len(pain) == 2
        assert "B sore finger" in pain[1]
        assert "A tweaked pulley" not in pain[1]

        checks = _rows(z, "WarmupStepCheck.csv")
        assert len(checks) == 2

        estimates = _rows(z, "SessionMaxEstimate.csv")
        assert len(estimates) == 2
        assert "62" in estimates[1] and "61" not in estimates[1]


def test_export_requires_authentication(client):
    response = client.get("/profile/export", follow_redirects=False)
    assert response.status_code == 401


def test_export_with_no_sessions_omits_session_files_but_writes_empty_user_files(client):
    """Pin the current absent-vs-empty split: a user with no training
    sessions gets no session-scoped files at all, while the directly
    user-scoped files are written even when empty."""
    register(client)

    with _export_zip(client) as z:
        names = z.namelist()
        assert "TrainingSession.csv" not in names
        assert "WorkSet.csv" not in names
        assert "MaxWeightTest.csv" in names
        assert len(_rows(z, "MaxWeightTest.csv")) == 1  # header only


def test_export_neutralizes_spreadsheet_formula_cells(client):
    """A text cell starting with = + - or @ executes as a formula when the
    CSV is opened in Excel/LibreOffice. The export prefixes such cells
    with a quote so a shared export can't carry a payload."""
    register(client)
    log_climb(client, "2026-07-04", "V3", notes="=HYPERLINK(\"http://evil\")")

    with _export_zip(client) as z:
        climbs = z.read("Climb.csv").decode()
        assert "'=HYPERLINK" in climbs
        assert ",=HYPERLINK" not in climbs
