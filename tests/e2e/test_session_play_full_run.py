"""One full warmup-to-last-set browser run through /session/play (#146):
proves the whole step chain -- warmup rung -> ... -> work set -> rest ->
work set -> ... -> summary -- actually works end to end in a real browser,
not just at the HTTP seam."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_full_session_from_warmup_through_last_set(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)

    # Warmup: click "Rung done" until the work-set step's hand cards appear.
    advance_to_worksets(page)
    expect(page.locator(".hand-card")).to_have_count(2)

    # Default protocol is 3 work sets. Commit each; after a non-final set,
    # the server sends the rest step -- Skip it to reach the next set.
    for set_number in range(1, 4):
        expect(page.locator(".set-done-btn")).to_be_visible()
        page.locator(".set-done-btn").click()

        if set_number < 3:
            skip_btn = page.get_by_role("button", name="Skip rest")
            expect(skip_btn).to_be_visible()
            skip_btn.click()

    # The final set's commit skips rest and goes straight to the summary.
    expect(page.get_by_text("Session done")).to_be_visible()
