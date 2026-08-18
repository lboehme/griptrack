"""Browser-smoke spec for the Focus work-sets screen (issue #79): the
tracer-bullet path where a real Chromium walks the weight stepper along
the loadable ladder and commits a set end-to-end. Deliberately just the
one spec named by the issue -- broader Focus-screen behavior (edit mode,
rest countdown, warmup) belongs to their own issues, not this file."""

from playwright.sync_api import expect


def test_weight_stepper_walks_the_ladder_and_set_done_advances_the_pill(
    live_server, authenticated_page
):
    page = authenticated_page

    # A MaxWeightTest for both hands so the warmup page renders the real
    # ramp (not the untested-hand estimate prompt) once we get there.
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

    pill = page.locator(".focus-pill")
    expect(pill).to_contain_text("Set 1 of")

    weight_display = page.locator('.weight-value[data-hand="left"]')
    before = weight_display.inner_text()

    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    expect(weight_display).not_to_have_text(before)

    page.locator(".set-done-btn").click()

    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(pill).to_contain_text("Set 2 of")


def test_rpe_stepper_wake_at_7_and_carry_down(live_server, authenticated_page):
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

    left_rpe_display = page.locator('[data-role="rpe-display"][data-hand="left"]')
    left_rpe_input = page.locator('[data-role="rpe-input"][data-hand="left"]')
    right_rpe_display = page.locator('[data-role="rpe-display"][data-hand="right"]')
    right_rpe_input = page.locator('[data-role="rpe-input"][data-hand="right"]')

    # Fresh set: greyed 7, empty input
    expect(left_rpe_display).to_have_text("7")
    expect(left_rpe_display).to_have_class("mini-value rpe-inactive")
    expect(left_rpe_input).to_have_value("")

    # First '+' tap wakes at active 7
    page.locator('.stepper-plus[data-field="rpe"][data-hand="left"]').click()
    expect(left_rpe_display).to_have_text("7")
    expect(left_rpe_display).not_to_have_class("rpe-inactive")
    expect(left_rpe_input).to_have_value("7")

    # Second '+' tap steps to 7.5
    page.locator('.stepper-plus[data-field="rpe"][data-hand="left"]').click()
    expect(left_rpe_display).to_have_text("7.5")
    expect(left_rpe_input).to_have_value("7.5")

    # First '-' tap on unset wakes at active 7
    page.locator('.stepper-minus[data-field="rpe"][data-hand="right"]').click()
    expect(right_rpe_display).to_have_text("7")
    expect(right_rpe_display).not_to_have_class("rpe-inactive")
    expect(right_rpe_input).to_have_value("7")

    # Second '-' tap steps to 6.5
    page.locator('.stepper-minus[data-field="rpe"][data-hand="right"]').click()
    expect(right_rpe_display).to_have_text("6.5")

    # Step down past 1 clears back to greyed 7
    for _ in range(12):
        page.locator('.stepper-minus[data-field="rpe"][data-hand="right"]').click()
    expect(right_rpe_display).to_have_text("7")
    expect(right_rpe_display).to_have_class("mini-value rpe-inactive")
    expect(right_rpe_input).to_have_value("")

    # Step left up to 8.0
    page.locator('.stepper-plus[data-field="rpe"][data-hand="left"]').click()
    expect(left_rpe_display).to_have_text("8")
    expect(left_rpe_input).to_have_value("8")

    # Commit set 1
    page.locator(".set-done-btn").click()

    completed_row = page.locator('.completed-row[data-set="1"]')
    expect(completed_row).to_be_visible()
    expect(completed_row).to_contain_text("L 40.0 × 5 @ 8")

    # Set 2 is now current -- left RPE carries down 8, right RPE stays greyed 7
    expect(left_rpe_display).to_have_text("8")
    expect(left_rpe_display).not_to_have_class("rpe-inactive")
    expect(left_rpe_input).to_have_value("8")

    expect(right_rpe_display).to_have_text("7")
    expect(right_rpe_display).to_have_class("mini-value rpe-inactive")
    expect(right_rpe_input).to_have_value("")

