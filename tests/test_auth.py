from tests.helpers import generate_invite, login, register


def test_first_user_registers_without_invite_and_is_logged_in(client):
    response = register(client, "founder@example.com", "s3cret-pw")

    assert response.status_code == 303

    home = client.get("/")
    assert home.status_code == 200
    assert "founder@example.com" in home.text


def test_second_registration_without_invite_is_rejected(client):
    register(client, "founder@example.com", "s3cret-pw")

    response = register(client, "friend@example.com", "other-pw")

    assert response.status_code == 400

    # And the rejected registrant must not end up with an account they
    # could log in to.
    login = client.post(
        "/login",
        data={"email": "friend@example.com", "password": "other-pw"},
        follow_redirects=False,
    )
    assert login.status_code != 303


def test_friend_registers_with_admin_generated_invite(client):
    register(client, "founder@example.com", "s3cret-pw")
    code = generate_invite(client)

    response = register(client, "friend@example.com", "friend-pw", invite_code=code)

    assert response.status_code == 303
    home = client.get("/")
    assert "friend@example.com" in home.text


def test_used_invite_cannot_be_redeemed_again(client):
    register(client, "founder@example.com", "s3cret-pw")
    code = generate_invite(client)
    register(client, "friend@example.com", "friend-pw", invite_code=code)

    response = register(client, "third@example.com", "third-pw", invite_code=code)

    assert response.status_code == 400


def test_non_admin_cannot_generate_invites(client):
    register(client, "founder@example.com", "s3cret-pw")
    code = generate_invite(client)
    register(client, "friend@example.com", "friend-pw", invite_code=code)

    # The client is now logged in as the (non-admin) friend.
    response = client.post("/invites", follow_redirects=False)

    assert response.status_code == 403


def test_bogus_invite_code_is_rejected(client):
    register(client, "founder@example.com", "s3cret-pw")

    response = register(
        client, "friend@example.com", "friend-pw", invite_code="not-a-real-code"
    )

    assert response.status_code == 400


def test_admin_resets_a_users_forgotten_password(client):
    register(client, "founder@example.com", "s3cret-pw")
    code = generate_invite(client)
    register(client, "friend@example.com", "forgotten-pw", invite_code=code)

    client.post("/logout")
    login(client, "founder@example.com", "s3cret-pw")
    response = client.post(
        "/admin/reset-password",
        data={"email": "friend@example.com", "new_password": "fresh-pw"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    client.post("/logout")
    assert login(client, "friend@example.com", "forgotten-pw").status_code != 303
    assert login(client, "friend@example.com", "fresh-pw").status_code == 303


def test_non_admin_cannot_reset_passwords(client):
    register(client, "founder@example.com", "s3cret-pw")
    code = generate_invite(client)
    register(client, "friend@example.com", "friend-pw", invite_code=code)

    # Logged in as the non-admin friend.
    response = client.post(
        "/admin/reset-password",
        data={"email": "founder@example.com", "new_password": "hijacked"},
        follow_redirects=False,
    )
    assert response.status_code == 403

    client.post("/logout")
    assert login(client, "founder@example.com", "s3cret-pw").status_code == 303


def test_protected_route_rejects_request_without_session(client):
    response = client.post("/invites", follow_redirects=False)

    assert response.status_code == 401


def test_login_and_logout_round_trip(client):
    register(client, "founder@example.com", "s3cret-pw")

    client.post("/logout")
    assert "founder@example.com" not in client.get("/").text

    wrong = client.post(
        "/login",
        data={"email": "founder@example.com", "password": "wrong-pw"},
        follow_redirects=False,
    )
    assert wrong.status_code != 303

    right = client.post(
        "/login",
        data={"email": "founder@example.com", "password": "s3cret-pw"},
        follow_redirects=False,
    )
    assert right.status_code == 303
    assert "founder@example.com" in client.get("/").text


def test_session_is_revoked_after_admin_password_reset(client):
    register(client, "founder@example.com", "s3cret-pw")
    code = generate_invite(client)
    register(client, "friend@example.com", "friend-pw", invite_code=code)

    # Save the friend's valid session cookie
    friend_session = client.cookies.get("session")

    # Log out friend, log in founder
    client.post("/logout")
    login(client, "founder@example.com", "s3cret-pw")

    # Admin resets friend's password
    client.post(
        "/admin/reset-password",
        data={"email": "friend@example.com", "new_password": "fresh-pw"},
        follow_redirects=True,
    )
    client.post("/logout")

    client.post("/logout")

    # Attempt to use the friend's old session. Sent as a raw Cookie header
    # (not client.cookies.set(), which can silently fail to reattach a
    # cookie after the jar has been cleared by a prior /logout, making a
    # test that only checks page text pass for the wrong reason) so this
    # genuinely exercises the stale cookie against the live app.
    #
    # Asserted against a route that requires login via auth.current_user
    # (which checks session_version), not "/" — the home route reads
    # user_id straight off the session without going through
    # current_user, so it doesn't observe revocation and isn't a suitable
    # probe for this behavior.
    stale_headers = {"Cookie": f"session={friend_session}"}
    protected = client.get("/dashboard", headers=stale_headers)
    assert protected.status_code == 401

    # The friend can log in with the new password
    assert login(client, "friend@example.com", "fresh-pw").status_code == 303


def test_other_users_session_survives_admin_password_reset(client):
    """Resetting one user's password must only revoke *that* user's
    sessions — an uninvolved user B should stay logged in throughout."""
    register(client, "founder@example.com", "s3cret-pw")
    code_a = generate_invite(client)
    register(client, "target@example.com", "target-pw", invite_code=code_a)

    client.post("/logout")
    login(client, "founder@example.com", "s3cret-pw")
    code_b = generate_invite(client)
    register(client, "bystander@example.com", "bystander-pw", invite_code=code_b)
    bystander_session = client.cookies.get("session")

    client.post("/logout")
    login(client, "founder@example.com", "s3cret-pw")
    client.post(
        "/admin/reset-password",
        data={"email": "target@example.com", "new_password": "fresh-pw"},
        follow_redirects=True,
    )
    client.post("/logout")

    # The bystander's session, untouched by the reset, still works — sent
    # as a raw Cookie header for the same reattachment reason noted above.
    response = client.get(
        "/dashboard", headers={"Cookie": f"session={bystander_session}"}
    )
    assert response.status_code == 200
