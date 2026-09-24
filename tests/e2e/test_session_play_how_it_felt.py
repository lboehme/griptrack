"""Browser-smoke spec for the "How did it feel?" disclosure, restored on
the play work-set step (issue #146 review item 1, replacing the pre-#146
tests/e2e/test_focus_how_it_felt.py): notes/deload/pain still autosave with
no submit step, tucked into a collapsed <details> below Set done. Broader
notes/deload/pain behavior (validation, per-user isolation, the
upsert-by-hand rule) is covered by the HTTP-seam tests in
tests/test_session_play.py -- this is just the Playwright spec confirming
the disclosure opens and a real browser change event still reaches the
server without a page reload."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_disclosure_opens_and_notes_autosave_without_a_reload(
    live_server, authenticated_page
):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    # A TrainingSession is created lazily on the first real write (see
    # training_log.start_or_get_session) -- commit a set first so it
    # exists for /session/update and /session/pain-report to find. A
    # non-final commit lands on the rest step; skip it to get back to the
    # work-set step's own disclosure.
    page.locator(".set-done-btn").click()
    page.get_by_role("button", name="Skip rest").click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()

    details = page.locator("#how-it-felt")
    notes = page.locator('textarea[name="notes"]')

    expect(details).not_to_have_js_property("open", True)
    expect(notes).not_to_be_visible()

    page.locator("#how-it-felt summary").click()
    expect(details).to_have_js_property("open", True)
    expect(notes).to_be_visible()

    notes.fill("Felt strong today.")
    notes.blur()

    page.locator('#pain-report-form input[name="hand"][value="left"]').check()
    severity = page.locator('#pain-report-form input[name="severity"]')
    severity.fill("1")
    severity.blur()

    expect(page.locator('#pain-reports-body tr[data-hand="left"]')).to_be_visible()

    # Reload -- no client-side state left, so this proves the POSTs above
    # actually reached /session/update and /session/pain-report and were
    # persisted, not just updated in the DOM.
    page.reload()
    page.locator("#how-it-felt summary").click()
    expect(page.locator('textarea[name="notes"]')).to_have_value("Felt strong today.")
    expect(page.locator('#pain-reports-body tr[data-hand="left"]')).to_contain_text("1")


def test_textarea_matches_dark_mode_background(live_server, authenticated_page):
    page = authenticated_page
    page.emulate_media(color_scheme="dark")

    start_session_play(page, live_server)
    advance_to_worksets(page)

    page.locator("#how-it-felt summary").click()
    notes = page.locator('textarea[name="notes"]')
    severity = page.locator('#pain-report-form input[name="severity"]')

    expect(notes).to_be_visible()
    notes_bg = notes.evaluate("el => window.getComputedStyle(el).backgroundColor")
    input_bg = severity.evaluate("el => window.getComputedStyle(el).backgroundColor")

    assert notes_bg == input_bg
    assert notes_bg != "rgb(255, 255, 255)"
