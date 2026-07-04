from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response


SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2
HASH_VERSION = "1"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(24)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return "$".join(
        [
            "scrypt",
            HASH_VERSION,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64encode(salt),
            _b64encode(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, version, n, r, p, encoded_salt, encoded_digest = password_hash.split("$")
        if algorithm != "scrypt" or version != HASH_VERSION:
            return False
        salt = _b64decode(encoded_salt)
        expected = _b64decode(encoded_digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@dataclass
class LoginAttempt:
    failures: int = 0
    locked_until: float = 0


class AuthManager:
    def __init__(self) -> None:
        password_hash = os.getenv("GOOFISH_ADMIN_PASSWORD_HASH", "").strip()
        plain_password = os.getenv("GOOFISH_ADMIN_PASSWORD", "")
        self.enabled = bool(password_hash or plain_password)
        self.password_hash = password_hash or (hash_password(plain_password) if plain_password else "")
        self.cookie_name = os.getenv("GOOFISH_AUTH_COOKIE", "goofish_session")
        self.session_max_age = int(os.getenv("GOOFISH_SESSION_MAX_AGE_SECONDS", "86400"))
        self.cookie_secure = os.getenv("GOOFISH_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
        configured_secret = os.getenv("GOOFISH_SESSION_SECRET", "").strip()
        self.session_secret = (
            configured_secret.encode("utf-8") if configured_secret else secrets.token_bytes(48)
        )
        self._attempts: dict[str, LoginAttempt] = {}

    def verify_login(self, password: str, client_key: str) -> bool:
        if not self.enabled:
            return True
        now = time.time()
        attempt = self._attempts.setdefault(client_key, LoginAttempt())
        if attempt.locked_until > now:
            return False
        ok = verify_password(password, self.password_hash)
        if ok:
            self._attempts.pop(client_key, None)
            return True
        attempt.failures += 1
        if attempt.failures >= 5:
            attempt.locked_until = now + min(900, 30 * (attempt.failures - 4))
        return False

    def create_session_cookie(self, response: Response) -> None:
        token = self._create_session_token()
        response.set_cookie(
            self.cookie_name,
            token,
            max_age=self.session_max_age,
            httponly=True,
            secure=self.cookie_secure,
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(self.cookie_name, path="/")

    def is_authenticated(self, request: Request) -> bool:
        if not self.enabled:
            return True
        token = request.cookies.get(self.cookie_name)
        return bool(token and self._verify_session_token(token))

    def client_key(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _create_session_token(self) -> str:
        payload = {
            "exp": int(time.time()) + self.session_max_age,
            "iat": int(time.time()),
            "nonce": secrets.token_urlsafe(18),
        }
        encoded_payload = _b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = self._sign(encoded_payload)
        return f"{encoded_payload}.{signature}"

    def _verify_session_token(self, token: str) -> bool:
        try:
            encoded_payload, signature = token.split(".", 1)
            if not hmac.compare_digest(signature, self._sign(encoded_payload)):
                return False
            payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
            return isinstance(payload, dict) and int(payload.get("exp", 0)) > int(time.time())
        except (ValueError, TypeError, json.JSONDecodeError):
            return False

    def _sign(self, encoded_payload: str) -> str:
        return _b64encode(
            hmac.new(self.session_secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        )


def auth_status_payload(manager: AuthManager, request: Request) -> dict[str, Any]:
    return {
        "enabled": manager.enabled,
        "authenticated": manager.is_authenticated(request),
    }


auth_manager = AuthManager()
