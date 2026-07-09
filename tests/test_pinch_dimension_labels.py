"""Pinch dimension semantics (Issue #52 / PR #65) shipped with no tests —
this covers the display surfaces where a grip's dimension_name
("edge depth" vs "block width") should appear next to its edge_mm value:
the max-tests page (both the summary table and test history) and the
session pages (warmup/worksets subtitle)."""

from tests.helpers import get_session_page, grip_type_id, log_max_test, register


def test_max_tests_page_shows_block_width_for_pinch_and_edge_depth_for_crimp(client):
    register(client)
    log_max_test(client, "left", "pinch", 30, "2026-07-01", "20")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")

    page = client.get("/max-tests").text

    assert "block width" in page
    assert "edge depth" in page


def test_session_page_subtitle_shows_the_grips_dimension_name(client):
    register(client)
    pinch_id = grip_type_id(client, "pinch")
    log_max_test(client, "left", "pinch", 30, "2026-07-01", "20")

    page = get_session_page(
        client,
        "/session/warmup",
        {"grip_type_id": pinch_id, "edge_mm": 30, "date": "2026-07-04"},
    ).text
    assert "block width" in page

    crimp_id = grip_type_id(client, "half crimp")
    log_max_test(client, "left", "half crimp", 20, "2026-07-01", "40")

    page = get_session_page(
        client,
        "/session/warmup",
        {"grip_type_id": crimp_id, "edge_mm": 20, "date": "2026-07-04"},
    ).text
    assert "edge depth" in page
