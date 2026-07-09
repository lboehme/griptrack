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
    too_short = register(client, password="short")
    assert too_short.status_code == 400

    too_long = register(client, password="x" * 73)
    assert too_long.status_code == 400

    # And neither attempt created an account.
    ok = register(client, password="long-enough-pw")
    assert ok.status_code == 303


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
