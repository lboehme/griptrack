def register(client, email, password, unit_pref=None):
    data = {"email": email, "password": password}
    if unit_pref is not None:
        data["unit_pref"] = unit_pref
    return client.post("/register", data=data, follow_redirects=False)


def test_unit_preference_is_chosen_at_registration(client):
    register(client, "lifter@example.com", "pw-123", unit_pref="lbs")

    profile = client.get("/profile")

    assert profile.status_code == 200
    assert "lbs" in profile.text


def test_unit_preference_defaults_to_kg(client):
    register(client, "lifter@example.com", "pw-123")

    profile = client.get("/profile")

    assert "kg" in profile.text


def log_bodyweight(client, date, weight):
    return client.post(
        "/profile/bodyweight",
        data={"date": date, "weight": weight},
        follow_redirects=True,
    )


def current_bodyweight(client):
    import re

    match = re.search(
        r'class="current-bodyweight">([^<]+)<', client.get("/profile").text
    )
    return match.group(1) if match else None


def test_latest_bodyweight_entry_is_current(client):
    register(client, "lifter@example.com", "pw-123")

    log_bodyweight(client, "2026-07-01", "71.4")
    assert current_bodyweight(client) == "71.4"

    log_bodyweight(client, "2026-07-03", "70.2")
    assert current_bodyweight(client) == "70.2"

    # A backdated entry must not displace the latest one.
    log_bodyweight(client, "2026-06-01", "74.0")
    assert current_bodyweight(client) == "70.2"


def test_bodyweight_is_scoped_to_the_logged_in_user(client):
    import re

    register(client, "founder@example.com", "pw-123")
    log_bodyweight(client, "2026-07-01", "71.4")

    invite = client.post("/invites", follow_redirects=True)
    code = re.search(r'class="invite-code">([^<]+)<', invite.text).group(1)
    client.post(
        "/register",
        data={"email": "friend@example.com", "password": "pw-456", "invite_code": code},
    )

    # Logged in as friend now: founder's bodyweight must not appear.
    assert current_bodyweight(client) is None

    log_bodyweight(client, "2026-07-02", "88.0")
    assert current_bodyweight(client) == "88.0"

    client.post("/logout")
    client.post("/login", data={"email": "founder@example.com", "password": "pw-123"})
    assert current_bodyweight(client) == "71.4"


def test_unit_preference_cannot_be_changed_after_signup(client):
    register(client, "lifter@example.com", "pw-123", unit_pref="kg")

    client.post(
        "/profile",
        data={"hand_order_pref": "sequential", "unit_pref": "lbs"},
        follow_redirects=True,
    )

    profile = client.get("/profile")
    assert '<span class="unit-pref">kg</span>' in profile.text


def test_hand_order_preference_defaults_and_is_editable(client):
    register(client, "lifter@example.com", "pw-123")

    assert "alternating" in client.get("/profile").text

    response = client.post(
        "/profile",
        data={"hand_order_pref": "sequential"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "sequential" in client.get("/profile").text
