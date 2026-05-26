from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..defaults import runtime_data_dir

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
    is_admin: bool = False
    is_active: bool = True


@dataclass
class _SessionRecord:
    token: str
    user_id: str
    created_at: float
    expires_at: float


class AuthService:
    def __init__(self, file_path: Path | None = None, session_ttl_seconds: int = 30 * 24 * 60 * 60) -> None:
        self._file_path = file_path or runtime_data_dir() / "runtime_users.json"
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
            # Bootstrap: erster User wird automatisch Admin. Außerdem: wenn die
            # E-Mail in AURORA_INITIAL_ADMIN_EMAIL aufgeführt ist, ebenfalls Admin.
            is_admin = (
                len(self._users_by_id) == 0
                or normalized_email in self._initial_admin_emails()
            )
            user = _UserRecord(
                id=user_id,
                name=normalized_name,
                email=normalized_email,
                password_salt=salt,
                password_hash=password_hash,
                created_at=now,
                last_login_at=now,
                is_admin=is_admin,
                is_active=True,
            )
            token = self._create_session_locked(user_id, now=now)
            self._users_by_id[user.id] = user
            self._users_by_email[user.email] = user
            self._persist_locked()
            return self._serialize_user(user), token

    @staticmethod
    def _initial_admin_emails() -> set[str]:
        raw = os.environ.get("AURORA_INITIAL_ADMIN_EMAIL", "")
        return {entry.strip().lower() for entry in raw.split(",") if entry.strip()}

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
            if not user.is_active:
                raise RuntimeError("Dieser Account wurde deaktiviert. Bitte den Administrator kontaktieren.")
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
            if not user.is_active:
                self._sessions_by_token.pop(normalized_token, None)
                self._persist_locked()
                raise RuntimeError("Dieser Account wurde deaktiviert.")
            return self._serialize_user(user)

    def logout(self, token: str) -> None:
        normalized_token = self._normalize_token(token)
        with self._lock:
            self._sessions_by_token.pop(normalized_token, None)
            self._persist_locked()

    # ------------------------------------------------------------------
    # Profile- und Admin-Operationen
    # ------------------------------------------------------------------

    def change_password(self, token: str, current_password: str, new_password: str) -> None:
        """Ändert das Passwort des aktuell angemeldeten Users. Erfordert aktuelles Passwort."""
        normalized_token = self._normalize_token(token)
        current = str(current_password or "")
        new_normalized = self._normalize_password(new_password)
        if not current:
            raise ValueError("Aktuelles Passwort darf nicht leer sein.")
        if current == new_normalized:
            raise ValueError("Neues Passwort darf nicht mit dem aktuellen identisch sein.")
        with self._lock:
            self._cleanup_expired_sessions_locked(now=time.time())
            session = self._sessions_by_token.get(normalized_token)
            if session is None:
                raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
            user = self._users_by_id.get(session.user_id)
            if user is None:
                raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
            expected = self._hash_password(current, user.password_salt)
            if not hmac.compare_digest(expected, user.password_hash):
                raise ValueError("Aktuelles Passwort ist nicht korrekt.")
            new_salt = secrets.token_hex(16)
            user.password_salt = new_salt
            user.password_hash = self._hash_password(new_normalized, new_salt)
            # Alle anderen Sessions invalidieren, aktuelle behalten
            for other_token in [t for t, s in self._sessions_by_token.items() if s.user_id == user.id and t != normalized_token]:
                self._sessions_by_token.pop(other_token, None)
            self._persist_locked()

    def update_profile(self, token: str, *, name: str | None = None) -> dict[str, Any]:
        """Update für vom User selbst editierbare Felder (aktuell nur Name)."""
        normalized_token = self._normalize_token(token)
        with self._lock:
            session = self._sessions_by_token.get(normalized_token)
            if session is None:
                raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
            user = self._users_by_id.get(session.user_id)
            if user is None:
                raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
            if name is not None:
                user.name = self._normalize_name(name)
            self._persist_locked()
            return self._serialize_user(user)

    # ---------- Admin operations (require admin token) ----------

    def _require_admin_locked(self, token: str) -> _UserRecord:
        normalized_token = self._normalize_token(token)
        session = self._sessions_by_token.get(normalized_token)
        if session is None:
            raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
        user = self._users_by_id.get(session.user_id)
        if user is None:
            raise RuntimeError("Sitzung abgelaufen oder ungueltig.")
        if not user.is_admin or not user.is_active:
            raise PermissionError("Diese Aktion erfordert Admin-Rechte.")
        return user

    def list_users(self, requester_token: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require_admin_locked(requester_token)
            return [
                self._serialize_user(user)
                for user in sorted(self._users_by_id.values(), key=lambda value: value.created_at)
            ]

    def admin_create_user(
        self,
        requester_token: str,
        *,
        name: str,
        email: str,
        password: str,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        normalized_name = self._normalize_name(name)
        normalized_email = self._normalize_email(email)
        normalized_password = self._normalize_password(password)
        with self._lock:
            self._require_admin_locked(requester_token)
            if normalized_email in self._users_by_email:
                raise ValueError("Diese E-Mail-Adresse ist bereits registriert.")
            now = time.time()
            salt = secrets.token_hex(16)
            user = _UserRecord(
                id=uuid.uuid4().hex,
                name=normalized_name,
                email=normalized_email,
                password_salt=salt,
                password_hash=self._hash_password(normalized_password, salt),
                created_at=now,
                last_login_at=None,
                is_admin=bool(is_admin),
                is_active=True,
            )
            self._users_by_id[user.id] = user
            self._users_by_email[user.email] = user
            self._persist_locked()
            return self._serialize_user(user)

    def admin_update_user(
        self,
        requester_token: str,
        user_id: str,
        *,
        name: str | None = None,
        email: str | None = None,
        is_admin: bool | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            requester = self._require_admin_locked(requester_token)
            target = self._users_by_id.get(str(user_id))
            if target is None:
                raise ValueError("Benutzer nicht gefunden.")
            # Self-Protection: Admin darf sich nicht selbst die Admin-Rolle entziehen
            # oder sich selbst deaktivieren -> sonst lockout-Gefahr
            if target.id == requester.id:
                if is_admin is False:
                    raise ValueError("Du kannst dir selbst nicht die Admin-Rechte entziehen.")
                if is_active is False:
                    raise ValueError("Du kannst dich selbst nicht deaktivieren.")
            if name is not None:
                target.name = self._normalize_name(name)
            if email is not None:
                new_email = self._normalize_email(email)
                if new_email != target.email and new_email in self._users_by_email:
                    raise ValueError("Diese E-Mail-Adresse ist bereits registriert.")
                self._users_by_email.pop(target.email, None)
                target.email = new_email
                self._users_by_email[new_email] = target
            if is_admin is not None:
                target.is_admin = bool(is_admin)
            if is_active is not None:
                target.is_active = bool(is_active)
                if not target.is_active:
                    # Alle Sessions des deaktivierten Users sofort beenden
                    for tok in [t for t, s in self._sessions_by_token.items() if s.user_id == target.id]:
                        self._sessions_by_token.pop(tok, None)
            self._persist_locked()
            return self._serialize_user(target)

    def admin_set_password(
        self,
        requester_token: str,
        user_id: str,
        new_password: str,
    ) -> None:
        new_normalized = self._normalize_password(new_password)
        with self._lock:
            self._require_admin_locked(requester_token)
            target = self._users_by_id.get(str(user_id))
            if target is None:
                raise ValueError("Benutzer nicht gefunden.")
            new_salt = secrets.token_hex(16)
            target.password_salt = new_salt
            target.password_hash = self._hash_password(new_normalized, new_salt)
            # Alle bestehenden Sessions des Ziel-Users beenden -> erzwingt Re-Login
            for tok in [t for t, s in self._sessions_by_token.items() if s.user_id == target.id]:
                self._sessions_by_token.pop(tok, None)
            self._persist_locked()

    def admin_delete_user(self, requester_token: str, user_id: str) -> None:
        with self._lock:
            requester = self._require_admin_locked(requester_token)
            target = self._users_by_id.get(str(user_id))
            if target is None:
                raise ValueError("Benutzer nicht gefunden.")
            if target.id == requester.id:
                raise ValueError("Du kannst dich selbst nicht löschen.")
            # Wenn das der letzte Admin wäre, blocken
            if target.is_admin:
                remaining_admins = sum(1 for u in self._users_by_id.values() if u.is_admin and u.id != target.id)
                if remaining_admins == 0:
                    raise ValueError("Mindestens ein Admin-Account muss erhalten bleiben.")
            self._users_by_id.pop(target.id, None)
            self._users_by_email.pop(target.email, None)
            for tok in [t for t, s in self._sessions_by_token.items() if s.user_id == target.id]:
                self._sessions_by_token.pop(tok, None)
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
        initial_admins = self._initial_admin_emails()
        for item in users:
            try:
                email = self._normalize_email(str(item["email"]))
                user = _UserRecord(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    email=email,
                    password_salt=str(item["password_salt"]),
                    password_hash=str(item["password_hash"]),
                    created_at=float(item.get("created_at", time.time())),
                    last_login_at=float(item["last_login_at"]) if item.get("last_login_at") is not None else None,
                    is_admin=bool(item.get("is_admin", False)) or email in initial_admins,
                    is_active=bool(item.get("is_active", True)),
                )
            except Exception:
                continue
            self._users_by_id[user.id] = user
            self._users_by_email[user.email] = user
        # Migration: wenn nach dem Laden noch kein Admin existiert, mache den
        # ältesten User zum Admin (ältere Datenbestände vor v1.0.3 hatten kein Feld).
        if self._users_by_id and not any(u.is_admin for u in self._users_by_id.values()):
            oldest = min(self._users_by_id.values(), key=lambda u: u.created_at)
            oldest.is_admin = True
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
                    "is_admin": user.is_admin,
                    "is_active": user.is_active,
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
            "is_admin": user.is_admin,
            "is_active": user.is_active,
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
