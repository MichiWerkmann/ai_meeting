from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas import MeetingMinutes, ModelSettings, SpeakerProfile, TranscriptResponse, TranscriptSegment


client = TestClient(app)


async def _fake_transcribe(*_args, **_kwargs):
    segments = [
        TranscriptSegment(
            speaker_id="speaker_a",
            speaker="Speaker A",
            start=0.0,
            end=4.0,
            text="Guten Morgen",
        )
    ]
    minutes = MeetingMinutes(summary="Kurze Zusammenfassung", agenda=["Sync"])
    speakers = [SpeakerProfile(speaker_id="speaker_a", label="Speaker A")]
    processing = {
        "device": "cpu",
        "total_seconds": 1.2,
        "steps": [
            {"key": "transcribe", "label": "Transkribieren", "duration_seconds": 0.6},
            {"key": "diarize", "label": "Sprecher erkennen", "duration_seconds": 0.3},
            {"key": "minutes", "label": "Minutes erstellen", "duration_seconds": 0.3},
        ],
    }
    return "session-123", segments, minutes, speakers, processing


def test_transcribe_endpoint_can_enable_diarization(monkeypatch):
    captured = {}

    async def _fake_transcribe_with_diarize(audio_path, diarize=False, cache_session=True):
        captured["diarize"] = diarize
        return await _fake_transcribe()

    monkeypatch.setattr(
        "backend.app.main.transcription_service.transcribe",
        _fake_transcribe_with_diarize,
    )

    response = client.post(
        "/api/transcribe",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
        data={"diarize": "true"},
    )

    assert response.status_code == 200
    assert captured["diarize"] is True


def test_create_async_transcription_job(monkeypatch):
    captured = {}

    def _fake_create_job(
        owner_id,
        meeting_name,
        filename,
        content=None,
        source_path=None,
        diarize=False,
        estimated_audio_duration_seconds=0.0,
    ):
        captured["owner_id"] = owner_id
        captured["meeting_name"] = meeting_name
        captured["filename"] = filename
        captured["content"] = content if content is not None else source_path.read_bytes()
        captured["diarize"] = diarize
        captured["estimated_audio_duration_seconds"] = estimated_audio_duration_seconds
        return {
            "job_id": "job-123",
            "meeting_name": meeting_name or "meeting",
            "audio_filename": filename,
            "status": "queued",
            "message": "Job wartet auf Verarbeitung.",
            "created_at": 1.0,
            "started_at": None,
            "finished_at": None,
            "poll_after_ms": 1000,
            "estimated_audio_duration_seconds": estimated_audio_duration_seconds,
            "queue_position": 1,
            "result": None,
        }

    monkeypatch.setattr("backend.app.main.async_job_service.create_job", _fake_create_job)
    upload_dir = Path(__file__).resolve().parents[2] / "tmp" / "test_api_create_job"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / "recording.wav"
    upload_path.write_bytes(b"123")

    async def _fake_receive_audio_file(_audio):
        return upload_dir, upload_path

    monkeypatch.setattr("backend.app.main._receive_audio_file", _fake_receive_audio_file)

    response = client.post(
        "/api/transcribe/jobs",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
        data={
            "diarize": "true",
            "estimated_audio_duration_seconds": "120",
        },
        headers={"X-Client-Id": "client-a"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-123"
    assert captured["owner_id"] == "client-a"
    assert captured["meeting_name"] is None
    assert body["meeting_name"] == "meeting"
    assert body["status"] == "queued"
    assert captured["filename"] == "meeting.wav"
    assert captured["content"] == b"123"
    assert captured["diarize"] is True
    assert captured["estimated_audio_duration_seconds"] == 120.0


def test_get_async_transcription_job_returns_result(monkeypatch):
    def _fake_get_job(owner_id, job_id):
        assert owner_id == "client-a"
        assert job_id == "job-123"
        return {
            "job_id": job_id,
            "meeting_name": "meeting",
            "audio_filename": "meeting.wav",
            "status": "completed",
            "message": "Transkription abgeschlossen.",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": 3.0,
            "poll_after_ms": 0,
            "estimated_audio_duration_seconds": 120.0,
            "queue_position": None,
            "result": TranscriptResponse(
                transcript=[
                    TranscriptSegment(
                        speaker_id="speaker_a",
                        speaker="Speaker A",
                        start=0.0,
                        end=4.0,
                        text="Guten Morgen",
                    )
                ],
                summary="Kurze Zusammenfassung",
                duration_seconds=4.0,
                minutes=MeetingMinutes(summary="Kurze Zusammenfassung", agenda=["Sync"]),
                speakers=[SpeakerProfile(speaker_id="speaker_a", label="Speaker A")],
                processing=None,
                session_id="session-123",
            ),
        }

    monkeypatch.setattr("backend.app.main.async_job_service.get_job", _fake_get_job)

    response = client.get("/api/transcribe/jobs/job-123", headers={"X-Client-Id": "client-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["meeting_name"] == "meeting"
    assert body["result"]["session_id"] == "session-123"
    assert body["result"]["summary"] == "Kurze Zusammenfassung"


def test_list_async_transcription_jobs(monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.async_job_service.list_jobs",
        lambda owner_id: [
            {
                "job_id": "job-123",
                "meeting_name": "meeting",
                "audio_filename": "meeting.wav",
                "status": "running",
                "message": "Transkription wird verarbeitet.",
                "created_at": 1.0,
                "started_at": 2.0,
                "finished_at": None,
                "poll_after_ms": 1000,
                "estimated_audio_duration_seconds": 120.0,
                "queue_position": 1,
                "result": None,
            }
        ],
    )

    response = client.get("/api/transcribe/jobs", headers={"X-Client-Id": "client-a"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["meeting_name"] == "meeting"
    assert body[0]["status"] == "running"


def test_cancel_async_transcription_job(monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.async_job_service.cancel_job",
        lambda owner_id, job_id: {
            "job_id": job_id,
            "meeting_name": "meeting",
            "audio_filename": "meeting.wav",
            "status": "cancelled",
            "message": "Job wurde gestoppt.",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": 3.0,
            "poll_after_ms": 0,
            "estimated_audio_duration_seconds": 120.0,
            "queue_position": None,
            "result": None,
        },
    )

    response = client.post("/api/transcribe/jobs/job-123/cancel", headers={"X-Client-Id": "client-a"})

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_delete_async_transcription_job(monkeypatch):
    captured = {}

    def _fake_delete_job(owner_id, job_id):
        captured["owner_id"] = owner_id
        captured["job_id"] = job_id

    monkeypatch.setattr("backend.app.main.async_job_service.delete_job", _fake_delete_job)

    response = client.delete("/api/transcribe/jobs/job-123", headers={"X-Client-Id": "client-a"})

    assert response.status_code == 204
    assert captured["owner_id"] == "client-a"
    assert captured["job_id"] == "job-123"


def test_job_endpoints_require_client_id_header():
    response = client.get("/api/transcribe/jobs")
    assert response.status_code == 400
    assert "X-Client-Id" in response.json()["detail"]


def test_submit_meeting_audio_returns_minutes(monkeypatch):
    monkeypatch.setattr("backend.app.main.transcription_service.transcribe", _fake_transcribe)

    response = client.post(
        "/api/meetings",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Kurze Zusammenfassung"
    assert body["agenda"] == ["Sync"]
    assert isinstance(body.get("sections"), list)


def test_submit_meeting_audio_response_has_no_room_metadata(monkeypatch):
    monkeypatch.setattr("backend.app.main.transcription_service.transcribe", _fake_transcribe)

    response = client.post(
        "/api/meetings",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert "room" not in body
    assert "minutes" not in body


def test_submit_meeting_and_forward_posts_minutes_to_webhook(monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.app.main.transcription_service.transcribe", _fake_transcribe)
    upload_dir = Path("codex-nonexistent-upload-submit-1")
    upload_path = upload_dir / "recording.wav"

    async def _fake_receive_audio_file(_audio):
        return upload_dir, upload_path

    monkeypatch.setattr("backend.app.main._receive_audio_file", _fake_receive_audio_file)

    async def _fake_send_minutes(room, recorded_at, minutes):
        captured["room"] = room
        captured["recorded_at"] = recorded_at
        captured["minutes_summary"] = minutes.summary
        return {
            "delivered": True,
            "url": "https://example.local/webhook/meeting",
            "attempts": 1,
            "status_code": 200,
            "detail": "Webhook erfolgreich zugestellt.",
        }

    monkeypatch.setattr("backend.app.main.webhook_service.send_minutes", _fake_send_minutes)

    response = client.post(
        "/api/meetings/submit",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
        data={"room": "E01-115 SWS", "recorded_at": "2026-04-15T05:30:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["room"] == "E01-115 SWS"
    assert body["recorded_at"] == "2026-04-15T05:30:00Z"
    assert body["minutes"]["summary"] == "Kurze Zusammenfassung"
    assert body["webhook"]["delivered"] is True
    assert captured["room"] == "E01-115 SWS"
    assert captured["recorded_at"] == "2026-04-15T05:30:00Z"
    assert captured["minutes_summary"] == "Kurze Zusammenfassung"


def test_submit_meeting_and_forward_uses_defaults_for_room_and_recorded_at(monkeypatch):
    captured = {}
    monkeypatch.setattr("backend.app.main.transcription_service.transcribe", _fake_transcribe)
    monkeypatch.setattr("backend.app.main._iso_utc_now", lambda: "2026-04-15T05:45:00Z")
    upload_dir = Path("codex-nonexistent-upload-submit-2")
    upload_path = upload_dir / "recording.wav"

    async def _fake_receive_audio_file(_audio):
        return upload_dir, upload_path

    monkeypatch.setattr("backend.app.main._receive_audio_file", _fake_receive_audio_file)

    async def _fake_send_minutes(room, recorded_at, minutes):
        captured["room"] = room
        captured["recorded_at"] = recorded_at
        return {
            "delivered": False,
            "url": "",
            "attempts": 0,
            "status_code": None,
            "detail": "MEETING_WEBHOOK_URL ist nicht gesetzt.",
        }

    monkeypatch.setattr("backend.app.main.webhook_service.send_minutes", _fake_send_minutes)

    response = client.post(
        "/api/meetings/submit",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["room"] == "unknown"
    assert body["recorded_at"] == "2026-04-15T05:45:00Z"
    assert body["webhook"]["delivered"] is False
    assert captured["room"] == "unknown"
    assert captured["recorded_at"] == "2026-04-15T05:45:00Z"


def test_forward_meeting_minutes_posts_to_webhook(monkeypatch):
    captured = {}

    async def _fake_send_minutes(room, recorded_at, minutes):
        captured["room"] = room
        captured["recorded_at"] = recorded_at
        captured["summary"] = minutes.summary
        return {
            "delivered": True,
            "url": "https://example.local/webhook/meeting",
            "attempts": 1,
            "status_code": 200,
            "detail": "Webhook erfolgreich zugestellt.",
        }

    monkeypatch.setattr("backend.app.main.webhook_service.send_minutes", _fake_send_minutes)

    response = client.post(
        "/api/meetings/forward",
        json={
            "room": "E01-115 SWS",
            "recorded_at": "2026-04-15T06:00:00Z",
            "duration_seconds": 120,
            "minutes": {
                "summary": "Kurze Zusammenfassung",
                "agenda": ["Sync"],
                "highlights": [],
                "decisions": [],
                "action_items": [],
                "risks": [],
                "sections": [],
                "model": "test",
                "chunk_count": 1,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["webhook"]["delivered"] is True
    assert body["room"] == "E01-115 SWS"
    assert body["recorded_at"] == "2026-04-15T06:00:00Z"
    assert body["minutes"]["summary"] == "Kurze Zusammenfassung"
    assert captured["room"] == "E01-115 SWS"
    assert captured["recorded_at"] == "2026-04-15T06:00:00Z"
    assert captured["summary"] == "Kurze Zusammenfassung"


async def _failing_transcribe(*_args, **_kwargs):
    raise RuntimeError("WhisperX-Modell konnte nicht geladen werden.")


def test_submit_meeting_audio_returns_503_when_transcription_fails(monkeypatch):
    monkeypatch.setattr("backend.app.main.transcription_service.transcribe", _failing_transcribe)

    response = client.post(
        "/api/meetings",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
    )

    assert response.status_code == 503
    assert "WhisperX-Modell" in response.json()["detail"]


def test_analyze_endpoint_enables_diarization_when_speakers_requested(monkeypatch):
    captured = {}

    async def _fake_transcribe_for_analyze(audio_path, diarize=False, cache_session=True):
        captured["diarize"] = diarize
        return await _fake_transcribe()

    monkeypatch.setattr(
        "backend.app.main.transcription_service.transcribe",
        _fake_transcribe_for_analyze,
    )

    response = client.post(
        "/api/analyze?include_speakers=true",
        files={"audio": ("meeting.wav", b"123", "audio/wav")},
    )

    assert response.status_code == 200
    assert captured["diarize"] is True


def test_get_model_settings_returns_runtime_configuration(monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: {
            "execution_device": "auto",
            "transcription_provider": "azure_openai",
            "whisper_model": "medium",
            "diarization_model": "pyannote/speaker-diarization-3.1",
            "azure_transcription_endpoint": "https://example.openai.azure.com",
            "azure_transcription_api_key": "azure-secret",
            "azure_transcription_api_version": "2024-02-01",
            "azure_transcription_deployment": "whisper-prod",
            "azure_speech_endpoint": "https://germanywestcentral.api.cognitive.microsoft.com/",
            "azure_speech_region": "germanywestcentral",
            "azure_speech_locales": "de-DE,en-US",
            "azure_speech_max_speakers": 4,
            "llm_provider": "llama_cpp",
            "llm_model": "gpt-4o-mini",
            "llm_azure_endpoint": "https://llm-example.openai.azure.com",
            "llm_azure_api_key": "Bearer azure-llm-token",
            "llm_azure_api_version": "2025-01-01-preview",
            "llm_base_url": "https://api.example.com",
            "llm_api_key": "secret",
            "llm_completions_path": "/v1/chat/completions",
            "llm_local_model_path": "C:/models/local.gguf",
            "llm_local_context_size": 4096,
            "llm_local_gpu_layers": 20,
            "summary_model": "gpt-4o-mini",
            "summary_llm_base_url": "",
            "summary_llm_api_key": "",
            "summary_llm_completions_path": "",
        },
    )

    response = client.get("/api/settings/models")

    assert response.status_code == 200
    body = response.json()
    assert body["transcription_provider"] == "azure_openai"
    assert body["azure_transcription_deployment"] == "whisper-prod"
    assert body["azure_speech_region"] == "germanywestcentral"
    assert body["llm_provider"] == "llama_cpp"
    assert body["llm_model"] == "gpt-4o-mini"
    assert body["llm_azure_endpoint"] == "https://llm-example.openai.azure.com"
    assert body["llm_azure_api_version"] == "2025-01-01-preview"
    assert body["llm_local_model_path"] == "C:/models/local.gguf"


def test_put_model_settings_updates_store_and_runtime(monkeypatch):
    captured = {}

    class DummyStore:
        def update(self, payload):
            captured["payload"] = payload.model_dump(exclude_none=True)
            return ModelSettings(
                whisper_model=payload.whisper_model or "auto",
                execution_device=payload.execution_device or "auto",
                transcription_provider=payload.transcription_provider or "local",
                diarization_model=payload.diarization_model or "auto",
                azure_transcription_endpoint=payload.azure_transcription_endpoint or "",
                azure_transcription_api_key=payload.azure_transcription_api_key or "",
                azure_transcription_api_version=payload.azure_transcription_api_version or "2024-02-01",
                azure_transcription_deployment=payload.azure_transcription_deployment or "",
                azure_speech_endpoint=payload.azure_speech_endpoint or "",
                azure_speech_region=payload.azure_speech_region or "",
                azure_speech_locales=payload.azure_speech_locales or "",
                azure_speech_max_speakers=payload.azure_speech_max_speakers,
                llm_provider=payload.llm_provider or "llama_cpp",
                llm_model=payload.llm_model or "gemma-3-4b-it-qat",
                llm_azure_endpoint=payload.llm_azure_endpoint or "",
                llm_azure_api_key=payload.llm_azure_api_key or "",
                llm_azure_api_version=payload.llm_azure_api_version or "2025-01-01-preview",
                llm_base_url=payload.llm_base_url or "",
                llm_api_key=payload.llm_api_key or "",
                llm_completions_path=payload.llm_completions_path or "/v1/chat/completions",
                llm_local_model_path=payload.llm_local_model_path or "",
                llm_local_context_size=payload.llm_local_context_size or 262144,
                llm_local_gpu_layers=payload.llm_local_gpu_layers or 0,
                summary_model=payload.summary_model or "gemma-3-4b-it-qat",
                summary_llm_base_url=payload.summary_llm_base_url or "",
                summary_llm_api_key=payload.summary_llm_api_key or "",
                summary_llm_completions_path=payload.summary_llm_completions_path or "",
            )

    applied = {}

    monkeypatch.setattr("backend.app.main.settings_store", DummyStore())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.apply_settings",
        lambda settings: applied.update(settings.model_dump()),
    )
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: applied,
    )

    response = client.put(
        "/api/settings/models",
        json={
            "transcription_provider": "azure_openai",
            "azure_transcription_endpoint": "https://example.openai.azure.com",
            "azure_transcription_api_key": "azure-secret",
            "azure_transcription_api_version": "2024-02-01",
            "azure_transcription_deployment": "whisper-prod",
            "azure_speech_region": "germanywestcentral",
            "llm_provider": "llama_cpp",
            "llm_model": "gpt-4o-mini",
            "execution_device": "cpu",
            "llm_local_model_path": "C:/models/local.gguf",
            "llm_local_context_size": 4096,
            "llm_local_gpu_layers": 16,
        },
    )

    assert response.status_code == 200
    assert captured["payload"]["execution_device"] == "cpu"
    assert captured["payload"]["transcription_provider"] == "azure_openai"
    assert captured["payload"]["azure_transcription_deployment"] == "whisper-prod"
    assert captured["payload"]["azure_speech_region"] == "germanywestcentral"
    assert captured["payload"]["llm_provider"] == "llama_cpp"
    assert captured["payload"]["llm_model"] == "gpt-4o-mini"
    assert applied["llm_local_model_path"] == "C:/models/local.gguf"


def test_put_model_settings_accepts_azure_openai_llm(monkeypatch):
    captured = {}

    class DummyStore:
        def save(self, settings):
            captured["settings"] = settings.model_dump()
            return settings

    applied = {}
    monkeypatch.setattr("backend.app.main.settings_store", DummyStore())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.apply_settings",
        lambda settings: applied.update(settings.model_dump()),
    )
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: ModelSettings(llm_local_model_path="C:/models/local.gguf"),
    )

    response = client.put(
        "/api/settings/models",
        json={
            "llm_provider": "azure_openai",
            "llm_model": "gpt-4.1-mini",
            "llm_azure_endpoint": "https://llm-example.openai.azure.com",
            "llm_azure_api_key": "Bearer azure-llm-token",
            "llm_azure_api_version": "2025-01-01-preview",
            "summary_model": "gpt-5-nano",
        },
    )

    assert response.status_code == 200
    assert captured["settings"]["llm_provider"] == "azure_openai"
    assert captured["settings"]["llm_model"] == "gpt-4.1-mini"
    assert captured["settings"]["llm_azure_endpoint"] == "https://llm-example.openai.azure.com"
    assert captured["settings"]["llm_azure_api_version"] == "2025-01-01-preview"
    assert applied["llm_provider"] == "azure_openai"
    assert applied["llm_model"] == "gpt-4.1-mini"


def test_health_includes_hardware_recommendation(monkeypatch):
    monkeypatch.setattr(
        "backend.app.main.transcription_service.hardware_profile",
        lambda: type(
            "DummyHardwareProfile",
            (),
            {
                "device": "cpu",
                "gpu_available": False,
                "gpu_memory_gb": 0.0,
                "performance_tier": "low",
                "recommended_execution": "api",
                "performance_message": "CPU-only erkannt, API empfohlen.",
            },
        )(),
    )

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["device"] == "cpu"
    assert body["recommended_execution"] == "api"
    assert body["performance_tier"] == "low"


def test_put_model_settings_rejects_missing_local_model_path(monkeypatch):
    class DummyStore:
        def update(self, _payload):
            raise ValueError("Fuer llama-cpp-python muss ein lokaler GGUF-Modellpfad gesetzt sein.")

    monkeypatch.setattr("backend.app.main.settings_store", DummyStore())

    response = client.put(
        "/api/settings/models",
        json={
            "llm_provider": "llama_cpp",
            "llm_model": "Qwen2.5-7B-Instruct",
            "llm_local_model_path": "",
        },
    )

    assert response.status_code == 400
    assert "GGUF-Modellpfad" in response.json()["detail"]


def test_put_model_settings_rejects_missing_azure_deployment(monkeypatch):
    monkeypatch.setattr("backend.app.main.settings_store", object())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: ModelSettings(),
    )

    response = client.put(
        "/api/settings/models",
        json={
            "transcription_provider": "azure_openai",
            "azure_transcription_endpoint": "https://example.openai.azure.com",
            "azure_transcription_api_key": "azure-secret",
            "azure_transcription_deployment": "",
        },
    )

    assert response.status_code == 400
    assert "Deployment" in response.json()["detail"]


def test_put_model_settings_rejects_missing_azure_llm_endpoint(monkeypatch):
    monkeypatch.setattr("backend.app.main.settings_store", object())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: ModelSettings(llm_local_model_path="C:/models/local.gguf"),
    )

    response = client.put(
        "/api/settings/models",
        json={
            "llm_provider": "azure_openai",
            "llm_model": "gpt-4.1-mini",
            "llm_azure_endpoint": "",
            "llm_azure_api_key": "Bearer azure-llm-token",
        },
    )

    assert response.status_code == 400
    assert "Azure-Endpoint" in response.json()["detail"]


def test_put_model_settings_accepts_azure_speech_without_deployment(monkeypatch):
    captured = {}

    class DummyStore:
        def save(self, settings):
            captured["settings"] = settings.model_dump()
            return settings

    applied = {}
    monkeypatch.setattr("backend.app.main.settings_store", DummyStore())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.apply_settings",
        lambda settings: applied.update(settings.model_dump()),
    )
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: ModelSettings(),
    )

    response = client.put(
        "/api/settings/models",
        json={
            "transcription_provider": "azure_speech",
            "azure_transcription_api_key": "speech-secret",
            "azure_transcription_api_version": "2024-11-15",
            "azure_speech_endpoint": "https://germanywestcentral.api.cognitive.microsoft.com/",
            "azure_speech_region": "germanywestcentral",
            "azure_speech_locales": "de-DE,en-US",
            "azure_speech_max_speakers": 4,
            "llm_local_model_path": "C:/models/local.gguf",
        },
    )

    assert response.status_code == 200
    assert captured["settings"]["transcription_provider"] == "azure_speech"
    assert captured["settings"]["azure_speech_region"] == "germanywestcentral"
    assert applied["transcription_provider"] == "azure_speech"


def test_put_model_settings_rejects_invalid_azure_speech_max_speakers(monkeypatch):
    monkeypatch.setattr("backend.app.main.settings_store", object())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.export_settings",
        lambda: ModelSettings(llm_local_model_path="C:/models/local.gguf"),
    )

    response = client.put(
        "/api/settings/models",
        json={
            "transcription_provider": "azure_speech",
            "azure_transcription_api_key": "speech-secret",
            "azure_speech_region": "germanywestcentral",
            "azure_speech_max_speakers": 0,
            "llm_local_model_path": "C:/models/local.gguf",
        },
    )

    assert response.status_code == 400
    assert "Max. Sprecher" in response.json()["detail"]


def test_download_model_updates_runtime_settings(monkeypatch):
    captured = {}

    class DummyDownloader:
        def start_download(self, model_id):
            captured["model_id"] = model_id
            return type(
                "DownloadStatus",
                (),
                {
                    "model_id": "gemma3_4b_gguf",
                    "state": "running",
                    "message": "Download wird vorbereitet ...",
                    "provider": "llama_cpp",
                    "llm_model": "gemma-3-4b-it-qat",
                    "llm_local_model_path": "C:/Users/Test/AppData/Local/AuroraMinutes/models/gemma3-4b/google_gemma-3-4b-it-qat-Q4_0.gguf",
                    "bytes_downloaded": 0,
                    "total_bytes": 100,
                },
            )()

    class DummyStore:
        def __init__(self):
            self.current = ModelSettings()

        def load(self):
            return self.current

        def save(self, settings):
            self.current = settings
            return settings

    applied = {}
    monkeypatch.setattr("backend.app.main.model_download_service", DummyDownloader())
    monkeypatch.setattr("backend.app.main.settings_store", DummyStore())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.apply_settings",
        lambda settings: applied.update(settings.model_dump()),
    )

    response = client.post("/api/settings/models/download", json={"model_id": "gemma3_4b_gguf"})

    assert response.status_code == 200
    body = response.json()
    assert captured["model_id"] == "gemma3_4b_gguf"
    assert body["state"] == "running"
    assert body["provider"] == "llama_cpp"
    assert body["llm_local_model_path"].endswith(".gguf")
    assert applied == {}


def test_get_download_status_applies_completed_model(monkeypatch):
    class DummyDownloader:
        def get_status(self, _model_id):
            return type(
                "DownloadStatus",
                (),
                {
                    "model_id": "gemma3_4b_gguf",
                    "state": "completed",
                    "message": "Modell heruntergeladen.",
                    "provider": "llama_cpp",
                    "llm_model": "gemma-3-4b-it-qat",
                    "llm_local_model_path": "C:/Users/Test/AppData/Local/AuroraMinutes/models/gemma3-4b/google_gemma-3-4b-it-qat-Q4_0.gguf",
                    "bytes_downloaded": 123,
                    "total_bytes": 123,
                },
            )()

    class DummyStore:
        def __init__(self):
            self.current = ModelSettings()

        def load(self):
            return self.current

        def save(self, settings):
            self.current = settings
            return settings

    applied = {}
    monkeypatch.setattr("backend.app.main.model_download_service", DummyDownloader())
    monkeypatch.setattr("backend.app.main.settings_store", DummyStore())
    monkeypatch.setattr(
        "backend.app.main.transcription_service.apply_settings",
        lambda settings: applied.update(settings.model_dump()),
    )

    response = client.get("/api/settings/models/download/gemma3_4b_gguf")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert applied["llm_provider"] == "llama_cpp"
    assert applied["llm_local_model_path"].endswith(".gguf")
