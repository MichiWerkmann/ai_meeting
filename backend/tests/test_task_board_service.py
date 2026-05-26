from pathlib import Path

from backend.app.schemas import (
    ActionItemNotificationStatus,
    MeetingMinutes,
    MinutesActionItem,
)
from backend.app.services.task_board import TaskBoardService


def test_task_board_records_entries_with_email_status(tmp_path: Path):
    service = TaskBoardService(file_path=tmp_path / "task_board.json")
    minutes = MeetingMinutes(
        summary="Release 1.4 Abstimmung und Testplanung",
        action_items=[
            MinutesActionItem(owner="Dennis", description="Testergebnisse auswerten"),
            MinutesActionItem(owner="Darius und Nils", description="Testboxen aufsetzen"),
        ],
    )
    statuses = [
        ActionItemNotificationStatus(
            owner="Dennis",
            action_item_description="Testergebnisse auswerten",
            recipient_email="dennis@example.com",
            delivered=True,
            detail="E-Mail erfolgreich versendet.",
        )
    ]

    created = service.record_meeting_tasks(
        owner_id="client-a",
        room="E01-115 SWS",
        recorded_at="2026-05-26T12:00:00Z",
        meeting_name="Weekly Sync",
        meeting_key="job-123",
        minutes=minutes,
        notify_action_items=True,
        notification_statuses=statuses,
    )

    assert len(created) == 3
    dennis = [entry for entry in created if entry.task_owner == "Dennis"][0]
    assert dennis.email_sent is True
    assert dennis.email_status == "sent"
    darius = [entry for entry in created if entry.task_owner == "Darius"][0]
    assert darius.email_sent is False
    assert darius.email_status in {"failed", "pending"}


def test_task_board_analytics_detects_repeats_and_similarity(tmp_path: Path):
    service = TaskBoardService(file_path=tmp_path / "task_board.json")

    first = MeetingMinutes(
        summary="Sprint review und Teststrategie fuer Version 1.4",
        action_items=[MinutesActionItem(owner="Dennis", description="Testergebnisse auswerten")],
    )
    second = MeetingMinutes(
        summary="Sprint review und Fehleranalyse fuer Version 1.4",
        action_items=[MinutesActionItem(owner="Dennis", description="Testergebnisse auswerten")],
    )
    service.record_meeting_tasks(
        owner_id="client-a",
        room="E01-115 SWS",
        recorded_at="2026-05-20T12:00:00Z",
        meeting_name="Sprint 1",
        meeting_key="job-1",
        minutes=first,
        notify_action_items=False,
        notification_statuses=[],
    )
    service.record_meeting_tasks(
        owner_id="client-a",
        room="E01-115 SWS",
        recorded_at="2026-05-26T12:00:00Z",
        meeting_name="Sprint 2",
        meeting_key="job-2",
        minutes=second,
        notify_action_items=False,
        notification_statuses=[],
    )

    board = service.get_board("client-a")
    assert board.analytics.total_tasks == 2
    assert board.analytics.total_meetings == 2
    assert len(board.analytics.repeated_tasks) >= 1
    assert board.analytics.repeated_tasks[0].occurrences >= 2
    assert len(board.analytics.similar_meetings) >= 1
