"""Progress tab (#150): the headline page plus its Go deeper detail pages.
Shallow adapters over backend.progress / backend.analytics. The old
Trends (/dashboard), History (/history) and Max tests (/max-tests) GETs
now 303 here."""

from datetime import date as date_type
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from backend import analytics, auth, progress, training_log
from backend.db import get_session
from backend.limits import MAX_EDGE_MM, MAX_ROW_ID
from backend.models import User
from backend.templating import templates

router = APIRouter()

RangeKey = Literal["6w", "3m", "all"]

# Go deeper detail pages whose content moved unchanged from /dashboard:
# section key -> page title. Registered after /progress/maxes and
# /progress/timeline so those literal paths win the match.
DETAIL_SECTIONS = {
    "volume": "Training volume",
    "balance": "Left/right balance",
    "grade": "Strength vs grade",
}


def _redirect(path: str, request: Request) -> RedirectResponse:
    query = request.url.query
    return RedirectResponse(path + (f"?{query}" if query else ""), status_code=303)


@router.get("/progress")
def progress_page(
    request: Request,
    grip_type_id: int | None = Query(default=None, ge=1, le=MAX_ROW_ID),
    edge_mm: int | None = Query(default=None, gt=0, le=MAX_EDGE_MM),
    range_key: RangeKey = Query(default=progress.DEFAULT_RANGE, alias="range"),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """The headline page. Combo and range are plain query params (the
    no-JS path); the pickers' htmx swaps get just #progress-root."""
    if grip_type_id is not None:
        try:
            training_log.require_grip_type(session, grip_type_id)
        except training_log.UnknownGripTypeError:
            raise HTTPException(status_code=404, detail="Unknown grip type") from None
    view = progress.progress_view(
        session, user, date_type.today(), grip_type_id, edge_mm, range_key
    )
    template = "_progress_body.html" if request.headers.get("HX-Request") else "progress.html"
    return templates.TemplateResponse(request, template, {"user": user, "view": view})


@router.get("/progress/maxes")
def progress_maxes(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "progress_maxes.html",
        {
            "user": user,
            **progress.maxes_view(session, user),
            "today": date_type.today().isoformat(),
        },
    )


@router.get("/progress/timeline")
def progress_timeline(
    request: Request,
    show: Literal["all", "climbs"] = Query(default="all"),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    climbs_only = show == "climbs"
    return templates.TemplateResponse(
        request,
        "progress_timeline.html",
        {
            "user": user,
            "climbs_only": climbs_only,
            "grip_names": training_log.grip_names(session),
            "grip_dimension_names": training_log.grip_dimension_names(session),
            "weeks": progress.timeline_view(
                session, user, date_type.today(), climbs_only=climbs_only
            ),
        },
    )


@router.get("/progress/{section}")
def progress_detail(
    request: Request,
    section: Literal["volume", "balance", "grade"],
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "progress_detail.html",
        {
            "user": user,
            "section": section,
            "title": DETAIL_SECTIONS[section],
            **analytics.dashboard_view(session, user),
        },
    )


# ---------------------------------------------------------- old routes


@router.get("/dashboard")
def dashboard_redirect(request: Request, user: User = Depends(auth.current_user)):
    return _redirect("/progress", request)


@router.get("/history")
def history_redirect(request: Request, user: User = Depends(auth.current_user)):
    return _redirect("/progress/timeline", request)


@router.get("/max-tests")
def max_tests_redirect(request: Request, user: User = Depends(auth.current_user)):
    return _redirect("/progress/maxes", request)
