"""HTTP-seam tests for the S3 native rest bridge's server side (#148,
docs/adr/0015): the per-user **Rest sound** setting (persisted, bounded,
isolated per user) and the data attributes the rest step hands the
feature-detected `window.GripTrackNative.startRest(...)` call -- the rest
end as epoch milliseconds, the sound flag, and the notification's
title/detail/ready lines."""

import re
from datetime import datetime

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


def post_sound(client, gid, value, htmx=False):
    return client.post(
        "/session/rest/sound",
        data={"grip_type_id": gid, "edge_mm": 20, "date": "2026-07-04", "rest_sound": value},
        headers={"HX-Request": "true"} if htmx else None,
        follow_redirects=False,
    )


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
    assert 'aria-pressed="false"' in page.text


# ---------- the sound toggle: persistence, no-JS + htmx ----------


def test_turning_rest_sound_on_persists_and_answers_303_back_to_play(client):
    gid, _ = setup_resting_user(client)

    response = post_sound(client, gid, "on")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/session/play?")

    page = play_page(client)
    assert step_kind(page.text) == "rest"
    assert data_attr(page.text, "data-rest-sound") == "true"

    post_sound(client, gid, "off")
    assert data_attr(play_page(client).text, "data-rest-sound") == "false"


def test_rest_sound_toggle_answers_an_htmx_fragment_and_leaves_rest_running(client):
    gid, page = setup_resting_user(client)
    before = rest_ends_at(page.text)

    response = post_sound(client, gid, "on", htmx=True)

    assert response.status_code == 200
    assert step_kind(response.text) == "rest"
    assert data_attr(response.text, "data-rest-sound") == "true"
    # Toggling the setting never touches the pending rest.
    assert rest_ends_at(response.text) == before


def test_rest_sound_rejects_anything_but_on_or_off(client):
    gid, _ = setup_resting_user(client)

    assert post_sound(client, gid, "maybe").status_code == 400
    assert post_sound(client, gid, "x" * 500).status_code == 422
    assert data_attr(play_page(client).text, "data-rest-sound") == "false"


# ---------- isolation ----------


def test_rest_sound_is_per_user(client):
    gid, _ = setup_resting_user(client)
    post_sound(client, gid, "on")

    register_second_user(client)
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "42.5")
    log_max_test(client, "right", "half crimp", 20, "2026-07-01", "40")
    complete_warmup(client, gid, 20)
    b_page = save_focus_set(client, 1, left=(30, 5, 7), right=(28, 5, 7))
    # User B never inherits user A's setting...
    assert data_attr(b_page.text, "data-rest-sound") == "false"
    # ...and switching B's off again can't reach A's row.
    post_sound(client, gid, "off")

    client.post("/logout")
    login(client, "lifter@example.com", "test-pw-1234")
    assert data_attr(play_page(client).text, "data-rest-sound") == "true"
