from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from backend import analytics, auth, training_log
from backend.db import get_session
from backend.models import User
from backend.templating import templates

router = APIRouter()


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
    # Fed to the client-side uPlot chart via the JSON-in-DOM idiom (see
    # worksets.html's ladder-data/saved-sets-data precedent) -- one entry
    # per trained combo, dates serialized to ISO strings since Jinja's
    # tojson can't encode date objects directly.
    chart_data = [
        {
            "combo": f"{combo['hand']}|{combo['grip_name']}|{combo['edge_mm']}",
            "dates": [d.isoformat() for d, _ in combo["trend"]],
            "volumes": [v for _, v in combo["trend"]],
        }
        for combo in combos
    ]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "combos": combos,
            "chart_data": chart_data,
            "correlation": analytics.strength_grade_correlation(session, user),
        },
    )
