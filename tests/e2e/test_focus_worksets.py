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

    pill = page.locator(".focus-pill")
    expect(pill).to_contain_text("Set 1 of")

    weight_display = page.locator('.weight-value[data-hand="left"]')
    before = weight_display.inner_text()

    page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
    expect(weight_display).not_to_have_text(before)

    page.locator(".set-done-btn").click()

    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()
    expect(pill).to_contain_text("Set 2 of")
