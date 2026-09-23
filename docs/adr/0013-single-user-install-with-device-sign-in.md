# On the phone, an install is one person, signed in by the device

Decided 2026-09-23, in the redesign grill that followed the UI review
(`docs/ui-review-2026-09.md`). Amends ADR-0004 (invite-only registration) and
ADR-0006 (personal instrument) **for the Android build only**.

ADR-0004 and ADR-0006 assume one shared server: the owner plus invited friends,
each with a password, an admin who issues invites and resets passwords, and
session cookies that expire. The Android pivot (PRD #93) removed that server.
Each phone now runs its own copy of the backend on `127.0.0.1` with its own
SQLite file, so a friend installs their own copy. On the phone, invites, admin
and password reset protect nothing. Login is pure friction, and the default
14-day cookie lifetime logs you out at the board.

## Decision

**In the WebView build (`GRIPTRACK_WEBVIEW_BUILD=1`), an install belongs to exactly
one person, who is signed in automatically by the Android shell. The server
build keeps ADR-0004 unchanged.**

- **First run replaces registration.** Three screens (name and units, plates,
  first max test or skip) create the single local `User`. It gets an unusable
  random password hash and `is_admin = True`, so existing admin-gated code paths
  keep working without special cases.
- **Device sign-in, not open access.** Other apps on the phone can reach
  `127.0.0.1:<port>`, so "no login" must not mean "the server trusts every
  request".
  - The launcher (`backend/launcher.py`) provisions a random **device token** in
    the app-private data directory, alongside the session secret it already
    persists.
  - A WebView-build-only endpoint exchanges that token (constant-time compare)
    for the normal signed session cookie.
  - The Kotlin shell reads the same file and performs the exchange before the
    first page load.
  - App-private storage is unreadable to other apps, so they can still reach the
    port but can't get a session.
  - The cookie is long-lived. `session_version` revocation stays as it is.
- **Hidden in the WebView build:** logout, invites, admin password reset, the
  register page, and the bootstrap token. The routes stay in the codebase
  (registered only for the server build), and so do their tests. Nothing is
  deleted, because the self-hosting path (ADR-0006) still needs them.

## Why

- A phone's own screen lock already gates the device. A second password inside
  the app adds friction without protecting anything that isn't already
  protected.
- The device token keeps the loopback server's security property ("only this
  app can act as the user") without asking the user for anything.
- Keeping the multi-user code behind the build flag preserves the open-source
  self-hosting future without forking the app.

## Consequences

- The auth module gains a device-sign-in path and a WebView-only first-run flow.
  Tests cover both flags: the server build must still require a password and
  refuse the device endpoint; the WebView build must refuse a wrong or missing
  device token.
- Import and export (ADR-0008) are unchanged. Restore-into-empty still works
  right after first run.
- Revisit if a shared device (e.g. a family tablet at a home board) ever needs
  more than one person per install.
