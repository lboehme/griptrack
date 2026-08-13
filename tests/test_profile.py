from tests.helpers import log_bodyweight, register, register_second_user


def test_unit_preference_is_chosen_at_registration(client):
    register(client, "lifter@example.com", "test-pw-1234", unit_pref="lbs")

    profile = client.get("/profile")

    assert profile.status_code == 200
    assert "lbs" in profile.text


def test_unit_preference_defaults_to_kg(client):
    register(client, "lifter@example.com", "test-pw-1234")

    profile = client.get("/profile")

    assert "kg" in profile.text


def test_profile_page_links_to_data_export(client):
    register(client, "lifter@example.com", "test-pw-1234")

    profile = client.get("/profile")

    assert 'href="/profile/export"' in profile.text


def current_bodyweight(client):
    import re

    match = re.search(
        r'class="current-bodyweight">([^<]+)<', client.get("/profile").text
    )
    return match.group(1) if match else None


def test_latest_bodyweight_entry_is_current(client):
    register(client, "lifter@example.com", "test-pw-1234")

    log_bodyweight(client, "2026-07-01", "71.4")
    assert current_bodyweight(client) == "71.4"

    log_bodyweight(client, "2026-07-03", "70.2")
    assert current_bodyweight(client) == "70.2"

    # A backdated entry must not displace the latest one.
    log_bodyweight(client, "2026-06-01", "74.0")
    assert current_bodyweight(client) == "70.2"


def test_bodyweight_is_scoped_to_the_logged_in_user(client):
    register(client, "founder@example.com", "test-pw-1234")
    log_bodyweight(client, "2026-07-01", "71.4")

    register_second_user(client)

    # Logged in as friend now: founder's bodyweight must not appear.
    assert current_bodyweight(client) is None

    log_bodyweight(client, "2026-07-02", "88.0")
    assert current_bodyweight(client) == "88.0"

    client.post("/logout")
    client.post("/login", data={"email": "founder@example.com", "password": "test-pw-1234"})
    assert current_bodyweight(client) == "71.4"


def test_unit_preference_cannot_be_changed_after_signup(client):
    register(client, "lifter@example.com", "test-pw-1234", unit_pref="kg")

    client.post(
        "/profile",
        data={"hand_order_pref": "sequential", "unit_pref": "lbs"},
        follow_redirects=True,
    )

    profile = client.get("/profile")
    assert '<span class="unit-pref">kg</span>' in profile.text


def test_hand_order_preference_defaults_and_is_editable(client):
    register(client, "lifter@example.com", "test-pw-1234")

    assert "alternating" in client.get("/profile").text

    response = client.post(
        "/profile",
        data={"hand_order_pref": "sequential"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "sequential" in client.get("/profile").text


def test_csv_export_returns_user_scoped_data(client):
    import io
    import zipfile

    from tests.helpers import log_climb, log_max_test

    # Setup User A
    register(client, "founder@example.com", "test-pw-1234", unit_pref="kg")
    log_bodyweight(client, "2026-07-01", "71.4")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "35")

    # Setup User B
    register_second_user(client, "friend@example.com", "test-pw-1234")
    log_bodyweight(client, "2026-07-02", "88.0")
    log_climb(client, "2026-07-02", "V3")
    log_climb(client, "2026-07-03", "V4")

    # Export User B data
    response = client.get("/profile/export")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        # Check files exist
        names = z.namelist()
        assert "BodyWeightLog.csv" in names
        assert "Climb.csv" in names
        assert "MaxWeightTest.csv" in names
        assert "GripType.csv" in names
        assert "PlateInventoryItem.csv" in names
        assert "manifest.json" in names

        # Verify row counts and scope
        bodyweights = z.read("BodyWeightLog.csv").decode().splitlines()
        # header + 1 row
        assert len(bodyweights) == 2
        assert "88.0" in bodyweights[1]

        climbs = z.read("Climb.csv").decode().splitlines()
        # header + 2 rows
        assert len(climbs) == 3

        max_tests = z.read("MaxWeightTest.csv").decode().splitlines()
        # header only
        assert len(max_tests) == 1

        # Verify units are in headers
        assert "weight (kg)" in bodyweights[0]

        # TrainingSession-scoped members are present (header-only) even
        # when the user has logged no sessions -- the archive's member
        # set is fixed by format_version, not by which tables happen to
        # be non-empty (see backend/export_spec.py).
        assert "TrainingSession.csv" in names
        assert "WorkSet.csv" in names
        assert "PainReport.csv" in names
        assert "WarmupStepCheck.csv" in names
        assert "SessionMaxEstimate.csv" in names
        assert len(z.read("TrainingSession.csv").decode().splitlines()) == 1
        assert len(z.read("WorkSet.csv").decode().splitlines()) == 1


def test_csv_export_grip_type_csv_carries_id_and_name(client):
    """GripType.csv is a global lookup (unfiltered by user) so the future
    importer (#102) can resolve a WorkSet/MaxWeightTest's grip_type_id by
    name -- not dimension_name, which is fixed seed data."""
    import io
    import zipfile

    from backend.models import STARTER_GRIP_TYPES

    register(client, "lifter@example.com", "test-pw-1234")

    response = client.get("/profile/export")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        lines = z.read("GripType.csv").decode().splitlines()
        assert lines[0] == "id,name"
        # header + one row per starter grip type
        assert len(lines) == 1 + len(STARTER_GRIP_TYPES)
        body = "\n".join(lines[1:])
        for name in STARTER_GRIP_TYPES:
            assert name in body


def test_csv_export_plate_inventory_round_trips_instead_of_seeded_default_only(client):
    """A restore without PlateInventoryItem.csv would silently fall back to
    seeded defaults (ADR-0008) -- this asserts the export actually carries
    the user's real (here: still-default, but user-scoped) inventory."""
    import io
    import zipfile

    register(client, "founder@example.com", "test-pw-1234", unit_pref="kg")
    register_second_user(client, "friend@example.com", "test-pw-1234")

    response = client.get("/profile/export")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        lines = z.read("PlateInventoryItem.csv").decode().splitlines()
        assert lines[0] == "id,user_id,weight (kg),count"
        # The seeded default kg inventory has 6 denominations.
        assert len(lines) == 1 + 6


def test_csv_export_manifest_carries_format_version_unit_and_timestamp(client):
    import io
    import json
    import zipfile
    from datetime import datetime

    from backend.export_spec import FORMAT_VERSION

    register(client, "lifter@example.com", "test-pw-1234", unit_pref="lbs")

    response = client.get("/profile/export")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        manifest = json.loads(z.read("manifest.json").decode())

    assert manifest["format_version"] == FORMAT_VERSION
    assert manifest["unit"] == "lbs"
    # Must parse as an ISO-8601 timestamp.
    datetime.fromisoformat(manifest["exported_at"])


def test_csv_export_neutralizes_spreadsheet_formula_cells(client):
    """A text cell starting with = + - or @ executes as a formula when the
    CSV is opened in Excel/LibreOffice. The export prefixes such cells with
    a quote so a shared export can't carry a payload."""
    import io
    import zipfile

    from tests.helpers import log_climb

    register(client)
    log_climb(client, "2026-07-04", "V3", notes='=HYPERLINK("http://evil")')

    response = client.get("/profile/export")
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        climbs = z.read("Climb.csv").decode()
        assert "'=HYPERLINK" in climbs
        assert ",=HYPERLINK" not in climbs
