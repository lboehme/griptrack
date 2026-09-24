"""Browser-smoke spec for the session-play rest ring (#146, docs/adr/0014):
the countdown is always computed from the stored `rest_ends_at`, never a
decrementing client counter, so a reload resumes at the right remaining time
instead of restarting the clock."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_rest_countdown_resumes_from_stored_end_time_after_reload(
    live_server, authenticated_page
):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    # Commit set 1 (a non-final set with the default 3-set protocol) -- this
    # starts the rest step server-side (rest_ends_at = now + default rest).
    page.locator(".set-done-btn").click()
    rest_time = page.locator("#rest-ring-time")
    expect(rest_time).to_be_visible()
    first_reading = rest_time.inner_text()
    assert ":" in first_reading  # "m:ss", not yet "Pull"

    page.wait_for_timeout(2500)
    before_reload = rest_time.inner_text()
    before_seconds = int(before_reload.split(":")[0]) * 60 + int(before_reload.split(":")[1])

    # A fresh GET (simulating a reload / the app being killed and reopened)
    # must land back on the rest step with a countdown that has kept moving
    # forward from the *stored* end time, not restarted at the full duration.
    page.reload()
    rest_time = page.locator("#rest-ring-time")
    expect(rest_time).to_be_visible()
    after_reload = rest_time.inner_text()
    assert ":" in after_reload, f"Expected still resting, got {after_reload!r}"
    after_seconds = int(after_reload.split(":")[0]) * 60 + int(after_reload.split(":")[1])

    assert after_seconds <= before_seconds, (
        "Countdown after reload should not be later than before it "
        f"(before={before_seconds}s, after={after_seconds}s)"
    )
    # And it shouldn't have jumped back up to the full default duration.
    assert before_seconds - after_seconds < 30
