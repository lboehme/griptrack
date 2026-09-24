"""Device sign-in and first run in the WebView build (#145, ADR-0013).

`webview_client` (tests/conftest.py) builds the app with
GRIPTRACK_WEBVIEW_BUILD=1 and a known GRIPTRACK_DEVICE_TOKEN
(WEBVIEW_DEVICE_TOKEN); the plain `client` fixture is the unchanged server
build, used here to prove nothing regressed there.
"""

from tests.conftest import WEBVIEW_DEVICE_TOKEN
from tests.helpers import register


def complete_first_run(client, name="Owner", unit_pref="kg", hand_order_pref="alternating"):
    # First run is only reachable after the shell's device-token exchange
    # (ADR-0013): /device-login with no user yet grants the bootstrap step.
    device_login(client)
    return client.post(
        "/welcome",
        data={"name": name, "unit_pref": unit_pref, "hand_order_pref": hand_order_pref},
        follow_redirects=False,
    )


def device_login(client, token=WEBVIEW_DEVICE_TOKEN, next=None):
    data = {"token": token}
    if next is not None:
        data["next"] = next
    return client.post("/device-login", data=data, follow_redirects=False)


# --- Server build: unaffected -----------------------------------------


def test_device_login_is_not_registered_in_the_server_build(client):
    response = client.post("/device-login", data={"token": "anything"})
    assert response.status_code == 404


def test_welcome_is_not_registered_in_the_server_build(client):
    assert client.get("/welcome").status_code == 404
    assert client.post("/welcome", data={}).status_code == 404
    assert client.get("/welcome/plates").status_code == 404
    assert client.get("/welcome/test").status_code == 404


def test_server_build_login_page_still_renders(client):
    # GET /login must not redirect in the server build.
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 200


def test_server_build_still_requires_a_password(client):
    register(client, "founder@example.com", "s3cret-pw")
    client.post("/logout")

    wrong = client.post(
        "/login",
        data={"email": "founder@example.com", "password": "wrong"},
        follow_redirects=False,
    )
    assert wrong.status_code != 303


# --- WebView build: first run -------------------------------------------


def test_root_redirects_to_welcome_before_first_run(webview_client):
    response = webview_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/welcome"


def test_login_and_register_redirect_to_welcome_before_first_run(webview_client):
    login = webview_client.get("/login", follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/welcome"

    # /register is unregistered in this build entirely.
    assert webview_client.get("/register").status_code == 404
    assert webview_client.post("/register", data={}).status_code == 404


def test_login_redirects_home_once_a_user_already_exists(webview_client):
    complete_first_run(webview_client)

    response = webview_client.get("/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_first_run_creates_the_device_user_and_signs_in(webview_client):
    response = complete_first_run(webview_client, name="Lukas", unit_pref="lbs",
                                   hand_order_pref="sequential")

    assert response.status_code == 303
    assert response.headers["location"] == "/welcome/plates"
    set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()

    home = webview_client.get("/")
    assert home.status_code == 200
    assert "Lukas" in home.text


def test_first_run_seeds_default_plate_inventory(webview_client):
    complete_first_run(webview_client, unit_pref="kg")

    plates_page = webview_client.get("/welcome/plates")
    assert plates_page.status_code == 200
    assert "10.0" in plates_page.text  # one of the seeded kg denominations


def test_first_run_screen_three_links_to_guided_test_and_skip(webview_client):
    complete_first_run(webview_client)

    test_screen = webview_client.get("/welcome/test")
    assert test_screen.status_code == 200
    assert 'href="/progress/maxes"' in test_screen.text
    assert 'href="/"' in test_screen.text


def test_welcome_redirects_to_home_once_a_user_already_exists(webview_client):
    complete_first_run(webview_client)

    response = webview_client.get("/welcome", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_first_run_is_idempotent_against_double_submit(webview_client):
    first = complete_first_run(webview_client, name="Owner")
    assert first.status_code == 303

    # A refresh/resubmit of screen 1 after the device user already exists
    # must not create a second user, and must not error.
    second = complete_first_run(webview_client, name="Someone Else")
    assert second.status_code in (303, 403)

    # Still the original single user -- a second user would either rename
    # the greeting or (since email is unique) have failed loudly instead
    # of being swallowed as "already set up".
    home = webview_client.get("/")
    assert "Owner" in home.text
    assert "Someone Else" not in home.text


def test_first_run_rejects_invalid_unit_pref(webview_client):
    device_login(webview_client)
    response = webview_client.post(
        "/welcome",
        data={"name": "Owner", "unit_pref": "stones", "hand_order_pref": "alternating"},
    )
    assert response.status_code == 400


def test_first_run_rejects_invalid_hand_order_pref(webview_client):
    device_login(webview_client)
    response = webview_client.post(
        "/welcome",
        data={"name": "Owner", "unit_pref": "kg", "hand_order_pref": "bogus"},
    )
    assert response.status_code == 400


def test_first_run_bounds_the_name_length(webview_client):
    device_login(webview_client)
    response = webview_client.post(
        "/welcome",
        data={"name": "x" * 5000, "unit_pref": "kg", "hand_order_pref": "alternating"},
    )
    assert response.status_code == 422


def test_welcome_plates_and_test_require_a_signed_in_user(webview_client):
    assert webview_client.get("/welcome/plates").status_code == 401
    assert webview_client.get("/welcome/test").status_code == 401


# --- WebView build: device sign-in ---------------------------------------


def test_device_login_signs_in_after_first_run(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    response = device_login(webview_client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "secure" not in set_cookie.lower()  # non-production, plain http

    home = webview_client.get("/")
    assert home.status_code == 200


def test_device_login_redirects_to_welcome_before_first_run(webview_client):
    response = device_login(webview_client)

    assert response.status_code == 303
    assert response.headers["location"] == "/welcome"
    # The cookie carries only the first-run grant -- it is not a sign-in.
    assert webview_client.get("/profile").status_code == 401


def test_device_login_rejects_a_wrong_token(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    response = device_login(webview_client, token="not-the-real-token")

    assert response.status_code == 403
    assert "session=" not in response.headers.get("set-cookie", "")


def test_device_login_rejects_a_missing_token(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    response = webview_client.post("/device-login", data={}, follow_redirects=False)

    assert response.status_code == 403


def test_device_login_is_rate_limited(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    for _ in range(10):
        assert device_login(webview_client, token="wrong").status_code == 403

    blocked = device_login(webview_client, token="wrong")
    assert blocked.status_code == 429

    # Even the right token is blocked while rate-limited.
    assert device_login(webview_client).status_code == 429


def test_device_login_honors_a_safe_next_path(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    response = device_login(webview_client, next="/dashboard")

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_device_login_ignores_an_unsafe_next_path(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    for unsafe in ("//evil.example/steal", "http://evil.example/steal", "javascript:alert(1)", "relative/path"):
        response = device_login(webview_client, next=unsafe)
        assert response.status_code == 303
        assert response.headers["location"] == "/", f"unsafe next {unsafe!r} was honored"


# --- WebView build: hidden/removed server-era UI and routes --------------


def test_register_invites_and_admin_reset_are_404_in_webview_build(webview_client):
    complete_first_run(webview_client)

    assert webview_client.get("/register").status_code == 404
    assert webview_client.post("/register", data={}).status_code == 404
    assert webview_client.post("/invites").status_code == 404
    assert webview_client.post(
        "/admin/reset-password", data={"email": "x@example.com", "new_password": "whatever1"}
    ).status_code == 404


def test_logout_button_is_hidden_in_webview_build(webview_client):
    complete_first_run(webview_client)

    home = webview_client.get("/")
    assert 'action="/logout"' not in home.text


def test_login_and_register_links_are_hidden_from_the_anonymous_home_page(webview_client):
    # A second, cookie-less "process" hitting the loopback server after
    # first run sees the anonymous home page (no data leaks -- see the
    # no-cookie-no-data test below), but must not be offered a login or
    # register link that leads nowhere useful in this build.
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    anonymous_home = webview_client.get("/")
    assert anonymous_home.status_code == 200
    assert 'href="/login"' not in anonymous_home.text
    assert 'href="/register"' not in anonymous_home.text


def test_invite_and_admin_grip_type_cards_are_hidden_from_settings(webview_client):
    complete_first_run(webview_client)

    settings = webview_client.get("/settings")
    assert settings.status_code == 200
    assert 'action="/invites"' not in settings.text
    assert 'action="/grip-types"' not in settings.text
    assert 'href="/settings/admin"' not in settings.text
    # ...and the Admin page itself doesn't exist in this build.
    assert webview_client.get("/settings/admin").status_code == 404


# --- Isolation: no token / no cookie means no data access -----------------


def test_no_cookie_requests_cannot_read_or_write_data_in_webview_build(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    # A second app on the phone can still reach the loopback port, but
    # without a valid session cookie (which only device sign-in grants) it
    # gets nothing.
    assert webview_client.get("/profile").status_code == 401
    assert webview_client.get("/dashboard").status_code == 401
    assert webview_client.get("/history").status_code == 401
    assert webview_client.get("/profile/export").status_code == 401
    assert webview_client.post(
        "/climbs", data={"date": "2026-07-04", "grade": "V5", "style": "flash"}
    ).status_code == 401


def test_wrong_device_token_cannot_read_or_write_data(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    device_login(webview_client, token="not-the-real-token")  # 403, no cookie set

    assert webview_client.get("/profile").status_code == 401
    assert webview_client.get("/dashboard").status_code == 401


# --- First run is gated on the device token (Copilot review, PR #153) ---


def test_first_run_post_without_a_device_token_exchange_is_refused(webview_client):
    # Another app on the phone can reach 127.0.0.1 but can't read the
    # device token -- it must not be able to claim a fresh install.
    response = webview_client.post(
        "/welcome",
        data={"name": "Intruder", "unit_pref": "kg", "hand_order_pref": "alternating"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "session=" not in response.headers.get("set-cookie", "")
    device_login(webview_client)
    assert webview_client.get("/welcome").status_code == 200  # still unclaimed


def test_first_run_page_without_a_device_token_exchange_is_refused(webview_client):
    assert webview_client.get("/welcome", follow_redirects=False).status_code == 403


def test_wrong_device_token_before_first_run_is_rejected(webview_client):
    response = device_login(webview_client, token="not-the-real-token")

    assert response.status_code == 403
    assert webview_client.get("/welcome", follow_redirects=False).status_code == 403


def test_correct_token_before_first_run_is_not_counted_as_a_failure(webview_client):
    for _ in range(10):
        response = device_login(webview_client)
        assert response.status_code == 303
        assert response.headers["location"] == "/welcome"


def test_first_run_bootstrap_grant_is_spent_after_the_user_is_created(webview_client):
    complete_first_run(webview_client)
    webview_client.cookies.clear()

    response = webview_client.post(
        "/welcome",
        data={"name": "Again", "unit_pref": "kg", "hand_order_pref": "alternating"},
        follow_redirects=False,
    )

    assert response.status_code in (303, 403)
    assert "session=" not in response.headers.get("set-cookie", "")
