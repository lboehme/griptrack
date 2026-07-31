"""Browser-smoke specs for the PR #85 review fixes.

Three client-side bugs the Focus screen shipped with:
- appended COMPLETED rows carried href="#", so once every set is logged and
  the form (and its click handler) are gone, tapping a just-logged row no
  longer reached the no-JS ?edit=N page. The appended row must carry the
  same real edit href the server renders.
- the set-commit fetch swallowed non-2xx responses (`if (!response.ok)
  return`), so a rejected /session/set failed silently. It must surface the
  error instead.
- the weight stepper could walk down onto the ladder's 0.0 rung (the
  "empty pin" fallback loadable_ladder always includes), producing an
  invalid work-set weight the server is guaranteed to reject.

Kept deliberately thin, like the rest of the e2e layer.
"""

from playwright.sync_api import expect


def _go_to_worksets(page, live_server):
    """Seed both hands' max tests, start a session, land on the work sets."""
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


def test_appended_completed_row_keeps_a_real_edit_href(live_server, authenticated_page):
    page = authenticated_page
    _go_to_worksets(page, live_server)

    total = int(page.locator(".focus-pill").inner_text().split("of")[1])

    # Log every default set. After the last one the form is removed, so the
    # appended rows are the only way back into a set -- via their href.
    for i in range(total):
        page.locator(".set-done-btn").click()
        if i < total - 1:
            page.locator("#rest-skip-btn").click()  # rest hides the button

    last_row = page.locator(f'.completed-row[data-set="{total}"]')
    expect(last_row).to_be_visible()
    href = last_row.get_attribute("href")
    assert href and f"edit={total}" in href, href
    assert href != "#"


def test_a_rejected_set_commit_surfaces_an_error(live_server, authenticated_page):
    page = authenticated_page
    _go_to_worksets(page, live_server)

    pill = page.locator(".focus-pill")
    expect(pill).to_contain_text("Set 1 of")

    # Force the server to reject the commit; the UI must not fail silently.
    page.route(
        "**/session/set",
        lambda route: route.fulfill(status=400, body="Weight out of range."),
    )
    page.locator(".set-done-btn").click()

    error = page.locator("#set-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Weight out of range.")
    # Did not advance -- the user stays on set 1 to fix and retry.
    expect(pill).to_contain_text("Set 1 of")


def test_weight_stepper_cannot_walk_down_onto_the_zero_rung(live_server, authenticated_page):
    page = authenticated_page
    _go_to_worksets(page, live_server)

    minus_btn = page.locator('.stepper-minus[data-field="weight"][data-hand="left"]')
    display = page.locator('[data-role="weight-display"][data-hand="left"]')

    # Mash it well past the bottom of the ladder -- it must floor at the
    # smallest positive rung, never land on 0.0 (the empty-pin fallback the
    # server rejects as an invalid weight).
    for _ in range(40):
        minus_btn.click()

    value = float(display.inner_text())
    assert value > 0, value
