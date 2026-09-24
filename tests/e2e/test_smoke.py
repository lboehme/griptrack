"""The one trivial smoke spec for the pytest-playwright harness (issue
#78). Proves the browser layer actually boots the app and drives a real
Chromium against it. Deliberately not a second functional suite — future
client-behavior specs (stepper walking, edit mode, rest countdown) belong
to the Focus redesign issues, not here."""


def test_authenticated_home_page_renders(authenticated_page):
    # Today (#149): the coach home, with the new tab bar.
    assert authenticated_page.locator("#today-root").is_visible()
    assert authenticated_page.locator(".tabbar .tabbar-log").is_visible()
