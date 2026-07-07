from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from backend import analytics, auth, charts, training_log
from backend.db import get_session
from backend.limits import MAX_EDGE_MM
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.get("/dashboard/volume.svg")
def volume_chart(
    hand: str = Query(),
    grip_type_id: int = Query(),
    edge_mm: int = Query(gt=0, le=MAX_EDGE_MM),
    theme: str = Query(default="light"),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    trend = analytics.training_volume_trend(session, user, hand, grip_type_id, edge_mm)
    if not trend:
        return Response(status_code=404)
    svg = charts.render_volume_chart(
        trend, theme if theme in charts.THEMES else "light"
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/dashboard")
def dashboard_page(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    combos = []
    for combo in training_log.trained_combinations(session, user):
        trend = analytics.training_volume_trend(
            session, user, combo["hand"], combo["grip_type_id"], combo["edge_mm"]
        )
        if not trend:
            continue
        combos.append(
            {
                **combo,
                "trend": trend,
                "plateau": analytics.plateau_flag(trend),
                "overtraining": analytics.overtraining_warning(trend),
            }
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "combos": combos,
            "correlation": analytics.strength_grade_correlation(session, user),
        },
    )
