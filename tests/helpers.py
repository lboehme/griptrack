"""Drivers for the HTTP seam — the one vocabulary every test file uses to
act on the app (register users, log tests/sets/climbs/bodyweight). Page
parsers stay in the test files that own the scenario, except the shared
max-tests parser."""

import re


def register(
    client,
    email="lifter@example.com",
    password="test-pw-1234",
    unit_pref=None,
    invite_code=None,
    headers=None,
    name=None,
):
    data = {"email": email, "password": password}
    if unit_pref is not None:
        data["unit_pref"] = unit_pref
    if name is not None:
        data["name"] = name
    if invite_code is not None:
        data["invite_code"] = invite_code
    return client.post(
        "/register", data=data, follow_redirects=False, headers=headers
    )


def login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def generate_invite(client):
    """Generate an invite as the currently logged-in user and return its code."""
    response = client.post("/invites", follow_redirects=True)
    assert response.status_code == 200
    match = re.search(r'class="invite-code">([^<]+)<', response.text)
    assert match, "no invite code found on the page"
    return match.group(1)


def register_second_user(client, email="friend@example.com", password="test-pw-4567"):
    """Invite + register a second account; the client ends up logged in as it."""
    code = generate_invite(client)
    return register(client, email, password, invite_code=code)


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


def save_work_set(
    client, hand, set_number, weight, reps,
    date="2026-07-04", rpe=None, grip="half crimp", edge_mm=20,
):
    data = {
        "grip_type_id": grip_type_id(client, grip),
        "edge_mm": edge_mm,
        "date": date,
        "hand": hand,
        "set_number": set_number,
        "weight": weight,
        "reps": reps,
    }
    if rpe is not None:
        data["rpe"] = rpe
    return client.post("/session/workset", data=data, follow_redirects=True)


def log_climb(
    client, date="2026-07-04", grade="V5", style="flash", notes=None,
    discipline=None, follow_redirects=True,
):
    """Log a climb via the HTTP seam. The climb form no longer offers a
    discipline choice (issue #55 — new climbs are always boulder), but a
    `discipline` kwarg is still accepted here so a test can assert the
    server ignores an attacker-supplied hidden field."""
    data = {"date": date, "grade": grade, "style": style}
    if discipline is not None:
        data["discipline"] = discipline
    if notes is not None:
        data["notes"] = notes
    return client.post(
        "/climbs", data=data, follow_redirects=follow_redirects
    )


def log_bodyweight(client, date, weight):
    return client.post(
        "/profile/bodyweight",
        data={"date": date, "weight": weight},
        follow_redirects=True,
    )


def get_session_page(client, path, params):
    """GET a session page (warmup/worksets), auto-confirming the "no
    session on this date — create one?" prompt if it appears.

    Most tests exercise the normal warmup/worksets content, not the
    past-date creation gate itself (see test_past_session_creation.py for
    that) — this keeps every other test's dates free to land anywhere in
    the past without tripping over the gate."""
    response = client.get(path, params=params, follow_redirects=True)
    if "session-confirm-card" in response.text:
        page = "warmup" if path.endswith("warmup") else "worksets"
        client.post(
            "/session/create", data={"page": page, **params}, follow_redirects=True
        )
        response = client.get(path, params=params, follow_redirects=True)
    return response


def current_maxes(client):
    """Parse the max-tests page into {(hand, grip, edge): weight}."""
    page = client.get("/max-tests").text
    return {
        (h, g, int(e)): float(w)
        for h, g, e, w in re.findall(
            r'data-combo="(\w+)\|([^|]+)\|(\d+)".*?class="max-weight">([\d.]+)<',
            page,
            re.DOTALL,
        )
    }
