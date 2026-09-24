"""Browser-smoke spec for the S3 native-bridge hooks steppers.js calls
(docs/adr/0015, session play issue #146 review item 4): startRest,
stopRest and setKeepScreenOn are feature-detected -- called when
window.GripTrackNative exists (the future Android WebView build), and a
silent no-op on the plain browser build where it doesn't."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_native_bridge_hooks_are_called_when_stubbed(live_server, authenticated_page):
    page = authenticated_page

    # Install a recording stub before any page script runs, so steppers.js
    # picks it up on its first DOMContentLoaded/htmx:afterSettle pass.
    page.add_init_script(
        """
        window.__nativeCalls = [];
        window.GripTrackNative = {
          startRest: function (info) { window.__nativeCalls.push(["startRest", info]); },
          stopRest: function () { window.__nativeCalls.push(["stopRest"]); },
          setKeepScreenOn: function (on) { window.__nativeCalls.push(["setKeepScreenOn", on]); },
        };
        """
    )

    start_session_play(page, live_server)
    advance_to_worksets(page)

    calls = page.evaluate("window.__nativeCalls")
    assert ["setKeepScreenOn", True] in calls

    page.locator(".set-done-btn").click()  # non-final commit -> rest step
    expect(page.locator("#rest-ring-time")).to_be_visible()

    calls = page.evaluate("window.__nativeCalls")
    assert any(c[0] == "startRest" for c in calls)


def test_page_works_normally_with_no_native_bridge_present(live_server, authenticated_page):
    """No window.GripTrackNative at all (the plain browser build) -- the
    rest countdown and steppers must work exactly the same, with no
    unhandled exception from the feature-detected calls."""
    page = authenticated_page

    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    start_session_play(page, live_server)
    advance_to_worksets(page)
    page.locator(".set-done-btn").click()

    assert "window.GripTrackNative" not in "".join(errors)
    assert errors == []
