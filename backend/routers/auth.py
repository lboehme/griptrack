from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from backend import auth
from backend.db import get_session
from backend.models import User
from backend.templating import templates

router = APIRouter()


@router.post("/invites")
def create_invite(
    request: Request,
    user: User = Depends(auth.require_admin),
    session: Session = Depends(get_session),
):
    invite = auth.generate_invite(session, user)
    return templates.TemplateResponse(request, "invite.html", {"invite": invite})


@router.post("/admin/reset-password")
def admin_reset_password(
    email: str = Form(),
    new_password: str = Form(),
    admin: User = Depends(auth.require_admin),
    session: Session = Depends(get_session),
):
    user = auth.reset_password(session, email, new_password)
    if user is None:
        return HTMLResponse("No user with that email.", status_code=404)
    return RedirectResponse("/", status_code=303)


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    session: Session = Depends(get_session),
):
    user = auth.authenticate(session, email, password)
    if user is None:
        return HTMLResponse("Wrong email or password.", status_code=401)
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    invite_code: str | None = Form(default=None),
    unit_pref: str = Form(default="kg"),
    session: Session = Depends(get_session),
):
    try:
        user = auth.register_user(session, email, password, invite_code, unit_pref)
    except auth.RegistrationError as error:
        return HTMLResponse(str(error), status_code=400)
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)
