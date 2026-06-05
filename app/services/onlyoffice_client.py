"""OnlyOffice Document Server — Editor-Config + JWT-Signierung.

Die App stellt OnlyOffice die Datei über einen App-internen URL bereit
(authentifiziert via einmaligem File-Token). OnlyOffice lädt sie per HTTP
und liefert das Editor-Frontend als Iframe.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from app.config import settings


def _jwt_secret() -> str:
    p = Path(settings.onlyoffice_jwt_path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def is_configured() -> bool:
    return bool(settings.onlyoffice_url) and bool(_jwt_secret())


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_jwt(payload: dict) -> str:
    """Minimaler HS256-JWT-Encoder. OnlyOffice akzeptiert nur HS256."""
    secret = _jwt_secret().encode("utf-8")
    header = {"alg": "HS256", "typ": "JWT"}
    seg1 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    seg2 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{seg1}.{seg2}".encode("ascii")
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f"{seg1}.{seg2}.{_b64url(sig)}"


# In-Memory Token-Store für eine kurze Lebenszeit (5 min). Der Browser des
# Lehrers triggert OnlyOffice, OnlyOffice lädt die Datei innerhalb von Sekunden.
_FILE_TOKENS: dict[str, dict] = {}
_TOKEN_TTL_S = 300


def issue_file_token(user_id: int, ls_id: int, filename: str) -> str:
    tok = secrets.token_urlsafe(24)
    _FILE_TOKENS[tok] = {
        "user_id": user_id,
        "ls_id": ls_id,
        "filename": filename,
        "expires_at": time.time() + _TOKEN_TTL_S,
    }
    return tok


def consume_file_token(tok: str) -> dict | None:
    info = _FILE_TOKENS.get(tok)
    if not info:
        return None
    if info["expires_at"] < time.time():
        _FILE_TOKENS.pop(tok, None)
        return None
    return info


DOC_TYPES = {
    "doc": "word", "docx": "word", "odt": "word", "rtf": "word", "txt": "word",
    "xls": "cell", "xlsx": "cell", "ods": "cell", "csv": "cell",
    "ppt": "slide", "pptx": "slide", "odp": "slide",
}


def doc_type_for(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower()
    return DOC_TYPES.get(ext)


def build_editor_config(
    *,
    public_base_url: str,
    file_url: str,
    filename: str,
    document_key: str,
    user_id: int,
    user_name: str,
    mode: str = "view",
) -> dict:
    """Baut die OnlyOffice-Editor-Config inkl. JWT-Signatur."""
    ext = filename.rsplit(".", 1)[-1].lower()
    cfg = {
        "document": {
            "fileType": ext,
            "key": document_key,
            "title": filename,
            "url": file_url,
            "permissions": {"edit": mode == "edit", "download": True, "print": True},
        },
        "documentType": doc_type_for(filename) or "word",
        "editorConfig": {
            "mode": "edit" if mode == "edit" else "view",
            "lang": "de-DE",
            "user": {"id": str(user_id), "name": user_name},
            "customization": {
                "autosave": False,
                "compactHeader": True,
                "hideRightMenu": True,
            },
        },
    }
    cfg["token"] = sign_jwt(cfg)
    return cfg
