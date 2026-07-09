import csv
import io
import zipfile
from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from backend import auth, training_log
from backend.db import get_session
from backend.limits import MAX_NAME_LENGTH, MAX_WEIGHT
from backend.models import (
    BodyWeightLog,
    Climb,
    MaxWeightTest,
    PainReport,
    SessionMaxEstimate,
    TrainingSession,
    User,
    WarmupStepCheck,
    WorkSet,
)
from backend.templating import templates

router = APIRouter()


@router.get("/profile")
def profile(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "current_bodyweight": training_log.bodyweight_at(session, user),
            "today": date_type.today().isoformat(),
        },
    )


@router.post("/profile/bodyweight")
def log_bodyweight(
    date: date_type = Form(),
    weight: float = Form(gt=0, le=MAX_WEIGHT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    session.add(BodyWeightLog(user_id=user.id, date=date, weight=weight))
    session.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/name")
def update_name(
    name: str | None = Form(default=None, max_length=MAX_NAME_LENGTH),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    user.name = auth.normalize_name(name)
    session.add(user)
    session.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile")
def update_profile(
    hand_order_pref: str = Form(),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if hand_order_pref not in ("alternating", "sequential"):
        return HTMLResponse("Invalid hand order preference.", status_code=400)
    user.hand_order_pref = hand_order_pref
    session.add(user)
    session.commit()
    return RedirectResponse("/profile", status_code=303)


@router.get("/profile/export")
def export_data(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        def add_csv(filename: str, rows, fieldnames: list[str]):
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            zf.writestr(filename, csv_buffer.getvalue())

        def dump_with_units(model, query, weight_cols):
            rows = session.exec(query).all()
            fields = list(model.model_fields.keys())
            renames = {col: f"{col} ({user.unit_pref})" for col in weight_cols}
            out_fields = [renames.get(f, f) for f in fields]
            
            if not rows:
                add_csv(f"{model.__name__}.csv", [], out_fields)
                return
                
            out_rows = []
            for r in rows:
                d = r.model_dump()
                out_dict = {}
                for f in fields:
                    if f in weight_cols:
                        out_dict[renames[f]] = d[f]
                    else:
                        out_dict[f] = d[f]
                out_rows.append(out_dict)
            add_csv(f"{model.__name__}.csv", out_rows, out_fields)

        # Scoped to user directly
        dump_with_units(BodyWeightLog, select(BodyWeightLog).where(BodyWeightLog.user_id == user.id), ["weight"])
        dump_with_units(Climb, select(Climb).where(Climb.user_id == user.id), [])
        dump_with_units(MaxWeightTest, select(MaxWeightTest).where(MaxWeightTest.user_id == user.id), ["weight"])
        
        # Scoped to user via TrainingSession
        ts_rows = session.exec(select(TrainingSession).where(TrainingSession.user_id == user.id)).all()
        if ts_rows:
            add_csv(
                "TrainingSession.csv",
                [r.model_dump() for r in ts_rows],
                list(TrainingSession.model_fields.keys())
            )
            ts_ids = [ts.id for ts in ts_rows]
            
            dump_with_units(
                PainReport,
                select(PainReport).where(PainReport.training_session_id.in_(ts_ids)),
                [],
            )
            dump_with_units(
                WarmupStepCheck,
                select(WarmupStepCheck).where(
                    WarmupStepCheck.training_session_id.in_(ts_ids)
                ),
                [],
            )
            dump_with_units(
                SessionMaxEstimate,
                select(SessionMaxEstimate).where(
                    SessionMaxEstimate.training_session_id.in_(ts_ids)
                ),
                ["weight"],
            )
            dump_with_units(
                WorkSet,
                select(WorkSet).where(WorkSet.training_session_id.in_(ts_ids)),
                ["weight"],
            )

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=griptrack-export.zip"}
    )
