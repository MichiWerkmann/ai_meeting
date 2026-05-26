from backend.app.schemas import ActionItemNotificationOverride, MeetingMinutes, MinutesActionItem
from backend.app.services.action_item_notifications import ActionItemNotificationService


class _DummySMTP:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages = []
        self.started_tls = False
        self.logged_in = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, _username, _password):
        self.logged_in = True

    def send_message(self, message):
        self.messages.append(message)


def test_notifications_return_mapping_error_without_smtp(monkeypatch):
    monkeypatch.setenv("ACTION_ITEM_EMAIL_ENABLED", "true")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("ACTION_ITEM_OWNER_EMAIL_MAP", '{"Dennis":"dennis@example.com"}')
    service = ActionItemNotificationService()

    minutes = MeetingMinutes(
        summary="Kurz",
        action_items=[
            MinutesActionItem(owner="Dennis", description="Validierung Version 1.4"),
            MinutesActionItem(owner="Darius und Nils", description="Boxen fuer Tests aufsetzen"),
        ],
    )

    statuses = service.send_notifications(
        room="E01-115 SWS",
        recorded_at="2026-05-26T12:00:00Z",
        minutes=minutes,
    )

    assert len(statuses) == 3
    assert all(status.delivered is False for status in statuses)
    assert any("SMTP_HOST" in status.detail for status in statuses)


def test_notifications_send_per_owner_with_context(monkeypatch):
    monkeypatch.setenv("ACTION_ITEM_EMAIL_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "meeting-bot@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Meeting Bot")
    monkeypatch.setenv(
        "ACTION_ITEM_OWNER_EMAIL_MAP",
        '{"Dennis":"dennis@example.com","Darius":"darius@example.com","Nils":"nils@example.com","Simone":"simone@example.com"}',
    )
    smtp_client = _DummySMTP("smtp.example.local", 587, 20)
    monkeypatch.setattr(
        "backend.app.services.action_item_notifications.smtplib.SMTP",
        lambda host, port, timeout: smtp_client,
    )

    service = ActionItemNotificationService()
    minutes = MeetingMinutes(
        summary="Release 1.4 wurde besprochen und Teststrategie abgestimmt.",
        decisions=[],
        action_items=[
            MinutesActionItem(
                owner="Dennis",
                description="Validierung der Basis fuer Version 1.4 und Analyse der Testergebnisse.",
            ),
            MinutesActionItem(
                owner="Darius und Nils",
                description="Mehrere Boxen aufsetzen und Datenbasis klonen.",
            ),
            MinutesActionItem(
                owner="Simone",
                description="Messebesuche in Muenchen und Dortmund vorbereiten.",
            ),
        ],
    )

    statuses = service.send_notifications(
        room="E01-115 SWS",
        recorded_at="2026-05-26T12:00:00Z",
        minutes=minutes,
    )

    assert len(statuses) == 4
    assert all(status.delivered is True for status in statuses)
    assert {status.recipient_email for status in statuses} == {
        "dennis@example.com",
        "darius@example.com, nils@example.com",
        "simone@example.com",
    }
    assert smtp_client.started_tls is True
    assert smtp_client.logged_in is True
    assert len(smtp_client.messages) == 3
    assert any("Kontext zum Meeting" in message.get_content() for message in smtp_client.messages)


def test_notifications_apply_override_recipient_and_custom_body(monkeypatch):
    monkeypatch.setenv("ACTION_ITEM_EMAIL_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    monkeypatch.setenv("SMTP_FROM", "meeting-bot@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Meeting Bot")
    monkeypatch.setenv("ACTION_ITEM_OWNER_EMAIL_MAP", '{"Dennis":"dennis@example.com"}')
    smtp_client = _DummySMTP("smtp.example.local", 587, 20)
    monkeypatch.setattr(
        "backend.app.services.action_item_notifications.smtplib.SMTP",
        lambda host, port, timeout: smtp_client,
    )

    service = ActionItemNotificationService()
    minutes = MeetingMinutes(
        summary="Release 1.4 abgestimmt.",
        action_items=[
            MinutesActionItem(
                owner="Dennis",
                description="Validierung der Basis fuer Version 1.4.",
            ),
        ],
    )
    overrides = [
        ActionItemNotificationOverride(
            owner="Dennis",
            action_item_description="Validierung der Basis fuer Version 1.4.",
            recipient_email="external.owner@example.net",
            email_body="Custom Draft fuer diese Aufgabe.",
        )
    ]

    statuses = service.send_notifications(
        room="E01-115 SWS",
        recorded_at="2026-05-26T12:00:00Z",
        minutes=minutes,
        overrides=overrides,
    )

    assert len(statuses) == 1
    assert statuses[0].delivered is True
    assert statuses[0].recipient_email == "external.owner@example.net"
    assert statuses[0].action_item_description == "Validierung der Basis fuer Version 1.4."
    assert len(smtp_client.messages) == 1
    assert smtp_client.messages[0]["To"] == "external.owner@example.net"
    assert "Custom Draft fuer diese Aufgabe." in smtp_client.messages[0].get_content()


def test_notifications_group_multiple_tasks_per_person_into_one_email(monkeypatch):
    monkeypatch.setenv("ACTION_ITEM_EMAIL_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.local")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    monkeypatch.setenv("SMTP_FROM", "meeting-bot@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Meeting Bot")
    monkeypatch.setenv("ACTION_ITEM_OWNER_EMAIL_MAP", '{"Dennis":"dennis@example.com"}')
    smtp_client = _DummySMTP("smtp.example.local", 587, 20)
    monkeypatch.setattr(
        "backend.app.services.action_item_notifications.smtplib.SMTP",
        lambda host, port, timeout: smtp_client,
    )

    service = ActionItemNotificationService()
    minutes = MeetingMinutes(
        summary="Mehrere Aufgaben fuer dieselbe Person.",
        action_items=[
            MinutesActionItem(owner="Dennis", description="Task A"),
            MinutesActionItem(owner="Dennis", description="Task B"),
        ],
    )

    statuses = service.send_notifications(
        room="E01-115 SWS",
        recorded_at="2026-05-26T12:00:00Z",
        minutes=minutes,
    )

    assert len(statuses) == 2
    assert all(status.delivered is True for status in statuses)
    assert len(smtp_client.messages) == 1
    message_body = smtp_client.messages[0].get_content()
    assert "Task A" in message_body
    assert "Task B" in message_body
