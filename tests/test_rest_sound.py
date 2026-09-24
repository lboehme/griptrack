"""HTTP-seam tests for the S3 native rest bridge's server side (#148,
docs/adr/0015): the per-user **Rest sound** setting (persisted, bounded,
isolated per user) and the data attributes the rest step hands the
feature-detected `window.GripTrackNative.startRest(...)` call -- the rest
end as epoch milliseconds, the sound flag, and the notification's
title/detail/ready lines.

Since #151 the toggle lives in Settings → Rest alerts
(`POST /settings/rest-sound`, over the same `training_log.set_rest_sound`);
the rest step only reads the stored flag."""

import re
from datetime import datetime

import pytest

from tests.helpers import (
    complete_warmup,
    grip_type_id,
    log_max_test,
    login,
    register,
    register_second_user,
    save_focus_set,
)
from tests.test_session_play import play_page, rest_ends_at, step_kind

# Every test here reaches the rest step on the fixed 2026-07-04 session date,
# which must count as "today" (a past date never starts a rest).
pytestmark = pytest.mark.usefixtures("session_date_is_today")


def setup_resting_user(client):
    register(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    gid = grip_type_id(client, "half crimp")
    complete_warmup(client, gid, 20)
    return gid, save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))


def data_attr(page_text, name):
    m = re.search(rf'{name}="([^"]*)"', page_text)
    return m.group(1) if m else None


def post_sound(client, value, htmx=False):
    return client.post(
        "/settings/rest-sound",
        data={"rest_sound": value},
        headers={"HX-Request": "true"} if htmx else None,
        follow_redirects=False,
    )


def settings_switch(client):
    return data_attr(client.get("/settings").text, 'id="rest-sound-btn"[^>]*aria-checked')


# ---------- what the rest step hands the native bridge ----------


def test_rest_step_exposes_the_end_time_as_epoch_ms_matching_rest_ends_at(client):
    _, page = setup_resting_user(client)
    assert step_kind(page.text) == "rest"

    ends_at = datetime.fromisoformat(rest_ends_at(page.text))
    ends_at_ms = int(data_attr(page.text, "data-rest-ends-at-ms"))

    assert ends_at_ms == int(ends_at.timestamp() * 1000)


def test_rest_step_exposes_the_notification_title_detail_and_ready_line(client):
    _, page = setup_resting_user(client)

    # Set 1 of 3 committed -> resting before set 2; the next set's seed
    # weights are the ones just logged ("same load").
    assert data_attr(page.text, "data-rest-title") == "Rest · set 2 of 3 next"
    assert data_attr(page.text, "data-rest-detail") == "30 / 28 kg"
    assert data_attr(page.text, "data-rest-ready") == "Pull. Set 2 is ready"


def test_rest_sound_is_off_by_default(client):
    _, page = setup_resting_user(client)

    assert data_attr(page.text, "data-rest-sound") == "false"
    assert settings_switch(client) == "false"


def test_the_rest_step_no_longer_carries_the_sound_toggle(client):
    _, page = setup_resting_user(client)

    assert "/session/rest/sound" not in page.text
    assert 'id="rest-sound-btn"' not in page.text


# ---------- the Settings toggle: persistence, no-JS + htmx ----------


def test_turning_rest_sound_on_persists_and_answers_303_back_to_settings(client):
    setup_resting_user(client)

    response = post_sound(client, "on")
    assert response.status_code == 303
    assert response.headers["location"] == "/settings?saved=sound"

    page = play_page(client)
    assert step_kind(page.text) == "rest"
    assert data_attr(page.text, "data-rest-sound") == "true"
    assert settings_switch(client) == "true"

    post_sound(client, "off")
    assert data_attr(play_page(client).text, "data-rest-sound") == "false"


def test_rest_sound_toggle_answers_htmx_with_the_switch_and_a_toast_and_leaves_rest_running(client):
    _, page = setup_resting_user(client)
    before = rest_ends_at(page.text)

    response = post_sound(client, "on", htmx=True)

    assert response.status_code == 200
    assert 'aria-checked="true"' in response.text
    assert 'hx-swap-oob="innerHTML"' in response.text
    assert 'class="toast"' in response.text
    # Toggling the setting never touches the pending rest.
    assert rest_ends_at(play_page(client).text) == before


def test_rest_sound_rejects_anything_but_on_or_off(client):
    setup_resting_user(client)

    assert post_sound(client, "maybe").status_code == 400
    assert post_sound(client, "x" * 500).status_code == 422
    assert data_attr(play_page(client).text, "data-rest-sound") == "false"


def test_rest_sound_toggle_requires_login(client):
    assert post_sound(client, "on").status_code == 401


# ---------- isolation ----------


def test_rest_sound_is_per_user(client):
    gid, _ = setup_resting_user(client)
    post_sound(client, "on")

    register_second_user(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    complete_warmup(client, gid, 20)
    b_page = save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    # User B never inherits user A's setting...
    assert data_attr(b_page.text, "data-rest-sound") == "false"
    # ...and switching B's off again can't reach A's row.
    post_sound(client, "off")

    client.post("/logout")
    login(client, "lifter@example.com", "test-pw-1234")
    assert data_attr(play_page(client).text, "data-rest-sound") == "true"
