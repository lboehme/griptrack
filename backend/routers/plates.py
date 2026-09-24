from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from backend import auth, plates
from backend.db import get_session
from backend.limits import MAX_PLATE_COUNT, MAX_PLATE_WEIGHT
from backend.models import User
from backend.routers.settings import is_htmx, saved_response
from backend.templating import templates

router = APIRouter()

# Where a no-JS tap lands back: the plate rack lives on these two pages
# only. Anything else falls back to Settings → Plates (never an open
# redirect).
TAP_RETURN_PAGES = ("/settings/plates", "/welcome/plates")
MAX_BACK_LENGTH = 32


@router.post("/plates")
def set_plate(
    request: Request,
    weight: float = Form(gt=0, le=MAX_PLATE_WEIGHT),
    count: int = Form(ge=0, le=MAX_PLATE_COUNT),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    plates.set_plate(session, user, weight, count)
    return saved_response(request, "plates")


@router.post("/plates/tap")
def tap_plate(
    request: Request,
    weight: float = Form(gt=0, le=MAX_PLATE_WEIGHT),
    back: str | None = Form(default=None, max_length=MAX_BACK_LENGTH),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
):
    """Tap-to-count (#151): one more of this plate, wrapping to 0 past
    plates.TAP_CYCLE_MAX. htmx swaps just the tapped plate's count badge
    (plus the "what can I load" line, out of band); a plain form post goes
    back to the page the rack is on."""
    count = plates.tap_plate(session, user, weight)
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "_plate_tap.html",
            {
                "user": user,
                "plate": {"weight": weight, "count": count},
                "rack": plates.rack_view(session, user),
            },
        )
    return RedirectResponse(
        back if back in TAP_RETURN_PAGES else "/settings/plates", status_code=303
    )


@router.get("/plates")
def plates_page(user: User = Depends(auth.current_user)):
    """The old Plates page moved into Settings (#151)."""
    return RedirectResponse("/settings/plates", status_code=303)
