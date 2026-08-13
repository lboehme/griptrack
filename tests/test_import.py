"""HTTP-seam tests for POST /profile/import (issue #102, ADR-0008): restoring
an Export archive into an empty account. Covers the round trip, the
non-empty refusal, manifest validation, grip-by-name resolution, and
atomicity -- untrusted-file-ingress bounds and cross-user isolation live in
tests/test_security.py alongside the app's other security cases."""

import io
import json
import zipfile

from tests.helpers import (
    current_maxes,
    export_archive,
    generate_invite,
    import_archive,
    log_bodyweight,
    log_climb,
    log_max_test,
    register,
    save_work_set,
)


def _zip_members(archive_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
        return {name: z.read(name) for name in z.namelist()}


def _rebuild_zip(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


def _replace_member(archive_bytes: bytes, filename: str, new_text: str) -> bytes:
    members = _zip_members(archive_bytes)
    members[filename] = new_text.encode("utf-8")
    return _rebuild_zip(members)


def _drop_member(archive_bytes: bytes, filename: str) -> bytes:
    members = _zip_members(archive_bytes)
    del members[filename]
    return _rebuild_zip(members)


def _replace_column(csv_text: str, row_index: int, column: str, new_value: str) -> str:
    """Overwrite one cell of `csv_text` (row_index is 0-based over the data
    rows, i.e. excluding the header). Safe here because none of this test
    file's mutated cells contain a comma."""
    lines = csv_text.splitlines()
    header = lines[0].split(",")
    col_idx = header.index(column)
    fields = lines[1 + row_index].split(",")
    fields[col_idx] = new_value
    lines[1 + row_index] = ",".join(fields)
    return "\n".join(lines) + "\n"


def test_round_trip_restores_a_populated_account_into_a_fresh_one(client):
    register(client, "founder@example.com", "test-pw-1234", unit_pref="kg")
    log_bodyweight(client, "2026-07-01", "71.4")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "38")
    log_climb(client, "2026-07-04", "V5", style="flash", notes="great send")
    client.post("/plates", data={"weight": "2.5", "count": "4"}, follow_redirects=True)

    save_work_set(client, "left", 1, "40", "5", date="2026-07-05")
    save_work_set(client, "right", 1, "38", "5", date="2026-07-05")
    client.post(
        "/session/pain-report",
        data={"date": "2026-07-05", "hand": "left", "severity": "2", "note": "twinge"},
        follow_redirects=True,
    )
    client.post(
        "/session/update",
        data={"date": "2026-07-05", "notes": "felt strong", "is_deload": "on"},
        follow_redirects=True,
    )

    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 303

    # Bodyweight, max tests, and climbs all reattached to the new account.
    profile = client.get("/profile").text
    assert "71.4" in profile

    assert current_maxes(client) == {
        ("left", "half crimp", 20): 40.0,
        ("right", "half crimp", 20): 38.0,
    }

    climbs_page = client.get("/climbs").text
    assert "great send" in climbs_page

    new_export = _zip_members(export_archive(client))

    # Plates: the founder's edit (2.5 -> count 4) round-trips, replacing
    # the new account's own seeded default rather than duplicating it.
    plate_lines = new_export["PlateInventoryItem.csv"].decode().splitlines()
    assert len(plate_lines) == 1 + 6
    assert any(",2.5," in line and line.endswith(",4") for line in plate_lines[1:])

    # Session-level data: one TrainingSession, two WorkSets, one PainReport,
    # notes + deload carried over.
    assert len(new_export["TrainingSession.csv"].decode().splitlines()) == 1 + 1
    assert len(new_export["WorkSet.csv"].decode().splitlines()) == 1 + 2
    assert len(new_export["PainReport.csv"].decode().splitlines()) == 1 + 1
    assert "twinge" in new_export["PainReport.csv"].decode()
    assert "felt strong" in new_export["TrainingSession.csv"].decode()
    assert "True" in new_export["TrainingSession.csv"].decode()  # is_deload

    assert len(new_export["BodyWeightLog.csv"].decode().splitlines()) == 1 + 1
    assert len(new_export["MaxWeightTest.csv"].decode().splitlines()) == 1 + 2
    assert len(new_export["Climb.csv"].decode().splitlines()) == 1 + 1


def test_import_adopts_unit_preference_from_the_manifest(client):
    register(client, "founder@example.com", "test-pw-1234", unit_pref="lbs")
    log_bodyweight(client, "2026-07-01", "160")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code, unit_pref="kg")

    response = import_archive(client, archive_bytes)
    assert response.status_code == 303

    profile = client.get("/profile").text
    assert '<span class="unit-pref">lbs</span>' in profile


def test_import_reverses_the_export_side_formula_neutralization(client):
    """The exporter (S6) prefixes a cell starting with = + - or @ with a
    quote so it can't execute as a spreadsheet formula (see
    test_csv_export_neutralizes_spreadsheet_formula_cells in
    tests/test_profile.py). A round trip must strip that quote back off on
    import rather than storing it verbatim (ADR-0008)."""
    register(client, "founder@example.com", "test-pw-1234")
    log_climb(client, "2026-07-04", "V3", notes='=HYPERLINK("http://evil")')
    archive_bytes = export_archive(client)

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
        climbs_csv = z.read("Climb.csv").decode()
    assert "'=HYPERLINK" in climbs_csv  # exporter neutralized it (sanity check)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 303

    # Jinja2 autoescapes the stored note when the climb list renders it, so
    # a still-present leading quote (unreversed neutralization) and a
    # correctly-reversed one are distinguishable here: `'` escapes to
    # `&#39;` only if it's really part of the stored value.
    climbs_page = client.get("/climbs").text
    assert "&#39;=HYPERLINK" not in climbs_page
    assert "=HYPERLINK(&#34;http://evil&#34;)" in climbs_page


def test_import_refuses_a_non_empty_account_and_writes_nothing(client):
    register(client, "founder@example.com", "test-pw-1234")
    log_bodyweight(client, "2026-07-01", "71.4")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)
    log_bodyweight(client, "2026-07-02", "80.0")

    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "empty" in response.text.lower() or "already has data" in response.text.lower()

    # Untouched: still just the one bodyweight entry the new user logged.
    bw_lines = _zip_members(export_archive(client))["BodyWeightLog.csv"].decode().splitlines()
    assert len(bw_lines) == 1 + 1
    assert "80.0" in bw_lines[1]


def test_import_seeded_default_plates_do_not_count_as_existing_data(client):
    """A freshly registered account already has seeded default plates
    (ADR-0002/0008) -- that alone must not trip the non-empty refusal."""
    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 303


def test_import_rejects_an_unrecognized_format_version(client):
    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)
    manifest = json.loads(_zip_members(archive_bytes)["manifest.json"].decode())
    manifest["format_version"] = 999
    archive_bytes = _replace_member(archive_bytes, "manifest.json", json.dumps(manifest))

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "unsupported" in response.text.lower() or "format" in response.text.lower()


def test_import_rejects_an_archive_missing_a_required_member(client):
    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)
    archive_bytes = _drop_member(archive_bytes, "SessionMaxEstimate.csv")

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "SessionMaxEstimate" in response.text


def test_import_requires_explicit_confirmation(client):
    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes, confirm=False)
    assert response.status_code == 400

    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        assert len(z.read("BodyWeightLog.csv").decode().splitlines()) == 1


def test_import_resolves_grips_by_name_and_fails_loud_on_an_unknown_one(client):
    register(client, "founder@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    archive_bytes = export_archive(client)

    members = _zip_members(archive_bytes)
    grip_csv = members["GripType.csv"].decode()
    max_test_csv = members["MaxWeightTest.csv"].decode()

    # Graft a grip type + reference the local (fresh) account can't have --
    # resolution must fail loud rather than silently dropping the row.
    grip_csv = grip_csv.rstrip("\n") + "\n999,exotic grip\n"
    max_test_csv = _replace_column(max_test_csv, 0, "grip_type_id", "999")

    archive_bytes = _replace_member(archive_bytes, "GripType.csv", grip_csv)
    archive_bytes = _replace_member(archive_bytes, "MaxWeightTest.csv", max_test_csv)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "grip" in response.text.lower()

    # Nothing landed -- including the BodyWeightLog/Climb/PlateInventoryItem
    # members processed before MaxWeightTest in archive order.
    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        assert len(z.read("MaxWeightTest.csv").decode().splitlines()) == 1
        assert len(z.read("PlateInventoryItem.csv").decode().splitlines()) == 1 + 6


def test_import_failure_mid_load_rolls_the_whole_account_back_to_empty(client):
    register(client, "founder@example.com", "test-pw-1234")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    save_work_set(client, "left", 1, "40", "5", date="2026-07-05")
    archive_bytes = export_archive(client)

    # Corrupt WorkSet.csv (processed after TrainingSession/PainReport/
    # WarmupStepCheck/SessionMaxEstimate) to reference a training session
    # id that doesn't exist in TrainingSession.csv.
    ws_csv = _zip_members(archive_bytes)["WorkSet.csv"].decode()
    ws_csv = _replace_column(ws_csv, 0, "training_session_id", "999999")
    archive_bytes = _replace_member(archive_bytes, "WorkSet.csv", ws_csv)

    code = generate_invite(client)
    register(client, "phone@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "training session" in response.text.lower()

    # Rolled all the way back: no TrainingSession/MaxWeightTest landed, and
    # PlateInventoryItem still shows the (undeleted) seeded default -- not
    # emptied, not doubled.
    with zipfile.ZipFile(io.BytesIO(export_archive(client))) as z:
        assert len(z.read("TrainingSession.csv").decode().splitlines()) == 1
        assert len(z.read("MaxWeightTest.csv").decode().splitlines()) == 1
        assert len(z.read("PlateInventoryItem.csv").decode().splitlines()) == 1 + 6
