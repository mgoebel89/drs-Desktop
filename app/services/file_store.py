"""Datei-Storage für App-eigene Uploads (Bilder, Anhänge).

Pro Datei eine UUID-Mappe unter `<data_dir>/files/<uuid>/`. Der Original-
Dateiname bleibt erhalten — eine UUID kann genau eine Datei enthalten.
Das Mapping UUID → User wird in der DB-Tabelle `app_files` hinterlegt,
damit Zugriff auf eigene Dateien beschränkt werden kann.

Diese Schicht ist absichtlich klein gehalten: sie kennt die Filesystem-
Layout, das Pfad-Sanitizing und das ID-Vergabe-Schema. Der HTTP-Endpoint
liegt in `app/routers/files.py`.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import settings


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".pdf", ".txt", ".md",
}
MAX_BYTES = 8 * 1024 * 1024  # 8 MB


def _files_root() -> Path:
    root = Path(settings.data_dir) / "files"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(name: str) -> str:
    """Restriktiv: nur ASCII-Buchstaben/Zahlen/._- erlaubt. Mehrfach-Punkte
    werden zu '_', Pfad-Komponenten ('/', '\\') entfernt. Leere/zu lange
    Namen werden auf 'datei' / 100 Zeichen begrenzt."""
    base = name.replace("\\", "/").split("/")[-1].strip() or "datei"
    base = _SAFE_NAME_RE.sub("_", base)
    base = base.strip("._-") or "datei"
    if len(base) > 100:
        stem, _, ext = base.rpartition(".")
        base = (stem[: 95] + "." + ext) if ext else base[:100]
    return base


def has_allowed_ext(name: str) -> bool:
    return Path(name.lower()).suffix in _ALLOWED_EXT


def store(payload: bytes, original_name: str) -> tuple[str, str]:
    """Schreibt `payload` unter neuer UUID-Mappe. Liefert (uuid, filename)."""
    if len(payload) > MAX_BYTES:
        raise ValueError(f"Datei zu groß (max {MAX_BYTES // (1024*1024)} MB)")
    fname = safe_filename(original_name)
    if not has_allowed_ext(fname):
        raise ValueError("Dateiendung nicht erlaubt")
    file_uuid = uuid.uuid4().hex
    folder = _files_root() / file_uuid
    folder.mkdir(parents=True, exist_ok=False)
    (folder / fname).write_bytes(payload)
    return file_uuid, fname


def resolve(file_uuid: str, filename: str) -> Path | None:
    """Sucht die physische Datei. UUID-Format wird geprüft, sonst None."""
    if not re.fullmatch(r"[a-f0-9]{32}", file_uuid or ""):
        return None
    safe = safe_filename(filename)
    p = _files_root() / file_uuid / safe
    if not p.is_file():
        return None
    return p


def delete(file_uuid: str) -> bool:
    if not re.fullmatch(r"[a-f0-9]{32}", file_uuid or ""):
        return False
    folder = _files_root() / file_uuid
    if not folder.is_dir():
        return False
    for f in folder.iterdir():
        try:
            f.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        return False
    return True
