"""Display names (issue #25): optional at signup, editable on the profile,
greeting falls back to the email's local part when unset."""

import html
import re

from tests.helpers import register, register_second_user


def greeting(client):
    """The name Today's headline greets with ("Pull day, Lukas." -- #149),
    read off the headline's data attribute so it's independent of which
    Today state (no data yet, plan, done, ...) the headline copy is in."""
    match = re.search(r'class="today-headline" data-greeting-name="([^"]*)"', client.get("/").text)
    return html.unescape(match.group(1))


def test_registering_with_a_name_personalizes_the_greeting(client):
    register(client, "lifter@example.com", "test-pw-1234", name="Lukas")

    assert greeting(client) == "Lukas"


def test_greeting_falls_back_to_email_local_part_without_a_name(client):
    register(client, "lifter@example.com", "test-pw-1234")

    assert greeting(client) == "lifter"


def test_blank_name_at_signup_means_no_name_set(client):
    register(client, "lifter@example.com", "test-pw-1234", name="   ")

    assert greeting(client) == "lifter"


def set_name(client, name):
    return client.post("/profile/name", data={"name": name}, follow_redirects=True)


def test_name_can_be_set_later_from_the_profile(client):
    register(client, "lifter@example.com", "test-pw-1234")

    response = set_name(client, "Lukas")

    assert response.status_code == 200
    assert greeting(client) == "Lukas"
    # Settings → Name prefills the saved name for the next edit.
    assert 'value="Lukas"' in client.get("/settings/name").text


def test_name_can_be_changed_again(client):
    register(client, "lifter@example.com", "test-pw-1234", name="Lukas")

    set_name(client, "Luki")

    assert greeting(client) == "Luki"


def test_name_is_trimmed_before_storage(client):
    register(client, "lifter@example.com", "test-pw-1234")

    set_name(client, "  Lukas  ")

    assert greeting(client) == "Lukas"


def test_overlong_name_is_rejected_at_both_entry_points(client):
    too_long = "x" * 61

    response = register(
        client, "lifter@example.com", "test-pw-1234", name=too_long
    )
    assert response.status_code in (400, 422)

    register(client, "lifter@example.com", "test-pw-1234")
    response = client.post("/profile/name", data={"name": too_long})
    assert response.status_code in (400, 422)
    assert greeting(client) == "lifter"


def test_name_is_rendered_inert_not_executed(client):
    register(client, "lifter@example.com", "test-pw-1234")

    set_name(client, "<script>alert(1)</script>")

    page = client.get("/").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_unicode_names_are_accepted(client):
    register(client, "lifter@example.com", "test-pw-1234", name="Łukas 攀")

    assert greeting(client) == "Łukas 攀"


def test_name_is_scoped_to_the_logged_in_user(client):
    register(client, "founder@example.com", "test-pw-1234", name="Founder")

    register_second_user(client)

    # Logged in as the friend now: founder's name must not leak through.
    assert greeting(client) == "friend"


def test_email_identity_display_is_unchanged_by_a_name(client):
    register(client, "lifter@example.com", "test-pw-1234", name="Lukas")

    # Today dropped its "Logged in as <email>" line (#149 -- it leaked the
    # device placeholder address on-device); Settings still shows it
    # (server build only).
    assert "Logged in as" not in client.get("/").text
    assert "lifter@example.com" in client.get("/settings").text
