from __future__ import annotations

import json
import os
import re
import smtplib
import unicodedata
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Iterable

from ..schemas import (
    ActionItemNotificationOverride,
    ActionItemNotificationStatus,
    MeetingMinutes,
    MinutesActionItem,
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OWNER_SPLIT_RE = re.compile(r"\s*(?:,|;|/|&|\bund\b|\band\b|\+)\s*", re.IGNORECASE)


@dataclass
class _TaskDeliveryRecord:
    owner: str
    item: MinutesActionItem
    recipients: tuple[str, ...]
    custom_body: str | None = None


@dataclass
class _EmailTask:
    item: MinutesActionItem
    owners: list[str] = field(default_factory=list)
    custom_bodies: list[str] = field(default_factory=list)


@dataclass
class _EmailGroup:
    recipients: tuple[str, ...]
    tasks: list[_EmailTask] = field(default_factory=list)
    delivery_records: list[_TaskDeliveryRecord] = field(default_factory=list)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class ActionItemNotificationService:
    def __init__(self) -> None:
        self.enabled = _env_bool("ACTION_ITEM_EMAIL_ENABLED", True)
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = max(1, _env_int("SMTP_PORT", 587))
        self.smtp_username = os.getenv("SMTP_USERNAME", "").strip()
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_use_tls = _env_bool("SMTP_USE_TLS", True)
        self.smtp_timeout = max(1, _env_int("SMTP_TIMEOUT_SECONDS", 20))
        self.from_email = os.getenv("SMTP_FROM", "").strip() or self.smtp_username
        self.from_name = os.getenv("SMTP_FROM_NAME", "Meeting Minutes").strip() or "Meeting Minutes"
        self.default_domain = os.getenv("ACTION_ITEM_DEFAULT_EMAIL_DOMAIN", "").strip().lower()
        self.owner_email_map = self._load_owner_email_map(os.getenv("ACTION_ITEM_OWNER_EMAIL_MAP", ""))

    def send_notifications(
        self,
        *,
        room: str,
        recorded_at: str,
        minutes: MeetingMinutes,
        overrides: Iterable[ActionItemNotificationOverride] | None = None,
    ) -> list[ActionItemNotificationStatus]:
        if not self.enabled:
            return []

        action_entries = self._expand_action_item_entries(minutes.action_items)
        if not action_entries:
            return []

        override_map = self._build_override_map(overrides)
        email_groups: dict[tuple[str, ...], _EmailGroup] = {}
        statuses: list[ActionItemNotificationStatus] = []

        for item, owners in action_entries:
            owner_rows: list[tuple[str, str, str | None]] = []
            missing_owner = False
            for owner in owners:
                override = override_map.get((owner.casefold(), item.description.strip().casefold()))
                recipient_override = override.recipient_email if override else None
                custom_body = override.email_body if override else None
                recipient = self._resolve_owner_email(owner, recipient_override)
                if not recipient:
                    missing_owner = True
                    statuses.append(
                        ActionItemNotificationStatus(
                            owner=owner,
                            action_item_description=item.description,
                            recipient_email=None,
                            action_items_count=1,
                            delivered=False,
                            detail="Keine E-Mail-Adresse fuer Owner gefunden (ACTION_ITEM_OWNER_EMAIL_MAP).",
                        )
                    )
                    continue
                owner_rows.append((owner, recipient, custom_body))

            if not owner_rows:
                continue
            if len(owners) > 1 and missing_owner:
                for owner, _recipient, _custom_body in owner_rows:
                    statuses.append(
                        ActionItemNotificationStatus(
                            owner=owner,
                            action_item_description=item.description,
                            recipient_email=None,
                            action_items_count=1,
                            delivered=False,
                            detail="Gemeinsame E-Mail nicht moeglich: mindestens eine Owner-Adresse fehlt.",
                        )
                    )
                continue

            recipient_key = tuple(sorted({recipient for _, recipient, _ in owner_rows}))
            group = email_groups.get(recipient_key)
            if group is None:
                group = _EmailGroup(recipients=recipient_key)
                email_groups[recipient_key] = group

            email_task = _EmailTask(
                item=item,
                owners=[owner for owner, _, _ in owner_rows],
                custom_bodies=[body.strip() for _, _, body in owner_rows if str(body or "").strip()],
            )
            group.tasks.append(email_task)
            for owner, _recipient, custom_body in owner_rows:
                group.delivery_records.append(
                    _TaskDeliveryRecord(
                        owner=owner,
                        item=item,
                        recipients=recipient_key,
                        custom_body=custom_body,
                    )
                )

        if not self.smtp_host:
            return statuses + self._build_group_failure_statuses(
                email_groups.values(),
                "SMTP_HOST ist nicht gesetzt.",
            )

        if not self.from_email:
            return statuses + self._build_group_failure_statuses(
                email_groups.values(),
                "SMTP_FROM oder SMTP_USERNAME fehlt.",
            )

        smtp_client = self._build_smtp_client()
        with smtp_client:
            if self.smtp_use_tls:
                smtp_client.starttls()
            if self.smtp_username:
                smtp_client.login(self.smtp_username, self.smtp_password)

            for group in email_groups.values():
                message = self._build_group_message(
                    recipients=group.recipients,
                    room=room,
                    recorded_at=recorded_at,
                    minutes=minutes,
                    tasks=group.tasks,
                )
                recipient_label = ", ".join(group.recipients)
                try:
                    smtp_client.send_message(message)
                    for record in group.delivery_records:
                        statuses.append(
                            ActionItemNotificationStatus(
                                owner=record.owner,
                                action_item_description=record.item.description,
                                recipient_email=recipient_label,
                                action_items_count=1,
                                delivered=True,
                                detail="E-Mail erfolgreich versendet.",
                            )
                        )
                except Exception as exc:
                    for record in group.delivery_records:
                        statuses.append(
                            ActionItemNotificationStatus(
                                owner=record.owner,
                                action_item_description=record.item.description,
                                recipient_email=recipient_label,
                                action_items_count=1,
                                delivered=False,
                                detail=f"E-Mail-Versand fehlgeschlagen: {exc}",
                            )
                        )
        return statuses

    def _build_smtp_client(self) -> smtplib.SMTP:
        return smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.smtp_timeout)

    @staticmethod
    def _expand_action_item_entries(
        action_items: Iterable[MinutesActionItem],
    ) -> list[tuple[MinutesActionItem, list[str]]]:
        entries: list[tuple[MinutesActionItem, list[str]]] = []
        for item in action_items:
            if not item.description.strip():
                continue
            owners = ActionItemNotificationService._expand_owners(item.owner)
            if not owners:
                fallback_owner = item.owner.strip() if item.owner else "Unbekannt"
                owners = [fallback_owner]
            entries.append((item, owners))
        entries.sort(
            key=lambda entry: (
                entry[0].description.casefold(),
                "|".join(owner.casefold() for owner in entry[1]),
            )
        )
        return entries

    @staticmethod
    def _expand_owners(raw_owner: str) -> list[str]:
        value = str(raw_owner or "").strip()
        if not value:
            return []
        if EMAIL_RE.fullmatch(value):
            return [value]
        parts = [part.strip() for part in OWNER_SPLIT_RE.split(value) if part.strip()]
        normalized = []
        for part in parts:
            part = re.sub(r"\s+", " ", part).strip()
            if part:
                normalized.append(part)
        return normalized or [value]

    def _resolve_owner_email(self, owner: str, recipient_override: str | None = None) -> str | None:
        override_email = str(recipient_override or "").strip()
        if EMAIL_RE.fullmatch(override_email):
            return override_email
        owner = owner.strip()
        if EMAIL_RE.fullmatch(owner):
            return owner
        direct = self.owner_email_map.get(owner.casefold())
        if direct:
            return direct
        if self.default_domain:
            local = self._to_email_localpart(owner)
            if local:
                return f"{local}@{self.default_domain}"
        return None

    @staticmethod
    def _build_override_map(
        overrides: Iterable[ActionItemNotificationOverride] | None,
    ) -> dict[tuple[str, str], ActionItemNotificationOverride]:
        if not overrides:
            return {}
        resolved: dict[tuple[str, str], ActionItemNotificationOverride] = {}
        for override in overrides:
            owner_key = str(override.owner or "").strip().casefold()
            action_key = str(override.action_item_description or "").strip().casefold()
            if owner_key and action_key:
                resolved[(owner_key, action_key)] = override
        return resolved

    @staticmethod
    def _to_email_localpart(owner: str) -> str:
        folded = unicodedata.normalize("NFKD", owner)
        ascii_owner = folded.encode("ascii", "ignore").decode("ascii").casefold()
        ascii_owner = re.sub(r"[^a-z0-9]+", ".", ascii_owner).strip(".")
        return ascii_owner[:64]

    @staticmethod
    def _build_group_failure_statuses(
        groups: Iterable[_EmailGroup],
        detail: str,
    ) -> list[ActionItemNotificationStatus]:
        statuses: list[ActionItemNotificationStatus] = []
        for group in groups:
            for record in group.delivery_records:
                statuses.append(
                    ActionItemNotificationStatus(
                        owner=record.owner,
                        action_item_description=record.item.description,
                        recipient_email=", ".join(record.recipients),
                        action_items_count=1,
                        delivered=False,
                        detail=detail,
                    )
                )
        return statuses

    def _build_group_message(
        self,
        *,
        recipients: tuple[str, ...],
        room: str,
        recorded_at: str,
        minutes: MeetingMinutes,
        tasks: list[_EmailTask],
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = ", ".join(recipients)
        primary_owner = tasks[0].owners[0] if tasks and tasks[0].owners else "Team"
        if len(recipients) > 1:
            msg["Subject"] = f"[Meeting Minutes] Gemeinsame Action Items ({room})"
        else:
            msg["Subject"] = f"[Meeting Minutes] Action Items fuer {primary_owner} ({room})"
        if len(tasks) == 1 and len(recipients) == 1 and tasks[0].custom_bodies:
            msg.set_content(tasks[0].custom_bodies[0])
            return msg

        lines: list[str] = []
        lines.append("Hallo zusammen," if len(recipients) > 1 else f"Hallo {primary_owner},")
        lines.append("")
        lines.append("aus dem aktuellen Meeting wurden folgende Aufgaben erkannt:")
        lines.append("")
        for index, task in enumerate(tasks, start=1):
            due = f" (Faelligkeit: {task.item.due_date})" if task.item.due_date else ""
            owner_label = ", ".join(task.owners)
            lines.append(f"{index}. {task.item.description}{due}")
            lines.append(f"   Owner: {owner_label}")
            if task.custom_bodies:
                lines.append(f"   Hinweis: {task.custom_bodies[0]}")
        lines.append("")
        lines.append("Kontext zum Meeting:")
        lines.append(f"- Raum: {room}")
        lines.append(f"- Zeitpunkt: {recorded_at}")
        if minutes.summary.strip():
            lines.append(f"- Kurzzusammenfassung: {minutes.summary.strip()}")
        if minutes.decisions:
            lines.append("- Wichtige Entscheidungen:")
            for decision in minutes.decisions[:4]:
                title = (decision.title or "Entscheidung").strip()
                details = (decision.details or "").strip()
                if details:
                    lines.append(f"  - {title}: {details}")
                else:
                    lines.append(f"  - {title}")
        lines.append("")
        lines.append("Bitte prueft die Aufgaben und gebt bei Bedarf Rueckmeldung.")
        lines.append("")
        lines.append("Viele Gruesse")
        lines.append(self.from_name)
        msg.set_content("\n".join(lines))
        return msg

    @staticmethod
    def _load_owner_email_map(raw_map: str) -> dict[str, str]:
        value = raw_map.strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        resolved: dict[str, str] = {}
        for owner, email in parsed.items():
            owner_key = str(owner or "").strip().casefold()
            email_value = str(email or "").strip()
            if owner_key and EMAIL_RE.fullmatch(email_value):
                resolved[owner_key] = email_value
        return resolved
