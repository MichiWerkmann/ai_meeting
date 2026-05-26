import shutil
import time
import uuid
from pathlib import Path

from backend.app.schemas import MeetingMinutes, SpeakerProfile, TranscriptSegment
from backend.app.services.async_jobs import AsyncTranscriptionJobService


class DummyTranscriptionService:
    async def transcribe(self, *_args, **_kwargs):
        return (
            "session-1",
            [TranscriptSegment(speaker_id="speaker_1", speaker="Speaker 1", start=0.0, end=1.0, text="Hallo")],
            MeetingMinutes(summary="Kurz"),
            [SpeakerProfile(speaker_id="speaker_1", label="Speaker 1")],
            {"device": "cpu", "total_seconds": 0.1, "steps": []},
        )


def _new_test_dir() -> Path:
    base = Path(__file__).resolve().parents[2] / "tmp" / "test_async_jobs" / uuid.uuid4().hex
    base.mkdir(parents=True, exist_ok=True)
    return base


def test_create_job_keeps_previous_meetings(monkeypatch):
    tmp_path = _new_test_dir()
    monkeypatch.setattr("backend.app.services.async_jobs.threading.Thread.start", lambda _self: None)
    try:
        service = AsyncTranscriptionJobService(DummyTranscriptionService(), base_dir=tmp_path)

        first = service.create_job(owner_id="client-a", meeting_name=None, filename="first.wav", content=b"111")
        second = service.create_job(owner_id="client-a", meeting_name=None, filename="second.wav", content=b"222")

        listed = service.list_jobs(owner_id="client-a")

        assert first.job_id != second.job_id
        assert len(listed) == 2
        assert listed[0].job_id == second.job_id
        assert listed[1].job_id == first.job_id
        metadata_files = sorted(path.parent.name for path in tmp_path.glob("*/metadata.json"))
        assert metadata_files == sorted([first.job_id, second.job_id])
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_list_jobs_filters_by_owner(monkeypatch):
    tmp_path = _new_test_dir()
    monkeypatch.setattr("backend.app.services.async_jobs.threading.Thread.start", lambda _self: None)
    try:
        service = AsyncTranscriptionJobService(DummyTranscriptionService(), base_dir=tmp_path)

        mine = service.create_job(owner_id="client-a", meeting_name=None, filename="mine.wav", content=b"111")
        service.create_job(owner_id="client-b", meeting_name=None, filename="other.wav", content=b"222")

        listed = service.list_jobs(owner_id="client-a")

        assert len(listed) == 1
        assert listed[0].job_id == mine.job_id
        assert service.get_job(owner_id="client-a", job_id=mine.job_id).audio_filename == "mine.wav"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_owner_cannot_read_foreign_job(monkeypatch):
    tmp_path = _new_test_dir()
    monkeypatch.setattr("backend.app.services.async_jobs.threading.Thread.start", lambda _self: None)
    try:
        service = AsyncTranscriptionJobService(DummyTranscriptionService(), base_dir=tmp_path)

        created = service.create_job(owner_id="client-a", meeting_name=None, filename="mine.wav", content=b"111")

        try:
            service.get_job(owner_id="client-b", job_id=created.job_id)
            assert False, "Expected RuntimeError for foreign job access"
        except RuntimeError as exc:
            assert "nicht gefunden" in str(exc)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_load_jobs_keeps_all_meetings(monkeypatch):
    tmp_path = _new_test_dir()
    monkeypatch.setattr("backend.app.services.async_jobs.threading.Thread.start", lambda _self: None)
    try:
        now = time.time()
        older_dir = tmp_path / "older"
        older_dir.mkdir()
        (older_dir / "recording.wav").write_bytes(b"111")
        older_payload = (
            """
{
  "job_id": "older",
  "owner_id": "client-a",
  "meeting_name": "Alt",
  "audio_filename": "older.wav",
  "audio_path": "recording.wav",
  "diarize": false,
  "estimated_audio_duration_seconds": 0.0,
  "status": "completed",
  "message": "fertig",
      "created_at": %s,
      "started_at": %s,
      "finished_at": %s,
  "cancel_requested": false,
  "result": null
}
""" % (now - 20.0, now - 19.0, now - 18.0)
        ).strip()
        (older_dir / "metadata.json").write_text(older_payload, encoding="utf-8")
        newer_dir = tmp_path / "newer"
        newer_dir.mkdir()
        (newer_dir / "recording.wav").write_bytes(b"222")
        newer_payload = (
            """
{
  "job_id": "newer",
  "owner_id": "client-a",
  "meeting_name": "Neu",
  "audio_filename": "newer.wav",
  "audio_path": "recording.wav",
  "diarize": false,
  "estimated_audio_duration_seconds": 0.0,
  "status": "completed",
  "message": "fertig",
      "created_at": %s,
      "started_at": %s,
      "finished_at": %s,
  "cancel_requested": false,
  "result": null
}
""" % (now - 10.0, now - 9.0, now - 8.0)
        ).strip()
        (newer_dir / "metadata.json").write_text(newer_payload, encoding="utf-8")

        service = AsyncTranscriptionJobService(DummyTranscriptionService(), base_dir=tmp_path)

        listed = service.list_jobs(owner_id="client-a")

        assert len(listed) == 2
        assert listed[0].job_id == "newer"
        assert listed[1].job_id == "older"
        assert Path(tmp_path / "older" / "metadata.json").exists()
        assert Path(tmp_path / "newer" / "metadata.json").exists()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_create_job_derives_meeting_name_from_filename(monkeypatch):
    tmp_path = _new_test_dir()
    monkeypatch.setattr("backend.app.services.async_jobs.threading.Thread.start", lambda _self: None)
    try:
        service = AsyncTranscriptionJobService(DummyTranscriptionService(), base_dir=tmp_path)

        created = service.create_job(owner_id="client-a", meeting_name="", filename="baujour-fixe_kw14.wav", content=b"123")

        assert created.meeting_name == "baujour fixe kw14"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_queue_position_reflects_queued_order(monkeypatch):
    tmp_path = _new_test_dir()
    monkeypatch.setattr("backend.app.services.async_jobs.threading.Thread.start", lambda _self: None)
    try:
        service = AsyncTranscriptionJobService(DummyTranscriptionService(), base_dir=tmp_path)

        first = service.create_job(owner_id="client-a", meeting_name=None, filename="first.wav", content=b"111")
        second = service.create_job(owner_id="client-a", meeting_name=None, filename="second.wav", content=b"222")

        first_job = service.get_job(owner_id="client-a", job_id=first.job_id)
        second_job = service.get_job(owner_id="client-a", job_id=second.job_id)
        assert first_job.queue_position == 1
        assert second_job.queue_position == 2
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
