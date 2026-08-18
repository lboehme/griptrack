"""Browser-smoke spec for the Focus screen's edit mode (issue #80):
tapping a COMPLETED row reloads that set's saved values into the hand
cards client-side, without a round trip. Broader edit-mode behavior
(Cancel, sequential hand order, the no-JS degradation) is covered by the
HTTP-seam tests in tests/test_worksets.py -- this is just the one
Playwright spec the issue calls for."""

from playwright.sync_api import expect


def test_tapping_a_completed_row_enters_edit_mode_with_the_right_values(
    live_server, authenticated_page
):
    page = authenticated_page

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

    left_weight = page.locator('.weight-value[data-hand="left"]')

    # Bump set 1's left weight up one rung so it's distinguishable from
    # whatever set 2 ends up carrying down, then commit it.
    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    set1_weight = left_weight.inner_text()
    page.locator(".set-done-btn").click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()

    # Committing a set starts the rest countdown (issue #82), which hides
    # the button; skip it to get back to "Set done" for set 2.
    page.locator("#rest-skip-btn").click()

    # Bump set 2's weight again so it's a different value than set 1's,
    # then commit it too -- now set 1 is a COMPLETED row to tap back into.
    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    set2_weight = left_weight.inner_text()
    assert set2_weight != set1_weight
    page.locator(".set-done-btn").click()
    expect(page.locator('.completed-row[data-set="2"]')).to_be_visible()

    pill = page.locator(".focus-pill")
    expect(pill).to_contain_text("Set 3 of")

    page.locator('.completed-row[data-set="1"]').click()

    expect(pill).to_have_text("Editing set 1")
    expect(left_weight).to_have_text(set1_weight)
    expect(page.locator(".set-done-btn")).to_have_text("Save")
    expect(page.locator(".set-cancel-btn")).to_be_visible()
    expect(page.locator(".set-delete-btn")).to_be_visible()


def test_delete_set_and_undo_in_edit_mode(live_server, authenticated_page):
    page = authenticated_page

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

    # Outside edit mode, delete button is hidden
    expect(page.locator(".set-delete-btn")).to_be_hidden()

    # Commit set 1
    page.locator(".set-done-btn").click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    page.locator("#rest-skip-btn").click()

    # Commit set 2
    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    page.locator(".set-done-btn").click()
    expect(page.locator('.completed-row[data-set="2"]')).to_be_visible()
    page.locator("#rest-skip-btn").click()

    pill = page.locator(".focus-pill")
    expect(pill).to_contain_text("Set 3 of")

    # Enter edit mode for set 1
    page.locator('.completed-row[data-set="1"]').click()
    expect(pill).to_have_text("Editing set 1")
    delete_btn = page.locator(".set-delete-btn")
    expect(delete_btn).to_be_visible()

    # Click delete
    delete_btn.click()

    # Now old set 2 is renumbered to set 1, and set 2 row is gone
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(page.locator('.completed-row[data-set="2"]')).to_be_hidden()
    expect(pill).to_contain_text("Set 2 of")

    # Undo snackbar is visible
    snackbar = page.locator("#undo-snackbar")
    expect(snackbar).to_be_visible()
    expect(snackbar).to_contain_text("Set 1 deleted")

    # Click undo
    page.locator("#undo-btn").click()

    # Both set 1 and set 2 are back in completed list
    expect(snackbar).to_be_hidden()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(page.locator('.completed-row[data-set="2"]')).to_be_visible()
    expect(pill).to_contain_text("Set 3 of")

