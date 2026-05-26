from __future__ import annotations

import json
import os
import shutil
import tempfile
import datetime as dt
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Header, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    AnalysisResponse,
    AuthenticatedUser,
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthSessionResponse,
    AsyncTranscriptionJobResponse,
    HealthResponse,
    ManualSegment,
    ModelDownloadRequest,
    ModelDownloadResponse,
    MeetingMinutes,
    MeetingForwardRequest,
    MeetingSubmitResponse,
    ModelSettings,
    ModelSettingsUpdate,
    ProcessingMetadata,
    TaskBoardResponse,
    MinutesEvaluationRequest,
    MinutesEvaluationResponse,
    TranscriptResponse,
)
from .services.async_jobs import AsyncTranscriptionJobService
from .services.action_item_notifications import ActionItemNotificationService
from .services.auth import AuthService
from .services.model_downloads import ModelDownloadService
from .services.settings import RuntimeSettingsStore
from .services.task_board import TaskBoardService
from .services.transcription import TranscriptionService
from .services.webhook import WebhookService

ALLOWED_OUTPUTS = {"transcript", "summary", "minutes"}
CLIENT_ID_HEADER = "X-Client-Id"


app = FastAPI(
    title="Aurora Minutes",
    description="Professionelle Meeting-Aufzeichnungen mit Transkription und Sprecherkennung",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings_store = RuntimeSettingsStore()
model_download_service = ModelDownloadService()
transcription_service = TranscriptionService()
async_job_service = AsyncTranscriptionJobService(transcription_service)
webhook_service = WebhookService()
auth_service = AuthService()
action_item_notification_service = ActionItemNotificationService()
task_board_service = TaskBoardService()
transcription_service.apply_settings(settings_store.load())


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    hardware = transcription_service.hardware_profile()
    return HealthResponse(
        status="ok",
        transcription_provider=transcription_service.transcription_provider,
        whisper_model=transcription_service.whisper_model,
        diarization_model=transcription_service.diarization_model,
        summary_model=transcription_service.summary_model,
        llm_model=transcription_service._minutes.model,
        device=hardware.device,
        gpu_available=hardware.gpu_available,
        gpu_memory_gb=hardware.gpu_memory_gb,
        performance_tier=hardware.performance_tier,
        recommended_execution=hardware.recommended_execution,
        performance_message=hardware.performance_message,
    )


RELEASE_INFO_CANDIDATES = (
    Path(os.environ.get("RELEASE_INFO_PATH", "")),
    Path("/app/RELEASE.json"),
    Path(__file__).resolve().parents[2] / "RELEASE.json",
    Path(__file__).resolve().parents[1] / "RELEASE.json",
)


def _load_release_info() -> dict:
    for candidate in RELEASE_INFO_CANDIDATES:
        if not candidate or str(candidate) == "":
            continue
        try:
            if candidate.is_file():
                with candidate.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict) and data.get("version"):
                    return data
        except (OSError, ValueError):
            continue
    return {
        "version": "0.0.0-dev",
        "date": dt.date.today().isoformat(),
        "title": "Entwicklungsversion",
        "subtitle": "Kein RELEASE.json gefunden",
        "highlights": [],
    }


@app.get("/api/release/current")
def get_current_release() -> dict:
    return _load_release_info()


@app.post("/api/auth/register", response_model=AuthSessionResponse)
def register_user(payload: AuthRegisterRequest) -> AuthSessionResponse:
    try:
        user, token = auth_service.register_user(
            name=payload.name,
            email=payload.email,
            password=payload.password,
        )
        return AuthSessionResponse(user=AuthenticatedUser.model_validate(user), token=token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auth/login", response_model=AuthSessionResponse)
def login_user(payload: AuthLoginRequest) -> AuthSessionResponse:
    try:
        user, token = auth_service.login_user(email=payload.email, password=payload.password)
        return AuthSessionResponse(user=AuthenticatedUser.model_validate(user), token=token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/auth/me", response_model=AuthenticatedUser)
def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    try:
        user = auth_service.get_user_by_token(token)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return AuthenticatedUser.model_validate(user)


@app.post("/api/auth/logout", status_code=204, response_class=Response)
def logout_user(authorization: str | None = Header(default=None)) -> Response:
    token = _extract_bearer_token(authorization)
    if token:
        try:
            auth_service.logout(token)
        except ValueError:
            pass
    return Response(status_code=204)


@app.get("/api/settings/models", response_model=ModelSettings)
def get_model_settings() -> ModelSettings:
    return transcription_service.export_settings()


@app.put("/api/settings/models", response_model=ModelSettings)
def update_model_settings(payload: ModelSettingsUpdate) -> ModelSettings:
    try:
        payload_data = payload.model_dump(exclude_none=True)
        current_settings_raw = transcription_service.export_settings()
        current_settings = (
            current_settings_raw
            if isinstance(current_settings_raw, ModelSettings)
            else ModelSettings.model_validate(current_settings_raw)
        )
        next_settings = current_settings.model_copy(update=payload_data)
        llm_azure_sensitive_fields = {
            "llm_provider",
            "llm_model",
            "llm_azure_endpoint",
            "llm_azure_api_key",
            "llm_azure_api_version",
        }
        llm_azure_settings_changed = bool(llm_azure_sensitive_fields.intersection(payload_data.keys()))
        if next_settings.transcription_provider == "azure_openai":
            if not next_settings.azure_transcription_endpoint.strip():
                raise ValueError("Fuer Azure OpenAI muss ein Azure-Endpoint gesetzt sein.")
            if not next_settings.azure_transcription_api_key.strip():
                raise ValueError("Fuer Azure OpenAI muss ein API-Key gesetzt sein.")
            if not next_settings.azure_transcription_deployment.strip():
                raise ValueError("Fuer Azure OpenAI muss ein Deployment-Name gesetzt sein.")
        if next_settings.transcription_provider == "azure_speech":
            if not (next_settings.azure_speech_endpoint.strip() or next_settings.azure_speech_region.strip()):
                raise ValueError("Fuer Azure Speech muss ein Endpoint oder eine Azure-Region gesetzt sein.")
            if not next_settings.azure_transcription_api_key.strip():
                raise ValueError("Fuer Azure Speech muss ein API-Key gesetzt sein.")
            if next_settings.azure_speech_max_speakers is not None and next_settings.azure_speech_max_speakers < 1:
                raise ValueError("Fuer Azure Speech muss Max. Sprecher groesser als 0 sein.")
        if llm_azure_settings_changed and next_settings.llm_provider == "azure_openai":
            if not next_settings.llm_azure_endpoint.strip():
                raise ValueError("Fuer Azure OpenAI LLM muss ein Azure-Endpoint gesetzt sein.")
            if not next_settings.llm_azure_api_key.strip():
                raise ValueError("Fuer Azure OpenAI LLM muss ein Bearer-Token oder API-Key gesetzt sein.")
            if not next_settings.llm_model.strip():
                raise ValueError("Fuer Azure OpenAI LLM muss eine Modell-ID bzw. ein Deployment gesetzt sein.")
        if hasattr(settings_store, "save"):
            next_settings = settings_store.save(next_settings)
        elif hasattr(settings_store, "update"):
            next_settings = settings_store.update(payload)
        else:
            raise ValueError("Settings-Store unterstuetzt weder save noch update.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    transcription_service.apply_settings(next_settings)
    return transcription_service.export_settings()


@app.post("/api/settings/models/download", response_model=ModelDownloadResponse)
def download_model(payload: ModelDownloadRequest) -> ModelDownloadResponse:
    try:
        status = model_download_service.start_download(payload.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ModelDownloadResponse(
        model_id=status.model_id,
        state=status.state,
        provider=status.provider,
        llm_model=status.llm_model,
        llm_local_model_path=status.llm_local_model_path,
        bytes_downloaded=status.bytes_downloaded,
        total_bytes=status.total_bytes,
        downloaded=status.state == "completed",
        message=status.message,
    )


@app.get("/api/settings/models/download/{model_id}", response_model=ModelDownloadResponse)
def get_download_status(model_id: str) -> ModelDownloadResponse:
    try:
        status = model_download_service.get_status(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if status.state == "completed":
        updated_settings = settings_store.save(
            transcription_service.export_settings().model_copy(
                update={
                    "llm_provider": status.provider,
                    "llm_model": status.llm_model,
                    "llm_local_model_path": status.llm_local_model_path,
                }
            )
        )
        transcription_service.apply_settings(updated_settings)

    return ModelDownloadResponse(
        model_id=status.model_id,
        state=status.state,
        provider=status.provider,
        llm_model=status.llm_model,
        llm_local_model_path=status.llm_local_model_path,
        bytes_downloaded=status.bytes_downloaded,
        total_bytes=status.total_bytes,
        downloaded=status.state == "completed",
        message=status.message,
    )


@app.post("/api/transcribe", response_model=TranscriptResponse)
async def upload_audio(
    audio: UploadFile = File(...),
    diarize: bool = Form(default=False),
) -> TranscriptResponse:
    temp_dir, temp_path = await _receive_audio_file(audio)
    try:
        try:
            session_id, segments, minutes, speakers, processing = await transcription_service.transcribe(temp_path, diarize=diarize)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        duration = segments[-1].end if segments else 0.0
        return TranscriptResponse(
            transcript=segments,
            summary=minutes.summary,
            duration_seconds=duration,
            minutes=minutes,
            speakers=speakers,
            processing=ProcessingMetadata.model_validate(processing),
            session_id=session_id,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/api/transcribe/jobs", response_model=AsyncTranscriptionJobResponse)
async def create_transcription_job(
    meeting_name: str | None = Form(default=None),
    audio: UploadFile = File(...),
    diarize: bool = Form(default=False),
    estimated_audio_duration_seconds: float = Form(default=0.0),
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> AsyncTranscriptionJobResponse:
    owner_id = _resolve_owner_id(x_client_id=x_client_id, authorization=authorization)
    try:
        temp_dir, temp_path = await _receive_audio_file(audio)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return async_job_service.create_job(
            owner_id=owner_id,
            meeting_name=meeting_name,
            filename=audio.filename or temp_path.name,
            source_path=temp_path,
            diarize=diarize,
            estimated_audio_duration_seconds=estimated_audio_duration_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.get("/api/transcribe/jobs/{job_id}", response_model=AsyncTranscriptionJobResponse)
def get_transcription_job(
    job_id: str,
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> AsyncTranscriptionJobResponse:
    owner_id = _resolve_owner_id(x_client_id=x_client_id, authorization=authorization)
    try:
        return async_job_service.get_job(owner_id=owner_id, job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/transcribe/jobs", response_model=list[AsyncTranscriptionJobResponse])
def list_transcription_jobs(
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> list[AsyncTranscriptionJobResponse]:
    owner_id = _resolve_owner_id(x_client_id=x_client_id, authorization=authorization)
    try:
        return async_job_service.list_jobs(owner_id=owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/transcribe/jobs/{job_id}/cancel", response_model=AsyncTranscriptionJobResponse)
def cancel_transcription_job(
    job_id: str,
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> AsyncTranscriptionJobResponse:
    owner_id = _resolve_owner_id(x_client_id=x_client_id, authorization=authorization)
    try:
        return async_job_service.cancel_job(owner_id=owner_id, job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/transcribe/jobs/{job_id}", status_code=204, response_class=Response)
def delete_transcription_job(
    job_id: str,
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> Response:
    owner_id = _resolve_owner_id(x_client_id=x_client_id, authorization=authorization)
    try:
        async_job_service.delete_job(owner_id=owner_id, job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 409 if "zuerst gestoppt" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return Response(status_code=204)


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_audio(
    audio: UploadFile = File(...),
    diarize: bool = Form(default=False),
    include: list[str] = Query(
        default=["transcript", "summary", "minutes"],
        description="Welche Bestandteile sollen zurückgegeben werden?",
    ),
    include_speakers: bool = Query(
        default=False,
        description="Ob Sprecherprofile mitgesendet werden sollen.",
    ),
) -> AnalysisResponse:
    normalized = {item.lower() for item in include}
    invalid = normalized - ALLOWED_OUTPUTS
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannte response-Typen: {', '.join(sorted(invalid))}",
        )
    diarize = diarize or include_speakers
    temp_dir, temp_path = await _receive_audio_file(audio)
    try:
        try:
            session_id, segments, minutes, speakers, processing = await transcription_service.transcribe(temp_path, diarize=diarize)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        duration = segments[-1].end if segments else 0.0
        response = AnalysisResponse(
            requested_outputs=sorted(normalized),
            duration_seconds=duration,
            processing=ProcessingMetadata.model_validate(processing),
            session_id=session_id,
        )
        if "transcript" in normalized:
            response.transcript = segments
        if "summary" in normalized:
            response.summary = minutes.summary
        if "minutes" in normalized:
            response.minutes = minutes
        if include_speakers:
            response.speakers = speakers
        return response
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/api/minutes/evaluate", response_model=MinutesEvaluationResponse)
async def evaluate_minutes(
    payload: MinutesEvaluationRequest,
) -> MinutesEvaluationResponse:
    if not payload.segments:
        raise HTTPException(status_code=400, detail="Keine Segmente bereitgestellt")
    _, minutes, predictions = transcription_service.evaluate_segments(payload.segments)
    return MinutesEvaluationResponse(minutes=minutes, predictions=predictions)


@app.post("/api/meetings", response_model=MeetingMinutes)
async def submit_meeting_audio(
    audio: UploadFile = File(...),
    diarize: bool = Form(default=False),
) -> MeetingMinutes:
    temp_dir, temp_path = await _receive_audio_file(audio)
    try:
        try:
            _, _, minutes, _, _ = await transcription_service.transcribe(temp_path, cache_session=False, diarize=diarize)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return minutes
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/api/meetings/submit", response_model=MeetingSubmitResponse)
async def submit_meeting_and_forward(
    audio: UploadFile = File(...),
    room: str = Form(default=""),
    recorded_at: str | None = Form(default=None),
    notify_action_items: bool = Form(default=True),
    diarize: bool = Form(default=False),
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> MeetingSubmitResponse:
    owner_id = _resolve_owner_id_optional(x_client_id=x_client_id, authorization=authorization)
    temp_dir, temp_path = await _receive_audio_file(audio)
    try:
        try:
            _, _, minutes, _, _ = await transcription_service.transcribe(temp_path, cache_session=False, diarize=diarize)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    normalized_room = room.strip() or "unknown"
    normalized_recorded_at = (recorded_at or "").strip() or _iso_utc_now()
    webhook_status = await webhook_service.send_minutes(
        room=normalized_room,
        recorded_at=normalized_recorded_at,
        minutes=minutes,
    )
    action_item_notifications = (
        action_item_notification_service.send_notifications(
            room=normalized_room,
            recorded_at=normalized_recorded_at,
            minutes=minutes,
        )
        if notify_action_items
        else []
    )
    task_board_service.record_meeting_tasks(
        owner_id=owner_id,
        room=normalized_room,
        recorded_at=normalized_recorded_at,
        meeting_name=Path(audio.filename or "Meeting").stem,
        meeting_key=None,
        minutes=minutes,
        notify_action_items=notify_action_items,
        notification_statuses=action_item_notifications,
    )
    return MeetingSubmitResponse(
        room=normalized_room,
        recorded_at=normalized_recorded_at,
        minutes=minutes,
        webhook=webhook_status,
        action_item_notifications=action_item_notifications,
    )


@app.post("/api/meetings/forward", response_model=MeetingSubmitResponse)
async def forward_meeting_minutes(
    payload: MeetingForwardRequest,
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> MeetingSubmitResponse:
    owner_id = _resolve_owner_id_optional(x_client_id=x_client_id, authorization=authorization)
    normalized_room = (payload.room or "").strip() or "unknown"
    normalized_recorded_at = (payload.recorded_at or "").strip() or _iso_utc_now()
    webhook_status = await webhook_service.send_minutes(
        room=normalized_room,
        recorded_at=normalized_recorded_at,
        minutes=payload.minutes,
    )
    action_item_notifications = (
        action_item_notification_service.send_notifications(
            room=normalized_room,
            recorded_at=normalized_recorded_at,
            minutes=payload.minutes,
            overrides=payload.action_item_notification_overrides,
        )
        if payload.notify_action_items
        else []
    )
    task_board_service.record_meeting_tasks(
        owner_id=owner_id,
        room=normalized_room,
        recorded_at=normalized_recorded_at,
        meeting_name=(payload.meeting_name or "").strip() or "Meeting",
        meeting_key=(payload.meeting_key or "").strip() or None,
        minutes=payload.minutes,
        notify_action_items=payload.notify_action_items,
        notification_statuses=action_item_notifications,
    )
    return MeetingSubmitResponse(
        room=normalized_room,
        recorded_at=normalized_recorded_at,
        minutes=payload.minutes,
        webhook=webhook_status,
        action_item_notifications=action_item_notifications,
    )


@app.get("/api/tasks/board", response_model=TaskBoardResponse)
def get_task_board(
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> TaskBoardResponse:
    owner_id = _resolve_owner_id(x_client_id=x_client_id, authorization=authorization)
    return task_board_service.get_board(owner_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, access_log=False)


async def _receive_audio_file(audio: UploadFile) -> tuple[Path, Path]:
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Keine Audiodatei übermittelt")
    suffix = Path(audio.filename).suffix or ".wav"
    temp_dir = Path(tempfile.mkdtemp(prefix="meeting-"))
    temp_path = temp_dir / f"recording{suffix}"
    with temp_path.open("wb") as buffer:
        while chunk := await audio.read(1024 * 1024):
            buffer.write(chunk)
    return temp_dir, temp_path


def _iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_client_id(value: str | None) -> str:
    client_id = (value or "").strip()
    if client_id:
        return client_id
    raise HTTPException(
        status_code=400,
        detail=f"Fehlender Header {CLIENT_ID_HEADER}. Bitte die Seite neu laden.",
    )


def _extract_bearer_token(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    prefix = "bearer "
    if raw.lower().startswith(prefix):
        token = raw[len(prefix) :].strip()
        return token or None
    return None


def _resolve_owner_id(x_client_id: str | None, authorization: str | None) -> str:
    token = _extract_bearer_token(authorization)
    if token:
        try:
            user = auth_service.get_user_by_token(token)
            return str(user["id"])
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _require_client_id(x_client_id)


def _resolve_owner_id_optional(x_client_id: str | None, authorization: str | None) -> str:
    token = _extract_bearer_token(authorization)
    if token:
        try:
            user = auth_service.get_user_by_token(token)
            return str(user["id"])
        except (ValueError, RuntimeError):
            return "__legacy__"
    client_id = (x_client_id or "").strip()
    return client_id or "__legacy__"
