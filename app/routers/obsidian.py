"""Read-only Anzeige der Obsidian-Notiz einer Lernsituation."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from markdown_it import MarkdownIt
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import LearningSituation, User
from app.services import obsidian_writer
from app.templating import templates

router = APIRouter()

# Mit den Plugins, die markdown-it-py mitbringt. KaTeX + Mermaid rendern wir
# clientseitig (Browser-Libs im Template).
_md = (
    MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
    .enable("table")
    .enable("strikethrough")
)


@router.get("/ls/{ls_id}/note", response_class=HTMLResponse)
def ls_note(
    request: Request,
    ls_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    ls = db.get(LearningSituation, ls_id)
    if not ls or ls.user_id != user.id:
        raise HTTPException(404)

    raw = obsidian_writer.read_note(user, ls)
    if not raw:
        body_html = "<p class='muted'>Noch keine Notiz in der Vault.</p>"
        fm = {}
    else:
        fm, body = obsidian_writer.split_frontmatter(raw)
        # Obsidian-Wikilinks [[...]] vorab in Markdown-Links umwandeln, damit
        # der Renderer sie als Links darstellt (Ziel bleibt funktionslos in
        # der Web-Anzeige — ist für Obsidian Desktop gedacht).
        body = _wikilinks_to_md(body)
        # Vault-relative Bilder durch die Vault-Image-Bridge proxen.
        # /api/files/<uuid>/<name>-Pfade bleiben unangetastet (laden direkt).
        body = _rewrite_vault_images(body, ls.id)
        body_html = _md.render(body)

    return templates.TemplateResponse(request, "obsidian_note.html", {
        "ls": ls,
        "frontmatter": fm,
        "body_html": body_html,
    })


def _wikilinks_to_md(text: str) -> str:
    import re
    def repl(m):
        inner = m.group(1)
        if "|" in inner:
            tgt, label = inner.split("|", 1)
        else:
            tgt, label = inner, inner
        return f"[{label.strip()}]({tgt.strip()})"
    return re.sub(r"\[\[([^\]]+)\]\]", repl, text)


def _rewrite_vault_images(text: str, ls_id: int) -> str:
    """`![alt](rel/oder/abs/pfad)` umschreiben: vault-relative Pfade auf
    `/api/vault-image/<ls_id>?p=<pfad>` lenken, /api/files-, http(s)- und
    data-URLs bleiben unangetastet."""
    import re
    from urllib.parse import quote

    def repl(m):
        alt, src = m.group(1), m.group(2).strip()
        low = src.lower()
        if (
            low.startswith("/api/files/")
            or low.startswith("http://")
            or low.startswith("https://")
            or low.startswith("data:")
        ):
            return m.group(0)
        rel = src.lstrip("/")
        return f"![{alt}](/api/vault-image/{ls_id}?p={quote(rel)})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, text)
