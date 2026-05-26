from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

from ..defaults import runtime_data_dir
from ..schemas import (
    ActionItemNotificationStatus,
    MeetingMinutes,
    OwnerWorkloadInsight,
    RepeatedTaskInsight,
    SimilarMeetingInsight,
    TaskBoardAnalytics,
    TaskBoardEntry,
    TaskBoardResponse,
)

_OWNER_SPLIT_RE = re.compile(r"\s*(?:,|;|/|&|\bund\b|\band\b|\+)\s*", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_STOPWORDS = {
    "und",
    "oder",
    "die",
    "der",
    "das",
    "ein",
    "eine",
    "mit",
    "fuer",
    "für",
    "auf",
    "von",
    "dem",
    "den",
    "des",
    "bei",
    "im",
    "in",
    "to",
    "the",
    "and",
    "for",
}


class TaskBoardService:
    def __init__(self, file_path: Path | None = None) -> None:
        self._file_path = file_path or runtime_data_dir() / "runtime_task_board.json"
        self._lock = threading.Lock()
        self._entries: list[TaskBoardEntry] = []
        self._load()

    def record_meeting_tasks(
        self,
        *,
        owner_id: str,
        room: str,
        recorded_at: str,
        meeting_name: str,
        meeting_key: str | None,
        minutes: MeetingMinutes,
        notify_action_items: bool,
        notification_statuses: list[ActionItemNotificationStatus] | None = None,
    ) -> list[TaskBoardEntry]:
        entries_to_save = self._build_entries(
            owner_id=owner_id,
            room=room,
            recorded_at=recorded_at,
            meeting_name=meeting_name,
            meeting_key=meeting_key,
            minutes=minutes,
            notify_action_items=notify_action_items,
            notification_statuses=notification_statuses or [],
        )
        with self._lock:
            existing_by_id = {entry.id: entry for entry in self._entries}
            for entry in entries_to_save:
                existing_by_id[entry.id] = entry
            self._entries = sorted(
                existing_by_id.values(),
                key=lambda entry: entry.updated_at,
                reverse=True,
            )
            self._persist_locked()
        return entries_to_save

    def get_board(self, owner_id: str) -> TaskBoardResponse:
        with self._lock:
            scoped = [entry for entry in self._entries if entry.id.startswith(f"{owner_id}:")]
        analytics = self._build_analytics(scoped)
        return TaskBoardResponse(entries=scoped, analytics=analytics)

    def _build_entries(
        self,
        *,
        owner_id: str,
        room: str,
        recorded_at: str,
        meeting_name: str,
        meeting_key: str | None,
        minutes: MeetingMinutes,
        notify_action_items: bool,
        notification_statuses: list[ActionItemNotificationStatus],
    ) -> list[TaskBoardEntry]:
        summary = (minutes.summary or "").strip()
        normalized_meeting_name = (meeting_name or "").strip() or "Meeting"
        resolved_meeting_key = (meeting_key or "").strip() or uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{owner_id}|{recorded_at}|{room}|{normalized_meeting_name}|{summary[:120]}",
        ).hex

        status_map: dict[tuple[str, str], ActionItemNotificationStatus] = {}
        for raw_status in notification_statuses:
            try:
                status = (
                    raw_status
                    if isinstance(raw_status, ActionItemNotificationStatus)
                    else ActionItemNotificationStatus.model_validate(raw_status)
                )
            except Exception:
                continue
            key = (
                (status.owner or "").strip().casefold(),
                (status.action_item_description or "").strip().casefold(),
            )
            if key[0] and key[1]:
                status_map[key] = status

        created_entries: list[TaskBoardEntry] = []
        now = time.time()
        for action_item in minutes.action_items:
            description = (action_item.description or "").strip()
            if not description:
                continue
            owners = self._expand_owners(action_item.owner)
            if not owners:
                owners = [((action_item.owner or "").strip() or "Unbekannt")]
            for task_owner in owners:
                task_key = (task_owner.casefold(), description.casefold())
                notification_status = status_map.get(task_key)
                email_sent = bool(notification_status.delivered) if notification_status else False
                email_status = "not_requested"
                email_detail = ""
                recipient_email = None
                if notify_action_items:
                    if notification_status is None:
                        email_status = "pending"
                    elif notification_status.delivered:
                        email_status = "sent"
                    else:
                        email_status = "failed"
                    email_detail = notification_status.detail if notification_status else ""
                    recipient_email = notification_status.recipient_email if notification_status else None

                entry_id = self._build_entry_id(
                    owner_id=owner_id,
                    meeting_key=resolved_meeting_key,
                    task_owner=task_owner,
                    task_description=description,
                )
                created_entries.append(
                    TaskBoardEntry(
                        id=entry_id,
                        meeting_key=resolved_meeting_key,
                        meeting_name=normalized_meeting_name,
                        room=room,
                        recorded_at=recorded_at,
                        minutes_summary=summary,
                        task_owner=task_owner,
                        task_description=description,
                        due_date=action_item.due_date,
                        email_requested=notify_action_items,
                        email_sent=email_sent,
                        email_status=email_status,
                        recipient_email=recipient_email,
                        email_detail=email_detail,
                        updated_at=now,
                    )
                )
        return created_entries

    @staticmethod
    def _build_entry_id(*, owner_id: str, meeting_key: str, task_owner: str, task_description: str) -> str:
        token = uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"{owner_id}|{meeting_key}|{task_owner.strip().casefold()}|{task_description.strip().casefold()}",
        ).hex
        return f"{owner_id}:{token}"

    @staticmethod
    def _expand_owners(raw_owner: str) -> list[str]:
        value = str(raw_owner or "").strip()
        if not value:
            return []
        parts = [part.strip() for part in _OWNER_SPLIT_RE.split(value) if part.strip()]
        return parts or [value]

    def _build_analytics(self, entries: list[TaskBoardEntry]) -> TaskBoardAnalytics:
        if not entries:
            return TaskBoardAnalytics()

        total_tasks = len(entries)
        meeting_keys = {entry.meeting_key for entry in entries}
        emailed_tasks = sum(1 for entry in entries if entry.email_sent)
        failed_emails = sum(1 for entry in entries if entry.email_requested and not entry.email_sent)

        repeated_tasks = self._build_repeated_task_insights(entries)
        owner_workload = self._build_owner_workload(entries)
        similar_meetings = self._build_similar_meeting_insights(entries)

        return TaskBoardAnalytics(
            total_tasks=total_tasks,
            total_meetings=len(meeting_keys),
            emailed_tasks=emailed_tasks,
            failed_emails=failed_emails,
            repeated_tasks=repeated_tasks,
            owner_workload=owner_workload,
            similar_meetings=similar_meetings,
        )

    @staticmethod
    def _build_repeated_task_insights(entries: list[TaskBoardEntry]) -> list[RepeatedTaskInsight]:
        grouped: dict[str, list[TaskBoardEntry]] = defaultdict(list)
        for entry in entries:
            key = entry.task_description.strip().casefold()
            if key:
                grouped[key].append(entry)
        insights: list[RepeatedTaskInsight] = []
        for grouped_entries in grouped.values():
            if len(grouped_entries) < 2:
                continue
            sample = grouped_entries[0]
            owners = sorted({entry.task_owner for entry in grouped_entries})
            meetings = len({entry.meeting_key for entry in grouped_entries})
            insights.append(
                RepeatedTaskInsight(
                    task_description=sample.task_description,
                    occurrences=len(grouped_entries),
                    meetings=meetings,
                    owners=owners,
                )
            )
        insights.sort(key=lambda item: (item.occurrences, item.meetings), reverse=True)
        return insights[:12]

    @staticmethod
    def _build_owner_workload(entries: list[TaskBoardEntry]) -> list[OwnerWorkloadInsight]:
        grouped: dict[str, list[TaskBoardEntry]] = defaultdict(list)
        for entry in entries:
            grouped[entry.task_owner].append(entry)
        insights = [
            OwnerWorkloadInsight(
                owner=owner,
                tasks=len(owner_entries),
                sent_emails=sum(1 for entry in owner_entries if entry.email_sent),
                failed_emails=sum(1 for entry in owner_entries if entry.email_requested and not entry.email_sent),
            )
            for owner, owner_entries in grouped.items()
        ]
        insights.sort(key=lambda item: (item.tasks, item.sent_emails), reverse=True)
        return insights

    def _build_similar_meeting_insights(self, entries: list[TaskBoardEntry]) -> list[SimilarMeetingInsight]:
        meeting_context: dict[str, dict[str, str | set[str]]] = {}
        for entry in entries:
            value = meeting_context.setdefault(
                entry.meeting_key,
                {
                    "meeting_name": entry.meeting_name,
                    "combined_text": "",
                },
            )
            combined_text = str(value["combined_text"])
            value["combined_text"] = " ".join(
                part for part in [combined_text, entry.minutes_summary, entry.task_description] if part
            ).strip()

        token_map: dict[str, set[str]] = {}
        for meeting_key, meta in meeting_context.items():
            token_map[meeting_key] = self._extract_tokens(str(meta.get("combined_text", "")))

        keys = sorted(token_map.keys())
        insights: list[SimilarMeetingInsight] = []
        for idx, left_key in enumerate(keys):
            for right_key in keys[idx + 1 :]:
                left_tokens = token_map[left_key]
                right_tokens = token_map[right_key]
                if not left_tokens or not right_tokens:
                    continue
                intersection = left_tokens.intersection(right_tokens)
                if len(intersection) < 2:
                    continue
                union = left_tokens.union(right_tokens)
                score = len(intersection) / len(union) if union else 0.0
                if score < 0.22:
                    continue
                insights.append(
                    SimilarMeetingInsight(
                        left_meeting_key=left_key,
                        left_meeting_name=str(meeting_context[left_key]["meeting_name"]),
                        right_meeting_key=right_key,
                        right_meeting_name=str(meeting_context[right_key]["meeting_name"]),
                        similarity_score=round(score, 3),
                        common_keywords=sorted(intersection)[:8],
                    )
                )
        insights.sort(key=lambda item: item.similarity_score, reverse=True)
        return insights[:10]

    @staticmethod
    def _extract_tokens(value: str) -> set[str]:
        tokens = set()
        for token in _TOKEN_RE.findall(value.lower()):
            if token in _STOPWORDS:
                continue
            tokens.add(token)
        return tokens

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        raw_entries = payload.get("entries", [])
        resolved_entries: list[TaskBoardEntry] = []
        for raw_entry in raw_entries:
            try:
                resolved_entries.append(TaskBoardEntry.model_validate(raw_entry))
            except Exception:
                continue
        self._entries = sorted(resolved_entries, key=lambda entry: entry.updated_at, reverse=True)

    def _persist_locked(self) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": [entry.model_dump() for entry in self._entries],
            "updated_at": time.time(),
        }
        self._file_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
