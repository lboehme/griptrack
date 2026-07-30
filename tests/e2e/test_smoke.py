"""The one trivial smoke spec for the pytest-playwright harness (issue
#78). Proves the browser layer actually boots the app and drives a real
Chromium against it. Deliberately not a second functional suite — future
client-behavior specs (stepper walking, edit mode, rest countdown) belong
to the Focus redesign issues, not here."""


def test_authenticated_home_page_renders(authenticated_page):
    assert "Logged in as e2e@example.com" in authenticated_page.content()
