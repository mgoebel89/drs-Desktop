"""Crypto-Helpers: Argon2id für Passwörter, AES-GCM für gespeicherte Secrets."""
import hashlib
import os

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


def _master_key() -> bytes:
    """Leite einen 32-Byte-Key aus settings.secret_key ab (SHA-256)."""
    return hashlib.sha256(settings.secret_key.encode("utf-8")).digest()


def encrypt_secret(plaintext: str) -> bytes:
    """AES-GCM verschlüsseln. Liefert nonce(12) || ciphertext || tag(16)."""
    if not plaintext:
        return b""
    aes = AESGCM(_master_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ct


def decrypt_secret(blob: bytes | None) -> str:
    if not blob:
        return ""
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(_master_key())
    return aes.decrypt(nonce, ct, associated_data=None).decode("utf-8")


def mask_key(plain: str, keep: int = 4) -> str:
    if not plain:
        return ""
    if len(plain) <= keep + 4:
        return "•" * len(plain)
    return plain[:7] + "…" + plain[-keep:]
