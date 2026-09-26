"""Capture the app's screens from a running demo server (see demo_server.sh).

Drives the real on-device build through Playwright at a Pixel-class
viewport (412 x 915 CSS px) and writes, into OUT_DIR:

  screens/<name>.png   device-pixel-ratio 3 screenshots (1236 x 2745)
  screens/rest/NNN.png a flipbook of the rest ring counting down
  screens/scroll/NNN.png Progress scrolling its chart into view
  manifest.json        CSS-px boxes of the controls the video "taps"

The server must be freshly seeded: this script starts and finishes a real
session, so run it once per demo_server.sh boot. DEMO_DB is the demo
SQLite file, used only to backdate the session's start so the summary
reads like a real 40-minute session instead of the few seconds the
capture takes.
"""

import argparse
import json
import sqlite3
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:8765"
TOKEN = "demo-device-token"
VIEWPORT = {"width": 412, "height": 915}
REST_FRAMES = 60
SCROLL_FRAMES = 30
SCROLL_TO = 260


def box(page: Page, selector: str) -> dict:
    b = page.locator(selector).first.bounding_box()
    assert b is not None, selector
    return {k: round(v, 1) for k, v in b.items()}


def settle(page: Page, ms: int = 450) -> None:
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(ms)


def main(out: Path, db: Path) -> None:
    screens = out / "screens"
    (screens / "rest").mkdir(parents=True, exist_ok=True)
    manifest: dict = {"viewport": VIEWPORT, "boxes": {}}
    boxes = manifest["boxes"]

    def shot(page: Page, name: str) -> None:
        page.screenshot(path=str(screens / f"{name}.png"))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            locale="en-GB",
            timezone_id="Europe/Berlin",
        )
        page = context.new_page()
        page.on("pageerror", lambda e: print("page error:", e))

        # Device sign-in, exactly as the Android shell does it (ADR-0013).
        page.goto(f"{BASE}/login")
        page.evaluate(
            """token => { const f = document.createElement('form');
            f.method = 'post'; f.action = '/device-login';
            const i = document.createElement('input'); i.name = 'token';
            i.value = token; f.appendChild(i); document.body.appendChild(f);
            f.submit(); }""",
            TOKEN,
        )
        settle(page)

        # ---- Today + the ＋ Log sheet
        shot(page, "today")
        boxes["today_start"] = box(page, "button:has-text('Start session')")
        boxes["today_plan"] = box(page, ".today-plan")
        boxes["tab_log"] = box(page, "nav >> text=Log")
        page.locator("nav").get_by_text("Log").click()
        settle(page, 700)
        shot(page, "log-sheet")
        chip = page.locator(".log-sheet label.grade-chip").filter(has_text="7A+").first
        boxes["log_grade"] = {k: round(v, 1) for k, v in (chip.bounding_box() or {}).items()}
        chip.click()
        page.wait_for_timeout(300)
        shot(page, "log-sheet-7a")

        # ---- Other tabs and Go deeper pages
        for name, path in (
            ("progress", "/progress?range=3m"),
            ("volume", "/progress/volume"),
            ("balance", "/progress/balance"),
            ("maxes", "/progress/maxes"),
            ("timeline", "/progress/timeline"),
            ("settings", "/settings"),
        ):
            page.goto(BASE + path)
            settle(page, 700)
            shot(page, name)

        # Progress scroll flipbook: the headline chart sliding into view.
        (screens / "scroll").mkdir(exist_ok=True)
        page.goto(BASE + "/progress?range=3m")
        settle(page, 700)
        for frame in range(SCROLL_FRAMES + 1):
            page.evaluate(f"window.scrollTo(0, {SCROLL_TO * frame / SCROLL_FRAMES})")
            page.wait_for_timeout(120)
            page.screenshot(path=str(screens / "scroll" / f"{frame:03d}.png"))
        shot(page, "progress-chart")

        # ---- Session play: warmup rungs
        page.goto(BASE + "/")
        settle(page)
        page.get_by_role("button", name="Start session").click()
        page.wait_for_url("**/session/play**")
        settle(page)
        rung = 1
        boxes["rung_done"] = box(page, "button:has-text('Rung done')")
        while page.locator(".hand-card").count() == 0:
            shot(page, f"warmup-{rung}")
            page.get_by_role("button", name="Rung done").click()
            settle(page, 350)
            rung += 1

        # ---- Work set 1: rate both hands, commit, rest
        def rate(rpe_taps: int) -> None:
            for hand in ("left", "right"):
                for _ in range(rpe_taps):
                    page.locator(f'.stepper-plus[data-field="rpe"][data-hand="{hand}"]').click()
                    page.wait_for_timeout(120)

        shot(page, "workset-1")
        rate(1)
        page.get_by_role("button", name="Set done").click()
        settle(page, 700)

        # Rest ring flipbook: pin Date.now to "rest started + N seconds" and
        # let the page's own 1 s ticker re-render the ring from the stored
        # rest_ends_at -- real app pixels, deterministic time.
        page.evaluate(
            """() => { const start = Date.now();
            window.__restAt = s => { window.__now = start + s * 1000; };
            window.__restAt(0);
            Date.now = () => window.__now; }"""
        )
        boxes["rest_skip"] = box(page, "#rest-end-btn")
        page.evaluate("window.__restAt(73)")
        page.wait_for_timeout(1100)
        shot(page, "rest")
        for frame in range(REST_FRAMES + 1):
            page.evaluate(f"window.__restAt({180 * frame / REST_FRAMES})")
            page.wait_for_timeout(1050)
            page.screenshot(path=str(screens / "rest" / f"{frame:03d}.png"))
        page.evaluate("window.__restAt(185)")
        page.wait_for_timeout(1100)
        shot(page, "rest-over")
        page.locator("#rest-end-btn").click()
        settle(page, 600)

        # ---- Work set 2 (the "hero" work-set screen), with a stepper tap
        rate(1)
        shot(page, "workset-2")
        boxes["weight_plus_left"] = box(page, '.stepper-plus[data-field="weight"][data-hand="left"]')
        boxes["weight_value_left"] = box(page, '[data-role="weight-display"][data-hand="left"]')
        boxes["set_done"] = box(page, "button:has-text('Set done')")
        page.locator('.stepper-plus[data-field="weight"][data-hand="left"]').click()
        page.wait_for_timeout(250)
        shot(page, "workset-2-bumped")
        page.locator('.stepper-minus[data-field="weight"][data-hand="left"]').click()
        page.wait_for_timeout(250)
        page.get_by_role("button", name="Set done").click()
        settle(page, 600)
        page.locator("#rest-end-btn").click()
        settle(page, 600)
        rate(2)
        page.get_by_role("button", name="Set done").click()
        settle(page, 600)

        # ---- Summary: backdate the start, rate the session, add a note
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE training_sessions SET started_at = "
                "datetime(started_at, '-41 minutes') WHERE finished_at IS NULL"
            )
        page.reload()
        settle(page)
        page.locator(".rpe-chip", has_text="7").first.click()
        settle(page, 500)
        page.locator("textarea").first.fill("Crimps felt strong. Right hand steady.")
        page.locator("textarea").first.blur()
        settle(page, 700)
        shot(page, "summary")
        page.locator(".summary-finish-btn").click()
        settle(page, 700)
        shot(page, "today-done")

        browser.close()

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("db", type=Path)
    args = parser.parse_args()
    main(args.out, args.db)
