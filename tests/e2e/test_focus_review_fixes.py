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
- with no plates at all the ladder is just [0.0], so the stepper had no
  valid rung to offer while js-enabled had already hidden the raw weight
  input -- locking the user out of logging a set entirely.

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


def _remove_all_plates(page, live_server):
    """Zero out the seeded default inventory, leaving the ladder as [0.0]."""
    page.goto(f"{live_server}/plates")
    remaining = page.locator("select[name='count']").count()
    while remaining:
        # Selecting "0 — remove" submits the row's form and reloads the page.
        with page.expect_navigation():
            page.locator("select[name='count']").first.select_option("0")
        remaining -= 1
        expect(page.locator("select[name='count']")).to_have_count(remaining)


def test_an_empty_ladder_falls_back_to_free_weight_entry(live_server, authenticated_page):
    page = authenticated_page
    _remove_all_plates(page, live_server)
    _go_to_worksets(page, live_server)

    # The stepper has no rung it could offer, so it steps aside and the
    # plain number input takes over -- the set must still be loggable.
    raw_input = page.locator('.raw-input[data-role="weight-input"][data-hand="left"]')
    expect(raw_input).to_be_visible()
    expect(
        page.locator('.stepper-plus[data-field="weight"][data-hand="left"]')
    ).to_be_hidden()

    raw_input.fill("32.5")
    page.locator('.raw-input[data-role="weight-input"][data-hand="right"]').fill("32.5")
    page.locator(".set-done-btn").click()

    row = page.locator('.completed-row[data-set="1"]')
    expect(row).to_be_visible()
    expect(row).to_contain_text("32.5")
