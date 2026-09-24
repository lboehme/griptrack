"""Browser-smoke spec for the work-set stepper hold-to-repeat (issue #141),
retargeted at /session/play (issue #146): the stepper JS moved into
backend/static/steppers.js and binds by event delegation so it keeps
working across htmx step swaps.

Verifies that:
1. A single tap/click advances a stepper by exactly one step (no double-step).
2. Pressing and holding a stepper repeats stepping along the ladder/values.
3. Releasing or moving pointer away stops the repeat.
"""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_stepper_single_click_and_hold_to_repeat(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)
    advance_to_worksets(page)

    # 1. Verify single click on reps stepper performs exactly one step
    reps_display = page.locator('[data-role="reps-display"][data-hand="left"]')
    reps_input = page.locator('[data-role="reps-input"][data-hand="left"]')
    initial_reps = int(reps_display.inner_text())

    plus_reps = page.locator('.stepper-plus[data-field="reps"][data-hand="left"]')
    plus_reps.click()
    expect(reps_display).to_have_text(str(initial_reps + 1))
    expect(reps_input).to_have_value(str(initial_reps + 1))

    minus_reps = page.locator('.stepper-minus[data-field="reps"][data-hand="left"]')
    minus_reps.click()
    expect(reps_display).to_have_text(str(initial_reps))
    expect(reps_input).to_have_value(str(initial_reps))

    # 2. Verify hold-to-repeat on weight stepper advances several steps along the ladder
    weight_display = page.locator('[data-role="weight-display"][data-hand="left"]')
    weight_input = page.locator('[data-role="weight-input"][data-hand="left"]')
    start_weight = float(weight_display.inner_text())

    plus_weight = page.locator('.stepper-plus[data-field="weight"][data-hand="left"]')
    box = plus_weight.bounding_box()
    assert box is not None

    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(1100)
    page.mouse.up()

    end_weight = float(weight_display.inner_text())
    assert end_weight > start_weight + 2.0, (
        f"Hold-to-repeat should have moved several ladder steps, but went from {start_weight} to {end_weight}"
    )
    expect(weight_input).to_have_value(str(end_weight))

    # 3. Verify moving pointer away (pointerleave) stops repetition
    weight_before_leave = float(weight_display.inner_text())
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(100)  # stepped once on press
    page.mouse.move(0, 0)  # leave the button
    page.wait_for_timeout(600)  # wait what would have been several repeat ticks
    page.mouse.up()

    weight_after_leave = float(weight_display.inner_text())
    step_diff = round(weight_after_leave - weight_before_leave, 2)
    assert 0 < step_diff <= 1.5, (
        f"Expected single step before pointerleave, but changed by {step_diff}"
    )
