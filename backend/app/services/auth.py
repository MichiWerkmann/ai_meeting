from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MIN_PASSWORD_LENGTH = 8
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class _UserRecord:
    id: str
    name: str
    email: str
    password_salt: str
    password_hash: str
    created_at: float
    last_login_at: float | None = None


@dataclass
class _SessionRecord:
    token: str
    user_id: str
    created_at: float
    expires_at: float


class AuthService:
    def __init__(self, file_path: Path | None = None, session_ttl_seconds: int = 30 * 24 * 60 * 60) -> None:
        self._file_path = file_path or Path(__file__).resolve().parents[2] / "runtime_users.json"
        self._session_ttl_seconds = max(60, int(session_ttl_seconds))
        self._lock = threading.Lock()
        self._users_by_id: dict[str, _UserRecord] = {}
        self._users_by_email: dict[str, _UserRecord] = {}
        self._sessions_by_token: dict[str, _SessionRecord] = {}
        self._load()

    def register_user(self, name: str, email: str, password: str) -> tuple[dict[str, Any], str]:
        normalized_name = self._normalize_name(name)
        normalized_email = self._normalize_email(email)
        normalized_password = self._normalize_password(password)
        with self._lock:
            if normalized_email in self._users_by_email:
                raise ValueError("Diese E-Mail-Adresse ist bereits registriert.")
            now = time.time()
            user_id = uuid.uuid4().hex
            salt = secrets.token_hex(16)
            password_hash = self._hash_password(normalized_password, salt)
            user = _UserRecord(
                id=user_id,
                name=normalized_name,
                email=normalized_email,
                password_salt=salt,
                password_hash=password_hash,
                created_at=now,
                last_login_at=now,
            )
            token = self._create_session_locked(user_id, now=now)
            self._users_by_id[user.id] = user
            self._users_by_email[user.email] = user
            self._persist_locked()
            return self._serialize_user(user), token

    def login_user(self, email: str, password: str) -> tuple[dict[str, Any], str]:
        normalized_email = self._normalize_email(email)
        normalized_password = self._normalize_password(password)
        with self._lock:
            self._cleanup_expired_sessions_locked(now=time.time())
            user = self._users_by_email.get(normalized_email)
            if user is None:
                raise RuntimeError("E-Mail oder Passwort ist ungueltig.")
            expected_hash = self._hash_password(normalized_password, user.password_salt)
            if not hmac.compare_digest(expected_hash, user.password_hash):
                raise RuntimeError("E-Mail oder Passwort ist ungueltig.")
            now = time.time()
            user.last_login_at = now
            token = self._create_session_locked(user.id, now=now)
            self._persist_locked()
            return self._serialize_user(user), token

    def get_user_by_token(self, token: str) -> dict[str, Any]:
        normalized_token = self._normalize_token(token)
        with self._lock:
            self._cleanup_expired_sessions_locked(now=time.time())
            session = self._sessions_by_token.get(normalized_token)
            if session is None:
                raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
            user = self._users_by_id.get(session.user_id)
            if user is None:
                self._sessions_by_token.pop(normalized_token, None)
                self._persist_locked()
                raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
            return self._serialize_user(user)

    def logout(self, token: str) -> None:
        normalized_token = self._normalize_token(token)
        with self._lock:
            self._sessions_by_token.pop(normalized_token, None)
            self._persist_locked()

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        users = payload.get("users", [])
        sessions = payload.get("sessions", [])
        for item in users:
            try:
                user = _UserRecord(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    email=self._normalize_email(str(item["email"])),
                    password_salt=str(item["password_salt"]),
                    password_hash=str(item["password_hash"]),
                    created_at=float(item.get("created_at", time.time())),
                    last_login_at=float(item["last_login_at"]) if item.get("last_login_at") is not None else None,
                )
            except Exception:
                continue
            self._users_by_id[user.id] = user
            self._users_by_email[user.email] = user
        now = time.time()
        for item in sessions:
            try:
                session = _SessionRecord(
                    token=self._normalize_token(str(item["token"])),
                    user_id=str(item["user_id"]),
                    created_at=float(item.get("created_at", now)),
                    expires_at=float(item.get("expires_at", now)),
                )
            except Exception:
                continue
            if session.expires_at <= now:
                continue
            if session.user_id not in self._users_by_id:
                continue
            self._sessions_by_token[session.token] = session

    def _persist_locked(self) -> None:
        self._cleanup_expired_sessions_locked(now=time.time())
        payload = {
            "users": [
                {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "password_salt": user.password_salt,
                    "password_hash": user.password_hash,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                }
                for user in sorted(self._users_by_id.values(), key=lambda value: value.created_at)
            ],
            "sessions": [
                {
                    "token": session.token,
                    "user_id": session.user_id,
                    "created_at": session.created_at,
                    "expires_at": session.expires_at,
                }
                for session in sorted(self._sessions_by_token.values(), key=lambda value: value.created_at)
            ],
        }
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _create_session_locked(self, user_id: str, now: float) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions_by_token[token] = _SessionRecord(
            token=token,
            user_id=user_id,
            created_at=now,
            expires_at=now + self._session_ttl_seconds,
        )
        return token

    def _cleanup_expired_sessions_locked(self, now: float) -> None:
        expired_tokens = [token for token, session in self._sessions_by_token.items() if session.expires_at <= now]
        for token in expired_tokens:
            self._sessions_by_token.pop(token, None)

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        )
        return digest.hex()

    @staticmethod
    def _serialize_user(user: _UserRecord) -> dict[str, Any]:
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = str(name or "").strip()
        if len(normalized) < 2:
            raise ValueError("Bitte einen Namen mit mindestens 2 Zeichen angeben.")
        return normalized[:120]

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = str(email or "").strip().lower()
        if not normalized:
            raise ValueError("E-Mail darf nicht leer sein.")
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Bitte eine gueltige E-Mail-Adresse angeben.")
        return normalized

    @staticmethod
    def _normalize_password(password: str) -> str:
        normalized = str(password or "")
        if len(normalized) < _MIN_PASSWORD_LENGTH:
            raise ValueError(f"Passwort muss mindestens {_MIN_PASSWORD_LENGTH} Zeichen lang sein.")
        return normalized

    @staticmethod
    def _normalize_token(token: str) -> str:
        normalized = str(token or "").strip()
        if not normalized:
            raise ValueError("Kein gueltiger Login-Token uebermittelt.")
        return normalized
