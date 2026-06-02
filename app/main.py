from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.routers import auth as auth_router
from app.routers import setup as setup_router
from app.routers import users as users_router
from app.routers import profile as profile_router
from app.routers import worksheets as worksheets_router
from app.routers import settings as settings_router
from app.routers import help as help_router
from app.models import User
from app.templating import templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="DRS Unterrichtsmaterial")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(setup_router.router)
app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(profile_router.router)
app.include_router(worksheets_router.router)
app.include_router(settings_router.router)
app.include_router(help_router.router)


@app.get("/")
def root(request: Request, db: Annotated[Session, Depends(get_db)]):
    # First-Run: solange noch kein Nutzer existiert, zur Setup-Seite leiten.
    if db.query(User.id).first() is None:
        return RedirectResponse(url="/setup", status_code=303)
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if user.must_change_pw:
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request, "home.html", {"user": user})


@app.get("/health")
def health():
    return {"status": "ok"}
