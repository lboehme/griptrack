"""Browser-smoke specs ported from the pre-#146 test_focus_review_fixes.py
(session play, issue #146 review item 4). The client-appended-COMPLETED-row
bug (href="#") no longer applies -- session play never appends a row client
side, every step (including the completed list) is server-rendered -- so
that one spec is dropped; the other three real client-behavior bugs it
guarded against are still real risks in the new steppers.js and are ported
here."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_a_rejected_set_commit_surfaces_an_error(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    expect(page.locator(".play-overline")).to_contain_text("Work set 1")

    # Force the server to reject the commit; the UI must not fail silently.
    page.route(
        "**/session/set",
        lambda route: route.fulfill(status=400, body="Weight out of range."),
    )
    page.locator(".set-done-btn").click()

    error = page.locator("#set-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Weight out of range.")
    # Did not advance -- the user stays on set 1 to fix and retry.
    expect(page.locator(".play-overline")).to_contain_text("Work set 1")


def test_weight_stepper_cannot_walk_down_onto_the_zero_rung(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    minus_btn = page.locator('.stepper-minus[data-field="weight"][data-hand="left"]')
    display = page.locator('[data-role="weight-display"][data-hand="left"]')

    for _ in range(40):
        minus_btn.click()

    value = float(display.inner_text())
    assert value > 0, value


def _remove_all_plates(page, live_server):
    """Tap every plate on Settings → Plates until it wraps to zero (#151:
    tap-to-count replaced the per-plate count selects)."""
    page.goto(f"{live_server}/settings/plates")
    for plate in page.locator("button.plate").all():
        count = plate.locator(".plate-count")
        while count.get_attribute("data-count") != "0":
            before = count.get_attribute("data-count")
            plate.click()
            expect(count).not_to_have_attribute("data-count", before)
    expect(page.locator(".plate-summary")).to_contain_text("No plates yet")


def test_an_empty_ladder_falls_back_to_free_weight_entry(live_server, authenticated_page):
    page = authenticated_page
    _remove_all_plates(page, live_server)
    start_session_play(page, live_server)
    advance_to_worksets(page)

    raw_input = page.locator('.raw-input[data-role="weight-input"][data-hand="left"]')
    expect(raw_input).to_be_visible()
    expect(
        page.locator('.stepper-plus[data-field="weight"][data-hand="left"]')
    ).to_be_hidden()

    raw_input.fill("32.5")
    page.locator('.raw-input[data-role="weight-input"][data-hand="right"]').fill("32.5")
    page.locator(".set-done-btn").click()

    # A non-final set commit lands on the rest step; skip it to see the
    # completed row.
    page.get_by_role("button", name="Skip rest").click()
    row = page.locator('.completed-row[data-set="1"]')
    expect(row).to_be_visible()
    expect(row).to_contain_text("32.5")
