"""Browser-smoke spec for the Focus screen's rest countdown (issue #82 / #131):
a real client-side rest countdown seeded from TrainingProtocol.default_rest_seconds
with Screen Wake Lock so the device doesn't sleep mid-rest.
"""

from playwright.sync_api import expect

WAKE_LOCK_MOCK_SCRIPT = """
window.__wakeLockEvents = [];
window.__sentinels = [];
Object.defineProperty(navigator, 'wakeLock', {
    value: {
        request: async function (type) {
            window.__wakeLockEvents.push({ event: "request", type: type });
            var sentinel = {
                type: type,
                released: false,
                _listeners: {},
                addEventListener: function (name, fn) {
                    this._listeners[name] = this._listeners[name] || [];
                    this._listeners[name].push(fn);
                },
                release: async function () {
                    this.released = true;
                    window.__wakeLockEvents.push({ event: "release", type: this.type });
                    var handlers = this._listeners["release"] || [];
                    for (var i = 0; i < handlers.length; i++) {
                        handlers[i]();
                    }
                }
            };
            window.__sentinels.push(sentinel);
            return sentinel;
        }
    },
    configurable: true,
    writable: true
});
"""


def _setup_session(live_server, page):
    for hand in ("left", "right"):
        page.goto(f"{live_server}/max-tests")
        form = page.locator('form[action="/max-tests"]')
        form.locator(f'input[name="hand"][value="{hand}"]').check()
        form.locator("select.grip-select").select_option(label="half crimp")
        form.locator('input[name="edge_mm"]').fill("20")
        form.locator('input[name="weight"]').fill("40")
        form.locator('button[type="submit"]').click()

    page.goto(f"{live_server}/session/new")
    page.locator(".grip-select").select_option(label="half crimp")
    page.locator('input[name="edge_mm"]').fill("20")
    page.get_by_role("button", name="Start warmup").click()
    page.get_by_role("link", name="Continue to work sets").click()


def test_committing_a_set_starts_the_rest_countdown_and_skip_ends_it(
    live_server, authenticated_page
):
    page = authenticated_page
    _setup_session(live_server, page)

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")
    rest_time = page.locator("#rest-countdown-time")

    expect(rest_countdown).to_be_hidden()

    set_done_btn.click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()

    # Committing the set starts a visible countdown and hides the button.
    expect(rest_countdown).to_be_visible()
    expect(rest_time).to_have_text("3:00")
    expect(set_done_btn).to_be_hidden()

    # Skip ends the rest immediately and restores "Set done" for set 2.
    page.locator("#rest-skip-btn").click()
    expect(rest_countdown).to_be_hidden()
    expect(set_done_btn).to_be_visible()
    expect(set_done_btn).to_have_text("Set done")


def test_rest_countdown_uses_user_configured_duration(
    live_server, authenticated_page
):
    page = authenticated_page

    # Configure custom rest duration (120s = 2:00)
    page.goto(f"{live_server}/profile")
    page.locator('input[name="default_rest_seconds"]').fill("120")
    page.locator('form[action="/profile/protocol"] button[type="submit"]').click()
    expect(page.locator('input[name="default_rest_seconds"]')).to_have_value("120")

    _setup_session(live_server, page)

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")
    rest_time = page.locator("#rest-countdown-time")

    expect(rest_countdown).to_be_hidden()

    set_done_btn.click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()

    expect(rest_countdown).to_be_visible()
    expect(rest_time).to_have_text("2:00")
    expect(set_done_btn).to_be_hidden()


def test_rest_countdown_acquires_and_releases_screen_wake_lock(
    live_server, authenticated_page
):
    page = authenticated_page
    page.add_init_script(WAKE_LOCK_MOCK_SCRIPT)
    _setup_session(live_server, page)

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")

    # Before commit, no wake lock requested
    events = page.evaluate("() => window.__wakeLockEvents")
    assert events == []

    # Commit set 1 -> rest starts, wake lock requested
    set_done_btn.click()
    expect(rest_countdown).to_be_visible()

    events = page.evaluate("() => window.__wakeLockEvents")
    assert events == [{"event": "request", "type": "screen"}]

    # Skip rest -> rest ends, wake lock released
    page.locator("#rest-skip-btn").click()
    expect(rest_countdown).to_be_hidden()

    events = page.evaluate("() => window.__wakeLockEvents")
    assert events == [
        {"event": "request", "type": "screen"},
        {"event": "release", "type": "screen"},
    ]


def test_rest_countdown_releases_wake_lock_on_entering_edit_mode(
    live_server, authenticated_page
):
    page = authenticated_page
    page.add_init_script(WAKE_LOCK_MOCK_SCRIPT)
    _setup_session(live_server, page)

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")

    # Commit set 1 -> rest starts
    set_done_btn.click()
    expect(rest_countdown).to_be_visible()

    events = page.evaluate("() => window.__wakeLockEvents")
    assert events == [{"event": "request", "type": "screen"}]

    # Clicking completed set 1 enters edit mode -> rest countdown stops and wake lock releases
    page.locator('.completed-row[data-set="1"]').click()
    expect(rest_countdown).to_be_hidden()
    expect(page.locator(".focus-pill-editing")).to_be_visible()

    events = page.evaluate("() => window.__wakeLockEvents")
    assert events == [
        {"event": "request", "type": "screen"},
        {"event": "release", "type": "screen"},
    ]


def test_rest_countdown_reacquires_wake_lock_on_visibility_change_if_active(
    live_server, authenticated_page
):
    page = authenticated_page
    page.add_init_script(WAKE_LOCK_MOCK_SCRIPT)
    _setup_session(live_server, page)

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")

    set_done_btn.click()
    expect(rest_countdown).to_be_visible()

    events = page.evaluate("() => window.__wakeLockEvents")
    assert len(events) == 1
    assert events[0] == {"event": "request", "type": "screen"}

    # Simulate system releasing lock when page becomes hidden
    page.evaluate("""() => {
        if (window.__sentinels.length > 0) {
            window.__sentinels[0].release();
        }
    }""")
    events = page.evaluate("() => window.__wakeLockEvents")
    assert len(events) == 2
    assert events[1] == {"event": "release", "type": "screen"}

    # Page becomes visible again while rest countdown is still running
    page.evaluate("""() => {
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
    }""")

    # Wake lock is re-acquired
    events = page.evaluate("() => window.__wakeLockEvents")
    assert len(events) == 3
    assert events[2] == {"event": "request", "type": "screen"}


def test_rest_countdown_works_gracefully_without_wake_lock_support(
    live_server, authenticated_page
):
    page = authenticated_page
    # Omit wakeLock from navigator
    page.add_init_script("""
        Object.defineProperty(navigator, 'wakeLock', { value: undefined, configurable: true, writable: true });
    """)
    _setup_session(live_server, page)

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")
    rest_time = page.locator("#rest-countdown-time")

    set_done_btn.click()
    expect(rest_countdown).to_be_visible()
    expect(rest_time).to_have_text("3:00")

    page.locator("#rest-skip-btn").click()
    expect(rest_countdown).to_be_hidden()
    expect(set_done_btn).to_be_visible()

