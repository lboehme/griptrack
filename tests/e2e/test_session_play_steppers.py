"""Browser-smoke specs for the work-set steppers on /session/play (session
play, issue #146 review item 4 -- ported from the pre-#146
test_focus_worksets.py): the weight stepper walking the loadable ladder
with Set done advancing the top-bar counter, and the RPE stepper's
wake-at-7 / carry-down behavior."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_weight_stepper_walks_the_ladder_and_set_done_advances_the_counter(
    live_server, authenticated_page
):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    expect(page.locator(".play-overline")).to_contain_text("Work set 1")

    weight_display = page.locator('[data-role="weight-display"][data-hand="left"]')
    before = weight_display.inner_text()

    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    expect(weight_display).not_to_have_text(before)

    counter_before = page.locator(".play-step-counter").inner_text()
    page.locator(".set-done-btn").click()

    # A non-final commit starts rest; the top-bar counter (k/N over both
    # rungs and sets, #146) has already moved on to the next set.
    expect(page.locator("#rest-ring-time")).to_be_visible()
    counter_during_rest = page.locator(".play-step-counter").inner_text()
    assert counter_during_rest != counter_before

    page.get_by_role("button", name="Skip rest").click()

    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(page.locator(".play-overline")).to_contain_text("Work set 2")


def test_rpe_stepper_wake_at_7_and_carry_down(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    left_rpe_display = page.locator('[data-role="rpe-display"][data-hand="left"]')
    left_rpe_input = page.locator('[data-role="rpe-input"][data-hand="left"]')
    right_rpe_display = page.locator('[data-role="rpe-display"][data-hand="right"]')
    right_rpe_input = page.locator('[data-role="rpe-input"][data-hand="right"]')

    expect(left_rpe_display).to_have_text("7")
    expect(left_rpe_display).to_have_class("mini-value rpe-inactive")
    expect(left_rpe_input).to_have_value("")

    page.locator('.stepper-plus[data-field="rpe"][data-hand="left"]').click()
    expect(left_rpe_display).to_have_text("7")
    expect(left_rpe_display).not_to_have_class("rpe-inactive")
    expect(left_rpe_input).to_have_value("7")

    page.locator('.stepper-plus[data-field="rpe"][data-hand="left"]').click()
    expect(left_rpe_display).to_have_text("7.5")
    expect(left_rpe_input).to_have_value("7.5")

    page.locator('.stepper-minus[data-field="rpe"][data-hand="right"]').click()
    expect(right_rpe_display).to_have_text("7")
    expect(right_rpe_display).not_to_have_class("rpe-inactive")
    expect(right_rpe_input).to_have_value("7")

    page.locator('.stepper-minus[data-field="rpe"][data-hand="right"]').click()
    expect(right_rpe_display).to_have_text("6.5")

    for _ in range(12):
        page.locator('.stepper-minus[data-field="rpe"][data-hand="right"]').click()
    expect(right_rpe_display).to_have_text("7")
    expect(right_rpe_display).to_have_class("mini-value rpe-inactive")
    expect(right_rpe_input).to_have_value("")

    page.locator('.stepper-plus[data-field="rpe"][data-hand="left"]').click()
    expect(left_rpe_display).to_have_text("8")
    expect(left_rpe_input).to_have_value("8")

    page.locator(".set-done-btn").click()
    page.get_by_role("button", name="Skip rest").click()

    completed_row = page.locator('.completed-row[data-set="1"]')
    expect(completed_row).to_be_visible()
    expect(completed_row).to_contain_text("L 40.0 × 5 @ 8")

    # Set 2 is now current -- left RPE carries down 8, right RPE stays greyed 7.
    # (The display span trims "8.0" to "8"; the raw <input> fallback keeps
    # the server's literal float value -- both parse identically on submit.)
    expect(left_rpe_display).to_have_text("8")
    expect(left_rpe_display).not_to_have_class("rpe-inactive")
    expect(left_rpe_input).to_have_value("8.0")

    expect(right_rpe_display).to_have_text("7")
    expect(right_rpe_display).to_have_class("mini-value rpe-inactive")
    expect(right_rpe_input).to_have_value("")
