"""SMB-Client für OMV-Share. Pro Nutzer eigene Credentials, Python-nativ via smbprotocol.

Funktionen:
- Verbindungstest
- Ordner-Lifecycle (ensure_folder, list)
- Datei-IO (read, write, stream)

Pfad-Konvention: alles wird als POSIX-Pfad innerhalb des Shares geführt.
Beispiel: //omv/drs-material/lernsituationen/LS-0001_test/aufgabe.pdf
         → share="drs-material", path="lernsituationen/LS-0001_test/aufgabe.pdf"
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

import smbclient
import smbclient.path as smbpath
from smbprotocol.exceptions import SMBException

from app.crypto import decrypt_secret, encrypt_secret
from app.models import User


@dataclass
class SmbConfig:
    host: str          # IP oder Hostname des OMV
    share: str         # Share-Name, z.B. "drs-material"
    username: str
    password: str
    vault_subpath: str = "/vault"
    material_subpath: str = "/lernsituationen"

    @property
    def base_unc(self) -> str:
        return f"\\\\{self.host}\\{self.share}"

    def unc(self, subpath: str) -> str:
        sp = subpath.replace("/", "\\").lstrip("\\")
        return f"{self.base_unc}\\{sp}" if sp else self.base_unc


def load_config(user: User) -> SmbConfig | None:
    if not user.smb_creds_enc:
        return None
    raw = decrypt_secret(user.smb_creds_enc)
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    return SmbConfig(
        host=d.get("host", "").strip(),
        share=d.get("share", "").strip(),
        username=d.get("username", "").strip(),
        password=d.get("password", ""),
        vault_subpath=(d.get("vault_subpath") or "/vault").strip() or "/vault",
        material_subpath=(d.get("material_subpath") or "/lernsituationen").strip() or "/lernsituationen",
    )


def save_config(user: User, cfg: SmbConfig) -> None:
    payload = {
        "host": cfg.host,
        "share": cfg.share,
        "username": cfg.username,
        "password": cfg.password,
        "vault_subpath": cfg.vault_subpath,
        "material_subpath": cfg.material_subpath,
    }
    user.smb_creds_enc = encrypt_secret(json.dumps(payload))


def clear_config(user: User) -> None:
    user.smb_creds_enc = None


def _register(cfg: SmbConfig) -> None:
    smbclient.register_session(
        cfg.host, username=cfg.username, password=cfg.password,
        connection_timeout=10,
    )


def test_connection(user: User) -> tuple[bool, str]:
    cfg = load_config(user)
    if not cfg:
        return False, "Keine SMB-Zugangsdaten hinterlegt."
    if not (cfg.host and cfg.share and cfg.username):
        return False, "Host, Share oder Benutzername fehlt."
    try:
        _register(cfg)
        # Versuch, das Share-Root zu listen
        smbclient.listdir(cfg.unc(""))
        return True, f"Verbunden mit \\\\{cfg.host}\\{cfg.share}"
    except SMBException as e:
        return False, f"SMB-Fehler: {e}"
    except Exception as e:
        return False, f"Verbindung fehlgeschlagen: {e}"


def ensure_folder(user: User, subpath: str) -> str:
    """Legt subpath (relativ zum Share) rekursiv an. Gibt UNC-Pfad zurück."""
    cfg = load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    _register(cfg)
    unc = cfg.unc(subpath)
    if not smbpath.exists(unc):
        smbclient.makedirs(unc, exist_ok=True)
    return unc


def list_folder(user: User, subpath: str) -> list[dict]:
    cfg = load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    _register(cfg)
    unc = cfg.unc(subpath)
    if not smbpath.exists(unc):
        return []
    entries = []
    for name in smbclient.listdir(unc):
        full = f"{unc}\\{name}"
        try:
            st = smbclient.stat(full)
        except Exception:
            continue
        is_dir = smbpath.isdir(full)
        entries.append({
            "name": name,
            "is_dir": is_dir,
            "size": 0 if is_dir else st.st_size,
            "mtime": st.st_mtime,
        })
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries


def read_file(user: User, subpath: str) -> bytes:
    cfg = load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    _register(cfg)
    with smbclient.open_file(cfg.unc(subpath), mode="rb") as f:
        return f.read()


def stream_file(user: User, subpath: str, chunk_size: int = 65536) -> Iterator[bytes]:
    cfg = load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    _register(cfg)
    with smbclient.open_file(cfg.unc(subpath), mode="rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def write_file(user: User, subpath: str, data: bytes) -> None:
    cfg = load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    _register(cfg)
    # Parent-Ordner sicherstellen
    parent = subpath.rsplit("/", 1)[0] if "/" in subpath else ""
    if parent:
        unc_parent = cfg.unc(parent)
        if not smbpath.exists(unc_parent):
            smbclient.makedirs(unc_parent, exist_ok=True)
    with smbclient.open_file(cfg.unc(subpath), mode="wb") as f:
        f.write(data)


def delete_file(user: User, subpath: str) -> None:
    cfg = load_config(user)
    if not cfg:
        raise RuntimeError("SMB nicht konfiguriert")
    _register(cfg)
    unc = cfg.unc(subpath)
    if smbpath.exists(unc):
        smbclient.remove(unc)


def material_subpath(cfg: SmbConfig, ls_folder_name: str) -> str:
    """Relativ-Pfad zum LS-Material-Ordner innerhalb des Shares."""
    base = cfg.material_subpath.strip("/")
    return f"{base}/{ls_folder_name}"


def vault_subpath(cfg: SmbConfig, note_filename: str) -> str:
    base = cfg.vault_subpath.strip("/")
    return f"{base}/{note_filename}"
