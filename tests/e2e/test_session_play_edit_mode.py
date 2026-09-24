"""Browser-smoke specs for session play's edit mode (issue #146 review item
4, replacing the pre-#146 tests/e2e/test_focus_edit_mode.py): tapping a
COMPLETED row now does a real htmx round trip to the server-rendered edit
view, rather than swapping in client-captured state -- broader edit-mode
behavior (Cancel, sequential hand order, the no-JS degradation) is covered
by the HTTP-seam tests in tests/test_session_play.py."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_tapping_a_completed_row_enters_edit_mode_with_the_right_values(
    live_server, authenticated_page
):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    left_weight = page.locator('[data-role="weight-display"][data-hand="left"]')

    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    set1_weight = left_weight.inner_text()
    page.locator(".set-done-btn").click()

    page.get_by_role("button", name="Skip rest").click()

    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    set2_weight = page.locator('[data-role="weight-display"][data-hand="left"]').inner_text()
    assert set2_weight != set1_weight
    page.locator(".set-done-btn").click()
    page.get_by_role("button", name="Skip rest").click()

    expect(page.locator(".play-overline")).to_contain_text("Work set 3")

    page.locator('.completed-row[data-set="1"]').click()

    expect(page.locator(".play-overline")).to_have_text("Editing set 1")
    expect(page.locator('[data-role="weight-display"][data-hand="left"]')).to_have_text(
        set1_weight
    )
    expect(page.locator(".set-done-btn")).to_have_text("Save")
    expect(page.locator(".set-cancel-btn")).to_be_visible()
    expect(page.locator(".set-delete-btn")).to_be_visible()


def test_delete_set_and_undo_in_edit_mode(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    expect(page.locator(".set-delete-btn")).to_be_hidden()

    page.locator(".set-done-btn").click()
    page.get_by_role("button", name="Skip rest").click()

    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    page.locator(".set-done-btn").click()
    page.get_by_role("button", name="Skip rest").click()

    expect(page.locator(".play-overline")).to_contain_text("Work set 3")

    page.locator('.completed-row[data-set="1"]').click()
    expect(page.locator(".play-overline")).to_have_text("Editing set 1")
    delete_btn = page.locator(".set-delete-btn")
    expect(delete_btn).to_be_visible()

    delete_btn.click()

    # Old set 2 is now renumbered to set 1; the undo banner (server-
    # rendered, #146 review item 2) names the deleted set.
    expect(page.locator(".undo-banner")).to_be_visible()
    expect(page.locator(".undo-banner")).to_contain_text("Set 1 deleted")
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(page.locator('.completed-row[data-set="2"]')).to_have_count(0)

    page.locator(".undo-banner .undo-btn").click()

    # Undo restored the original set 1, shifting the renumbered one back up.
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(page.locator('.completed-row[data-set="2"]')).to_be_visible()
