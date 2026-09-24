"""Browser-smoke specs for Settings (#151): a changed setting autosaves
(the "Saved" toast appears, and the value survives a reload), and a plate
tap on the rack counts one more and saves."""

from playwright.sync_api import expect


def test_changing_a_setting_autosaves_with_a_toast_and_persists(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/settings/training")

    reps = page.locator('input[name="base_work_set_reps"]')
    reps.fill("7")
    reps.press("Tab")  # blur fires `change`: the form autosaves via htmx

    toast = page.locator(".toast")
    expect(toast).to_be_visible()
    expect(toast).to_contain_text("Saved")
    assert page.url.endswith("/settings/training"), "autosave must not navigate"

    page.reload()
    expect(page.locator('input[name="base_work_set_reps"]')).to_have_value("7")

    # A choice chip autosaves on tap too.
    page.locator("label.settings-choice", has_text="One hand, then the other").click()
    expect(page.locator(".toast")).to_be_visible()
    page.goto(f"{live_server}/settings")
    expect(page.locator("[data-hand-order]")).to_have_attribute("data-hand-order", "sequential")


def test_display_name_autosaves_on_enter(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/settings/name")

    name = page.locator('input[name="name"]')
    name.fill("Lukas")
    name.press("Enter")

    expect(page.locator(".toast")).to_be_visible()
    page.reload()
    expect(page.locator('input[name="name"]')).to_have_value("Lukas")


def test_tapping_a_plate_counts_it_and_saves(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/settings/plates")

    plate = page.locator('button.plate[data-weight="20.0"]')
    count = plate.locator(".plate-count")
    expect(count).to_have_attribute("data-count", "1")

    plate.click()
    expect(count).to_have_attribute("data-count", "2")
    expect(count).to_have_text("×2")
    plate.click()
    expect(count).to_have_attribute("data-count", "3")
    assert page.url.endswith("/settings/plates"), "a tap must not navigate"

    page.reload()
    expect(page.locator('button.plate[data-weight="20.0"] .plate-count')).to_have_attribute(
        "data-count", "3"
    )
    # 3 × 20 now: the "what can I load" line followed the tap.
    expect(page.locator(".plate-summary")).to_contain_text("98.5 kg")
