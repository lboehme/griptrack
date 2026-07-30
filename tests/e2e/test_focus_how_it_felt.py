"""Browser-smoke spec for the "How did it feel?" disclosure (issue #81):
notes/deload/pain still autosave with no submit step once they're tucked
into a collapsed <details> below the COMPLETED list. Broader notes/deload/
pain behavior (validation, per-user isolation, the upsert-by-hand rule) is
covered by the HTTP-seam tests in tests/test_worksets.py -- this is just
the one Playwright spec confirming the disclosure opens and a real browser
change event still reaches the server without a page reload."""

from playwright.sync_api import expect


def test_disclosure_opens_and_notes_autosave_without_a_reload(
    live_server, authenticated_page
):
    page = authenticated_page

    for hand in ("left", "right"):
        page.goto(f"{live_server}/max-tests")
        form = page.locator('form[action="/max-tests"]')
        form.locator('select[name="hand"]').select_option(hand)
        form.locator("select.grip-select").select_option(label="half crimp")
        form.locator('input[name="edge_mm"]').fill("20")
        form.locator('input[name="weight"]').fill("40")
        form.locator('button[type="submit"]').click()

    page.goto(f"{live_server}/session/new")
    page.locator(".grip-select").select_option(label="half crimp")
    page.locator('input[name="edge_mm"]').fill("20")
    page.get_by_role("button", name="Start warmup").click()
    page.get_by_role("link", name="Continue to work sets").click()

    # A TrainingSession is created lazily on the first real write (see
    # training_log.start_or_get_session) -- commit a set first so it
    # exists for /session/update and /session/pain-report to find.
    page.locator(".set-done-btn").click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()

    details = page.locator("#how-it-felt")
    notes = page.locator('textarea[name="notes"]')

    # Collapsed by default; the field isn't visible until opened.
    expect(details).not_to_have_js_property("open", True)
    expect(notes).not_to_be_visible()

    page.locator("#how-it-felt summary").click()
    expect(details).to_have_js_property("open", True)
    expect(notes).to_be_visible()

    notes.fill("Felt strong today.")
    notes.blur()  # fires the change event the autosave listener waits for

    # Fill and autosave a pain report too, in the same disclosure.
    page.locator('#pain-report-form select[name="hand"]').select_option("left")
    severity = page.locator('#pain-report-form input[name="severity"]')
    severity.fill("1")
    severity.blur()

    expect(page.locator('#pain-reports-body tr[data-hand="left"]')).to_be_visible()

    # Reload -- no client-side state left, so this proves the POSTs above
    # actually reached /session/update and /session/pain-report and were
    # persisted, not just updated in the DOM.
    page.reload()
    page.locator("#how-it-felt summary").click()
    expect(page.locator('textarea[name="notes"]')).to_have_value(
        "Felt strong today."
    )
    expect(page.locator('#pain-reports-body tr[data-hand="left"]')).to_contain_text(
        "1"
    )
