from __future__ import annotations

import asyncio
import os

import httpx

from ..schemas import MeetingMinutes, WebhookDeliveryStatus


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


class WebhookService:
    def __init__(self) -> None:
        self.url = os.getenv("MEETING_WEBHOOK_URL", "").strip()
        self.timeout_seconds = max(1.0, _env_float("MEETING_WEBHOOK_TIMEOUT_SECONDS", 20.0))
        self.max_retries = max(1, _env_int("MEETING_WEBHOOK_MAX_RETRIES", 3))
        self.backoff_seconds = max(0.0, _env_float("MEETING_WEBHOOK_BACKOFF_SECONDS", 1.0))
        verify_tls = _env_bool("MEETING_WEBHOOK_VERIFY_TLS", True)
        ca_cert_path = os.getenv("MEETING_WEBHOOK_CA_CERT_PATH", "").strip()
        self.verify = ca_cert_path or verify_tls

    async def send_minutes(
        self,
        room: str,
        recorded_at: str,
        minutes: MeetingMinutes,
    ) -> WebhookDeliveryStatus:
        if not self.url:
            return WebhookDeliveryStatus(
                delivered=False,
                url="",
                attempts=0,
                status_code=None,
                detail="MEETING_WEBHOOK_URL ist nicht gesetzt.",
            )

        payload = {
            "room": room,
            "recorded_at": recorded_at,
            "minutes": minutes.model_dump(),
        }

        attempts = 0
        last_status_code: int | None = None
        last_error = ""

        for attempts in range(1, self.max_retries + 1):
            retryable = True
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, verify=self.verify) as client:
                    response = await client.post(self.url, json=payload)
                last_status_code = response.status_code
                response.raise_for_status()
                return WebhookDeliveryStatus(
                    delivered=True,
                    url=self.url,
                    attempts=attempts,
                    status_code=response.status_code,
                    detail="Webhook erfolgreich zugestellt.",
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                last_status_code = status_code
                retryable = status_code == 429 or status_code >= 500
                body = (exc.response.text or "").strip()
                detail = f"Webhook antwortete mit HTTP {status_code}."
                if body:
                    detail = f"{detail} Body: {body[:300]}"
                last_error = detail
            except httpx.HTTPError as exc:
                last_error = f"Webhook-Anfrage fehlgeschlagen: {exc}"

            if not retryable:
                break
            if retryable and attempts < self.max_retries and self.backoff_seconds > 0:
                await asyncio.sleep(self.backoff_seconds * attempts)

        return WebhookDeliveryStatus(
            delivered=False,
            url=self.url,
            attempts=attempts,
            status_code=last_status_code,
            detail=last_error or "Webhook-Zustellung fehlgeschlagen.",
        )
