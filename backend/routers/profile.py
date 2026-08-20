from datetime import date as date_type

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from backend import archive, auth, training_log
from backend.db import get_session
from backend.limits import (
    MAX_EDGE_MM,
    MAX_MAX_SETS,
    MAX_NAME_LENGTH,
    MAX_REP_MAX,
    MAX_REP_MIN,
    MAX_REP_TARGET,
    MAX_REST_SECONDS,
    MAX_WEIGHT,
    MIN_MAX_SETS,
    MIN_REP_MAX,
    MIN_REP_MIN,
    MIN_REP_TARGET,
    MIN_REST_SECONDS,
)
from backend.models import (
    VALID_PROGRESSION_PATHS,
    BodyWeightLog,
    GripType,
    TrainingProtocol,
    User,
)
from backend.templating import templates

router = APIRouter()


@router.get("/profile")
def profile(
    request: Request,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    all_settings = training_log.list_progression_settings(session, user)
    combo_progressions = [
        ps for ps in all_settings if ps.grip_type_id is not None and ps.edge_mm is not None
    ]
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "protocol": training_log.get_protocol(session, user),
            "current_bodyweight": training_log.bodyweight_at(session, user),
            "today": date_type.today().isoformat(),
            "default_progression": training_log.get_progression_settings(session, user),
            "combo_progressions": combo_progressions,
            "grip_types": session.exec(select(GripType).order_by(GripType.name)).all(),
            "grip_names": training_log.grip_names(session),
            "grip_dimension_names": training_log.grip_dimension_names(session),
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


@router.post("/profile/protocol")
def update_protocol(
    base_work_set_reps: int = Form(ge=MIN_REP_TARGET, le=MAX_REP_TARGET),
    default_rest_seconds: int = Form(ge=MIN_REST_SECONDS, le=MAX_REST_SECONDS),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    protocol = session.exec(
        select(TrainingProtocol).where(TrainingProtocol.user_id == user.id)
    ).first()
    if protocol is None:
        protocol = TrainingProtocol(
            user_id=user.id,
            base_work_set_reps=base_work_set_reps,
            default_rest_seconds=default_rest_seconds,
        )
    else:
        protocol.base_work_set_reps = base_work_set_reps
        protocol.default_rest_seconds = default_rest_seconds
    session.add(protocol)
    session.commit()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/progression")
def update_progression(
    path: str = Form(default="weight"),
    rep_min: int = Form(ge=MIN_REP_MIN, le=MAX_REP_MIN),
    rep_max: int = Form(ge=MIN_REP_MAX, le=MAX_REP_MAX),
    max_sets: int = Form(ge=MIN_MAX_SETS, le=MAX_MAX_SETS),
    grip_type_id: int | None = Form(default=None),
    edge_mm: int | None = Form(default=None, gt=0, le=MAX_EDGE_MM),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    if path not in VALID_PROGRESSION_PATHS:
        return HTMLResponse("Invalid progression path.", status_code=400)
    if rep_min > rep_max:
        return HTMLResponse("rep_min cannot exceed rep_max.", status_code=400)
    if grip_type_id is not None:
        if edge_mm is None:
            return HTMLResponse("edge_mm required for combo progression.", status_code=400)
        try:
            training_log.require_grip_type(session, grip_type_id)
        except training_log.UnknownGripTypeError:
            raise HTTPException(status_code=404, detail="Unknown grip type") from None

    training_log.save_progression_settings(
        session,
        user,
        path=path,
        rep_min=rep_min,
        rep_max=rep_max,
        max_sets=max_sets,
        grip_type_id=grip_type_id,
        edge_mm=edge_mm,
    )
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/progression/delete")
def delete_progression(
    grip_type_id: int = Form(),
    edge_mm: int = Form(gt=0, le=MAX_EDGE_MM),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    training_log.delete_progression_settings(session, user, grip_type_id, edge_mm)
    return RedirectResponse("/profile", status_code=303)


@router.get("/profile/export")
def export_data(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Export the current user's data as a versioned ZIP archive (ADR-0008)."""
    archive_bytes = archive.create_archive(session, user)
    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=griptrack-export.zip"},
    )


@router.post("/profile/import")
async def import_data(
    archive_file: UploadFile = File(..., alias="archive"),
    confirm: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Restore an Export archive into the current user's **empty** account
    (ADR-0008, #102). `backend.archive` owns validation, atomicity, and the
    empty-account precondition; this handler just marshals the multipart
    upload into bytes and the outcome into a response."""
    if confirm != "yes":
        return HTMLResponse(
            "Import requires explicit confirmation.", status_code=400
        )

    upload_bytes = await archive_file.read(archive.MAX_IMPORT_UPLOAD_BYTES + 1)

    try:
        archive.restore_archive(session, user, upload_bytes)
    except archive.ArchiveError as error:
        return HTMLResponse(str(error), status_code=400)

    return RedirectResponse("/profile", status_code=303)
