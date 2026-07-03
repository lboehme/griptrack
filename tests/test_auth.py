import re


def register(client, email, password, invite_code=None):
    data = {"email": email, "password": password}
    if invite_code is not None:
        data["invite_code"] = invite_code
    return client.post("/register", data=data, follow_redirects=False)


def generate_invite(client):
    """Generate an invite as the currently logged-in user and return its code."""
    response = client.post("/invites", follow_redirects=True)
    assert response.status_code == 200
    match = re.search(r'class="invite-code">([^<]+)<', response.text)
    assert match, "no invite code found on the page"
    return match.group(1)


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


def login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


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
