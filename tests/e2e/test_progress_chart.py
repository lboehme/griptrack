"""Progress (#150): the headline %BW chart actually draws (a uPlot canvas,
no console errors) and the range picker swaps it in place via htmx."""

from datetime import date, timedelta

import pytest
from playwright.sync_api import expect


@pytest.fixture
def browser_context_args(browser_context_args):
    """Pin a plain BCP-47 locale: uPlot formats axis dates with Intl, which
    throws on a POSIX-style default like "en-US@posix" (some CI/container
    shells) before the chart can draw. The phone's WebView always reports a
    real locale."""
    return {**browser_context_args, "locale": "en-US"}


def _post(page, live_server, path, form):
    response = page.request.post(f"{live_server}{path}", form=form, max_redirects=0)
    assert response.status in (200, 303), (path, response.status)


def _seed(page, live_server):
    """Strength and sends both inside and outside the 6-week range, so the
    6W and All views plot different data."""
    today = date.today()
    old = (today - timedelta(days=80)).isoformat()
    recent = (today - timedelta(days=5)).isoformat()
    page.goto(f"{live_server}/progress/maxes")
    grip_id = page.locator("select.grip-select").first.locator("option", has_text="Half crimp").get_attribute("value")
    _post(page, live_server, "/profile/bodyweight", {"date": old, "weight": "70"})
    for hand, weight in (("left", "35"), ("right", "33")):
        _post(page, live_server, "/max-tests", {
            "hand": hand, "grip_type_id": grip_id, "edge_mm": "20", "date": old, "weight": weight,
        })
    for hand, weight in (("left", "37"), ("right", "34")):
        _post(page, live_server, "/session/workset", {
            "grip_type_id": grip_id, "edge_mm": "20", "date": recent, "hand": hand,
            "set_number": "1", "weight": weight, "reps": "5",
        })
    _post(page, live_server, "/climbs", {"date": old, "grade": "6B", "style": "flash"})
    _post(page, live_server, "/climbs", {"date": recent, "grade": "7A", "style": "flash"})


def test_headline_chart_renders_and_range_picker_swaps_it(live_server, authenticated_page):
    page = authenticated_page
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    _seed(page, live_server)

    page.goto(f"{live_server}/progress")
    expect(page.locator(".progress-chart canvas")).to_have_count(1)
    six_weeks = page.evaluate(
        "() => JSON.parse(document.getElementById('progress-chart-data').textContent).hands.left.dates.length"
    )
    assert six_weeks == 1

    page.locator('.progress-ranges a[data-range="all"]').click()
    expect(page.locator('#progress-root[data-range="all"]')).to_be_visible()
    expect(page.locator(".progress-chart canvas")).to_have_count(1)
    all_time = page.evaluate(
        "() => JSON.parse(document.getElementById('progress-chart-data').textContent).hands.left.dates.length"
    )
    assert all_time == 2
    assert "range=all" in page.url
    # Swapped in place: still one root, one chart, no full navigation.
    expect(page.locator("#progress-root")).to_have_count(1)
    expect(page.locator(".progress-chart .uplot")).to_have_count(1)
    expect(page.locator('.story-sentence[data-kind="change"]').first).to_be_visible()

    # Back restores the 6W view with a drawn chart.
    page.go_back()
    expect(page.locator('#progress-root[data-range="6w"]')).to_be_visible()
    expect(page.locator(".progress-chart canvas")).to_have_count(1)

    assert errors == [], errors


def test_progress_page_fits_about_two_screens_at_360(live_server, authenticated_page):
    page = authenticated_page
    page.set_viewport_size({"width": 360, "height": 740})
    _seed(page, live_server)
    page.goto(f"{live_server}/progress?range=all")
    expect(page.locator(".progress-chart canvas")).to_have_count(1)

    height = page.evaluate("() => document.documentElement.scrollHeight")
    assert height <= 2 * 740 + 200, f"Progress is {height}px tall"
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 360
