from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.routers import auth as auth_router
from app.routers import users as users_router
from app.routers import profile as profile_router
from app.routers import worksheets as worksheets_router


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="DRS Unterrichtsmaterial")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(profile_router.router)
app.include_router(worksheets_router.router)


@app.get("/")
def root(request: Request, db: Annotated[Session, Depends(get_db)]):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if user.must_change_pw:
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request, "home.html", {"user": user})


@app.get("/health")
def health():
    return {"status": "ok"}
