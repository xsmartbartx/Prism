"""Encrypt credentials Prism must keep (database source passwords) at rest.

Fernet (AES-128-CBC with HMAC-SHA256), keyed from the instance secret key with
HKDF, so a stolen database dump alone reveals no password. If the instance
secret key changes, sealed values can no longer be opened; the caller asks the
user to enter the password again.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from core.errors import PrismError

_INFO = b"prism source credentials v1"


class SecretUnavailable(PrismError):
    """A stored credential cannot be decrypted (the instance secret key changed)."""


def _fernet(secret_key: str) -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def seal(value: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(value.encode()).decode()


def unseal(token: str | None, secret_key: str) -> str:
    if not token:
        raise SecretUnavailable("No password is stored for this source; enter it again")
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnavailable(
            "The stored password can no longer be read (the server's secret key changed); "
            "enter it again"
        ) from exc
