"""Browser-smoke spec for the S3 native rest bridge (#148, docs/adr/0015).

steppers.js calls `window.GripTrackNative.startRest / stopRest /
setKeepScreenOn` only when the Android shell has injected that object; a
recording stub stands in for it here. Without the bridge (the plain browser
build) nothing must error, and the Screen Wake Lock API is the fallback for
keeping the screen on."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play

RECORDING_BRIDGE = """
window.__nativeCalls = [];
window.GripTrackNative = {
  startRest: function (endsAtMs, title, detail, sound, ready) {
    window.__nativeCalls.push(["startRest", endsAtMs, title, detail, sound, ready]);
  },
  stopRest: function () { window.__nativeCalls.push(["stopRest"]); },
  setKeepScreenOn: function (on) { window.__nativeCalls.push(["setKeepScreenOn", on]); },
};
"""

RECORDING_WAKE_LOCK = """
window.__wakeLockRequests = [];
window.__wakeLockReleases = 0;
Object.defineProperty(navigator, "wakeLock", {
  configurable: true,
  value: {
    request: function (type) {
      window.__wakeLockRequests.push(type);
      return Promise.resolve({
        released: false,
        release: function () { window.__wakeLockReleases += 1; this.released = true; return Promise.resolve(); },
        addEventListener: function () {},
      });
    },
  },
});
"""


def calls(page):
    return page.evaluate("window.__nativeCalls")


def start_rest_calls(page):
    return [c for c in calls(page) if c[0] == "startRest"]


def wait_for_more_start_rest_calls(page, count_before, timeout_ms=5000):
    # Polled from Python: the app's CSP (no 'unsafe-eval') blocks
    # page.wait_for_function's string predicates.
    waited = 0
    while len(start_rest_calls(page)) <= count_before and waited < timeout_ms:
        page.wait_for_timeout(100)
        waited += 100
    assert len(start_rest_calls(page)) > count_before, "startRest was not re-called"


def reach_rest(page, live_server):
    start_session_play(page, live_server)
    advance_to_worksets(page)
    page.locator(".set-done-btn").click()  # non-final commit -> rest step
    expect(page.locator("#rest-ring-time")).to_be_visible()


def rest_ends_at_ms(page):
    return int(page.locator("#rest-step").get_attribute("data-rest-ends-at-ms"))


def test_keep_screen_on_is_requested_on_play(live_server, authenticated_page):
    page = authenticated_page
    page.add_init_script(RECORDING_BRIDGE)

    start_session_play(page, live_server)
    advance_to_worksets(page)

    assert ["setKeepScreenOn", True] in calls(page)


def test_start_rest_gets_the_server_end_time_and_notification_text(
    live_server, authenticated_page
):
    page = authenticated_page
    page.add_init_script(RECORDING_BRIDGE)
    reach_rest(page, live_server)

    started = start_rest_calls(page)
    assert started, "startRest was never called on the rest step"
    _, ends_at_ms, title, detail, sound, ready = started[-1]
    assert ends_at_ms == rest_ends_at_ms(page)
    assert title == "Rest · set 2 of 3 next"
    assert detail.endswith(" kg") and " / " in detail
    assert sound is False
    assert ready == "Pull. Set 2 is ready"


def test_plus_30_s_reschedules_start_rest_30000_ms_later(live_server, authenticated_page):
    page = authenticated_page
    page.add_init_script(RECORDING_BRIDGE)
    reach_rest(page, live_server)
    first_ms = start_rest_calls(page)[-1][1]
    count_before = len(start_rest_calls(page))

    page.locator("#rest-extend-btn").click()
    wait_for_more_start_rest_calls(page, count_before)

    assert start_rest_calls(page)[-1][1] == first_ms + 30000
    # Re-arming cancels the previous alarm first, so a refused start can't
    # leave the old one to fire 30 s early (PR #154 review MUST-FIX 7).
    recorded = calls(page)
    last_start = max(i for i, c in enumerate(recorded) if c[0] == "startRest")
    assert recorded[last_start - 1] == ["stopRest"]


def test_settings_sound_toggle_passes_sound_true_to_start_rest(live_server, authenticated_page):
    """#151: the Rest sound switch moved from the rest step to Settings →
    Rest alerts; the rest step still hands the stored flag to startRest."""
    page = authenticated_page
    page.add_init_script(RECORDING_BRIDGE)
    page.goto(f"{live_server}/settings")
    switch = page.locator("#rest-sound-btn")
    expect(switch).to_have_attribute("aria-checked", "false")

    switch.click()
    expect(page.locator("#rest-sound-btn")).to_have_attribute("aria-checked", "true")
    expect(page.locator(".toast")).to_be_visible()

    reach_rest(page, live_server)
    assert start_rest_calls(page), "startRest was never called on the rest step"
    assert start_rest_calls(page)[-1][4] is True
    expect(page.locator("#rest-sound-btn")).to_have_count(0)


def test_skip_rest_calls_stop_rest(live_server, authenticated_page):
    page = authenticated_page
    page.add_init_script(RECORDING_BRIDGE)
    reach_rest(page, live_server)
    page.evaluate("window.__nativeCalls = []")

    page.get_by_role("button", name="Skip rest").click()
    expect(page.locator(".hand-card").first).to_be_visible()

    assert ["stopRest"] in calls(page)
    assert start_rest_calls(page) == []


def test_keep_screen_on_is_released_on_the_summary(live_server, authenticated_page):
    page = authenticated_page
    page.add_init_script(RECORDING_BRIDGE)
    start_session_play(page, live_server)
    advance_to_worksets(page)

    for set_number in range(1, 4):
        page.locator(".set-done-btn").click()
        if set_number < 3:
            page.get_by_role("button", name="Skip rest").click()
    expect(page.locator("#play-step[data-step=\"summary\"]")).to_be_visible()

    keep_on = [c for c in calls(page) if c[0] == "setKeepScreenOn"]
    assert keep_on[-1] == ["setKeepScreenOn", False]


def test_no_bridge_nothing_errors_and_wake_lock_is_the_fallback(
    live_server, authenticated_page
):
    """No window.GripTrackNative at all (the plain browser build): the rest
    countdown and steppers work exactly the same with no unhandled
    exception, and the Screen Wake Lock API keeps the screen on instead."""
    page = authenticated_page
    page.add_init_script(RECORDING_WAKE_LOCK)

    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    reach_rest(page, live_server)
    page.locator("#rest-extend-btn").click()
    page.get_by_role("button", name="Skip rest").click()
    expect(page.locator(".hand-card").first).to_be_visible()

    assert errors == []
    assert "screen" in page.evaluate("window.__wakeLockRequests")


def test_wake_lock_is_not_used_when_the_bridge_exists(live_server, authenticated_page):
    page = authenticated_page
    page.add_init_script(RECORDING_WAKE_LOCK)
    page.add_init_script(RECORDING_BRIDGE)

    start_session_play(page, live_server)
    advance_to_worksets(page)

    assert page.evaluate("window.__wakeLockRequests") == []
