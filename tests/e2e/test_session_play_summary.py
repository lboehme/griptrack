"""Browser-smoke spec for the session play Summary step (#147; replaces
the "How did it feel?" disclosure spec, whose notes/deload/tweaks moved
here). Confirms in a real browser that the Session RPE chips swap via htmx,
notes/deload and tweaks autosave on change with no submit step, the
tweak severity picker reveals only for a chosen hand (pure CSS), and
Finish goes home. Validation, idempotence and per-user isolation are
covered at the HTTP seam in tests/test_session_summary.py."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def run_to_summary(page, live_server):
    start_session_play(page, live_server)
    advance_to_worksets(page)
    for set_number in range(1, 4):
        page.locator(".set-done-btn").click()
        if set_number < 3:
            page.get_by_role("button", name="Skip rest").click()
    expect(page.get_by_text("Session done")).to_be_visible()


def test_summary_chips_notes_deload_and_tweaks_autosave(live_server, authenticated_page):
    page = authenticated_page
    run_to_summary(page, live_server)
    summary_url = page.url

    # Session RPE: an htmx swap of just the chip group, no page load.
    page.evaluate("() => { window.__noReload = true; }")
    hard = page.locator('.rpe-chip[value="7"]')
    hard.click()
    expect(page.locator('.rpe-chip[value="7"]')).to_have_class("chip rpe-chip on")
    expect(page.locator('.rpe-chip[value="7"]')).to_have_attribute("aria-pressed", "true")
    assert page.evaluate("() => window.__noReload === true")

    notes = page.locator('textarea[name="notes"]')
    notes.fill("Felt strong today.")
    notes.blur()
    page.locator('input[name="is_deload"]').check()

    # Tweaks: severity is hidden until a hand is chosen.
    left_form = page.locator("#tweak-form-left")
    expect(left_form).to_be_hidden()
    page.locator('label:has(#tweak-hand-left)').click()
    expect(left_form).to_be_visible()
    left_form.locator('label:has(#tweak-left-severity-2)').click()
    expect(left_form.locator('[data-role="tweak-status"]')).to_have_text("Saved")
    # Hiding the severity form again by picking Right keeps the saved tweak.
    page.locator('label:has(#tweak-hand-right)').click()
    expect(left_form).to_be_hidden()

    # Reload: no client-side state left, so this proves every change above
    # actually reached the server.
    page.goto(summary_url)
    expect(page.locator('.rpe-chip[value="7"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator('textarea[name="notes"]')).to_have_value("Felt strong today.")
    expect(page.locator('input[name="is_deload"]')).to_be_checked()
    expect(page.locator("#tweak-hand-left")).to_be_checked()
    expect(page.locator("#tweak-left-severity-2")).to_be_checked()

    # "None" clears the tweak (PR #154 review): gone after a reload.
    page.locator('label:has(#tweak-hand-none)').click()
    page.wait_for_timeout(300)
    page.goto(summary_url)
    expect(page.locator("#tweak-hand-none")).to_be_checked()
    expect(page.locator("#tweak-left-severity-2")).not_to_be_checked()

    # Finish goes home; reopening the session resumes on its summary.
    page.locator(".summary-finish-btn").click()
    page.wait_for_url(f"{live_server}/")
    page.goto(summary_url)
    expect(page.get_by_text("Session done")).to_be_visible()


def test_notes_field_matches_the_dark_mode_input_background(live_server, authenticated_page):
    page = authenticated_page
    page.emulate_media(color_scheme="dark")
    run_to_summary(page, live_server)

    page.locator('label:has(#tweak-hand-right)').click()
    notes = page.locator('textarea[name="notes"]')
    tweak_note = page.locator('#tweak-form-right input[name="note"]')
    expect(tweak_note).to_be_visible()

    notes_bg = notes.evaluate("el => window.getComputedStyle(el).backgroundColor")
    input_bg = tweak_note.evaluate("el => window.getComputedStyle(el).backgroundColor")
    assert notes_bg == input_bg
    assert notes_bg != "rgb(255, 255, 255)"
