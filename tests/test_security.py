import pytest

from tests.helpers import grip_type_id, log_max_test, register, save_work_set


def test_responses_carry_security_headers(client):
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in response.headers
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_cross_origin_posts_are_rejected(client):
    register(client)

    response = client.post(
        "/climbs",
        data={"date": "2026-07-04", "discipline": "boulder", "grade": "V5",
              "style": "flash"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    # The climb must not have been created (the page's grade placeholder
    # also contains "V5", so check the logged-climb data attribute).
    assert 'data-grade="V5"' not in client.get("/climbs").text


def test_same_origin_posts_pass(client):
    # Browsers send a matching Origin on same-origin form posts.
    response = register(client, headers={"Origin": "http://testserver"})

    assert response.status_code == 303


def test_password_rules_are_enforced(client):
    from backend.auth import PASSWORD_MAX_BYTES

    # All failing attempts stay on the first-registration path (no invite
    # needed and no account created), so the only rejection reason is the
    # password rule under test.
    too_short = register(client, password="short")
    assert too_short.status_code == 400

    # There's still a sane upper bound (DoS hygiene), just no longer bcrypt's
    # 72 bytes.
    too_long = register(client, password="x" * (PASSWORD_MAX_BYTES + 1))
    assert too_long.status_code == 400

    # PBKDF2 (unlike bcrypt) doesn't truncate at 72 bytes, so a passphrase
    # longer than 72 chars that would once have been rejected now registers.
    ok = register(client, password="x" * 73)
    assert ok.status_code == 303


def test_password_hashing_uses_pbkdf2():
    """#108: password hashing is stdlib PBKDF2 (no Rust bcrypt wheel), stored
    in a self-describing format, and rejects malformed/legacy hashes without
    crashing.

    This deliberately crosses below the HTTP seam (the repo's usual test
    boundary): the self-describing format, per-hash salt, and — most
    importantly — the fail-closed-on-legacy-bcrypt-hash behavior are invisible
    from the outside, and getting them wrong is a security bug, so they're
    asserted directly against backend.auth.
    """
    from backend.auth import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")

    # Self-describing: algorithm$iterations$salt$hash.
    assert hashed.startswith("pbkdf2_sha256$")
    algorithm, iterations, salt_b64, hash_b64 = hashed.split("$")
    assert int(iterations) >= 200_000  # sanity floor, not the exact tuned value
    assert salt_b64 and hash_b64

    # Round-trips, and only for the right password.
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False

    # Random per-hash salt: same password hashes to different strings.
    assert hash_password("same") != hash_password("same")

    # A legacy bcrypt hash can no longer be verified (reset-on-cutover), but
    # must fail closed rather than raise.
    assert verify_password("x", "$2b$12$" + "a" * 53) is False
    # Arbitrary garbage also fails closed.
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "") is False


def test_duplicate_email_is_rejected_cleanly(client):
    register(client, email="founder@example.com", password="long-enough-pw")

    from tests.helpers import generate_invite

    code = generate_invite(client)
    response = register(
        client, email="founder@example.com", password="other-long-pw",
        invite_code=code,
    )

    assert response.status_code == 400


def test_login_is_rate_limited(client):
    register(client, email="founder@example.com", password="long-enough-pw")
    client.post("/logout")

    from tests.helpers import login

    for _ in range(10):
        assert login(client, "founder@example.com", "wrong-pw").status_code == 401

    blocked = login(client, "founder@example.com", "wrong-pw")
    assert blocked.status_code == 429

    # Even the right password is blocked while rate-limited.
    assert login(client, "founder@example.com", "long-enough-pw").status_code == 429


def test_production_requires_a_real_session_secret(monkeypatch):
    monkeypatch.setenv("GRIPTRACK_ENV", "production")
    monkeypatch.delenv("GRIPTRACK_SESSION_SECRET", raising=False)

    from backend.main import create_app

    with pytest.raises(RuntimeError):
        create_app()


def test_production_session_cookie_is_secure(monkeypatch, client_factory):
    monkeypatch.setenv("GRIPTRACK_ENV", "production")
    monkeypatch.setenv("GRIPTRACK_SESSION_SECRET", "a-real-secret-for-tests")

    client = client_factory()
    response = register(client, password="long-enough-pw")

    set_cookie = response.headers["set-cookie"].lower()
    assert "secure" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_absurd_numeric_inputs_are_rejected(client):
    register(client, password="long-enough-pw")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")

    huge_weight = save_work_set(client, "left", 1, "999999", "5")
    assert huge_weight.status_code == 422

    huge_reps = save_work_set(client, "left", 1, "40", "100000")
    assert huge_reps.status_code == 422

    hoarder = client.post(
        "/plates", data={"weight": "1000000", "count": "1"}, follow_redirects=False
    )
    assert hoarder.status_code == 422

    stack_of_doom = client.post(
        "/plates", data={"weight": "1.25", "count": "1000000"},
        follow_redirects=False,
    )
    assert stack_of_doom.status_code == 422

    razor_blade = client.post(
        "/max-tests",
        data={
            "hand": "left",
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": "99999",
            "date": "2026-07-01",
            "weight": "40",
        },
        follow_redirects=False,
    )
    assert razor_blade.status_code == 422

    huge_estimate = client.post(
        "/max-tests/guided",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": "20",
            "date": "2026-07-01",
            "hand": "left",
            "estimate": "1000001",
        },
        follow_redirects=False,
    )
    assert huge_estimate.status_code == 422

    huge_actual = client.post(
        "/max-tests/guided/step",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": "20",
            "date": "2026-07-01",
            "hand": "left",
            "estimate": "40",
            "kind": "warmup",
            "set_number": "2",
            "actual": "1000001",
            "rating": "enough",
        },
        follow_redirects=False,
    )
    assert huge_actual.status_code == 422

    huge_other_weight = client.post(
        "/max-tests/guided/step",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": "20",
            "date": "2026-07-01",
            "hand": "left",
            "estimate": "40",
            "kind": "warmup",
            "set_number": "2",
            "actual": "22",
            "rating": "enough",
            # The other hand's ladder-state token, with a weight past the
            # ceiling — rejected by the module's decode validation.
            "other_column": '{"hand": "right", "status": "done", "weight": 1000001}',
        },
        follow_redirects=False,
    )
    assert huge_other_weight.status_code == 400

    huge_both_estimate = client.post(
        "/max-tests/guided/both",
        data={
            "grip_type_id": grip_type_id(client, "half crimp"),
            "edge_mm": "20",
            "date": "2026-07-01",
            "left_estimate": "1000001",
            "right_estimate": "40",
        },
        follow_redirects=False,
    )
    assert huge_both_estimate.status_code == 422


def test_oversized_climb_text_inputs_are_rejected(client):
    register(client, password="long-enough-pw")

    novel_grade = client.post(
        "/climbs",
        data={"date": "2026-07-04", "grade": "V" * 5000, "style": "flash"},
        follow_redirects=False,
    )
    assert novel_grade.status_code == 422

    novel_notes = client.post(
        "/climbs",
        data={"date": "2026-07-04", "grade": "V5", "style": "flash",
              "notes": "x" * 100_000},
        follow_redirects=False,
    )
    assert novel_notes.status_code == 422

    # Nothing was saved.
    assert 'data-grade=' not in client.get("/climbs").text


def test_session_number_is_bounded(client):
    register(client, password="long-enough-pw")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")
    grip_id = grip_type_id(client, "half crimp")

    too_high = client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "hand": "left", "set_number": 1, "weight": "40", "reps": "5",
            "session_number": 999999,
        },
        follow_redirects=False,
    )
    assert too_high.status_code == 422

    too_low = client.post(
        "/session/workset",
        data={
            "grip_type_id": grip_id, "edge_mm": 20, "date": "2026-07-04",
            "hand": "left", "set_number": 1, "weight": "40", "reps": "5",
            "session_number": 0,
        },
        follow_redirects=False,
    )
    assert too_low.status_code == 422

    # Neither absurd attempt created a row.
    history = client.get("/history").text
    assert 'data-date="2026-07-04"' not in history


def test_bootstrap_token_gates_the_first_admin(monkeypatch, client_factory):
    monkeypatch.setenv("GRIPTRACK_BOOTSTRAP_TOKEN", "let-me-in")
    client = client_factory()

    # Without the token, even the first registration is refused.
    no_token = register(client, password="long-enough-pw")
    assert no_token.status_code == 400

    wrong = register(client, password="long-enough-pw", invite_code="nope")
    assert wrong.status_code == 400

    # With the token as the invite code, the first admin is created.
    ok = register(client, password="long-enough-pw", invite_code="let-me-in")
    assert ok.status_code == 303


def test_unknown_grip_type_is_a_404_not_a_crash(client):
    register(client, password="long-enough-pw")

    for page in ("warmup", "worksets"):
        response = client.get(
            f"/session/{page}",
            params={"grip_type_id": 9999, "edge_mm": 20, "date": "2026-07-04"},
        )
        assert response.status_code == 404


def test_register_is_rate_limited(client):
    from tests.helpers import generate_invite
    register(client)  # register founder to generate invite
    code = generate_invite(client)
    client.post("/logout")

    # Spam the register endpoint (even with failures, it should rate limit)
    for _ in range(10):
        assert register(client, "test@example.com", "pw", invite_code="bad").status_code == 400

    blocked = register(client, "test@example.com", "pw", invite_code="bad")
    assert blocked.status_code == 429
    
    # Even a valid registration is blocked while rate-limited
    valid = register(client, "newuser@example.com", "long-pw", invite_code=code)
    assert valid.status_code == 429


def test_import_discards_a_spoofed_file_supplied_user_id(client):
    """A restored row must always attach to the importing user, never to a
    user_id embedded in the file (issue #102, ADR-0008) -- otherwise one
    account's archive (or a tampered one) could write rows that appear to
    belong to a different user_id."""
    import io
    import zipfile

    from tests.helpers import export_archive, generate_invite, import_archive, log_climb

    register(client, "founder@example.com", "test-pw-1234")
    log_climb(client, "2026-07-04", "V5", notes="founders climb")
    archive_bytes = export_archive(client)

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
        members = {name: z.read(name) for name in z.namelist()}
    lines = members["Climb.csv"].decode().splitlines()
    header = lines[0].split(",")
    row = lines[1].split(",")
    row[header.index("user_id")] = "1"  # an attempted spoof of founder's own id
    lines[1] = ",".join(row)
    members["Climb.csv"] = ("\n".join(lines) + "\n").encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    archive_bytes = out.getvalue()

    code = generate_invite(client)
    register(client, "friend@example.com", "test-pw-5678", invite_code=code)

    response = import_archive(client, archive_bytes)
    assert response.status_code == 303

    # Landed under the importing user (friend) ...
    assert "founders climb" in client.get("/climbs").text

    # ... and founder's own data was neither duplicated nor overwritten.
    client.post("/logout")
    from tests.helpers import login

    login(client, "founder@example.com", "test-pw-1234")
    founder_climbs = client.get("/climbs").text
    assert founder_climbs.count("founders climb") == 1


def test_import_upload_size_is_bounded(client, monkeypatch):
    import backend.import_restore as import_restore
    from tests.helpers import export_archive, generate_invite, import_archive

    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "friend@example.com", "test-pw-5678", invite_code=code)

    monkeypatch.setattr(import_restore, "MAX_IMPORT_UPLOAD_BYTES", 100)
    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "large" in response.text.lower()


def test_import_per_member_decompressed_size_is_bounded(client, monkeypatch):
    import backend.import_restore as import_restore
    from tests.helpers import export_archive, generate_invite, import_archive

    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "friend@example.com", "test-pw-5678", invite_code=code)

    monkeypatch.setattr(import_restore, "MAX_IMPORT_MEMBER_BYTES", 5)
    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "exceeds" in response.text.lower()


def test_import_member_count_is_bounded(client, monkeypatch):
    import backend.import_restore as import_restore
    from tests.helpers import export_archive, generate_invite, import_archive

    register(client, "founder@example.com", "test-pw-1234")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "friend@example.com", "test-pw-5678", invite_code=code)

    monkeypatch.setattr(import_restore, "MAX_IMPORT_MEMBERS", 3)
    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "too many files" in response.text.lower()


def test_import_row_count_per_member_is_bounded(client, monkeypatch):
    """The row cap must trip on real user-supplied data (Climb.csv here),
    not just on the archive's fixed-size members -- GripType.csv (5 starter
    rows) and PlateInventoryItem.csv (6 seeded rows) are read before
    Climb.csv in archive order, so the cap is set above both of those and
    below the climb count to prove it's actually bounding the row the test
    means to bound."""
    import backend.import_restore as import_restore
    from tests.helpers import export_archive, generate_invite, import_archive, log_climb

    register(client, "founder@example.com", "test-pw-1234")
    for day in range(1, 11):
        log_climb(client, f"2026-07-{day:02d}", "V5")
    archive_bytes = export_archive(client)

    code = generate_invite(client)
    register(client, "friend@example.com", "test-pw-5678", invite_code=code)

    monkeypatch.setattr(import_restore, "MAX_IMPORT_ROWS_PER_MEMBER", 8)
    response = import_archive(client, archive_bytes)
    assert response.status_code == 400
    assert "too many rows" in response.text.lower()
    assert "Climb.csv" in response.text
