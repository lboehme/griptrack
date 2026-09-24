"""Today + the ＋ Log sheet in a real browser (#149): the sheet opens in
place from any tab-bar page without adding history entries, a climb logs
in three taps, the bodyweight stepper reuses the hold-to-repeat steppers,
and the Change picker swaps the plan in place."""

import re

from playwright.sync_api import expect

from tests.e2e.conftest import seed_max_tests


def test_logging_a_climb_takes_three_taps(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/")
    history_before = page.evaluate("() => history.length")
    url_before = page.url

    page.locator(".tabbar-log").click()  # 1: ＋ Log
    page.locator('label.grade-chip:has(input[value="7A"])').click()  # 2: grade
    submit = page.locator(".sheet-climb .sheet-submit")
    expect(submit).to_have_text("Log 7A flash")
    submit.click()  # 3: save (style Flash and When Today are the defaults)

    expect(page.locator(".toast")).to_contain_text("Climb logged")
    expect(page.locator(".log-sheet")).to_have_count(0)
    # Nothing Android Back has to step through: same URL, same history.
    assert page.url == url_before
    assert page.evaluate("() => history.length") == history_before
    # Today's week strip refreshed in place.
    expect(page.locator("[data-week-climbs]")).to_have_attribute("data-week-climbs", "1")

    page.goto(f"{live_server}/history")
    expect(page.locator('li.climb[data-grade="7A"][data-style="flash"]')).to_have_count(1)


def test_sheet_opens_and_closes_from_another_tab_page(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/progress")
    history_before = page.evaluate("() => history.length")

    page.locator(".tabbar-log").click()
    expect(page.locator(".log-sheet")).to_be_visible()
    page.locator(".sheet-tab", has_text="Tweak").click()
    expect(page.locator(".sheet-tweak")).to_be_visible()
    page.locator(".sheet-close").click()

    expect(page.locator(".log-sheet")).to_have_count(0)
    assert page.url.endswith("/progress")
    assert page.evaluate("() => history.length") == history_before


def test_bodyweight_stepper_steps_by_a_tenth_and_saves(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/")
    page.locator(".today-bodyweight").click()

    weight = page.locator("#bw-weight")
    expect(weight).to_have_value("70.0")
    page.locator('.bw-stepper .stepper-plus').click()
    page.locator('.bw-stepper .stepper-plus').click()
    page.locator('.bw-stepper .stepper-minus').click()
    expect(weight).to_have_value("70.1")
    page.get_by_role("button", name="Save bodyweight").click()

    expect(page.locator(".toast")).to_contain_text("Bodyweight logged")
    expect(page.locator(".today-bodyweight")).to_have_count(0)


def test_bodyweight_stepper_hold_to_repeat(live_server, authenticated_page):
    page = authenticated_page
    page.goto(f"{live_server}/?log=bodyweight")
    plus = page.locator(".bw-stepper .stepper-plus")
    expect(plus).to_be_visible()
    page.wait_for_timeout(400)  # let the sheet's slide-up settle
    box = plus.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(900)
    page.mouse.up()

    value = float(page.locator("#bw-weight").input_value())
    assert value >= 70.4, f"hold-to-repeat should have run past one step, got {value}"


def test_change_picker_swaps_the_plan_in_place(live_server, authenticated_page):
    page = authenticated_page
    seed_max_tests(page, live_server)
    page.goto(f"{live_server}/")
    history_before = page.evaluate("() => history.length")
    expect(page.locator(".today-combo")).to_contain_text("Half crimp · 20 mm")

    page.locator(".today-change").click()
    picker = page.locator("#today-picker")
    expect(picker).to_be_visible()
    picker.locator('input[name="edge_mm"]').fill("15")
    picker.get_by_role("button", name="Use this").click()

    expect(page.locator(".today-combo")).to_contain_text("Half crimp · 15 mm")
    expect(page.locator("#today-picker")).to_have_count(0)
    assert page.evaluate("() => history.length") == history_before
    assert re.search(r"/$", page.url)


def test_tweak_offers_go_lighter_and_the_toggle_scales_the_plan(live_server, authenticated_page):
    page = authenticated_page
    seed_max_tests(page, live_server)
    page.goto(f"{live_server}/")
    expect(page.locator('.today-hand[data-hand="left"]')).to_have_attribute("data-weight", "40.0")
    expect(page.locator(".go-lighter-btn")).to_have_count(0)

    page.locator(".tabbar-log").click()
    page.locator(".sheet-tab", has_text="Tweak").click()
    page.locator('label.severity-chip:has(input[value="1"])').click()
    page.get_by_role("button", name="Save tweak").click()
    expect(page.locator(".toast")).to_contain_text("Tweak noted")

    lighter = page.locator(".go-lighter-btn")
    expect(lighter).to_have_text("Go lighter")
    lighter.click()
    expect(page.locator('.today-hand[data-hand="left"]')).to_have_attribute("data-weight", "33.75")
    expect(page.locator(".go-lighter-btn")).to_have_text("Undo lighter")

    page.locator(".go-lighter-btn").click()
    expect(page.locator('.today-hand[data-hand="left"]')).to_have_attribute("data-weight", "40.0")
