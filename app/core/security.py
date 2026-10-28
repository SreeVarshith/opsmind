"""Login and roles: password hashing, a small user store, and JWT access tokens.

- Passwords are never stored: only a salted PBKDF2-SHA256 hash (Python standard library).
- After login the API returns a signed JWT. Every protected request sends it as
  `Authorization: Bearer <token>`; the signature proves it was issued by this server.
- Users live in config/users.json (git-ignored). Create them with scripts/create_user.py.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import get_settings
from app.rag.access import ROLE_ACCESS, levels_for_role

PBKDF2_ITERATIONS = 310_000  # OWASP recommendation for PBKDF2-SHA256
ALGORITHM = "HS256"


class User(BaseModel):
    username: str
    role: str

    @property
    def access(self) -> list[str]:
        return levels_for_role(self.role)


# ---------- passwords ----------
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITERATIONS, base64.b64encode(salt).decode(),
                                       base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(candidate, base64.b64decode(digest))  # constant time: no timing leaks
    except (ValueError, TypeError):
        return False


# ---------- user store ----------
class UserStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def add(self, username: str, password: str, role: str) -> None:
        if role not in ROLE_ACCESS:
            raise ValueError(f"unknown role '{role}', use one of {list(ROLE_ACCESS)}")
        users = self._load()
        users[username] = {"role": role, "password_hash": hash_password(password)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(users, indent=2), encoding="utf-8")

    def authenticate(self, username: str, password: str) -> User | None:
        record = self._load().get(username)
        # Hash even for unknown users so response time does not reveal which usernames exist.
        stored = record["password_hash"] if record else hash_password("dummy-password")
        if verify_password(password, stored) and record:
            return User(username=username, role=record["role"])
        return None


def get_user_store() -> UserStore:
    return UserStore(Path(get_settings().users_file))


# ---------- tokens ----------
def create_token(user: User, secret: str, ttl_minutes: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user.username, "role": user.role, "iat": now, "exp": now + ttl_minutes * 60},
                      secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> User:
    claims = jwt.decode(token, secret, algorithms=[ALGORITHM])  # checks signature and expiry
    return User(username=claims["sub"], role=claims["role"])


def new_secret() -> str:
    return secrets.token_urlsafe(48)


# ---------- FastAPI dependencies ----------
bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    s = get_settings()
    if not s.auth_enabled:
        return User(username="local-dev", role="admin")
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in", headers={"WWW-Authenticate": "Bearer"})
    if not s.jwt_secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "JWT_SECRET is not configured")
    try:
        return decode_token(creds.credentials, s.jwt_secret)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, log in again") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from None


def require_role(*roles: str):
    def check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {' or '.join(roles)}")
        return user
    return check
