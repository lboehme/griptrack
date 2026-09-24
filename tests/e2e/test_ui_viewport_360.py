"""E2E verification for 360 px viewport rendering and UI review bug fixes (issue #138)."""

from playwright.sync_api import expect

from tests.e2e.conftest import advance_to_worksets, start_session_play


def _seed_session_and_worksets(page, live_server):
    start_session_play(page, live_server)
    advance_to_worksets(page)


def test_main_pages_have_no_horizontal_overflow_at_360px(live_server, authenticated_page):
    """Across all main pages at 360 px viewport width, document.documentElement.scrollWidth
    must not exceed window.innerWidth (no horizontal page scroll)."""
    page = authenticated_page
    page.set_viewport_size({"width": 360, "height": 740})

    # Ensure max tests has history so the Test History table is tested
    _seed_session_and_worksets(page, live_server)

    routes = [
        "/",
        "/max-tests",
        "/session/new",
        "/climbs",
        "/dashboard",
        "/profile",
        "/plates",
    ]

    for route in routes:
        page.goto(f"{live_server}{route}")
        page.wait_for_load_state("domcontentloaded")
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        inner_width = page.evaluate("() => window.innerWidth")
        assert scroll_width <= inner_width, (
            f"Horizontal overflow on {route}: scrollWidth {scroll_width} > innerWidth {inner_width}"
        )


def test_worksets_card_elements_and_set_done_within_360x740(live_server, authenticated_page):
    """On a 360x740 screen:
    1. 'Set done' button is above the fold (not hidden below the tab bar).
    2. Mini-stepper buttons sit completely inside the hand card without overflowing.
    3. Completed-set checkmark renders visibly (>= 10px)."""
    page = authenticated_page
    page.set_viewport_size({"width": 360, "height": 740})
    _seed_session_and_worksets(page, live_server)

    # 1. No horizontal scroll
    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    inner_width = page.evaluate("() => window.innerWidth")
    assert scroll_width <= inner_width

    # 2. Check steppers are inside hand-card bounding boxes
    cards = page.locator(".hand-card").all()
    assert len(cards) >= 2
    for card in cards:
        card_box = card.bounding_box()
        assert card_box is not None
        rpe_plus = card.locator('.stepper-btn-sm.stepper-plus[data-field="rpe"]').bounding_box()
        assert rpe_plus is not None
        assert rpe_plus["x"] + rpe_plus["width"] <= card_box["x"] + card_box["width"] + 1, (
            f"RPE + button overflows card: right edge {rpe_plus['x'] + rpe_plus['width']} "
            f"> card right {card_box['x'] + card_box['width']}"
        )

    # 3. 'Set done' button is above the fold on a 360x740 viewport -- session
    # play has no tab bar (V5: full screen, no chrome during a session), so
    # this checks against the viewport itself rather than a .tabbar element.
    btn = page.locator(".set-done-btn")
    expect(btn).to_be_visible()
    btn_box = btn.bounding_box()
    assert btn_box is not None
    assert btn_box["y"] + btn_box["height"] <= 740, (
        f"Set done button bottom {btn_box['y'] + btn_box['height']} is below the 740px viewport"
    )
    assert page.locator(".tabbar").count() == 0, "No tab bar during a session (V5)"

    # 4. Check completed-set checkmark SVG size after logging a set -- a
    # non-final commit lands on the rest step first (session play, #146),
    # so skip rest to get back to the work-set step's completed list.
    btn.click()
    page.get_by_role("button", name="Skip rest").click()
    completed_row = page.locator('.completed-row[data-set="1"]')
    expect(completed_row).to_be_visible()
    svg = page.locator(".completed-check svg").first
    svg_box = svg.bounding_box()
    assert svg_box is not None
    assert svg_box["width"] >= 10, f"Checkmark svg width {svg_box['width']} < 10px"
    assert svg_box["height"] >= 10, f"Checkmark svg height {svg_box['height']} < 10px"


def test_summary_finish_is_above_the_fold_with_no_overflow_at_360x740(
    live_server, authenticated_page
):
    """The summary step (#147) is the longest session screen; its Finish
    button is pinned in the bottom action area (V8), so it must be visible
    at 360x740 without scrolling, with no horizontal overflow."""
    page = authenticated_page
    page.set_viewport_size({"width": 360, "height": 740})
    _seed_session_and_worksets(page, live_server)
    for set_number in range(1, 4):
        page.locator(".set-done-btn").click()
        if set_number < 3:
            page.get_by_role("button", name="Skip rest").click()
    expect(page.get_by_text("Session done")).to_be_visible()

    for tweak in ("none", "left"):  # also with the tweak picker revealed
        page.locator(f"label:has(#tweak-hand-{tweak})").click()
        page.evaluate("() => window.scrollTo(0, 0)")
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        inner_width = page.evaluate("() => window.innerWidth")
        assert scroll_width <= inner_width, (
            f"Horizontal overflow on summary: scrollWidth {scroll_width} > {inner_width}"
        )
        finish = page.locator(".summary-finish-btn")
        expect(finish).to_be_visible()
        box = finish.bounding_box()
        assert box is not None
        assert box["y"] >= 0 and box["y"] + box["height"] <= 740, (
            f"Finish button spans {box['y']}..{box['y'] + box['height']}, outside 0..740"
        )
        assert box["height"] >= 44


def test_worksets_stepper_buttons_fit_at_130_percent_font_scale(live_server, authenticated_page):
    """At 412 px with 130% font scale, stepper buttons must still sit inside their cards."""
    page = authenticated_page
    page.set_viewport_size({"width": 412, "height": 844})
    _seed_session_and_worksets(page, live_server)

    # Simulate 130% font scale (20.8px root font size)
    page.evaluate("() => { document.documentElement.style.fontSize = '20.8px'; }")

    cards = page.locator(".hand-card").all()
    for card in cards:
        card_box = card.bounding_box()
        assert card_box is not None
        rpe_plus = card.locator('.stepper-btn-sm.stepper-plus[data-field="rpe"]').bounding_box()
        assert rpe_plus is not None
        assert rpe_plus["x"] + rpe_plus["width"] <= card_box["x"] + card_box["width"] + 1


def test_profile_progression_select_has_full_width_at_412px(live_server, authenticated_page):
    """Default progression select has a full row and is not squeezed/truncated."""
    page = authenticated_page
    page.set_viewport_size({"width": 412, "height": 844})
    page.goto(f"{live_server}/profile")

    select = page.locator('select[name="path"]').first
    expect(select).to_be_visible()
    select_box = select.bounding_box()
    assert select_box is not None
    # In a full-row layout, select spans almost the whole card width (> 250px on 412px viewport)
    assert select_box["width"] > 250, f"Progression select width {select_box['width']} is too narrow, likely half-row"
