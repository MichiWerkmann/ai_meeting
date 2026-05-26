import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from backend.app.schemas import MeetingMinutes, ModelSettings, TranscriptSegment
from backend.app.services.transcription import TranscriptionService


class DummyMinutesGenerator:
    def build_minutes(self, segments):
        return MeetingMinutes(summary="")


class DummySummaryLLM:
    def __init__(self) -> None:
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan."


class HallucinatingSummaryLLM:
    def __call__(self, prompt: str) -> str:
        return (
            "Das Meeting behandelte Produktionsauftraege, Roboterarme und Maschinenfreigaben. "
            "Claudia prueft die Halle."
        )


class JsonSummaryLLM:
    def __call__(self, prompt: str) -> str:
        return (
            '{"summary":"Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan.",'
            '"decisions":["Budget freigegeben"],'
            '"next_steps":["Ben schickt den aktualisierten Zeitplan"],'
            '"risks":["Liefertermin bleibt offen"]}'
        )


class GermanAliasJsonSummaryLLM:
    def __call__(self, prompt: str) -> str:
        return (
            '{"zusammenfassung":"Kurzstatus zum Meeting.",'
            '"themen":["Budget"],'
            '"stichpunkte":["Projekt wird priorisiert"],'
            '"entscheidungen":[{"titel":"Budget freigegeben","begruendung":"Fuer Projekt Apollo"}],'
            '"aufgaben":[{"verantwortlich":"Dennis","aufgabe":"Ticket erstellen","faellig":"morgen"}],'
            '"offene_punkte":["Liefertermin offen"]}'
        )


def test_collapse_segments_merges_consecutive_blocks():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    segments = [
        TranscriptSegment(
            speaker_id="speaker_a",
            speaker="Speaker A",
            start=0.0,
            end=5.0,
            text="Hallo",
        ),
        TranscriptSegment(
            speaker_id="speaker_a",
            speaker="Speaker A",
            start=5.0,
            end=9.0,
            text="Welt",
        ),
        TranscriptSegment(
            speaker_id="speaker_b",
            speaker="Speaker B",
            start=9.0,
            end=12.0,
            text="Weitere Infos",
        ),
    ]

    collapsed = service._collapse_segments(segments)

    assert len(collapsed) == 2
    assert collapsed[0].text == "Hallo Welt"
    assert collapsed[0].end == 9.0
    assert collapsed[1].speaker_id == "speaker_b"


def test_build_transcript_without_diarization_keeps_segment_boundaries():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    transcript, speakers = service._build_transcript(
        [
            {"start": 0.0, "end": 2.0, "text": "Hallo zusammen"},
            {"start": 2.0, "end": 4.5, "text": "Nächster Punkt"},
        ],
        collapse_consecutive=False,
    )

    assert len(transcript) == 2
    assert transcript[0].speaker == "Speaker"
    assert transcript[1].speaker == "Speaker"
    assert speakers[0].label == "Speaker"


def test_prepare_whisperx_defaults_imports_asr(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    fake_whisperx = SimpleNamespace()
    defaults = {}

    class DummyTranscriptionOptions:
        def __init__(
            self,
            *,
            max_new_tokens=None,
            clip_timestamps=None,
            hallucination_silence_threshold=None,
            hotwords=None,
        ) -> None:
            self.max_new_tokens = max_new_tokens

    asr_module = SimpleNamespace(default_asr_options=defaults)
    fake_options_module = SimpleNamespace(TranscriptionOptions=DummyTranscriptionOptions)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(transcribe=fake_options_module))
    monkeypatch.setitem(sys.modules, "faster_whisper.transcribe", fake_options_module)
    monkeypatch.setitem(sys.modules, "whisperx.asr", asr_module)

    service._prepare_whisperx_defaults(fake_whisperx)

    assert fake_whisperx.asr is asr_module
    assert defaults["max_new_tokens"] is None
    assert defaults["clip_timestamps"] == "0"


def test_load_diarizer_uses_env_token(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator(), device="cpu")
    captured = {}

    class DummyPipeline:
        def __init__(self, device, use_auth_token, model_name):
            captured["device"] = device
            captured["token"] = use_auth_token
            captured["model"] = model_name

    module = SimpleNamespace(DiarizationPipeline=DummyPipeline)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", module)
    monkeypatch.setenv("PYANNOTE_TOKEN", "hf_test")

    pipeline = service._load_diarizer()

    assert isinstance(pipeline, DummyPipeline)
    assert captured["token"] == "hf_test"


def test_load_diarizer_reuses_cached_pipeline(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator(), device="cpu")
    captured = {"count": 0}

    class DummyPipeline:
        def __init__(self, device, use_auth_token, model_name):
            captured["count"] += 1
            self.device = device
            self.use_auth_token = use_auth_token
            self.model_name = model_name

    module = SimpleNamespace(DiarizationPipeline=DummyPipeline)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", module)
    monkeypatch.setenv("PYANNOTE_TOKEN", "hf_test")

    first = service._load_diarizer()
    second = service._load_diarizer()

    assert first is second
    assert captured["count"] == 1


def test_call_diarizer_invokes_pipeline():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    captured = {}

    class DummyDiarizer:
        def __call__(self, audio):
            captured["audio"] = audio
            return "diarized"

    result = service._call_diarizer(DummyDiarizer(), "audio-data")

    assert result == "diarized"
    assert captured["audio"] == "audio-data"


def test_cache_session_and_get_session():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = Path(temp_dir) / "sample.wav"
        audio_path.write_bytes(b"abc")

        session_id = service._cache_session(audio_path, {"segments": [{"text": "Hallo"}]})
        session = service._session_cache[session_id]

        assert session.session_id == session_id
        assert session.audio_path.exists()
        assert session.aligned_result["segments"][0]["text"] == "Hallo"


def test_low_information_minutes_detects_fallback():
    fallback = MeetingMinutes(summary="", model="gemma-3-4b-it-qat (fallback)")
    rich = MeetingMinutes(summary="Kurze Zusammenfassung", model="gemma-3-4b-it-qat")

    assert TranscriptionService._is_low_information_minutes(fallback) is True
    assert TranscriptionService._is_low_information_minutes(rich) is False


def test_auto_profile_prefers_large_v3_on_strong_gpu(monkeypatch):
    monkeypatch.setattr(TranscriptionService, "_gpu_available", staticmethod(lambda: True))
    monkeypatch.setattr(TranscriptionService, "_gpu_total_memory_gb", staticmethod(lambda: 12.0))

    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        whisper_model="auto",
        diarization_model="auto",
    )

    assert service.whisper_model == "large-v3"
    assert service.diarization_model == "pyannote/speaker-diarization-3.1"


def test_auto_profile_prefers_medium_on_midrange_gpu(monkeypatch):
    monkeypatch.setattr(TranscriptionService, "_gpu_available", staticmethod(lambda: True))
    monkeypatch.setattr(TranscriptionService, "_gpu_total_memory_gb", staticmethod(lambda: 7.5))

    service = TranscriptionService(minutes_generator=DummyMinutesGenerator(), whisper_model="auto")

    assert service.whisper_model == "medium"


def test_auto_profile_prefers_small_on_cpu(monkeypatch):
    monkeypatch.setattr(TranscriptionService, "_gpu_available", staticmethod(lambda: False))
    monkeypatch.setattr(TranscriptionService, "_gpu_total_memory_gb", staticmethod(lambda: 0.0))

    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        whisper_model="auto",
        diarization_model="auto",
    )

    assert service.whisper_model == "small"
    assert service.diarization_model == "pyannote/speaker-diarization-3.1"


def test_summarize_uses_llm_when_summary_model_contains_colon():
    llm = DummySummaryLLM()
    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        summary_model="gpt-oss:20b",
        summary_llm_client=llm,
    )

    summary = service._summarize("Erstes Statement. Zweites folgt.")

    assert summary == "Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan."
    assert llm.prompts
    assert "Transkript" in llm.prompts[0]


def test_summarize_rejects_ungrounded_llm_output():
    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        summary_model="gpt-oss:20b",
        summary_llm_client=HallucinatingSummaryLLM(),
    )

    summary = service._summarize("Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan.")

    assert "Produktionsauftraege" not in summary
    assert "Budget" in summary


def test_summarize_extracts_summary_text_from_json_payload():
    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        summary_model="gpt-oss:20b",
        summary_llm_client=JsonSummaryLLM(),
    )

    summary = service._summarize("Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan.")

    assert summary == "Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan."


def test_merge_summary_fallback_populates_minutes_sections():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    minutes = MeetingMinutes(summary="")
    fallback = service._extract_summary_fallback(JsonSummaryLLM()(""))

    service._merge_summary_fallback(minutes, fallback)

    assert minutes.summary == "Anna bestaetigt das Budget. Ben aktualisiert den Zeitplan."
    assert minutes.decisions[0].title == "Budget freigegeben"
    assert minutes.action_items[0].owner == "Offen"
    assert minutes.action_items[0].description == "Ben schickt den aktualisierten Zeitplan"
    assert minutes.risks == ["Liefertermin bleibt offen"]


def test_enrich_minutes_with_summary_fallback_when_only_summary_exists():
    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        summary_model="gpt-oss:20b",
        summary_llm_client=JsonSummaryLLM(),
    )
    minutes = MeetingMinutes(summary="Kurzzusammenfassung vorhanden.")

    service._enrich_minutes_with_summary_fallback(
        minutes,
        "Budget freigegeben. Ben schickt den aktualisierten Zeitplan. Liefertermin bleibt offen.",
    )

    assert minutes.summary == "Kurzzusammenfassung vorhanden."
    assert minutes.decisions[0].title == "Budget freigegeben"
    assert minutes.action_items[0].description == "Ben schickt den aktualisierten Zeitplan"
    assert minutes.risks == ["Liefertermin bleibt offen"]


def test_enrich_minutes_bootstraps_sections_from_transcript_when_minutes_are_empty():
    service = TranscriptionService(
        minutes_generator=DummyMinutesGenerator(),
        summary_model="gpt-oss:20b",
        summary_llm_client=HallucinatingSummaryLLM(),
    )
    minutes = MeetingMinutes(summary="")
    transcript = (
        "Anna priorisiert Projekt Apollo. "
        "Ben erstellt eine Aufgabe fuer den Zeitplan. "
        "Ein Risiko fuer Lieferverzug bleibt offen."
    )

    service._enrich_minutes_with_summary_fallback(minutes, transcript)

    assert minutes.summary
    assert minutes.agenda
    assert minutes.highlights
    assert minutes.action_items
    assert minutes.risks


def test_extract_summary_fallback_supports_german_alias_keys():
    fallback = TranscriptionService._extract_summary_fallback(GermanAliasJsonSummaryLLM()(""))

    assert fallback.summary == "Kurzstatus zum Meeting."
    assert fallback.agenda == ["Budget"]
    assert fallback.highlights == ["Projekt wird priorisiert"]
    assert fallback.decisions[0].title == "Budget freigegeben"
    assert fallback.decisions[0].details == "Fuer Projekt Apollo"
    assert fallback.action_items[0].owner == "Dennis"
    assert fallback.action_items[0].description == "Ticket erstellen"
    assert fallback.action_items[0].due_date == "morgen"
    assert fallback.risks == ["Liefertermin offen"]


def test_summary_prompt_requests_structured_json_output():
    prompt = TranscriptionService._summary_prompt("Budget wurde abgestimmt.")

    assert "JSON-Objekt" in prompt
    assert '"action_items"' in prompt
    assert "Transkript" in prompt


def test_apply_settings_updates_runtime_models():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    service.apply_settings(
        ModelSettings(
            execution_device="cpu",
            transcription_provider="azure_openai",
            whisper_model="medium",
            diarization_model="pyannote/speaker-diarization-3.1",
            azure_transcription_endpoint="https://example.openai.azure.com",
            azure_transcription_api_key="azure-secret",
            azure_transcription_api_version="2024-02-01",
            azure_transcription_deployment="whisper-prod",
            azure_speech_endpoint="https://germanywestcentral.api.cognitive.microsoft.com/",
            azure_speech_region="germanywestcentral",
            azure_speech_locales="de-DE,en-US",
            azure_speech_max_speakers=4,
            llm_provider="llama_cpp",
            llm_model="Qwen2.5-7B-Instruct",
            llm_base_url="",
            llm_api_key="",
            llm_completions_path="",
            llm_local_model_path="C:/models/qwen.gguf",
            llm_local_context_size=262144,
            llm_local_gpu_layers=24,
            summary_model="gpt-4o-mini",
            summary_llm_base_url="https://api.example.com",
            summary_llm_api_key="summary-secret",
            summary_llm_completions_path="/v1/chat/completions",
        )
    )

    exported = service.export_settings()

    assert service.whisper_model == "medium"
    assert service.device == "cpu"
    assert service.transcription_provider == "azure_openai"
    assert service.summary_model == "gpt-4o-mini"
    assert exported.transcription_provider == "azure_openai"
    assert exported.azure_transcription_deployment == "whisper-prod"
    assert exported.azure_speech_region == "germanywestcentral"
    assert exported.azure_speech_locales == "de-DE,en-US"
    assert exported.azure_speech_max_speakers == 4
    assert exported.llm_provider == "llama_cpp"
    assert exported.llm_model == "Qwen2.5-7B-Instruct"
    assert exported.llm_local_model_path == "C:/models/qwen.gguf"
    assert exported.llm_local_context_size == 262144
    assert exported.llm_local_gpu_layers == 24
    assert exported.summary_llm_api_key == "summary-secret"


def test_apply_settings_updates_azure_llm_runtime_models():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    service.apply_settings(
        ModelSettings(
            llm_provider="azure_openai",
            llm_model="gpt-4.1-mini",
            llm_azure_endpoint="https://llm-example.openai.azure.com",
            llm_azure_api_key="Bearer azure-llm-token",
            llm_azure_api_version="2025-01-01-preview",
            summary_model="gpt-5-nano",
            llm_local_model_path="C:/models/qwen.gguf",
        )
    )

    exported = service.export_settings()

    assert service.llm_provider == "azure_openai"
    assert service.llm_azure_endpoint == "https://llm-example.openai.azure.com"
    assert service.llm_azure_api_version == "2025-01-01-preview"
    assert exported.llm_provider == "azure_openai"
    assert exported.llm_model == "gpt-4.1-mini"
    assert exported.llm_azure_endpoint == "https://llm-example.openai.azure.com"
    assert exported.llm_azure_api_key == "Bearer azure-llm-token"
    assert exported.summary_model == "gpt-5-nano"


def test_local_llama_cpp_provider_enables_llm_summary():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    service.apply_settings(
        ModelSettings(
            llm_provider="llama_cpp",
            llm_model="Qwen2.5-7B-Instruct",
            llm_local_model_path="C:/models/qwen.gguf",
            summary_model="Qwen2.5-7B-Instruct",
        )
    )

    assert service._use_llm_summary is True


def test_azure_openai_provider_enables_llm_summary():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    service.apply_settings(
        ModelSettings(
            llm_provider="azure_openai",
            llm_model="gpt-4.1-mini",
            llm_azure_endpoint="https://llm-example.openai.azure.com",
            llm_azure_api_key="Bearer azure-llm-token",
            llm_azure_api_version="2025-01-01-preview",
            summary_model="gpt-5-nano",
            llm_local_model_path="C:/models/qwen.gguf",
        )
    )

    assert service._use_llm_summary is True


def test_azure_summary_client_disables_json_mode():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    service.apply_settings(
        ModelSettings(
            llm_provider="azure_openai",
            llm_model="gpt-4.1-mini",
            llm_azure_endpoint="https://llm-example.openai.azure.com",
            llm_azure_api_key="Bearer azure-llm-token",
            llm_azure_api_version="2025-01-01-preview",
            summary_model="gpt-5-nano",
            llm_local_model_path="C:/models/qwen.gguf",
        )
    )

    client = service._build_summary_llm_client()

    assert client is not None
    assert getattr(client, "expect_json", True) is False


def test_normalize_transcription_provider_maps_azure_aliases():
    assert TranscriptionService._normalize_transcription_provider("azure") == "azure_openai"
    assert TranscriptionService._normalize_transcription_provider("azure-openai") == "azure_openai"
    assert TranscriptionService._normalize_transcription_provider("local") == "local"


def test_build_azure_transcript_uses_segments_when_present():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    transcript = service._build_azure_transcript(
        {
            "text": "Hallo zusammen",
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "Hallo"},
                {"start": 1.5, "end": 3.0, "text": "zusammen"},
            ],
        }
    )

    assert len(transcript) == 2
    assert transcript[0].text == "Hallo"
    assert transcript[1].end == 3.0


def test_run_azure_transcription_pipeline_returns_generic_speaker_labels(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    service.azure_transcription_endpoint = "https://example.openai.azure.com"
    service.azure_transcription_api_key = "azure-secret"
    service.azure_transcription_api_version = "2024-02-01"
    service.azure_transcription_deployment = "whisper-prod"

    monkeypatch.setattr(
        service,
        "_request_azure_transcription",
        lambda _audio_path: {
            "segments": [{"start": 0.0, "end": 2.0, "text": "Hallo Azure"}],
        },
    )

    session_id, segments, speakers, transcription_seconds, diarization_seconds = service._run_azure_transcription_pipeline(
        Path("dummy.wav")
    )

    assert session_id is None
    assert segments[0].text == "Hallo Azure"
    assert speakers == []
    assert transcription_seconds >= 0.0
    assert diarization_seconds == 0.0


def test_request_azure_transcription_builds_multipart_files(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    service.azure_transcription_endpoint = "https://example.openai.azure.com"
    service.azure_transcription_api_key = "azure-secret"
    service.azure_transcription_api_version = "2024-02-01"
    service.azure_transcription_deployment = "whisper-prod"
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"text": "Hallo Welt"}

    def fake_post(url, params=None, headers=None, files=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["files"] = files
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("backend.app.services.transcription.httpx.post", fake_post)

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = Path(temp_dir) / "sample.wav"
        audio_path.write_bytes(b"abc")
        payload = service._request_azure_transcription(audio_path)

    assert payload["text"] == "Hallo Welt"
    assert captured["params"] == {"api-version": "2024-02-01"}
    assert captured["headers"]["api-key"] == "azure-secret"
    assert [item[0] for item in captured["files"][:3]] == [
        "response_format",
        "timestamp_granularities[]",
        "model",
    ]
    assert captured["files"][-1][0] == "file"


def test_request_azure_speech_transcription_uses_speech_headers(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    service.azure_speech_endpoint = "https://germanywestcentral.api.cognitive.microsoft.com/"
    service.azure_speech_region = "germanywestcentral"
    service.azure_speech_locales = "de-DE,en-US"
    service.azure_speech_max_speakers = 4
    service.azure_transcription_api_key = "speech-secret"
    service.azure_transcription_api_version = "2024-11-15"
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"combinedPhrases": [{"text": "Hallo Speech"}]}

    def fake_post(url, params=None, headers=None, files=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["files"] = files
        return DummyResponse()

    monkeypatch.setattr("backend.app.services.transcription.httpx.post", fake_post)
    monkeypatch.setattr(
        service,
        "_prepare_audio_for_azure_speech",
        lambda audio_path: (audio_path, lambda: None),
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = Path(temp_dir) / "sample.wav"
        audio_path.write_bytes(b"abc")
        payload = service._request_azure_speech_transcription(audio_path)

    assert payload["combinedPhrases"][0]["text"] == "Hallo Speech"
    assert captured["url"].endswith("/speechtotext/transcriptions:transcribe")
    assert captured["params"] == {"api-version": "2024-11-15"}
    assert captured["headers"]["Ocp-Apim-Subscription-Key"] == "speech-secret"
    assert "audio" in captured["files"]
    definition = captured["files"]["definition"]
    assert definition[1] == '{"locales": ["de-DE", "en-US"], "profanityFilterMode": "Masked", "diarization": {"maxSpeakers": 4}}'


def test_build_azure_speech_transcript_uses_phrase_timings():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    transcript, speakers = service._build_azure_speech_transcript(
        {
            "phrases": [
                {
                    "text": "Hallo",
                    "offsetMilliseconds": 0,
                    "durationMilliseconds": 1200,
                    "speaker": 1,
                },
                {
                    "text": "Welt",
                    "offsetMilliseconds": 1200,
                    "durationMilliseconds": 800,
                    "speaker": 2,
                },
            ]
        }
    )

    assert len(transcript) == 2
    assert transcript[0].start == 0.0
    assert transcript[0].end == 1.2
    assert transcript[0].speaker == "Speaker 1"
    assert transcript[1].text == "Welt"
    assert [speaker.label for speaker in speakers] == ["Speaker 1", "Speaker 2"]


def test_resolve_azure_speech_endpoint_builds_from_region():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    service.azure_speech_region = "germanywestcentral"

    assert service._resolve_azure_speech_endpoint() == "https://germanywestcentral.api.cognitive.microsoft.com"


def test_prepare_audio_for_azure_speech_keeps_wav_files():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = Path(temp_dir) / "sample.wav"
        audio_path.write_bytes(b"RIFF")
        prepared, cleanup = service._prepare_audio_for_azure_speech(audio_path)
        try:
            assert prepared == audio_path
        finally:
            cleanup()


def test_hardware_profile_prefers_local_on_cpu(monkeypatch):
    monkeypatch.setattr(TranscriptionService, "_gpu_available", staticmethod(lambda: False))
    monkeypatch.setattr(TranscriptionService, "_gpu_total_memory_gb", staticmethod(lambda: 0.0))

    service = TranscriptionService(minutes_generator=DummyMinutesGenerator(), device="auto")
    profile = service.hardware_profile()

    assert profile.device == "cpu"
    assert profile.gpu_available is False
    assert profile.performance_tier == "medium"
    assert profile.recommended_execution == "local"
    assert "CPU" in profile.performance_message


def test_hardware_profile_prefers_local_on_strong_cuda(monkeypatch):
    monkeypatch.setattr(TranscriptionService, "_gpu_available", staticmethod(lambda: True))
    monkeypatch.setattr(TranscriptionService, "_gpu_total_memory_gb", staticmethod(lambda: 12.0))

    service = TranscriptionService(minutes_generator=DummyMinutesGenerator(), device="auto")
    profile = service.hardware_profile()

    assert profile.device == "cuda"
    assert profile.gpu_available is True
    assert profile.performance_tier == "high"
    assert profile.recommended_execution == "local"


def test_build_transcript_detects_self_named_speaker_in_german_intro():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    raw_segments = [
        {
            "text": "Hallo zusammen, mein Name ist Anna Müller und freue mich.",
            "start": 0.0,
            "end": 4.0,
            "speaker": "SPEAKER_00",
        },
        {
            "text": "Danke euch allen.",
            "start": 4.0,
            "end": 5.0,
            "speaker": "SPEAKER_00",
        },
        {
            "text": "Ich übernehme danach.",
            "start": 5.0,
            "end": 6.0,
            "speaker": "SPEAKER_01",
        },
    ]

    segments, speakers = service._build_transcript(raw_segments)

    assert segments[0].speaker == "Anna Müller"
    assert speakers[0].label == "Anna Müller"


def test_build_transcript_keeps_generic_label_without_name_detection():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    raw_segments = [
        {
            "text": "Ich bin bereit für das Update.",
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_02",
        }
    ]

    segments, speakers = service._build_transcript(raw_segments)

    assert segments[0].speaker == "Speaker 1"
    assert speakers[0].label == "Speaker 1"


def test_build_transcript_detects_self_named_speaker_with_ich_heisse():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    raw_segments = [
        {
            "text": "Guten Morgen, ich heiße Max Mustermann und übernehme den ersten Punkt.",
            "start": 0.0,
            "end": 3.0,
            "speaker": "SPEAKER_10",
        }
    ]

    segments, speakers = service._build_transcript(raw_segments)

    assert segments[0].speaker == "Max Mustermann"
    assert speakers[0].label == "Max Mustermann"


def test_build_transcript_ignores_mood_statements_for_name_detection():
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    raw_segments = [
        {
            "text": "Guten Morgen, ich bin müde aber starte trotzdem.",
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_03",
        }
    ]

    segments, speakers = service._build_transcript(raw_segments)

    assert segments[0].speaker == "Speaker 1"
    assert speakers[0].label == "Speaker 1"

    english_segments = [
        {
            "text": "Hello everyone, I'm tired but still here.",
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_EN",
        }
    ]

    segments_en, speakers_en = service._build_transcript(english_segments)

    assert segments_en[0].speaker == "Speaker 1"
    assert speakers_en[0].label == "Speaker 1"


def test_run_whisperx_pipeline_raises_when_model_unavailable(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    monkeypatch.setattr(service, "_load_whisperx_model", lambda: None)

    try:
        service._run_whisperx_pipeline(Path("dummy.wav"))
    except RuntimeError as exc:
        assert "WhisperX-Modell" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError when WhisperX model is unavailable")


def test_run_whisperx_pipeline_skips_alignment_without_diarization(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())

    class DummyModel:
        def transcribe(self, _audio, **_kwargs):
            return {
                "language": "de",
                "segments": [{"start": 0.0, "end": 1.0, "text": "Hallo"}],
            }

    align_called = {"value": False}
    whisperx_module = SimpleNamespace(
        load_audio=lambda _path: "audio-data",
        align=lambda *_args, **_kwargs: align_called.__setitem__("value", True),
    )
    monkeypatch.setitem(sys.modules, "whisperx", whisperx_module)
    monkeypatch.setattr(service, "_load_whisperx_model", lambda: DummyModel())
    monkeypatch.setattr(
        service,
        "_prepare_audio_for_local_transcription",
        lambda path: (path, lambda: None),
    )
    monkeypatch.setattr(service, "_load_align_model", lambda _language: ("align-model", {"meta": True}))
    monkeypatch.setattr(
        service,
        "_apply_diarization",
        lambda _audio, result, diarize=True, progress_callback=None: (
            [TranscriptSegment(speaker_id="speaker_1", speaker="Speaker", start=0.0, end=1.0, text="Hallo")],
            [],
            0.0,
        ),
    )

    service._run_whisperx_pipeline(Path("dummy.wav"), cache_session=False, diarize=False)

    assert align_called["value"] is False


def test_run_whisperx_pipeline_normalizes_audio_before_loading(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator())
    captured = {}

    class DummyModel:
        def transcribe(self, _audio, **_kwargs):
            return {
                "language": "de",
                "segments": [{"start": 0.0, "end": 1.0, "text": "Hallo"}],
            }

    def prepare_audio(path):
        captured["input_path"] = path
        prepared = Path("normalized.wav")
        return prepared, lambda: captured.__setitem__("cleanup_called", True)

    whisperx_module = SimpleNamespace(load_audio=lambda path: captured.__setitem__("loaded_path", path) or "audio-data")
    monkeypatch.setitem(sys.modules, "whisperx", whisperx_module)
    monkeypatch.setattr(service, "_load_whisperx_model", lambda: DummyModel())
    monkeypatch.setattr(service, "_prepare_audio_for_local_transcription", prepare_audio)
    monkeypatch.setattr(
        service,
        "_apply_diarization",
        lambda _audio, result, diarize=True, progress_callback=None: (
            [TranscriptSegment(speaker_id="speaker_1", speaker="Speaker", start=0.0, end=1.0, text="Hallo")],
            [],
            0.0,
        ),
    )

    service._run_whisperx_pipeline(Path("input.mp3"), cache_session=False, diarize=False)

    assert captured["input_path"] == Path("input.mp3")
    assert captured["loaded_path"] == "normalized.wav"
    assert captured["cleanup_called"] is True


def test_load_align_model_reuses_cached_bundle(monkeypatch):
    service = TranscriptionService(minutes_generator=DummyMinutesGenerator(), device="cpu")
    captured = {"count": 0}

    def load_align_model(language_code, device):
        captured["count"] += 1
        return (f"align-{language_code}", {"device": device})

    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(load_align_model=load_align_model))

    first = service._load_align_model("de")
    second = service._load_align_model("de")

    assert first == second
    assert captured["count"] == 1
