import csv
import io
import json
import zipfile
from datetime import date as date_type
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

from backend import auth, import_restore, training_log
from backend.db import get_session
from backend.export_spec import ARCHIVE_MEMBERS, FORMAT_VERSION, MANIFEST_FILENAME, scoped_query
from backend.limits import MAX_IMPORT_UPLOAD_BYTES, MAX_NAME_LENGTH, MAX_WEIGHT
from backend.models import BodyWeightLog, TrainingSession, User
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
    """A versioned ZIP archive: `manifest.json` + one CSV per
    `backend.export_spec.ARCHIVE_MEMBERS` entry (ADR-0008). The member
    list, weight columns, and per-model user-scoping are the single shared
    spec the future importer (#102) will read too -- this function only
    turns that spec into bytes."""

    def neutralize(value):
        # A text cell starting with = + - or @ would execute as a formula
        # when the CSV is opened in a spreadsheet; prefix with a quote so
        # a shared export can't carry a payload.
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def add_csv(zf: zipfile.ZipFile, filename: str, rows, fieldnames: list[str]):
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: neutralize(v) for k, v in row.items()})
        zf.writestr(filename, csv_buffer.getvalue())

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "format_version": FORMAT_VERSION,
            "unit": user.unit_pref,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, indent=2))

        # TRAINING_SESSION-scoped members (PainReport, WarmupStepCheck,
        # SessionMaxEstimate, WorkSet) need the user's TrainingSession ids
        # to scope their query. ARCHIVE_MEMBERS lists TrainingSession
        # before all of them (see export_spec.py), so one forward pass
        # both dumps every member and, in passing, captures those ids the
        # moment the TrainingSession member itself is reached -- no
        # separate lookup pass.
        training_session_ids: list[int] = []
        for member in ARCHIVE_MEMBERS:
            query = scoped_query(member, user, training_session_ids)
            rows = session.exec(query).all()
            if member.model is TrainingSession:
                training_session_ids = [r.id for r in rows]
            renames = {col: f"{col} ({user.unit_pref})" for col in member.weight_cols}
            out_fields = [renames.get(f, f) for f in member.csv_fields]
            out_rows = [
                {renames.get(f, f): d[f] for f in member.csv_fields}
                for d in (r.model_dump() for r in rows)
            ]
            add_csv(zf, member.filename, out_rows, out_fields)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=griptrack-export.zip"}
    )


@router.post("/profile/import")
async def import_data(
    archive: UploadFile = File(...),
    confirm: str | None = Form(default=None),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Restore an Export archive into the current user's **empty** account
    (ADR-0008, #102). `backend.import_restore` owns validation, atomicity,
    and the file-PK-discard/rewiring rules -- this route just adapts the
    multipart upload into bytes and the outcome into a response."""
    if confirm != "yes":
        return HTMLResponse(
            "Import requires explicit confirmation.", status_code=400
        )

    # Bounded read: never buffer more than the cap into memory, regardless
    # of what the client claims to be sending.
    upload_bytes = await archive.read(MAX_IMPORT_UPLOAD_BYTES + 1)

    try:
        import_restore.restore_archive(session, user, upload_bytes)
    except import_restore.ImportRestoreError as error:
        return HTMLResponse(str(error), status_code=400)

    return RedirectResponse("/profile", status_code=303)
