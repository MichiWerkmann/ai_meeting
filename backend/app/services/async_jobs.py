from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..defaults import runtime_data_dir
from ..schemas import (
    AsyncTranscriptionJobResponse,
    ProcessingMetadata,
    TranscriptResponse,
)
from .transcription import TranscriptionService

_OWNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,128}$")


@dataclass
class AsyncTranscriptionJob:
    job_id: str
    owner_id: str
    meeting_name: str
    audio_filename: str
    job_dir: Path
    audio_path: Path
    diarize: bool
    estimated_audio_duration_seconds: float = 0.0
    status: str = "queued"
    message: str = "Job wartet in der Warteschlange."
    active_step: str | None = None
    progress_percent: float = 0.0
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    result: TranscriptResponse | None = None
    cancel_requested: bool = False


class AsyncTranscriptionJobService:
    def __init__(
        self,
        transcription_service: TranscriptionService,
        base_dir: Path | None = None,
        ttl_seconds: int = 30 * 24 * 60 * 60,
        max_concurrent_jobs: int | None = None,
    ) -> None:
        self._transcription_service = transcription_service
        self._base_dir = base_dir or runtime_data_dir() / "runtime_jobs"
        self._ttl_seconds = ttl_seconds
        self._jobs: dict[str, AsyncTranscriptionJob] = {}
        self._retired_job_dirs: set[Path] = set()
        self._lock = threading.Lock()
        configured_workers = max_concurrent_jobs or int(os.getenv("TRANSCRIPTION_MAX_CONCURRENT_JOBS", "1"))
        self._max_concurrent_jobs = max(1, configured_workers)
        self._execution_slots = threading.Semaphore(self._max_concurrent_jobs)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._load_jobs()

    def create_job(
        self,
        owner_id: str,
        meeting_name: str | None,
        filename: str,
        content: bytes | None = None,
        source_path: Path | None = None,
        diarize: bool = False,
        estimated_audio_duration_seconds: float = 0.0,
    ) -> AsyncTranscriptionJobResponse:
        normalized_owner_id = self._normalize_owner_id(owner_id)
        cleaned_name = self._derive_meeting_name(meeting_name, filename)

        self._cleanup_expired_jobs()
        job_id = uuid.uuid4().hex
        suffix = Path(filename or "recording.wav").suffix or ".wav"
        job_dir = self._base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        audio_path = job_dir / f"recording{suffix}"
        if source_path is not None:
            shutil.move(str(source_path), str(audio_path))
        elif content is not None:
            audio_path.write_bytes(content)
        else:
            raise ValueError("Es muss entweder content oder source_path gesetzt sein.")

        job = AsyncTranscriptionJob(
            job_id=job_id,
            owner_id=normalized_owner_id,
            meeting_name=cleaned_name,
            audio_filename=filename or audio_path.name,
            job_dir=job_dir,
            audio_path=audio_path,
            diarize=diarize,
            estimated_audio_duration_seconds=max(float(estimated_audio_duration_seconds or 0.0), 0.0),
            created_at=time.time(),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._persist_job(job)
            queue_position = self._queued_position_locked(job_id)
            response = self._serialize(job, queue_position=queue_position)

        threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"transcription-job-{job_id[:8]}",
        ).start()
        return response

    def list_jobs(self, owner_id: str) -> list[AsyncTranscriptionJobResponse]:
        normalized_owner_id = self._normalize_owner_id(owner_id)
        self._cleanup_expired_jobs()
        with self._lock:
            jobs = sorted(
                (item for item in self._jobs.values() if item.owner_id == normalized_owner_id),
                key=lambda item: item.created_at,
                reverse=True,
            )
            return [
                self._serialize(job, queue_position=self._queued_position_locked(job.job_id))
                for job in jobs
            ]

    def get_job(self, owner_id: str, job_id: str) -> AsyncTranscriptionJobResponse:
        normalized_owner_id = self._normalize_owner_id(owner_id)
        self._cleanup_expired_jobs()
        with self._lock:
            job = self._get_job_for_owner_locked(normalized_owner_id, job_id)
            return self._serialize(job, queue_position=self._queued_position_locked(job_id))

    def cancel_job(self, owner_id: str, job_id: str) -> AsyncTranscriptionJobResponse:
        normalized_owner_id = self._normalize_owner_id(owner_id)
        with self._lock:
            job = self._get_job_for_owner_locked(normalized_owner_id, job_id)
            if job.status == "queued":
                job.status = "cancelled"
                job.message = "Job wurde gestoppt."
                job.finished_at = time.time()
                job.cancel_requested = True
                self._persist_job(job)
                return self._serialize(job, queue_position=None)
            if job.status == "running":
                job.cancel_requested = True
                job.message = "Stopp angefordert. Job wird nach dem aktuellen Verarbeitungsschritt beendet."
                self._persist_job(job)
                return self._serialize(job, queue_position=None)
            return self._serialize(job, queue_position=self._queued_position_locked(job_id))

    def delete_job(self, owner_id: str, job_id: str) -> None:
        normalized_owner_id = self._normalize_owner_id(owner_id)
        with self._lock:
            job = self._get_job_for_owner_locked(normalized_owner_id, job_id)
            if job.status == "running":
                raise RuntimeError("Laufende Jobs muessen zuerst gestoppt werden.")
            self._jobs.pop(job_id, None)
        self._delete_job_dir(job.job_dir)

    def _load_jobs(self) -> None:
        loaded_jobs: list[AsyncTranscriptionJob] = []
        for metadata_path in self._base_dir.glob("*/metadata.json"):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                job = self._deserialize_job(metadata_path.parent, payload)
            except Exception:
                continue
            loaded_jobs.append(job)

        if not loaded_jobs:
            return

        for job in sorted(loaded_jobs, key=lambda item: item.created_at):
            if job.status == "running":
                job.status = "failed"
                job.active_step = None
                job.started_at = None
                job.finished_at = time.time()
                job.result = None
                job.message = "Verarbeitung wurde durch einen Neustart unterbrochen."
            self._jobs[job.job_id] = job
            self._persist_job(job)

    def _run_job(self, job_id: str) -> None:
        slot_acquired = False
        job_dir: Path | None = None
        try:
            if not self._wait_for_execution_slot(job_id):
                return
            slot_acquired = True

            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.message = "Job wurde gestoppt."
                    job.active_step = None
                    job.finished_at = time.time()
                    self._persist_job(job)
                    return
                job.status = "running"
                job.message = "Transkription wird verarbeitet."
                job.active_step = "transcribe"
                job.progress_percent = 5.0
                job.started_at = time.time()
                self._persist_job(job)
                job_dir = job.job_dir
                audio_path = job.audio_path
                diarize = job.diarize

            session_id, segments, minutes, speakers, processing = asyncio.run(
                self._transcription_service.transcribe(
                    audio_path,
                    diarize=diarize,
                    progress_callback=lambda message, active_step=None, progress_percent=None: self._update_job_progress(
                        job_id,
                        message=message,
                        active_step=active_step,
                        progress_percent=progress_percent,
                    ),
                )
            )
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    if job_dir is not None:
                        self._retire_job_dir(job_dir)
                    return
                if current.cancel_requested:
                    current.status = "cancelled"
                    current.message = "Job wurde gestoppt."
                    current.active_step = None
                    current.finished_at = time.time()
                    current.result = None
                    self._persist_job(current)
                    return
            duration = segments[-1].end if segments else 0.0
            result = TranscriptResponse(
                transcript=segments,
                summary=minutes.summary,
                duration_seconds=duration,
                minutes=minutes,
                speakers=speakers,
                processing=ProcessingMetadata.model_validate(processing),
                session_id=session_id,
            )
            with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    if job_dir is not None:
                        self._retire_job_dir(job_dir)
                    return
                current.status = "completed"
                current.message = "Transkription abgeschlossen."
                current.active_step = "minutes"
                current.progress_percent = 100.0
                current.finished_at = time.time()
                current.result = result
                self._persist_job(current)
        except RuntimeError as exc:
            self._mark_failed(job_id, str(exc))
        except Exception as exc:
            self._mark_failed(job_id, f"Unerwarteter Fehler: {exc}")
        finally:
            if slot_acquired:
                self._execution_slots.release()
            self._flush_retired_job_dirs()

    def _wait_for_execution_slot(self, job_id: str) -> bool:
        while True:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return False
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.message = "Job wurde gestoppt."
                    job.active_step = None
                    job.finished_at = time.time()
                    self._persist_job(job)
                    return False
            if self._execution_slots.acquire(timeout=0.5):
                return True

    def _mark_failed(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "failed"
            job.message = message
            job.active_step = None
            job.finished_at = time.time()
            self._persist_job(job)

    def _update_job_progress(
        self,
        job_id: str,
        message: str,
        active_step: str | None = None,
        progress_percent: float | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "running"}:
                return
            if message:
                job.message = message
            if active_step is not None:
                job.active_step = active_step
            if progress_percent is not None:
                job.progress_percent = max(0.0, min(float(progress_percent), 99.0))
            self._persist_job(job)

    def _deserialize_job(self, job_dir: Path, payload: dict[str, Any]) -> AsyncTranscriptionJob:
        result_payload = payload.get("result")
        result = TranscriptResponse.model_validate(result_payload) if result_payload else None
        audio_filename = payload.get("audio_filename") or "recording.wav"
        audio_path = job_dir / payload.get("audio_path", f"recording{Path(audio_filename).suffix or '.wav'}")
        return AsyncTranscriptionJob(
            job_id=payload["job_id"],
            owner_id=self._normalize_owner_id(payload.get("owner_id", "__legacy__"), default="__legacy__"),
            meeting_name=payload.get("meeting_name", "Unbenanntes Meeting"),
            audio_filename=audio_filename,
            job_dir=job_dir,
            audio_path=audio_path,
            diarize=bool(payload.get("diarize", False)),
            estimated_audio_duration_seconds=float(payload.get("estimated_audio_duration_seconds", 0.0) or 0.0),
            status=payload.get("status", "queued"),
            message=payload.get("message", ""),
            active_step=payload.get("active_step"),
            progress_percent=float(payload.get("progress_percent", 0.0) or 0.0),
            created_at=float(payload.get("created_at", time.time())),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            result=result,
            cancel_requested=bool(payload.get("cancel_requested", False)),
        )

    def _persist_job(self, job: AsyncTranscriptionJob) -> None:
        metadata_path = job.job_dir / "metadata.json"
        payload = {
            "job_id": job.job_id,
            "owner_id": job.owner_id,
            "meeting_name": job.meeting_name,
            "audio_filename": job.audio_filename,
            "audio_path": job.audio_path.name,
            "diarize": job.diarize,
            "estimated_audio_duration_seconds": job.estimated_audio_duration_seconds,
            "status": job.status,
            "message": job.message,
            "active_step": job.active_step,
            "progress_percent": job.progress_percent,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "cancel_requested": job.cancel_requested,
            "result": job.result.model_dump() if job.result is not None else None,
        }
        metadata_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _serialize(self, job: AsyncTranscriptionJob, queue_position: int | None = None) -> AsyncTranscriptionJobResponse:
        return AsyncTranscriptionJobResponse(
            job_id=job.job_id,
            meeting_name=job.meeting_name,
            audio_filename=job.audio_filename,
            status=job.status,
            message=job.message,
            active_step=job.active_step,
            progress_percent=job.progress_percent,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            poll_after_ms=1000 if job.status in {"queued", "running"} else 0,
            estimated_audio_duration_seconds=job.estimated_audio_duration_seconds,
            queue_position=queue_position if job.status == "queued" else None,
            result=job.result,
        )

    def _cleanup_expired_jobs(self) -> None:
        now = time.time()
        expired: list[tuple[str, Path]] = []
        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.status == "running":
                    continue
                reference = job.finished_at or job.created_at
                if now - reference > self._ttl_seconds:
                    self._jobs.pop(job_id, None)
                    expired.append((job_id, job.job_dir))
        for _, job_dir in expired:
            self._delete_job_dir(job_dir)
        self._flush_retired_job_dirs()

    def _queued_position_locked(self, job_id: str) -> int | None:
        reference_job = self._jobs.get(job_id)
        if reference_job is None or reference_job.status != "queued":
            return None
        queued = sorted(
            (
                item
                for item in self._jobs.values()
                if item.status == "queued" and item.owner_id == reference_job.owner_id
            ),
            key=lambda item: item.created_at,
        )
        for index, item in enumerate(queued, start=1):
            if item.job_id == job_id:
                return index
        return None

    def _get_job_for_owner_locked(self, owner_id: str, job_id: str) -> AsyncTranscriptionJob:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise RuntimeError("Transkriptions-Job nicht gefunden oder abgelaufen")
        return job

    def _retire_job_dir(self, job_dir: Path) -> None:
        self._retired_job_dirs.add(job_dir)

    def _flush_retired_job_dirs(self) -> None:
        pending = list(self._retired_job_dirs)
        self._retired_job_dirs.clear()
        for job_dir in pending:
            self._delete_job_dir(job_dir)

    @staticmethod
    def _delete_job_dir(job_dir: Path) -> None:
        shutil.rmtree(job_dir, ignore_errors=True)

    @staticmethod
    def _derive_meeting_name(meeting_name: str | None, filename: str | None) -> str:
        cleaned_name = (meeting_name or "").strip()
        if cleaned_name:
            return cleaned_name

        file_stem = Path(filename or "meeting").stem.strip()
        if file_stem:
            normalized = re.sub(r"[_-]+", " ", file_stem)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if normalized:
                return normalized

        return "Meeting"

    @staticmethod
    def _normalize_owner_id(owner_id: str | None, default: str | None = None) -> str:
        normalized = (owner_id or "").strip()
        if not normalized:
            if default is not None:
                return default
            raise ValueError("Client-ID fehlt.")
        if _OWNER_ID_PATTERN.fullmatch(normalized):
            return normalized
        if default is not None:
            return default
        raise ValueError("Client-ID ist ungueltig.")
