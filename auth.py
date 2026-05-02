"""JWT issuance, password hashing, and user lookup for dim_user."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import duckdb
from jose import JWTError, jwt

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET, VALID_APP_ROLES


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def normalize_role(role: str) -> str:
    s = (role or "").strip()
    if s in VALID_APP_ROLES:
        return s
    low = s.lower()
    if low == "analyst":
        return "Analyst"
    if low in ("supervisor", "super"):
        return "Supervisor"
    if low in ("auditor", "audit"):
        return "Auditor"
    if low in ("admin", "administrator"):
        return "Admin"
    return "Analyst"


def create_access_token(*, user_id: int, username: str, role: str) -> str:
    role_n = normalize_role(role)
    expire = datetime.now(UTC) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role_n,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def authenticate_user(conn: duckdb.DuckDBPyConnection, username: str, password: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT user_id, username, password_hash, role
        FROM dim_user
        WHERE lower(username) = lower(?)
        """,
        [username.strip()],
    ).fetchone()
    if not row:
        return None
    uid, uname, phash, role = row[0], row[1], row[2], row[3]
    if not verify_password(password, str(phash)):
        return None
    return {"user_id": int(uid), "username": str(uname), "role": normalize_role(str(role))}
