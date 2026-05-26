from __future__ import annotations

import asyncio
import copy
import gc
import inspect
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import quote, urlparse

import httpx

from ..schemas import (
    MinutesActionItem,
    MinutesDecision,
    ManualSegment,
    MeetingMinutes,
    ModelSettings,
    SegmentPrediction,
    SpeakerProfile,
    TranscriptSegment,
)
from ..defaults import MAX_LLM_CONTEXT_SIZE
from .minutes import AzureOpenAICompletionClient, HTTPCompletionClient, LLMCallable, LLMMinutesGenerator


_NAME_FRAGMENT = r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'\-]*"
_SELF_NAME_PATTERNS = [
    re.compile(
        r"\bich\s+hei[ßs]e\s+(?:(?:dr|prof|herr|frau)\.?\s+)?(?P<name>{name}(?:\s+{name}){{0,2}})".format(
            name=_NAME_FRAGMENT
        ),
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmein\s+name\s+ist\s+(?:(?:dr|prof|herr|frau)\.?\s+)?(?P<name>{name}(?:\s+{name}){{0,2}})".format(
            name=_NAME_FRAGMENT
        ),
        re.IGNORECASE,
    ),
]
_NAME_TITLE_WORDS = {"dr", "prof", "herr", "frau", "mr", "mrs", "ms", "miss", "monsieur", "madame"}
_ALLOWED_LOWER_NAME_PARTS = {"von", "van", "de", "del", "di", "da", "dos", "das", "du", "la", "le"}
_DISALLOWED_NAME_PARTS = {
    "bereit",
    "dabei",
    "hier",
    "zurück",
    "wieder",
    "online",
    "fertig",
    "gerne",
    "gut",
    "super",
    "prima",
    "happy",
    "ready",
    "present",
    "available",
    "connected",
    "dran",
    "gleich",
    "jetzt",
    "später",
    "bald",
    "morgen",
    "heute",
    "abend",
    "call",
    "meeting",
    "projekt",
    "project",
    "plan",
    "update",
    "demo",
    "topic",
    "agenda",
    "issue",
    "problem",
    "support",
    "service",
    "team",
    "crew",
    "group",
    "consultant",
    "manager",
    "lead",
    "müde",
    "mude",
    "muede",
    "hungrig",
    "hungry",
    "durstig",
    "thirsty",
    "tired",
    "sleepy",
    "krank",
    "krankheit",
    "sick",
    "ill",
    "busy",
    "verfügbar",
    "verfuegbar",
    "verfugbar",
    "beschäftigt",
    "beschaeftigt",
    "gestresst",
    "stressed",
    "stress",
    "erschöpft",
    "erschoepft",
    "kaputt",
    "exhausted",
    "angry",
    "sad",
    "glücklich",
    "glucklich",
    "glad",
    "excited",
    "verliebt",
    "anwesend",
    "abwesend",
}
_NAME_BREAK_WORDS = {
    "und",
    "and",
    "aber",
    "but",
    "then",
    "dann",
    "also",
    "so",
    "deshalb",
    "daher",
    "weil",
    "since",
    "because",
}

ProgressCallback = Callable[[str, str | None, float | None], None]

logger = logging.getLogger(__name__)


@dataclass
class CachedTranscriptionSession:
    session_id: str
    temp_dir: Path
    audio_path: Path
    aligned_result: dict
    created_at: float


@dataclass
class SummaryFallbackResult:
    summary: str = ""
    agenda: List[str] = field(default_factory=list)
    highlights: List[str] = field(default_factory=list)
    decisions: List[MinutesDecision] = field(default_factory=list)
    action_items: List[MinutesActionItem] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)

    def has_content(self) -> bool:
        return any(
            [
                self.summary,
                self.agenda,
                self.highlights,
                self.decisions,
                self.action_items,
                self.risks,
            ]
        )


@dataclass
class HardwareProfile:
    device: str
    gpu_available: bool
    gpu_memory_gb: float
    performance_tier: str
    recommended_execution: str
    performance_message: str
    minutes: MeetingMinutes | None = None


class TranscriptionService:
    """Wraps open-source transcription and diarization pipelines."""

    def __init__(
        self,
        whisper_model: str | None = None,
        diarization_model: str | None = None,
        device: str | None = None,
        whisper_batch_size: int | None = None,
        minutes_generator: LLMMinutesGenerator | None = None,
        summary_model: str | None = None,
        summary_llm_client: LLMCallable | None = None,
    ) -> None:
        self.device = self._normalize_execution_device(device or os.getenv("WHISPER_DEVICE", "auto"))
        self.transcription_provider = self._normalize_transcription_provider(
            os.getenv("TRANSCRIPTION_PROVIDER", "local")
        )
        configured_whisper_model = whisper_model or os.getenv("WHISPER_MODEL", "turbo")
        configured_diarization_model = diarization_model or os.getenv("DIARIZATION_MODEL", "auto")
        self.whisper_model = self._resolve_whisper_model(configured_whisper_model)
        self.diarization_model = self._resolve_diarization_model(configured_diarization_model)
        self.speaker_recognition_enabled = self._coerce_bool(
            os.getenv("SPEAKER_RECOGNITION_ENABLED"), default=True
        )
        self.azure_transcription_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.azure_transcription_api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        self.azure_transcription_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
        self.azure_transcription_deployment = os.getenv("AZURE_OPENAI_WHISPER_DEPLOYMENT", "")
        self.azure_speech_endpoint = os.getenv("AZURE_SPEECH_ENDPOINT", "")
        self.azure_speech_region = os.getenv("AZURE_SPEECH_REGION", "")
        self.azure_speech_locales = os.getenv("AZURE_SPEECH_LOCALES", "")
        self.azure_speech_max_speakers = self._parse_optional_int(os.getenv("AZURE_SPEECH_MAX_SPEAKERS"))
        self.whisper_batch_size = int(os.getenv("WHISPER_BATCH_SIZE", whisper_batch_size or 16))
        self._whisper = None
        self._diarizer = None
        self._diarizer_cache_key: tuple[str, str] | None = None
        self._align_models: Dict[tuple[str, str], tuple[Any, Any]] = {}
        self._summarizer = None
        self._runtime_device = None
        self._minutes = minutes_generator or LLMMinutesGenerator()
        self.llm_provider = getattr(self._minutes, "provider", "http")
        self.llm_azure_endpoint = getattr(self._minutes, "azure_endpoint", "") or os.getenv(
            "LLM_AZURE_ENDPOINT", ""
        )
        self.llm_azure_api_key = getattr(self._minutes, "azure_api_key", None) or os.getenv(
            "LLM_AZURE_API_KEY", ""
        )
        self.llm_azure_api_version = getattr(
            self._minutes, "azure_api_version", "2025-01-01-preview"
        ) or os.getenv("LLM_AZURE_API_VERSION", "2025-01-01-preview")
        self.llm_local_model_path = getattr(self._minutes, "local_model_path", "") or os.getenv(
            "LLM_LOCAL_MODEL_PATH", ""
        )
        self.llm_local_context_size = int(
            getattr(self._minutes, "local_context_size", MAX_LLM_CONTEXT_SIZE)
            or os.getenv("LLM_LOCAL_CONTEXT_SIZE", MAX_LLM_CONTEXT_SIZE)
        )
        self.llm_local_gpu_layers = int(
            getattr(self._minutes, "local_gpu_layers", 0) or os.getenv("LLM_LOCAL_GPU_LAYERS", 0)
        )
        self.summary_model = summary_model or os.getenv("SUMMARY_MODEL", "gpt-4.1-mini")
        self._use_llm_summary = self._should_use_llm_summary(self.summary_model, self.llm_provider)
        default_llm_base = getattr(self._minutes, "base_url", None) or os.getenv(
            "LLM_BASE_URL", ""
        )
        default_llm_path = getattr(self._minutes, "completions_path", None) or os.getenv(
            "LLM_COMPLETIONS_PATH"
        )
        if not default_llm_path or default_llm_path.strip() in {"", "/"}:
            default_llm_path = "/v1/chat/completions"
        default_llm_key = getattr(self._minutes, "api_key", None) or os.getenv("LLM_API_KEY")
        self.summary_llm_base_url = os.getenv("SUMMARY_LLM_BASE_URL") or default_llm_base
        self.summary_llm_path = os.getenv("SUMMARY_LLM_COMPLETIONS_PATH") or default_llm_path
        self.summary_llm_api_key = os.getenv("SUMMARY_LLM_API_KEY") or default_llm_key
        self._summary_llm_client = summary_llm_client
        self._session_cache: Dict[str, CachedTranscriptionSession] = {}
        self._session_ttl_seconds = 2 * 60 * 60

    async def transcribe(
        self,
        audio_path: Path,
        cache_session: bool = True,
        diarize: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str | None, List[TranscriptSegment], MeetingMinutes, List[SpeakerProfile], Dict[str, Any]]:
        # Wenn die Sprechererkennung global deaktiviert ist, wird sie hier
        # zwingend abgeschaltet, unabhaengig davon, was der Aufrufer angefragt hat.
        effective_diarize = bool(diarize) and self.speaker_recognition_enabled
        loop = asyncio.get_running_loop()
        session_id, segments, summary, speakers, processing = await loop.run_in_executor(
            None, self._run_pipeline, audio_path, cache_session, effective_diarize, progress_callback
        )
        if not self.speaker_recognition_enabled:
            segments, speakers = self._strip_speaker_information(segments)
        return session_id, segments, summary, speakers, processing

    def evaluate_segments(
        self, manual_segments: List[ManualSegment]
    ) -> tuple[List[TranscriptSegment], MeetingMinutes, List[SegmentPrediction]]:
        if not manual_segments:
            return [], MeetingMinutes(), []
        segments: List[TranscriptSegment] = []
        for idx, segment in enumerate(manual_segments, start=1):
            speaker_label = segment.speaker.strip() if segment.speaker else f"Speaker {idx}"
            start = float(segment.start) if segment.start is not None else float(idx - 1)
            end = float(segment.end) if segment.end is not None else float(idx)
            segments.append(
                TranscriptSegment(
                    speaker_id=f"manual_{idx}",
                    speaker=speaker_label,
                    start=start,
                    end=end,
                    text=segment.text.strip(),
                )
            )
        minutes = self._minutes.build_minutes(segments)
        predictions = self._minutes.label_segments(segments)
        return segments, minutes, predictions

    def export_settings(self) -> ModelSettings:
        minutes_settings = self._minutes.export_settings()
        return ModelSettings(
            execution_device=self.device,
            transcription_provider=self.transcription_provider,
            whisper_model=self.whisper_model,
            speaker_recognition_enabled=self.speaker_recognition_enabled,
            diarization_model=self.diarization_model,
            azure_transcription_endpoint=self.azure_transcription_endpoint,
            azure_transcription_api_key=self.azure_transcription_api_key,
            azure_transcription_api_version=self.azure_transcription_api_version,
            azure_transcription_deployment=self.azure_transcription_deployment,
            azure_speech_endpoint=self.azure_speech_endpoint,
            azure_speech_region=self.azure_speech_region,
            azure_speech_locales=self.azure_speech_locales,
            azure_speech_max_speakers=self.azure_speech_max_speakers,
            llm_provider=minutes_settings["llm_provider"],
            llm_model=minutes_settings["llm_model"],
            llm_azure_endpoint=minutes_settings["llm_azure_endpoint"],
            llm_azure_api_key=minutes_settings["llm_azure_api_key"],
            llm_azure_api_version=minutes_settings["llm_azure_api_version"],
            llm_base_url=minutes_settings["llm_base_url"],
            llm_api_key=minutes_settings["llm_api_key"],
            llm_completions_path=minutes_settings["llm_completions_path"],
            llm_local_model_path=minutes_settings["llm_local_model_path"],
            llm_local_context_size=int(minutes_settings["llm_local_context_size"]),
            llm_local_gpu_layers=int(minutes_settings["llm_local_gpu_layers"]),
            summary_model=self.summary_model,
            summary_llm_base_url=self.summary_llm_base_url or "",
            summary_llm_api_key=self.summary_llm_api_key or "",
            summary_llm_completions_path=self.summary_llm_path or "",
        )

    def apply_settings(self, settings: ModelSettings) -> None:
        previous_transcription_provider = self.transcription_provider
        previous_device = self.device
        previous_whisper = self.whisper_model
        previous_diarization = self.diarization_model
        previous_summary_model = self.summary_model

        self.device = self._normalize_execution_device(settings.execution_device)
        self.transcription_provider = self._normalize_transcription_provider(settings.transcription_provider)
        self.whisper_model = self._resolve_whisper_model(settings.whisper_model)
        self.speaker_recognition_enabled = self._coerce_bool(
            settings.speaker_recognition_enabled, default=True
        )
        self.diarization_model = self._resolve_diarization_model(settings.diarization_model)
        self.azure_transcription_endpoint = (settings.azure_transcription_endpoint or "").strip()
        self.azure_transcription_api_key = (settings.azure_transcription_api_key or "").strip()
        self.azure_transcription_api_version = (
            (settings.azure_transcription_api_version or "").strip() or "2024-02-01"
        )
        self.azure_transcription_deployment = (settings.azure_transcription_deployment or "").strip()
        self.azure_speech_endpoint = (settings.azure_speech_endpoint or "").strip()
        self.azure_speech_region = (settings.azure_speech_region or "").strip()
        self.azure_speech_api_version = (
            (settings.azure_speech_api_version or "").strip() or "2024-11-15"
        )
        self.azure_speech_locales = (settings.azure_speech_locales or "").strip()
        self.azure_speech_max_speakers = self._parse_optional_int(settings.azure_speech_max_speakers)
        self._minutes.apply_settings(
            provider=settings.llm_provider,
            model=settings.llm_model,
            azure_endpoint=settings.llm_azure_endpoint,
            azure_api_key=settings.llm_azure_api_key,
            azure_api_version=settings.llm_azure_api_version,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            completions_path=settings.llm_completions_path,
            local_model_path=settings.llm_local_model_path,
            local_context_size=settings.llm_local_context_size,
            local_gpu_layers=settings.llm_local_gpu_layers,
        )
        self.llm_provider = self._minutes.provider
        self.llm_azure_endpoint = self._minutes.azure_endpoint
        self.llm_azure_api_key = self._minutes.azure_api_key or ""
        self.llm_azure_api_version = self._minutes.azure_api_version
        self.llm_local_model_path = self._minutes.local_model_path
        self.llm_local_context_size = self._minutes.local_context_size
        self.llm_local_gpu_layers = self._minutes.local_gpu_layers

        self.summary_model = (settings.summary_model or "").strip() or self._minutes.model
        self._use_llm_summary = self._should_use_llm_summary(self.summary_model, self.llm_provider)
        self.summary_llm_base_url = (
            (settings.summary_llm_base_url or "").strip() or self._minutes.base_url
        )
        self.summary_llm_path = (
            (settings.summary_llm_completions_path or "").strip() or self._minutes.completions_path
        )
        self.summary_llm_api_key = (
            (settings.summary_llm_api_key or "").strip() or self._minutes.api_key
        )

        if (
            previous_transcription_provider != self.transcription_provider
            or previous_device != self.device
            or previous_whisper != self.whisper_model
        ):
            self._whisper = None
            self._diarizer = None
            self._diarizer_cache_key = None
            self._align_models.clear()
            self._runtime_device = None
        if previous_diarization != self.diarization_model:
            self._diarizer = None
            self._diarizer_cache_key = None
        if previous_summary_model != self.summary_model or self._use_llm_summary:
            self._summarizer = None
        self._summary_llm_client = None

    def hardware_profile(self) -> HardwareProfile:
        gpu_available = self._gpu_available()
        gpu_memory_gb = round(self._gpu_total_memory_gb(), 1) if gpu_available else 0.0
        device = self._resolve_device()

        if gpu_available and gpu_memory_gb >= 10:
            return HardwareProfile(
                device=device,
                gpu_available=True,
                gpu_memory_gb=gpu_memory_gb,
                performance_tier="high",
                recommended_execution="local",
                performance_message=(
                    "CUDA-GPU mit ausreichend VRAM erkannt. Lokale Verarbeitung sollte schnell genug sein."
                ),
            )
        if gpu_available and gpu_memory_gb >= 6:
            return HardwareProfile(
                device=device,
                gpu_available=True,
                gpu_memory_gb=gpu_memory_gb,
                performance_tier="medium",
                recommended_execution="local",
                performance_message=(
                    "CUDA-GPU erkannt. Lokale Verarbeitung ist sinnvoll, bei langen Meetings kann eine externe API trotzdem schneller sein."
                ),
            )
        if gpu_available:
            return HardwareProfile(
                device=device,
                gpu_available=True,
                gpu_memory_gb=gpu_memory_gb,
                performance_tier="low",
                recommended_execution="api",
                performance_message=(
                    "CUDA ist vorhanden, aber mit wenig GPU-Speicher. Fuer schnellere Ergebnisse kann ein API-Modell sinnvoll sein."
                ),
            )
        return HardwareProfile(
            device=device,
            gpu_available=False,
            gpu_memory_gb=0.0,
            performance_tier="medium",
            recommended_execution="local",
            performance_message=(
                "Es wurde nur CPU-Verarbeitung erkannt. Die lokale Transkription laeuft weiterhin vollstaendig offline, benoetigt bei langen Meetings aber deutlich mehr Zeit."
            ),
        )

    # ----- private helpers -------------------------------------------------

    def _run_pipeline(
        self,
        audio_path: Path,
        cache_session: bool = True,
        diarize: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str | None, List[TranscriptSegment], MeetingMinutes, List[SpeakerProfile], Dict[str, Any]]:
        pipeline_started = time.perf_counter()
        self._emit_progress(progress_callback, "Audio wird vorbereitet.", "transcribe", 10.0)
        if self.transcription_provider == "azure_openai":
            session_id, enriched, speakers, transcription_seconds, diarization_seconds = (
                self._run_azure_transcription_pipeline(audio_path, progress_callback=progress_callback)
            )
            processing_device = "azure"
        elif self.transcription_provider == "azure_speech":
            session_id, enriched, speakers, transcription_seconds, diarization_seconds = (
                self._run_azure_speech_pipeline(audio_path, progress_callback=progress_callback)
            )
            processing_device = "azure"
        else:
            session_id, enriched, speakers, transcription_seconds, diarization_seconds = self._run_whisperx_pipeline(
                audio_path, cache_session, diarize, progress_callback
            )
            processing_device = self._effective_device()
        self._emit_progress(progress_callback, "Minutes werden erstellt.", "minutes", 85.0)
        minutes_started = time.perf_counter()
        minutes = self._minutes.build_minutes(enriched)
        self._enrich_minutes_with_summary_fallback(minutes, " ".join(seg.text for seg in enriched))
        if session_id:
            session = self._session_cache.get(session_id)
            if session is not None:
                session.minutes = copy.deepcopy(minutes)
        minutes_seconds = time.perf_counter() - minutes_started
        return session_id, enriched, minutes, speakers, {
            "device": processing_device,
            "total_seconds": time.perf_counter() - pipeline_started,
            "steps": [
                {
                    "key": "transcribe",
                    "label": "Transkribieren",
                    "duration_seconds": transcription_seconds,
                },
                {
                    "key": "diarize",
                    "label": "Sprecher erkennen",
                    "duration_seconds": diarization_seconds,
                },
                {
                    "key": "minutes",
                    "label": "Minutes erstellen",
                    "duration_seconds": minutes_seconds,
                },
            ],
        }

    def _run_azure_transcription_pipeline(
        self,
        audio_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Tuple[str | None, List[TranscriptSegment], List[SpeakerProfile], float, float]:
        if not self.azure_transcription_endpoint:
            raise RuntimeError("Azure OpenAI Endpoint ist nicht konfiguriert.")
        if not self.azure_transcription_api_key:
            raise RuntimeError("Azure OpenAI API-Key ist nicht konfiguriert.")
        if not self.azure_transcription_deployment:
            raise RuntimeError("Azure OpenAI Deployment ist nicht konfiguriert.")

        request_started = time.perf_counter()
        self._emit_progress(progress_callback, "Azure-Transkription wird angefragt.", "transcribe", 35.0)
        payload = self._request_azure_transcription(audio_path)
        transcription_seconds = time.perf_counter() - request_started
        diarization_seconds = 0.0

        segments = self._build_azure_transcript(payload)
        return None, segments, [], transcription_seconds, diarization_seconds

    def _run_azure_speech_pipeline(
        self,
        audio_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Tuple[str | None, List[TranscriptSegment], List[SpeakerProfile], float, float]:
        if not self._resolve_azure_speech_endpoint():
            raise RuntimeError("Azure Speech Endpoint ist nicht konfiguriert.")
        if not self.azure_transcription_api_key:
            raise RuntimeError("Azure Speech API-Key ist nicht konfiguriert.")

        request_started = time.perf_counter()
        self._emit_progress(progress_callback, "Azure Speech verarbeitet die Audiodatei.", "transcribe", 35.0)
        payload = self._request_azure_speech_transcription(audio_path)
        transcription_seconds = time.perf_counter() - request_started
        diarization_seconds = 0.0

        segments, speakers = self._build_azure_speech_transcript(payload)
        return None, segments, speakers, transcription_seconds, diarization_seconds

    def _run_whisperx_pipeline(
        self,
        audio_path: Path,
        cache_session: bool = True,
        diarize: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> Tuple[str | None, List[TranscriptSegment], List[SpeakerProfile], float, float]:
        model = self._load_whisperx_model()
        if model is None:
            raise RuntimeError(
                "WhisperX-Modell konnte nicht geladen werden. Bitte Abhaengigkeiten und Modellkonfiguration pruefen."
            )
        import whisperx

        try:
            prepared_audio_path, cleanup_audio = self._prepare_audio_for_local_transcription(audio_path)
        except Exception as exc:
            raise RuntimeError(
                "Audio konnte fuer die lokale Transkription nicht vorbereitet werden."
            ) from exc

        try:
            self._emit_progress(progress_callback, "Audiodatei wird geladen.", "transcribe", 20.0)
            audio = whisperx.load_audio(str(prepared_audio_path))
            transcribe_kwargs: Dict[str, Any] = {}
            forced_language = os.getenv("WHISPER_LANGUAGE")
            if forced_language:
                transcribe_kwargs["language"] = forced_language
            transcribe_kwargs.setdefault("batch_size", self.whisper_batch_size)
            transcribe_started = time.perf_counter()
            self._emit_progress(progress_callback, "Whisper transkribiert das Meeting.", "transcribe", 45.0)
            try:
                result = model.transcribe(audio, **transcribe_kwargs)
            except Exception as exc:
                if self._is_cuda_oom(exc):
                    logger.warning("CUDA OOM bei WhisperX. Wechsle auf CPU-Fallback: %s", exc)
                    gc.collect()
                    self._release_torch_cuda_cache()
                    self._whisper = None
                    self._runtime_device = "cpu"
                    model = self._load_whisperx_model()
                    if model is None:
                        raise RuntimeError(
                            "CUDA ist vollgelaufen und das CPU-Fallback konnte nicht geladen werden."
                        ) from exc
                    transcribe_kwargs["batch_size"] = min(int(transcribe_kwargs.get("batch_size", 4)), 4)
                    transcribe_started = time.perf_counter()
                    result = model.transcribe(audio, **transcribe_kwargs)
                else:
                    raise
            transcription_seconds = time.perf_counter() - transcribe_started
            if not isinstance(result, dict):
                raise RuntimeError("WhisperX lieferte ein unerwartetes Transkriptionsergebnis")
            detected_language = result.get("language") or forced_language

            if diarize and result.get("segments"):
                self._emit_progress(progress_callback, "Wortzeiten werden ausgerichtet.", "transcribe", 60.0)
                align_bundle = self._load_align_model(detected_language)
                if align_bundle is not None:
                    align_model, metadata = align_bundle
                    result = whisperx.align(
                        result["segments"],
                        align_model,
                        metadata,
                        audio,
                        self._effective_device(),
                        return_char_alignments=False,
                    )

            session_id = self._cache_session(prepared_audio_path, result) if cache_session else None
            segments, speakers, diarization_seconds = self._apply_diarization(
                audio,
                result,
                diarize=diarize,
                progress_callback=progress_callback,
            )
            return session_id, segments, speakers, transcription_seconds, diarization_seconds
        finally:
            cleanup_audio()

    def _apply_diarization(
        self,
        audio: Any,
        aligned_result: dict,
        diarize: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[List[TranscriptSegment], List[SpeakerProfile], float]:
        import whisperx

        diarization_started = time.perf_counter()
        diarizer = self._load_diarizer()
        diarization_enabled = bool(
            diarize
            and diarizer is not None
            and aligned_result.get("segments")
            and aligned_result.get("word_segments")
        )
        result = copy.deepcopy(aligned_result) if diarization_enabled else aligned_result
        if diarization_enabled:
            self._emit_progress(progress_callback, "Sprecher werden erkannt.", "diarize", 72.0)
            diarization = self._call_diarizer(diarizer, audio)
            result = whisperx.assign_word_speakers(diarization, result)
        else:
            self._emit_progress(progress_callback, "Sprechererkennung wird uebersprungen.", "diarize", 72.0)
        result_segments = result.get("segments", [])
        if not result_segments:
            raise RuntimeError("Keine Transkriptsegmente aus der Audiodatei extrahiert")
        segments, speakers = self._build_transcript(result_segments, collapse_consecutive=diarization_enabled)
        return segments, speakers, time.perf_counter() - diarization_started

    @staticmethod
    def _emit_progress(
        progress_callback: ProgressCallback | None,
        message: str,
        active_step: str | None = None,
        progress_percent: float | None = None,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(message, active_step, progress_percent)

    def _cache_session(self, audio_path: Path, aligned_result: dict) -> str:
        self._cleanup_expired_sessions()
        session_id = uuid.uuid4().hex
        temp_dir = Path(tempfile.mkdtemp(prefix=f"meeting-session-{session_id[:8]}-"))
        cached_audio_path = temp_dir / audio_path.name
        shutil.copy2(audio_path, cached_audio_path)
        self._session_cache[session_id] = CachedTranscriptionSession(
            session_id=session_id,
            temp_dir=temp_dir,
            audio_path=cached_audio_path,
            aligned_result=aligned_result,
            created_at=time.time(),
        )
        return session_id

    def _cleanup_expired_sessions(self) -> None:
        now = time.time()
        expired = [
            session_id
            for session_id, session in self._session_cache.items()
            if now - session.created_at > self._session_ttl_seconds
        ]
        for session_id in expired:
            session = self._session_cache.pop(session_id, None)
            if session is not None:
                shutil.rmtree(session.temp_dir, ignore_errors=True)

    @staticmethod
    def _is_low_information_minutes(minutes: MeetingMinutes) -> bool:
        if (minutes.model or "").endswith("(fallback)"):
            return True
        return not any(
            [
                (minutes.summary or "").strip(),
                minutes.agenda,
                minutes.highlights,
                minutes.decisions,
                minutes.action_items,
                minutes.risks,
            ]
        )

    def _call_diarizer(self, diarizer: Any, audio: Any) -> Any:
        return diarizer(audio)

    def _build_transcript(
        self, segments: List[dict], collapse_consecutive: bool = True
    ) -> Tuple[List[TranscriptSegment], List[SpeakerProfile]]:
        if not segments:
            return [], []

        speaker_labels: Dict[str, str] = {}
        speaker_order: List[str] = []

        def label_for(speaker_id: str) -> str:
            if speaker_id not in speaker_labels:
                speaker_order.append(speaker_id)
                speaker_labels[speaker_id] = f"Speaker {len(speaker_order)}"
            return speaker_labels[speaker_id]

        transcript_segments: List[TranscriptSegment] = []
        for idx, segment in enumerate(segments, start=1):
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", start))
            raw_speaker_id = str(segment.get("speaker") or "").strip()
            if raw_speaker_id:
                speaker_id = raw_speaker_id
                label = label_for(speaker_id)
            else:
                speaker_id = "speaker_1"
                label = "Speaker"
            transcript_segments.append(
                TranscriptSegment(
                    speaker_id=speaker_id,
                    speaker=label,
                    start=start,
                    end=end,
                    text=text,
                )
            )

        if speaker_labels:
            self._apply_detected_speaker_names(transcript_segments, speaker_labels)
        collapsed = self._collapse_segments(transcript_segments) if collapse_consecutive else transcript_segments
        speakers = [
            SpeakerProfile(speaker_id=sid, label=speaker_labels[sid]) for sid in speaker_order
        ]
        if not speakers:
            speakers = [SpeakerProfile(speaker_id="speaker_1", label="Speaker")]
        return collapsed, speakers

    def _request_azure_transcription(self, audio_path: Path) -> dict[str, Any]:
        endpoint = self._normalize_azure_endpoint(self.azure_transcription_endpoint)
        deployment = quote(self.azure_transcription_deployment, safe="")
        api_version = (self.azure_transcription_api_version or "2024-02-01").strip()
        url = f"{endpoint}/openai/deployments/{deployment}/audio/transcriptions"
        params = {"api-version": api_version}
        headers = {"api-key": self.azure_transcription_api_key}
        multipart_fields: list[tuple[str, tuple[str | None, Any, str | None]]] = [
            ("response_format", (None, "verbose_json", None)),
            ("timestamp_granularities[]", (None, "segment", None)),
            ("model", (None, self.azure_transcription_deployment, None)),
        ]
        forced_language = (os.getenv("WHISPER_LANGUAGE") or "").strip()
        if forced_language:
            multipart_fields.append(("language", (None, forced_language, None)))

        with audio_path.open("rb") as audio_file:
            multipart_fields.append(
                ("file", (audio_path.name, audio_file, "application/octet-stream"))
            )
            try:
                response = httpx.post(
                    url,
                    params=params,
                    headers=headers,
                    files=multipart_fields,
                    timeout=300.0,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text.strip() or str(exc)
                raise RuntimeError(f"Azure OpenAI Transkription fehlgeschlagen: {detail}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Azure OpenAI konnte nicht erreicht werden: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Azure OpenAI lieferte keine gueltige JSON-Antwort.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Azure OpenAI lieferte ein unerwartetes Antwortformat.")
        return payload

    def _build_azure_transcript(self, payload: dict[str, Any]) -> List[TranscriptSegment]:
        raw_segments = payload.get("segments")
        transcript: List[TranscriptSegment] = []
        if isinstance(raw_segments, list):
            for index, item in enumerate(raw_segments, start=1):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                start = self._coerce_seconds(item.get("start"), fallback=float(index - 1))
                end = self._coerce_seconds(item.get("end"), fallback=max(start, float(index)))
                transcript.append(
                    TranscriptSegment(
                        speaker_id="speaker_1",
                        speaker="Speaker",
                        start=start,
                        end=max(start, end),
                        text=text,
                    )
                )
        if transcript:
            return transcript

        text = str(payload.get("text", "")).strip()
        if not text:
            return []
        return [
            TranscriptSegment(
                speaker_id="speaker_1",
                speaker="Speaker",
                start=0.0,
                end=0.0,
                text=text,
            )
        ]

    def _request_azure_speech_transcription(self, audio_path: Path) -> dict[str, Any]:
        endpoint = self._resolve_azure_speech_endpoint()
        api_version = self.azure_speech_api_version
        url = f"{endpoint}/speechtotext/transcriptions:transcribe"
        params = {"api-version": api_version}
        headers = {"Ocp-Apim-Subscription-Key": self.azure_transcription_api_key}
        prepared_audio_path, cleanup = self._prepare_audio_for_azure_speech(audio_path)
        try:
            with prepared_audio_path.open("rb") as audio_file:
                definition = {
                    "locales": self._azure_speech_locales(),
                    "profanityFilterMode": "Masked",
                }
                if self.speaker_recognition_enabled:
                    definition["diarization"] = {
                        "maxSpeakers": self.azure_speech_max_speakers or 10,
                    }
                files = {
                    "audio": (prepared_audio_path.name, audio_file, "audio/wav"),
                    "definition": (
                        None,
                        json.dumps(definition),
                        "application/json",
                    ),
                }
                try:
                    response = httpx.post(
                        url,
                        params=params,
                        headers=headers,
                        files=files,
                        timeout=300.0,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text.strip() or str(exc)
                    raise RuntimeError(f"Azure Speech Transkription fehlgeschlagen: {detail}") from exc
                except httpx.HTTPError as exc:
                    raise RuntimeError(f"Azure Speech konnte nicht erreicht werden: {exc}") from exc
        finally:
            cleanup()

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Azure Speech lieferte keine gueltige JSON-Antwort.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Azure Speech lieferte ein unerwartetes Antwortformat.")
        return payload

    def _prepare_audio_for_azure_speech(self, audio_path: Path) -> tuple[Path, Any]:
        suffix = audio_path.suffix.lower()
        if suffix in {".wav", ".wave"}:
            return audio_path, lambda: None

        temp_dir = Path(tempfile.mkdtemp(prefix="azure-speech-audio-"))
        wav_path = temp_dir / f"{audio_path.stem}.wav"
        try:
            try:
                import torchaudio

                waveform, sample_rate = torchaudio.load(str(audio_path))
                if waveform.ndim > 1 and waveform.shape[0] > 1:
                    waveform = waveform.mean(dim=0, keepdim=True)
                torchaudio.save(
                    str(wav_path),
                    waveform,
                    sample_rate,
                    format="wav",
                    encoding="PCM_S",
                    bits_per_sample=16,
                )
            except ImportError:
                # torchaudio nicht verfügbar – FFmpeg als Fallback (Azure-only Installation)
                import subprocess

                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", str(audio_path),
                        "-ac", "1", "-ar", "16000",
                        "-sample_fmt", "s16",
                        str(wav_path),
                    ],
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"FFmpeg-Konvertierung fehlgeschlagen: {result.stderr.decode(errors='replace')}"
                    )
        except RuntimeError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(
                "Audioformat konnte fuer Azure Speech nicht in WAV konvertiert werden. "
                "Bitte eine WAV-Datei hochladen oder FFmpeg installieren (winget install Gyan.FFmpeg)."
            ) from exc
        return wav_path, lambda: shutil.rmtree(temp_dir, ignore_errors=True)

    def _prepare_audio_for_local_transcription(self, audio_path: Path) -> tuple[Path, Any]:
        temp_dir = Path(tempfile.mkdtemp(prefix="local-transcription-audio-"))
        wav_path = temp_dir / f"{audio_path.stem}.wav"
        try:
            import torch
            import torchaudio

            waveform, sample_rate = torchaudio.load(str(audio_path))
            if waveform.ndim == 1:
                waveform = waveform.unsqueeze(0)
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            if sample_rate != 16000:
                waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)
                sample_rate = 16000
            peak = float(torch.max(torch.abs(waveform)).item()) if waveform.numel() else 0.0
            if peak > 0.0:
                waveform = waveform / peak
            torchaudio.save(
                str(wav_path),
                waveform,
                sample_rate,
                format="wav",
                encoding="PCM_S",
                bits_per_sample=16,
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(
                "Audio konnte nicht in ein lokal optimiertes WAV-Format konvertiert werden."
            ) from exc
        return wav_path, lambda: shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_azure_speech_transcript(
        self, payload: dict[str, Any]
    ) -> tuple[List[TranscriptSegment], List[SpeakerProfile]]:
        transcript: List[TranscriptSegment] = []
        speaker_labels: Dict[str, str] = {}
        phrases = payload.get("phrases")
        if isinstance(phrases, list):
            for index, phrase in enumerate(phrases, start=1):
                if not isinstance(phrase, dict):
                    continue
                text = str(
                    phrase.get("text")
                    or phrase.get("display")
                    or phrase.get("lexical")
                    or ""
                ).strip()
                if not text:
                    continue
                offset_ms = self._coerce_milliseconds(
                    phrase.get("offsetMilliseconds") or phrase.get("offsetInTicks"),
                    fallback=float(index - 1) * 1000.0,
                )
                duration_ms = self._coerce_milliseconds(
                    phrase.get("durationMilliseconds") or phrase.get("durationInTicks"),
                    fallback=1000.0,
                )
                start = max(0.0, offset_ms / 1000.0)
                end = max(start, start + (duration_ms / 1000.0))
                speaker_id = self._azure_speech_speaker_id(phrase)
                speaker_label = speaker_labels.setdefault(
                    speaker_id,
                    self._azure_speech_speaker_label(speaker_id, len(speaker_labels) + 1),
                )
                transcript.append(
                    TranscriptSegment(
                        speaker_id=speaker_id,
                        speaker=speaker_label,
                        start=start,
                        end=end,
                        text=text,
                    )
                )
        if transcript:
            self._apply_detected_speaker_names(transcript, speaker_labels)
            speakers = [
                SpeakerProfile(speaker_id=speaker_id, label=label)
                for speaker_id, label in speaker_labels.items()
            ]
            return transcript, speakers

        combined = payload.get("combinedPhrases")
        if isinstance(combined, list) and combined:
            text = str(
                combined[0].get("text")
                or combined[0].get("display")
                or combined[0].get("lexical")
                or ""
            ).strip()
            if text:
                return (
                    [
                        TranscriptSegment(
                            speaker_id="speaker_1",
                            speaker="Speaker",
                            start=0.0,
                            end=0.0,
                            text=text,
                        )
                    ],
                    [SpeakerProfile(speaker_id="speaker_1", label="Speaker")],
                )
        return [], []

    def _apply_detected_speaker_names(
        self, segments: List[TranscriptSegment], speaker_labels: Dict[str, str]
    ) -> None:
        detected = self._detect_speaker_names(segments)
        if not detected:
            return
        for speaker_id, label in detected.items():
            speaker_labels[speaker_id] = label
        for segment in segments:
            if segment.speaker_id in detected:
                segment.speaker = detected[segment.speaker_id]

    def _detect_speaker_names(self, segments: List[TranscriptSegment]) -> Dict[str, str]:
        detected: Dict[str, str] = {}
        for segment in segments:
            if segment.speaker_id in detected:
                continue
            candidate = self._extract_self_named_reference(segment.text)
            if candidate:
                detected[segment.speaker_id] = candidate
        return detected

    def _extract_self_named_reference(self, text: str) -> str | None:
        content = text.strip()
        if not content:
            return None
        for pattern in _SELF_NAME_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            raw_name = match.group("name") or ""
            sanitized = self._sanitize_detected_name(raw_name)
            if sanitized:
                return sanitized
        return None

    def _sanitize_detected_name(self, raw_name: str) -> str | None:
        cleaned = raw_name.strip(" \t.,:;!?\"'()[]{}")
        if not cleaned:
            return None
        tokens = [token for token in re.split(r"\s+", cleaned) if token]
        if not tokens or len(tokens) > 3:
            return None
        normalized: List[str] = []
        skipping_titles = True
        for token in tokens:
            stripped = token.strip(".,:;!?\"'()[]{}")
            if not stripped:
                continue
            lowered = stripped.lower().rstrip(".")
            if skipping_titles and lowered in _NAME_TITLE_WORDS:
                continue
            skipping_titles = False
            if normalized and lowered in _NAME_BREAK_WORDS:
                break
            if lowered in _DISALLOWED_NAME_PARTS:
                return None
            if not any(ch.isalpha() for ch in stripped):
                return None
            if lowered in _ALLOWED_LOWER_NAME_PARTS:
                normalized.append(lowered)
                continue
            normalized.append(self._normalize_name_token(stripped))
        if not normalized:
            return None
        if all(word.lower() in _ALLOWED_LOWER_NAME_PARTS for word in normalized):
            return None
        candidate = " ".join(normalized)
        letters = sum(1 for ch in candidate if ch.isalpha())
        if letters == 0:
            return None
        if len(candidate) < 2:
            return None
        candidate_lower = candidate.lower()
        if candidate_lower in _DISALLOWED_NAME_PARTS:
            return None
        return candidate

    @staticmethod
    def _normalize_name_token(token: str) -> str:
        if not token:
            return token
        if token.islower():
            return TranscriptionService._smart_capitalize(token)
        if token.isupper():
            return TranscriptionService._smart_capitalize(token.lower())
        return token

    @staticmethod
    def _smart_capitalize(token: str) -> str:
        def _capitalize_fragment(fragment: str) -> str:
            if not fragment:
                return fragment
            return fragment[0].upper() + fragment[1:]

        result = token
        for separator in ("-", "'"):
            parts = result.split(separator)
            parts = [_capitalize_fragment(part.lower()) for part in parts]
            result = separator.join(parts)
        if not any(ch.isupper() for ch in result):
            result = _capitalize_fragment(result)
        return result

    @staticmethod
    def _collapse_segments(segments: List[TranscriptSegment]) -> List[TranscriptSegment]:
        collapsed: List[TranscriptSegment] = []
        for segment in segments:
            if collapsed and collapsed[-1].speaker_id == segment.speaker_id:
                previous = collapsed[-1]
                collapsed[-1] = TranscriptSegment(
                    speaker_id=previous.speaker_id,
                    speaker=previous.speaker,
                    start=previous.start,
                    end=segment.end,
                    text=(previous.text + " " + segment.text).strip(),
                )
            else:
                collapsed.append(segment)
        return collapsed

    def _summarize(self, transcript: str) -> str:
        return self._summarize_result(transcript).summary

    def _summarize_result(self, transcript: str) -> SummaryFallbackResult:
        if not transcript.strip():
            return SummaryFallbackResult()
        if self._use_llm_summary:
            llm_summary = self._summarize_with_llm(transcript)
            if llm_summary.has_content():
                if llm_summary.summary:
                    return llm_summary
                return SummaryFallbackResult(
                    summary=self._summarize_classically(transcript),
                    agenda=llm_summary.agenda,
                    highlights=llm_summary.highlights,
                    decisions=llm_summary.decisions,
                    action_items=llm_summary.action_items,
                    risks=llm_summary.risks,
                )
        return SummaryFallbackResult(summary=self._summarize_classically(transcript))

    def _summarize_classically(self, transcript: str) -> str:
        summarizer = self._load_summarizer()
        if summarizer is None:
            sentences = transcript.split(". ")
            return ". ".join(sentences[:2]).strip()
        summary = summarizer(
            transcript,
            max_length=180,
            min_length=60,
            do_sample=False,
        )
        return summary[0]["summary_text"].strip()

    @staticmethod
    def _merge_summary_fallback(minutes: MeetingMinutes, fallback: SummaryFallbackResult) -> None:
        if not minutes.summary and fallback.summary:
            minutes.summary = fallback.summary
        if not minutes.agenda and fallback.agenda:
            minutes.agenda = list(fallback.agenda)
        if not minutes.highlights and fallback.highlights:
            minutes.highlights = list(fallback.highlights)
        if not minutes.decisions and fallback.decisions:
            minutes.decisions = list(fallback.decisions)
        if not minutes.action_items and fallback.action_items:
            minutes.action_items = list(fallback.action_items)
        if not minutes.risks and fallback.risks:
            minutes.risks = list(fallback.risks)

    def _enrich_minutes_with_summary_fallback(self, minutes: MeetingMinutes, transcript: str) -> None:
        if not transcript.strip():
            self._ensure_minutes_sections(minutes)
            return
        if not ((minutes.summary or "").strip() and self._has_structured_minutes_content(minutes)):
            fallback = self._summarize_result(transcript)
            self._merge_summary_fallback(minutes, fallback)
        self._bootstrap_minutes_from_transcript(minutes, transcript)
        self._ensure_minutes_sections(minutes)

    @staticmethod
    def _has_structured_minutes_content(minutes: MeetingMinutes) -> bool:
        return any(
            [
                minutes.agenda,
                minutes.highlights,
                minutes.decisions,
                minutes.action_items,
                minutes.risks,
            ]
        )

    def _bootstrap_minutes_from_transcript(self, minutes: MeetingMinutes, transcript: str) -> None:
        sentences = self._extract_transcript_sentences(transcript)
        if not sentences:
            return

        if not (minutes.summary or "").strip():
            summary = self._summarize_classically(transcript).strip()
            if not summary:
                summary = ". ".join(sentences[:2]).strip()
            if summary and summary[-1] not in ".!?":
                summary = f"{summary}."
            minutes.summary = summary

        summary_sentences = self._extract_transcript_sentences(minutes.summary or "")
        if not minutes.agenda and summary_sentences:
            minutes.agenda = list(summary_sentences[:2])

        if not minutes.highlights and summary_sentences:
            minutes.highlights = list(summary_sentences[:3])

        if not minutes.decisions:
            decision_keywords = (
                "entscheidung",
                "entschieden",
                "beschluss",
                "freigegeben",
                "approve",
                "approved",
                "genehmigt",
            )
            decisions = [entry for entry in sentences if any(keyword in entry.casefold() for keyword in decision_keywords)]
            minutes.decisions = [MinutesDecision(title="Entscheidung", details=entry) for entry in decisions[:3]]

        if not minutes.action_items:
            extracted_actions: List[MinutesActionItem] = []
            action_pattern = re.compile(
                r"^(?P<owner>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]{2,})\s+hat(?:\s+\w+){0,4}\s+die\s+aufgabe\b(?P<rest>.*)$",
                re.IGNORECASE,
            )
            for entry in sentences:
                match = action_pattern.search(entry)
                if not match:
                    continue
                owner = match.group("owner").strip()
                details = match.group("rest").strip(" .,:;!-")
                description = f"Aufgabe {details}".strip() if details else entry
                if len(description) < 14:
                    continue
                extracted_actions.append(
                    MinutesActionItem(owner=owner, description=description, due_date=None)
                )
            minutes.action_items = extracted_actions[:4]

        if not minutes.risks:
            risk_keywords = (
                "risiko",
                "offen",
                "problem",
                "kritisch",
                "blocker",
                "verzug",
                "unsicher",
            )
            risks = [entry for entry in sentences if any(keyword in entry.casefold() for keyword in risk_keywords)]
            minutes.risks = list(risks[:4])

    @staticmethod
    def _extract_transcript_sentences(transcript: str) -> List[str]:
        raw = (transcript or "").strip()
        if not raw:
            return []
        parts = re.split(r"[.!?]\s+|\n+", raw)
        normalized: List[str] = []
        seen: set[str] = set()
        for part in parts:
            sentence = " ".join(part.split()).strip(" .,:;!-")
            if len(sentence) < 12:
                continue
            if len(sentence) > 220:
                sentence = f"{sentence[:217].rstrip()}..."
            tokenized = re.findall(r"[A-Za-zÄÖÜäöüß0-9_-]+", sentence)
            if len(tokenized) >= 8:
                unique_ratio = len({token.casefold() for token in tokenized}) / len(tokenized)
                if unique_ratio < 0.45:
                    continue
            key = sentence.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(sentence)
        return normalized

    def _ensure_minutes_sections(self, minutes: MeetingMinutes) -> None:
        ensure_sections = getattr(self._minutes, "ensure_sections", None)
        if callable(ensure_sections):
            ensure_sections(minutes)

    # ----- lazy loaders ----------------------------------------------------
    # TODO: Erstelle einen loader welcher verschiedene Modelle laden kann

    def _load_whisperx_model(self):
        if self._whisper is not None:
            return self._whisper
        try:
            import whisperx
        except Exception:
            return None

        self._prepare_whisperx_defaults(whisperx)
        errors: list[Exception] = []
        for target_device in self._device_candidates():
            for compute_type in self._compute_type_candidates(target_device):
                try:
                    self._whisper = whisperx.load_model(
                        self.whisper_model,
                        device=target_device,
                        compute_type=compute_type,
                    )
                    self._runtime_device = target_device
                    logger.info(
                        "WhisperX-Modell geladen auf %s mit compute_type=%s",
                        target_device,
                        compute_type,
                    )
                    return self._whisper
                except Exception as exc:
                    errors.append(exc)
                    logger.warning(
                        "WhisperX-Laden fehlgeschlagen fuer device=%s compute_type=%s: %s",
                        target_device,
                        compute_type,
                        exc,
                    )
                    if target_device == "cuda":
                        gc.collect()
                    continue
        if errors:
            logger.error("WhisperX konnte auf keinem Device geladen werden: %s", errors[-1])
        return None

    def _load_diarizer(self):
        try:
            from whisperx.diarize import DiarizationPipeline
        except Exception:
            return None
        token = os.getenv("PYANNOTE_TOKEN")
        if not token:
            return None
        device = self._effective_device()
        cache_key = (device, self.diarization_model)
        if self._diarizer is not None and self._diarizer_cache_key == cache_key:
            return self._diarizer
        try:
            self._diarizer = DiarizationPipeline(
                device=device,
                use_auth_token=token,
                model_name=self.diarization_model,
            )
            self._diarizer_cache_key = cache_key
            return self._diarizer
        except Exception:
            self._diarizer = None
            self._diarizer_cache_key = None
            return None
        return None

    def _load_align_model(self, language: str | None) -> tuple[Any, Any] | None:
        if not language:
            return None
        try:
            import whisperx
        except Exception:
            return None
        device = self._effective_device()
        cache_key = (language, device)
        cached = self._align_models.get(cache_key)
        if cached is not None:
            return cached
        try:
            align_bundle = whisperx.load_align_model(language_code=language, device=device)
            self._align_models[cache_key] = align_bundle
            return align_bundle
        except Exception:
            return None

    def _prepare_whisperx_defaults(self, whisperx_module: Any) -> None:
        """Ensure whisperx uses TranscriptionOptions defaults compatible with newer faster-whisper versions."""

        try:
            from faster_whisper.transcribe import TranscriptionOptions
        except Exception:
            return

        params = None
        try:
            params = inspect.signature(TranscriptionOptions.__init__).parameters
        except (ValueError, TypeError):
            params = None
        if not params or len(params) <= 1:
            try:
                params = inspect.signature(TranscriptionOptions.__new__).parameters
            except (ValueError, TypeError):
                params = None
        if not params:
            return

        asr_module = getattr(whisperx_module, "asr", None)
        if asr_module is None:
            try:
                from importlib import import_module

                asr_module = import_module("whisperx.asr")
                setattr(whisperx_module, "asr", asr_module)
            except Exception:
                return

        defaults = getattr(asr_module, "default_asr_options", None)
        if not isinstance(defaults, dict):
            return

        fallback_values: Dict[str, Any] = {
            "max_new_tokens": None,
            "clip_timestamps": "0",
            "hallucination_silence_threshold": 0.6,
            "hotwords": None,
        }
        for name, value in fallback_values.items():
            if name in params and name not in defaults:
                defaults[name] = value

    def _load_summarizer(self):
        if self._use_llm_summary:
            return None
        if self._summarizer is not None:
            return self._summarizer
        try:
            from transformers import pipeline
        except Exception:
            return None
        self._summarizer = pipeline("summarization", model=self.summary_model)
        return self._summarizer

    def _resolve_whisper_model(self, configured_model: str | None) -> str:
        normalized = (configured_model or "").strip()
        if normalized and normalized.lower() != "auto":
            return normalized
        if self._gpu_available():
            gpu_memory_gb = self._gpu_total_memory_gb()
            if gpu_memory_gb >= 12:
                return "large-v3"
            if gpu_memory_gb >= 10:
                return "medium"
            if gpu_memory_gb >= 6:
                return "small"
            return "small"
        return "small"

    def _resolve_diarization_model(self, configured_model: str | None) -> str:
        normalized = (configured_model or "").strip()
        if normalized and normalized.lower() != "auto":
            return normalized
        return "pyannote/speaker-diarization-3.1"

    @staticmethod
    def _gpu_available() -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except Exception:
            return False

    @staticmethod
    def _gpu_total_memory_gb() -> float:
        try:
            import torch

            if not torch.cuda.is_available():
                return 0.0
            properties = torch.cuda.get_device_properties(0)
            return float(properties.total_memory) / float(1024**3)
        except Exception:
            return 0.0

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        return "cuda" if self._gpu_available() else "cpu"

    @staticmethod
    def _normalize_execution_device(configured_device: str | None) -> str:
        normalized = (configured_device or "").strip().lower()
        if normalized in {"cpu", "cuda", "auto"}:
            return normalized
        return "auto"

    @staticmethod
    def _normalize_transcription_provider(provider: str | None) -> str:
        normalized = (provider or "").strip().lower()
        if normalized in {"azure", "azure_openai", "azure-openai"}:
            return "azure_openai"
        if normalized in {"azure_speech", "azure-speech", "speech", "speechservices"}:
            return "azure_speech"
        return "local"

    @staticmethod
    def _normalize_azure_endpoint(endpoint: str) -> str:
        value = (endpoint or "").strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.scheme and "://" in value:
            return value.rstrip("/")
        return f"https://{value.lstrip('/')}".rstrip("/")

    @staticmethod
    def _coerce_seconds(value: Any, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _coerce_milliseconds(value: Any, fallback: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return fallback
        if numeric > 10_000_000:
            return numeric / 10_000.0
        return numeric

    @staticmethod
    def _parse_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _strip_speaker_information(
        segments: List[TranscriptSegment],
    ) -> Tuple[List[TranscriptSegment], List[SpeakerProfile]]:
        """Setzt alle Sprechermerkmale zurueck, wenn die Sprechererkennung global deaktiviert ist.

        - Alle Segmente bekommen einen neutralen Speaker-Identifier ohne Label.
        - Die Sprecherprofil-Liste wird geleert, damit die Frontend-Logik keine
          Sprechererkennung anzeigt.
        """
        sanitized: List[TranscriptSegment] = []
        for segment in segments:
            sanitized.append(
                TranscriptSegment(
                    speaker_id="speaker_disabled",
                    speaker="",
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                )
            )
        return sanitized, []

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "on", "y", "t"}:
            return True
        if normalized in {"0", "false", "no", "off", "n", "f"}:
            return False
        return default

    def _resolve_azure_speech_endpoint(self) -> str:
        if self.azure_speech_endpoint:
            return self._normalize_azure_endpoint(self.azure_speech_endpoint)
        if self.azure_speech_region:
            return self._normalize_azure_endpoint(
                f"https://{self.azure_speech_region}.api.cognitive.microsoft.com/"
            )
        return self._normalize_azure_endpoint(self.azure_transcription_endpoint)

    def _azure_speech_locales(self) -> List[str]:
        raw_value = self.azure_speech_locales.strip()
        if not raw_value:
            return ["de-DE"]
        locales = [item.strip() for item in raw_value.split(",") if item.strip()]
        return locales or ["de-DE"]

    @staticmethod
    def _azure_speech_speaker_id(phrase: dict[str, Any]) -> str:
        for key in ("speaker", "speakerId", "speaker_id"):
            if key in phrase and phrase[key] is not None and str(phrase[key]).strip() != "":
                return f"speaker_{str(phrase[key]).strip()}"
        return "speaker_1"

    @staticmethod
    def _azure_speech_speaker_label(speaker_id: str, fallback_index: int) -> str:
        suffix = speaker_id.removeprefix("speaker_")
        if suffix and suffix != speaker_id:
            return f"Speaker {suffix}"
        return f"Speaker {fallback_index}"

    def _effective_device(self) -> str:
        return self._runtime_device or self._resolve_device()

    def _device_candidates(self) -> List[str]:
        preferred = self._resolve_device()
        if preferred == "cpu":
            return ["cpu"]
        return [preferred, "cpu"]

    def _compute_type_candidates(self, device: str) -> List[str]:
        configured = os.getenv("WHISPER_COMPUTE_TYPE")
        if configured:
            return [configured]
        if device == "cuda":
            return ["float16", "int8"]
        return ["int8", "float32"]

    @staticmethod
    def _is_cuda_oom(exc: Exception) -> bool:
        message = str(exc).lower()
        return "out of memory" in message or "cuda failed with error out of memory" in message

    @staticmethod
    def _release_torch_cuda_cache() -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return

    def _summarize_with_llm(self, transcript: str) -> SummaryFallbackResult:
        client = self._summary_llm_client or self._build_summary_llm_client()
        if client is None:
            return SummaryFallbackResult()
        prompt = self._summary_prompt(transcript)
        try:
            raw_output = client(prompt).strip()
            fallback = self._extract_summary_fallback(raw_output)
            summary_text = fallback.summary if fallback.has_content() else raw_output
            if summary_text and not self._is_summary_plausibly_grounded(transcript, summary_text):
                logger.debug("LLM-Summary verworfen, da sie nicht ausreichend im Transkript verankert ist")
                return SummaryFallbackResult()
            if fallback.has_content():
                fallback.summary = summary_text
                return self._filter_grounded_summary_fallback(transcript, fallback)
            return SummaryFallbackResult(summary=summary_text)
        except Exception as exc:  # pragma: no cover - network errors
            logger.warning("LLM-Summary fehlgeschlagen, nutze klassischen Fallback: %s", exc)
            return SummaryFallbackResult()

    @staticmethod
    def _is_summary_plausibly_grounded(transcript: str, summary_text: str) -> bool:
        if LLMMinutesGenerator.is_text_grounded(transcript, summary_text):
            return True
        summary_tokens = LLMMinutesGenerator._content_tokens(summary_text)
        if len(summary_tokens) < 4:
            return True
        transcript_vocabulary = set(LLMMinutesGenerator._content_tokens(transcript))
        overlap_count = sum(1 for token in summary_tokens if token in transcript_vocabulary)
        minimum_overlap = max(2, int(len(summary_tokens) * 0.25))
        return overlap_count >= minimum_overlap

    @staticmethod
    def _extract_summary_fallback(raw_output: str) -> SummaryFallbackResult:
        try:
            blob = LLMMinutesGenerator._extract_json_any(raw_output)
            data = json.loads(blob)
        except Exception:
            return SummaryFallbackResult()

        if not isinstance(data, dict):
            return SummaryFallbackResult()

        summary = str(
            TranscriptionService._first_present_value(
                data,
                ["summary", "kurzzusammenfassung", "zusammenfassung"],
                "",
            )
        ).strip()
        agenda = TranscriptionService._normalize_summary_string_list(
            TranscriptionService._first_present_value(
                data,
                ["agenda", "agenda_items", "agenda_points", "topics", "themen", "agenda_punkte"],
                [],
            )
        )
        highlights = TranscriptionService._normalize_summary_string_list(
            TranscriptionService._first_present_value(
                data,
                ["highlights", "key_points", "bullet_points", "stichpunkte"],
                [],
            )
        )
        risks = TranscriptionService._normalize_summary_string_list(
            TranscriptionService._first_present_value(
                data,
                ["risks", "open_points", "issues", "risiken", "offene_punkte"],
                [],
            )
        )

        decisions: List[MinutesDecision] = []
        raw_decisions = TranscriptionService._first_present_value(
            data,
            ["decisions", "entscheidungen"],
            [],
        )
        for item in raw_decisions or []:
            if isinstance(item, dict):
                title = str(
                    TranscriptionService._first_present_value(
                        item,
                        ["title", "titel", "decision", "topic", "name"],
                        "",
                    )
                ).strip() or "Entscheidung"
                details = str(
                    TranscriptionService._first_present_value(
                        item,
                        ["details", "detail", "description", "begruendung", "context", "reason"],
                        "",
                    )
                ).strip()
                if title or details:
                    decisions.append(MinutesDecision(title=title, details=details))
            else:
                text = str(item or "").strip()
                if text:
                    decisions.append(MinutesDecision(title=text, details=""))

        action_items: List[MinutesActionItem] = []
        raw_actions = TranscriptionService._first_present_value(
            data,
            [
                "action_items",
                "next_steps",
                "actions",
                "tasks",
                "todos",
                "aufgaben",
                "naechste_schritte",
            ],
            [],
        )
        for item in raw_actions or []:
            if isinstance(item, dict):
                owner = str(
                    TranscriptionService._first_present_value(
                        item,
                        ["owner", "assignee", "responsible", "verantwortlich", "person"],
                        "Offen",
                    )
                ).strip() or "Offen"
                description = str(
                    TranscriptionService._first_present_value(
                        item,
                        ["description", "task", "action", "todo", "aufgabe"],
                        "",
                    )
                ).strip()
                due_date = str(
                    TranscriptionService._first_present_value(
                        item,
                        ["due_date", "due", "deadline", "dueDate", "faellig"],
                        "",
                    )
                ).strip() or None
                if owner or description or due_date:
                    action_items.append(
                        MinutesActionItem(owner=owner, description=description, due_date=due_date)
                    )
            else:
                text = str(item or "").strip()
                if text:
                    action_items.append(
                        MinutesActionItem(owner="Offen", description=text, due_date=None)
                    )

        return SummaryFallbackResult(
            summary=summary,
            agenda=agenda,
            highlights=highlights,
            decisions=decisions,
            action_items=action_items,
            risks=risks,
        )

    @staticmethod
    def _normalize_summary_string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _first_present_value(container: dict[str, Any], keys: List[str], default: Any) -> Any:
        for key in keys:
            if key in container and container[key] is not None:
                return container[key]
        return default

    @staticmethod
    def _filter_grounded_summary_fallback(
        transcript: str, fallback: SummaryFallbackResult
    ) -> SummaryFallbackResult:
        filtered = SummaryFallbackResult(summary=fallback.summary)
        filtered.agenda = [
            item for item in fallback.agenda if LLMMinutesGenerator.is_text_grounded(transcript, item)
        ]
        filtered.highlights = [
            item
            for item in fallback.highlights
            if LLMMinutesGenerator.is_text_grounded(transcript, item)
        ]
        filtered.decisions = [
            item
            for item in fallback.decisions
            if LLMMinutesGenerator.is_text_grounded(transcript, f"{item.title} {item.details}")
        ]
        filtered.action_items = [
            item
            for item in fallback.action_items
            if LLMMinutesGenerator.is_text_grounded(
                transcript, f"{item.owner} {item.description} {item.due_date or ''}"
            )
        ]
        filtered.risks = [
            item for item in fallback.risks if LLMMinutesGenerator.is_text_grounded(transcript, item)
        ]
        return filtered

    def _build_summary_llm_client(self) -> LLMCallable | None:
        if self.llm_provider == "azure_openai":
            if not self.llm_azure_endpoint:
                return None
            self._summary_llm_client = AzureOpenAICompletionClient(
                endpoint=self.llm_azure_endpoint,
                model=self.summary_model,
                api_key=self.summary_llm_api_key or self.llm_azure_api_key,
                api_version=self.llm_azure_api_version,
                expect_json=False,
            )
            return self._summary_llm_client
        if not self.summary_llm_base_url:
            return None
        self._summary_llm_client = HTTPCompletionClient(
            base_url=self.summary_llm_base_url,
            model=self.summary_model,
            api_key=self.summary_llm_api_key,
            completions_path=self.summary_llm_path or "/v1/chat/completions",
        )
        return self._summary_llm_client

    @staticmethod
    def _summary_prompt(transcript: str) -> str:
        context = transcript.strip()
        if len(context) > 8000:
            context = context[:8000]
        return (
            "Lies das Meeting-Transkript und gib bevorzugt ein JSON-Objekt zurueck. "
            'Schema: {"summary": string, "agenda": [string], "highlights": [string], '
            '"decisions": [{"title": string, "details": string}], '
            '"action_items": [{"owner": string, "description": string, "due_date": string|null}], '
            '"risks": [string]}. '
            "summary soll 2-3 Saetze enthalten. Falls keine Informationen fuer ein Feld vorhanden sind, "
            "liefere ein leeres Array fuer dieses Feld. Nutze nur Inhalte aus dem Transkript."
            f"\nTranskript:\n{context}"
        )

    @staticmethod
    def _should_use_llm_summary(model_name: str, provider: str = "http") -> bool:
        prefer_llm = os.getenv("SUMMARY_USE_LLM")
        if prefer_llm and prefer_llm.lower() in {"1", "true", "yes"}:
            return True
        if provider == "azure_openai":
            return True
        return bool((model_name or "").strip()) and provider == "http"
