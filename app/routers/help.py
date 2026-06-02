"""Hilfe-Reiter: LaTeX/SI-Referenz."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import require_user
from app.models import User
from app.templating import templates

router = APIRouter()


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request, user: Annotated[User, Depends(require_user)]):
    return templates.TemplateResponse(request, "help.html", {"user": user})
