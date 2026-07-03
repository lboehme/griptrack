import re


def register(client, email="lifter@example.com", password="pw-123"):
    return client.post(
        "/register", data={"email": email, "password": password}, follow_redirects=False
    )


def register_second_user(client, email="friend@example.com", password="pw-456"):
    invite = client.post("/invites", follow_redirects=True)
    code = re.search(r'class="invite-code">([^<]+)<', invite.text).group(1)
    client.post(
        "/register",
        data={"email": email, "password": password, "invite_code": code},
    )


def grip_type_id(client, name):
    page = client.get("/max-tests").text
    return re.search(rf'value="(\d+)">{name}<', page).group(1)


def log_max_test(client, hand, grip, edge_mm, date, weight):
    return client.post(
        "/max-tests",
        data={
            "hand": hand,
            "grip_type_id": grip_type_id(client, grip),
            "edge_mm": edge_mm,
            "date": date,
            "weight": weight,
        },
        follow_redirects=True,
    )


def current_maxes(client):
    """Parse the max-tests page into {(hand, grip, edge): weight}."""
    page = client.get("/max-tests").text
    return {
        (h, g, int(e)): float(w)
        for h, g, e, w in re.findall(
            r'data-combo="(\w+)\|(\w+)\|(\d+)".*?class="max-weight">([\d.]+)<',
            page,
            re.DOTALL,
        )
    }


def test_current_max_per_combination_latest_test_supersedes(client):
    register(client)

    log_max_test(client, "left", "half_crimp", 20, "2026-07-01", "42.5")
    assert current_maxes(client) == {("left", "half_crimp", 20): 42.5}

    # A different edge on the same hand/grip is its own combination.
    log_max_test(client, "left", "half_crimp", 10, "2026-07-01", "30")
    assert current_maxes(client)[("left", "half_crimp", 20)] == 42.5
    assert current_maxes(client)[("left", "half_crimp", 10)] == 30.0

    # A newer test supersedes even when lower (deliberate reset).
    log_max_test(client, "left", "half_crimp", 20, "2026-07-02", "40")
    assert current_maxes(client)[("left", "half_crimp", 20)] == 40.0


def test_max_tests_are_scoped_to_the_logged_in_user(client):
    register(client)
    log_max_test(client, "left", "half_crimp", 20, "2026-07-01", "42.5")

    register_second_user(client)

    assert current_maxes(client) == {}


def test_starter_grip_types_are_offered(client):
    register(client)

    page = client.get("/max-tests")

    assert page.status_code == 200
    for name in ("half_crimp", "full_crimp", "open_hand", "three_finger_drag", "pinch"):
        assert name in page.text


def test_admin_can_add_a_grip_type_but_non_admin_cannot(client):
    register(client)  # founder = admin

    response = client.post(
        "/grip-types", data={"name": "mono_pocket"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "mono_pocket" in client.get("/max-tests").text

    register_second_user(client)  # logged in as non-admin friend now
    response = client.post(
        "/grip-types", data={"name": "sloper"}, follow_redirects=False
    )
    assert response.status_code == 403
    assert "sloper" not in client.get("/max-tests").text
