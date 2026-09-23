"""Browser-smoke spec for Focus stepper hold-to-repeat (issue #141).

Verifies that:
1. A single tap/click advances a stepper by exactly one step (no double-step).
2. Pressing and holding a stepper repeats stepping along the ladder/values.
3. Releasing or moving pointer away stops the repeat.
"""

from playwright.sync_api import expect


def test_stepper_single_click_and_hold_to_repeat(live_server, authenticated_page):
    page = authenticated_page

    # Seed max test so warmup and worksets are active
    for hand in ("left", "right"):
        page.goto(f"{live_server}/max-tests")
        form = page.locator('form[action="/max-tests"]')
        form.locator(f'input[name="hand"][value="{hand}"]').check()
        form.locator("select.grip-select").select_option(label="Half crimp")
        form.locator('input[name="edge_mm"]').fill("20")
        form.locator('input[name="weight"]').fill("40")
        form.locator('button[type="submit"]').click()

    page.goto(f"{live_server}/session/new")
    page.locator(".grip-select").select_option(label="Half crimp")
    page.locator('input[name="edge_mm"]').fill("20")
    page.get_by_role("button", name="Start warmup").click()
    page.get_by_role("link", name="Continue to work sets").click()

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
    weight_display = page.locator('.weight-value[data-hand="left"]')
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
    # Started at e.g. 32.5 or 34, after >1s holding it should have stepped 5+ times along the ladder
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
    # Should only have stepped once (from initial press) before pointer left
    # With ladder steps >= 0.5, a single step changes by one ladder increment, not 4-5 increments
    step_diff = round(weight_after_leave - weight_before_leave, 2)
    assert 0 < step_diff <= 1.5, (
        f"Expected single step before pointerleave, but changed by {step_diff}"
    )
