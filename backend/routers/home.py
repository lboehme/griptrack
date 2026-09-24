from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth, climbing, today, training_log
from backend.db import get_session
from backend.limits import MAX_EDGE_MM, MAX_ROW_ID, MAX_SESSION_NUMBER
from backend.models import User
from backend.templating import templates

router = APIRouter()


def _require_grip(session: Session, grip_type_id: int | None) -> None:
    if grip_type_id is None:
        return
    try:
        training_log.require_grip_type(session, grip_type_id)
    except training_log.UnknownGripTypeError:
        raise HTTPException(status_code=404, detail="Unknown grip type") from None


def _combo_query(grip_type_id: int | None, edge_mm: int | None) -> str:
    if grip_type_id is None or edge_mm is None:
        return ""
    return f"grip_type_id={grip_type_id}&edge_mm={edge_mm}"


@router.get("/")
def home(
    request: Request,
    log: str | None = Query(default=None, max_length=16),
    change: bool = Query(default=False),
    saved: str | None = Query(default=None, max_length=16),
    grade_warning: bool = Query(default=False),
    grip_type_id: int | None = Query(default=None, ge=1, le=MAX_ROW_ID),
    edge_mm: int | None = Query(default=None, gt=0, le=MAX_EDGE_MM),
    user: User | None = Depends(auth.optional_user),
    session: Session = Depends(get_session),
):
    """Today (#149): the coach home. Renders for everyone; auth.optional_user
    hides the session-cookie inspection (and the revoked-session check), so
    the home page never greets a revoked session as logged-in.

    `?log=climb|bodyweight|tweak` opens the ＋ Log sheet server-side (the
    no-JS path, and the ＋ tab's plain href); `?change=1` opens the Change
    picker; grip_type_id/edge_mm are the picker's choice."""
    if (
        request.app.state.webview_build
        and user is None
        and not auth.any_user_exists(session)
    ):
        # WebView build, no device user yet: first run replaces both the
        # anonymous landing card and registration (ADR-0013).
        return RedirectResponse("/welcome", status_code=303)
    if user is None:
        return templates.TemplateResponse(request, "home.html", {"user": None})
    _require_grip(session, grip_type_id)
    now = date_type.today()
    view = today.today_view(session, user, now, grip_type_id, edge_mm)
    context: dict = {
        "user": user,
        "view": view,
        "combo_query": _combo_query(grip_type_id, edge_mm),
        "toast": today.SAVED_MESSAGES.get(saved or ""),
        "grade_warning": climbing.GRADE_NOT_RECOGNIZED_MESSAGE if grade_warning else None,
    }
    if log in today.SHEET_TABS:
        context["sheet"] = today.sheet_view(session, user, log, now)
    if change:
        context["picker"] = today.picker_view(session, user, grip_type_id, edge_mm)
    return templates.TemplateResponse(request, "home.html", context)


@router.get("/today/change")
def change_picker(
    request: Request,
    grip_type_id: int | None = Query(default=None, ge=1, le=MAX_ROW_ID),
    edge_mm: int | None = Query(default=None, gt=0, le=MAX_EDGE_MM),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The Change picker as an htmx fragment (opened in place, no history
    entry). `/?change=1` is the same picker server-side."""
    _require_grip(session, grip_type_id)
    return templates.TemplateResponse(
        request,
        "_today_picker.html",
        {
            "user": user,
            "picker": today.picker_view(session, user, grip_type_id, edge_mm),
            "view": today.today_view(session, user, date_type.today(), grip_type_id, edge_mm),
        },
    )


@router.post("/today/lighter")
def toggle_go_lighter(
    date: date_type = Form(),
    on: bool = Form(),
    session_number: int | None = Form(default=None, ge=1, le=MAX_SESSION_NUMBER),
    grip_type_id: int | None = Form(default=None, ge=1, le=MAX_ROW_ID),
    edge_mm: int | None = Form(default=None, gt=0, le=MAX_EDGE_MM),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Go lighter toggle: marks (or unmarks) today's session is_deload.
    Answers with a 303 back to Today either way -- htmx's XHR follows it
    and swaps #today-root in place, a plain form post just lands there."""
    _require_grip(session, grip_type_id)
    if training_log.is_past_date(date) and training_log.find_session(session, user, date) is None:
        return HTMLResponse("No session on that date.", status_code=400)
    today.set_go_lighter(session, user, date, on, session_number)
    query = _combo_query(grip_type_id, edge_mm)
    return RedirectResponse("/" + (f"?{query}" if query else ""), status_code=303)
