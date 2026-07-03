import re


def register(client, email="lifter@example.com", password="pw-123", unit_pref=None):
    data = {"email": email, "password": password}
    if unit_pref is not None:
        data["unit_pref"] = unit_pref
    return client.post("/register", data=data, follow_redirects=False)


def inventory_rows(client):
    """Parse the plates page into {weight: count}."""
    page = client.get("/plates").text
    return {
        float(w): int(c)
        for w, c in re.findall(
            r'class="plate-weight">([^<]+)</\w+>.*?'
            r'class="plate-count" data-count="(\d+)"',
            page,
            re.DOTALL,
        )
    }


def test_new_user_gets_a_seeded_default_inventory(client):
    register(client)

    rows = inventory_rows(client)

    assert rows, "expected a non-empty seeded inventory"
    # A sensible kg default must include small change and workhorse plates.
    assert 1.25 in rows
    assert 5.0 in rows
    assert all(count >= 1 for count in rows.values())


def test_lbs_user_gets_lbs_denominated_defaults(client):
    register(client, unit_pref="lbs")

    rows = inventory_rows(client)

    # 45 lb is the canonical big plate; 20 kg would make no sense here.
    assert 45.0 in rows
    assert 20.0 not in rows


def test_plate_inventory_is_scoped_to_the_logged_in_user(client):
    register(client, email="founder@example.com")
    client.post("/plates", data={"weight": "7.5", "count": "2"}, follow_redirects=True)

    invite = client.post("/invites", follow_redirects=True)
    code = re.search(r'class="invite-code">([^<]+)<', invite.text).group(1)
    client.post(
        "/register",
        data={"email": "friend@example.com", "password": "pw-456", "invite_code": code},
    )

    # Logged in as friend: founder's custom 7.5 plate must not be there,
    # and removing a plate must not touch the founder's stack.
    assert 7.5 not in inventory_rows(client)
    client.post("/plates", data={"weight": "5", "count": "0"}, follow_redirects=True)

    client.post("/logout")
    client.post("/login", data={"email": "founder@example.com", "password": "pw-123"})
    rows = inventory_rows(client)
    assert rows[7.5] == 2
    assert 5.0 in rows


def test_user_can_add_change_and_remove_plates(client):
    register(client)

    client.post("/plates", data={"weight": "7.5", "count": "2"}, follow_redirects=True)
    assert inventory_rows(client)[7.5] == 2

    client.post("/plates", data={"weight": "7.5", "count": "4"}, follow_redirects=True)
    assert inventory_rows(client)[7.5] == 4

    client.post("/plates", data={"weight": "7.5", "count": "0"}, follow_redirects=True)
    assert 7.5 not in inventory_rows(client)
