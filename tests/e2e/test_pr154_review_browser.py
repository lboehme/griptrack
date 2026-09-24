"""Browser-only fixes from the PR #154 review: summary notes survive an
immediate Finish (keepalive autosave), client-date.js never overwrites a
date the user already changed on an unrelated htmx swap, and the ＋ Log
sheet shows a human message instead of raw FastAPI 422 JSON."""

from playwright.sync_api import expect

from tests.e2e.test_session_play_summary import run_to_summary

RECORDING_FETCH = """
window.__fetchInits = [];
(function () {
  var original = window.fetch;
  window.fetch = function (url, init) {
    window.__fetchInits.push({url: String(url), keepalive: !!(init && init.keepalive)});
    return original.apply(this, arguments);
  };
})();
"""


def test_summary_autosave_uses_keepalive_so_finish_cannot_abort_it(
    live_server, authenticated_page
):
    page = authenticated_page
    page.add_init_script(RECORDING_FETCH)
    run_to_summary(page, live_server)
    summary_url = page.url

    notes = page.locator('textarea[name="notes"]')
    notes.fill("Typed right before Finish.")
    notes.blur()
    page.locator(".summary-finish-btn").click()
    page.wait_for_url(f"{live_server}/")

    page.goto(summary_url)
    expect(page.locator('textarea[name="notes"]')).to_have_value("Typed right before Finish.")


def test_summary_autosave_fetch_is_keepalive(live_server, authenticated_page):
    page = authenticated_page
    page.add_init_script(RECORDING_FETCH)
    run_to_summary(page, live_server)

    notes = page.locator('textarea[name="notes"]')
    notes.fill("x")
    notes.blur()
    page.wait_for_timeout(200)

    inits = page.evaluate("window.__fetchInits")
    updates = [i for i in inits if i["url"].endswith("/session/update")]
    assert updates and all(i["keepalive"] for i in updates)


def test_a_date_the_user_changed_survives_an_unrelated_htmx_swap(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/progress/maxes")
    date_input = page.locator('input[type="date"][name="date"]').first
    date_input.fill("2026-01-02")

    page.locator(".tabbar-log").click()  # htmx swaps the ＋ sheet in
    expect(page.locator(".log-sheet")).to_be_visible()

    expect(date_input).to_have_value("2026-01-02")


def test_log_sheet_shows_a_human_message_for_a_422(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/")
    page.locator(".tabbar-log").click()
    page.locator('label.grade-chip:has(input[value="7A"])').click()
    # Corrupt a hidden field so the server answers FastAPI's 422 JSON.
    page.evaluate(
        "document.querySelector('.sheet-climb input[name=\"today\"]').value = 'not-a-date'"
    )
    page.locator(".sheet-climb .sheet-submit").click()

    error = page.locator("#sheet-error")
    expect(error).to_be_visible()
    expect(error).not_to_contain_text("detail")
    expect(error).not_to_contain_text("{")
    expect(error).to_contain_text("try again")
