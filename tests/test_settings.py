"""HTTP-seam tests for Settings (#151): the list page and its detail pages,
the old Profile/Plates URLs redirecting into it, the shared autosave answer
(htmx toast vs. no-JS 303 with `?saved=`), the server-only Admin group, and
per-user isolation of what the list page shows."""

import re

import pytest

from tests.helpers import (
    grip_type_id,
    log_bodyweight,
    login,
    register,
    register_second_user,
)

DETAIL_PAGES = [
    "/settings/name",
    "/settings/training",
    "/settings/progression",
    "/settings/plates",
    "/settings/restore",
    "/settings/about",
]

HTMX = {"HX-Request": "true"}


def primary_buttons(html):
    """Buttons/links styled as the primary action: a <button> or .btn with
    no btn-secondary / settings-switch / plate / small-button styling."""
    count = 0
    for tag in re.findall(r"<(?:button|a)\b[^>]*>", html):
        classes = re.search(r'class="([^"]*)"', tag)
        names = set(classes.group(1).split()) if classes else set()
        is_button = tag.startswith("<button")
        if not is_button and "btn" not in names:
            continue
        if names & {"btn-secondary", "settings-switch", "plate", "sheet-tab", "sheet-close"}:
            continue
        if 'form="logout' in tag or "Log out" in tag:
            continue
        count += 1
    return count


def main_html(page_text):
    """Just <main>: the header's Log out button and the tab bar aren't
    part of any page's own actions."""
    return re.search(r"<main[^>]*>(.*)</main>", page_text, re.DOTALL).group(1)


# ---------- pages and redirects ----------


def test_settings_is_a_page_with_the_grouped_rows(client):
    register(client)

    page = client.get("/settings")

    assert page.status_code == 200
    for group in ("You", "Training", "Equipment", "Rest alerts", "Your data"):
        assert f">{group}</p>" in page.text
    for href in DETAIL_PAGES:
        assert f'href="{href}"' in page.text
    assert 'href="/profile/export"' in page.text
    assert "kg</span> · fixed" in page.text


@pytest.mark.parametrize("path", DETAIL_PAGES)
def test_every_detail_page_renders_and_links_back(client, path):
    register(client)

    page = client.get(path)

    assert page.status_code == 200
    assert 'href="/settings"' in page.text


@pytest.mark.parametrize("path", ["/settings", *DETAIL_PAGES, "/settings/admin"])
def test_settings_pages_require_login(client, path):
    assert client.get(path, follow_redirects=False).status_code == 401


@pytest.mark.parametrize("path", ["/settings", *DETAIL_PAGES])
def test_no_settings_page_has_more_than_one_primary_button(client, path):
    register(client)

    assert primary_buttons(main_html(client.get(path).text)) <= 1


def test_old_profile_page_redirects_to_settings(client):
    register(client)

    response = client.get("/profile", follow_redirects=False)

    assert (response.status_code, response.headers["location"]) == (303, "/settings")


# ---------- autosave: htmx toast, no-JS 303 back to the settings page ----------


@pytest.mark.parametrize(
    "url, data, lands_on",
    [
        ("/profile/name", {"name": "Lukas"}, "/settings/name?saved=name"),
        ("/profile", {"hand_order_pref": "sequential"}, "/settings/training?saved=training"),
        (
            "/profile/protocol",
            {"base_work_set_reps": "6", "default_rest_seconds": "120"},
            "/settings/training?saved=training",
        ),
        (
            "/profile/progression",
            {"path": "double", "rep_min": "5", "rep_max": "10", "max_sets": "6"},
            "/settings/progression?saved=progression",
        ),
        ("/profile/bodyweight", {"date": "2026-07-01", "weight": "70"}, "/settings?saved=bodyweight"),
        ("/plates", {"weight": "7.5", "count": "2"}, "/settings/plates?saved=plates"),
    ],
)
def test_settings_writes_redirect_back_to_their_settings_page(client, url, data, lands_on):
    register(client)

    response = client.post(url, data=data, follow_redirects=False)

    assert (response.status_code, response.headers["location"]) == (303, lands_on)
    landed = client.get(lands_on)
    assert 'class="toast"' in landed.text


@pytest.mark.parametrize(
    "url, data",
    [
        ("/profile/name", {"name": "Lukas"}),
        ("/profile", {"hand_order_pref": "sequential"}),
        ("/profile/protocol", {"base_work_set_reps": "6", "default_rest_seconds": "120"}),
        ("/profile/progression", {"path": "set", "rep_min": "5", "rep_max": "5", "max_sets": "6"}),
    ],
)
def test_htmx_autosave_answers_with_the_saved_toast(client, url, data):
    register(client)

    response = client.post(url, data=data, headers=HTMX, follow_redirects=False)

    assert response.status_code == 200
    assert '<p class="toast" role="status">' in response.text
    assert "Saved" in response.text


def test_autosave_forms_post_on_change_into_the_toast_slot(client):
    register(client)

    for path, action in [
        ("/settings/name", "/profile/name"),
        ("/settings/training", "/profile"),
        ("/settings/training", "/profile/protocol"),
        ("/settings/progression", "/profile/progression"),
    ]:
        page = client.get(path).text
        form = re.search(rf'<form[^>]*hx-post="{re.escape(action)}"[^>]*>', page)
        assert form, (path, action)
        assert 'hx-trigger="change, submit"' in form.group(0)
        assert 'hx-target="#log-sheet-slot"' in form.group(0)


def test_a_settings_page_without_saved_shows_no_toast(client):
    register(client)

    assert 'class="toast"' not in client.get("/settings/name").text


def test_combo_override_add_and_remove_land_on_progression(client):
    register(client)
    gid = grip_type_id(client, "half crimp")

    added = client.post(
        "/profile/progression",
        data={"grip_type_id": gid, "edge_mm": 20, "path": "set", "rep_min": 5, "rep_max": 5, "max_sets": 6},
        follow_redirects=False,
    )
    assert added.headers["location"] == "/settings/progression?saved=override"
    page = client.get("/settings/progression").text
    assert f'data-grip-type-id="{gid}" data-edge-mm="20"' in page

    removed = client.post(
        "/profile/progression/delete",
        data={"grip_type_id": gid, "edge_mm": 20},
        follow_redirects=False,
    )
    assert removed.headers["location"] == "/settings/progression?saved=override-removed"
    assert 'data-edge-mm="20"' not in client.get("/settings/progression").text


def test_hand_order_shows_on_the_list_and_as_the_checked_choice(client):
    register(client)
    client.post("/profile", data={"hand_order_pref": "sequential"})

    assert 'data-hand-order="sequential"' in client.get("/settings").text
    training = client.get("/settings/training").text
    assert re.search(r'value="sequential" class="chip-radio" checked', training)


def test_restore_page_is_a_secondary_danger_action_with_a_proper_dash(client):
    register(client)

    page = client.get("/settings/restore").text

    assert 'action="/profile/import"' in page
    assert 'class="btn-secondary btn-danger"' in page
    assert "--" not in main_html(page).replace("<!--", "").replace("-->", "")


# ---------- About these numbers ----------


def test_about_page_explains_the_numbers_in_plain_language(client):
    register(client)

    page = client.get("/settings/about").text

    for anchor in ("volume", "max", "rpe", "load", "correlation", "balance"):
        assert f'id="{anchor}"' in page
    assert "weight × reps" in page
    assert "Spearman" in page  # the technical term lives here now


def test_progress_detail_pages_link_to_about_instead_of_jargon(client):
    register(client)

    for section in ("volume", "balance", "grade"):
        page = client.get(f"/progress/{section}").text
        assert "Spearman" not in page
        assert "TrainingVolume" not in page
    volume = client.get("/progress/volume").text
    assert 'href="/settings/about#volume"' in volume


# ---------- Admin (server build only) ----------


def test_admin_group_is_shown_to_the_admin_only(client):
    register(client)  # founder = admin

    assert 'href="/settings/admin"' in client.get("/settings").text
    admin = client.get("/settings/admin")
    assert admin.status_code == 200
    for action in ("/invites", "/grip-types", "/admin/reset-password"):
        assert f'action="{action}"' in admin.text

    register_second_user(client)
    assert 'href="/settings/admin"' not in client.get("/settings").text
    assert client.get("/settings/admin").status_code == 403


def test_admin_writes_land_back_on_the_admin_page(client):
    register(client, "founder@example.com")
    register_second_user(client)
    client.post("/logout")
    login(client, "founder@example.com", "test-pw-1234")

    grip = client.post("/grip-types", data={"name": "sloper"}, follow_redirects=False)
    reset = client.post(
        "/admin/reset-password",
        data={"email": "friend@example.com", "new_password": "fresh-pw-123"},
        follow_redirects=False,
    )

    assert grip.headers["location"] == "/settings/admin?saved=grip-type"
    assert reset.headers["location"] == "/settings/admin?saved=password"


def test_invite_page_links_back_to_admin(client):
    register(client)

    page = client.post("/invites", follow_redirects=True).text

    assert 'href="/settings/admin"' in page
    assert 'href="/profile"' not in page


# ---------- isolation ----------


def test_settings_list_shows_only_the_logged_in_users_values(client):
    register(client, "founder@example.com", name="Founder")
    log_bodyweight(client, "2026-07-01", "71.4")
    client.post("/profile", data={"hand_order_pref": "sequential"})
    client.post("/profile/protocol", data={"base_work_set_reps": "8", "default_rest_seconds": "240"})

    register_second_user(client)
    page = client.get("/settings").text

    assert "71.4" not in page
    assert "Founder" not in page
    assert 'data-hand-order="alternating"' in page
    assert "5 reps · 3:00 rest" in page

    client.post("/logout")
    login(client, "founder@example.com", "test-pw-1234")
    founder = client.get("/settings").text
    assert "71.4" in founder
    assert "8 reps · 4:00 rest" in founder
