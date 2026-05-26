import asyncio

import httpx

from backend.app.schemas import MeetingMinutes
from backend.app.services.webhook import WebhookService


class _DummyAsyncClient:
    def __init__(self, timeout, verify, responses, call_log):
        self.timeout = timeout
        self.verify = verify
        self._responses = responses
        self._call_log = call_log

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        self._call_log.append({"url": url, "json": json})
        status_code, text = self._responses.pop(0)
        request = httpx.Request("POST", url)
        return httpx.Response(status_code, text=text, request=request)


def test_send_minutes_returns_not_configured_when_url_missing(monkeypatch):
    monkeypatch.delenv("MEETING_WEBHOOK_URL", raising=False)
    service = WebhookService()

    result = asyncio.run(
        service.send_minutes(
            room="E01-115 SWS",
            recorded_at="2026-04-15T05:30:00Z",
            minutes=MeetingMinutes(summary="Kurz"),
        )
    )

    assert result.delivered is False
    assert result.attempts == 0
    assert "nicht gesetzt" in result.detail


def test_send_minutes_retries_on_server_error(monkeypatch):
    monkeypatch.setenv("MEETING_WEBHOOK_URL", "https://example.local/webhook/meeting")
    monkeypatch.setenv("MEETING_WEBHOOK_MAX_RETRIES", "3")
    monkeypatch.setenv("MEETING_WEBHOOK_BACKOFF_SECONDS", "0")
    call_log = []
    responses = [(500, "temporary"), (200, "ok")]

    def _client_factory(timeout, verify):
        return _DummyAsyncClient(timeout, verify, responses, call_log)

    monkeypatch.setattr("backend.app.services.webhook.httpx.AsyncClient", _client_factory)
    service = WebhookService()

    result = asyncio.run(
        service.send_minutes(
            room="E01-115 SWS",
            recorded_at="2026-04-15T05:30:00Z",
            minutes=MeetingMinutes(summary="Kurz"),
        )
    )

    assert result.delivered is True
    assert result.attempts == 2
    assert result.status_code == 200
    assert len(call_log) == 2
    assert "minutes" in call_log[0]["json"]
    assert "meeting_minutes" not in call_log[0]["json"]


def test_send_minutes_does_not_retry_on_bad_request(monkeypatch):
    monkeypatch.setenv("MEETING_WEBHOOK_URL", "https://example.local/webhook/meeting")
    monkeypatch.setenv("MEETING_WEBHOOK_MAX_RETRIES", "3")
    monkeypatch.setenv("MEETING_WEBHOOK_BACKOFF_SECONDS", "0")
    call_log = []
    responses = [(400, "invalid payload")]

    def _client_factory(timeout, verify):
        return _DummyAsyncClient(timeout, verify, responses, call_log)

    monkeypatch.setattr("backend.app.services.webhook.httpx.AsyncClient", _client_factory)
    service = WebhookService()

    result = asyncio.run(
        service.send_minutes(
            room="E01-115 SWS",
            recorded_at="2026-04-15T05:30:00Z",
            minutes=MeetingMinutes(summary="Kurz"),
        )
    )

    assert result.delivered is False
    assert result.attempts == 1
    assert result.status_code == 400
    assert len(call_log) == 1
    assert "minutes" in call_log[0]["json"]
    assert "meeting_minutes" not in call_log[0]["json"]
