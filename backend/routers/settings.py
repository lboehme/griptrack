"""Settings tab (#151): the list page and its small detail pages.

Shallow adapters only: `backend.account_settings` assembles what each page
shows, and the writes go through the modules that own them. The old
Profile/Plates POST endpoints (`/profile/*`, `/plates`) keep working and
answer through `saved_response`, so every settings form autosaves the same
way: an htmx request gets the "Saved ✓" toast fragment, a plain form post
a 303 back to its settings page with `?saved=<key>`.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

from backend import account_settings, auth, plates, training_log
from backend.db import get_session
from backend.limits import MAX_TOGGLE_LENGTH
from backend.models import User
from backend.templating import templates

router = APIRouter()

MAX_SAVED_KEY_LENGTH = 32


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def saved_response(request: Request, key: str) -> Response:
    """The shared answer for every settings write: the toast fragment for
    htmx (swapped into #log-sheet-slot, the same toast the ＋ Log sheet
    uses), else a 303 back to the page the form lives on."""
    if is_htmx(request):
        return templates.TemplateResponse(
            request, "_log_toast.html", {"toast": account_settings.saved_message(key)}
        )
    return RedirectResponse(f"{account_settings.PAGES[key]}?saved={key}", status_code=303)


def _page(request: Request, template: str, user: User, saved: str | None, **context):
    return templates.TemplateResponse(
        request,
        template,
        {"user": user, "toast": account_settings.saved_message(saved), **context},
    )


SavedQuery = Query(default=None, max_length=MAX_SAVED_KEY_LENGTH)


@router.get("/settings")
def settings_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return _page(
        request,
        "settings.html",
        user,
        saved,
        view=account_settings.settings_view(session, user),
    )


@router.get("/settings/name")
def name_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.current_user),
):
    return _page(request, "settings_name.html", user, saved)


@router.get("/settings/training")
def training_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return _page(
        request,
        "settings_training.html",
        user,
        saved,
        protocol=training_log.get_protocol(session, user),
    )


@router.get("/settings/progression")
def progression_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return _page(
        request,
        "settings_progression.html",
        user,
        saved,
        view=account_settings.progression_view(session, user),
    )


@router.get("/settings/plates")
def plates_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return _page(
        request,
        "settings_plates.html",
        user,
        saved,
        rack=plates.rack_view(session, user),
        back="/settings/plates",
    )


@router.get("/settings/restore")
def restore_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.current_user),
):
    return _page(request, "settings_restore.html", user, saved)


@router.get("/settings/about")
def about_page(request: Request, user: User = Depends(auth.current_user)):
    return _page(request, "settings_about.html", user, None)


@router.get("/settings/admin")
def admin_page(
    request: Request,
    saved: str | None = SavedQuery,
    user: User = Depends(auth.require_admin),
):
    # Server build only (ADR-0013): the WebView build has no invites, no
    # other users and no grip-type admin, so the page doesn't exist there.
    if request.app.state.webview_build:
        raise HTTPException(status_code=404)
    return _page(request, "settings_admin.html", user, saved)


@router.post("/settings/rest-sound")
def set_rest_sound(
    request: Request,
    rest_sound: str = Form(max_length=MAX_TOGGLE_LENGTH),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Settings → Rest alerts: the per-user Rest sound (#148, ADR-0015),
    moved here from the rest step. htmx gets the re-rendered switch row
    plus the toast (out of band); a plain post a 303 back to Settings."""
    if rest_sound not in ("on", "off"):
        return HTMLResponse("Rest sound must be on or off.", status_code=400)
    training_log.set_rest_sound(session, user, rest_sound == "on")
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "_settings_sound.html",
            {"user": user, "toast": account_settings.saved_message("sound"), "oob_toast": True},
        )
    return saved_response(request, "sound")
