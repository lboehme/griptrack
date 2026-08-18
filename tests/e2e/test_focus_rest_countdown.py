"""Browser-smoke spec for the Focus screen's rest countdown (issue #82):
a deliberately throwaway, client-only 3:00 countdown that appears in the
button area after a normal (non-edit) set commit, with a skip affordance
that returns the button to "Set done" immediately. Broader behavior
(no-JS usability, no persistence) doesn't need a browser -- this is just
the one Playwright spec the issue calls for: start, then skip."""

from playwright.sync_api import expect


def test_committing_a_set_starts_the_rest_countdown_and_skip_ends_it(
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

    set_done_btn = page.locator(".set-done-btn")
    rest_countdown = page.locator("#rest-countdown")
    rest_time = page.locator("#rest-countdown-time")

    expect(rest_countdown).to_be_hidden()

    set_done_btn.click()
    expect(page.locator('.completed-row[data-set="1"]')).to_be_visible()

    # Committing the set starts a visible countdown and hides the button.
    expect(rest_countdown).to_be_visible()
    expect(rest_time).to_have_text("3:00")
    expect(set_done_btn).to_be_hidden()

    # Skip ends the rest immediately and restores "Set done" for set 2.
    page.locator("#rest-skip-btn").click()
    expect(rest_countdown).to_be_hidden()
    expect(set_done_btn).to_be_visible()
    expect(set_done_btn).to_have_text("Set done")
