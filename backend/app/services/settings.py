from __future__ import annotations

import json
import os
from pathlib import Path

from ..schemas import ModelSettings, ModelSettingsUpdate


def _env_defaults() -> dict:
    """Liest optionale Env-Vars und gibt sie als Defaults-Dict zurück."""
    defaults: dict = {}
    speaker = os.environ.get("SPEAKER_RECOGNITION_ENABLED", "").strip().lower()
    if speaker in ("true", "false"):
        defaults["speaker_recognition_enabled"] = speaker == "true"
    send = os.environ.get("SEND_ENABLED", "").strip().lower()
    if send in ("true", "false"):
        defaults["send_enabled"] = send == "true"

    provider = os.environ.get("TRANSCRIPTION_PROVIDER", "").strip()
    if provider:
        defaults["transcription_provider"] = provider

    speech_key = (
        os.environ.get("AZURE_SPEECH_KEY", "").strip()
        or os.environ.get("AZURE_SPEECH_API_KEY", "").strip()
        or os.environ.get("AZURE_TRANSCRIPTION_API_KEY", "").strip()
        or os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    )
    if speech_key:
        defaults["azure_transcription_api_key"] = speech_key

    speech_region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
    if speech_region:
        defaults["azure_speech_region"] = speech_region

    speech_endpoint = os.environ.get("AZURE_SPEECH_ENDPOINT", "").strip()
    if speech_endpoint:
        defaults["azure_speech_endpoint"] = speech_endpoint

    speech_api_version = os.environ.get("AZURE_SPEECH_API_VERSION", "").strip()
    if speech_api_version:
        defaults["azure_speech_api_version"] = speech_api_version

    speech_locales = os.environ.get("AZURE_SPEECH_LOCALES", "").strip()
    if speech_locales:
        defaults["azure_speech_locales"] = speech_locales

    max_speakers_raw = os.environ.get("AZURE_SPEECH_MAX_SPEAKERS", "").strip()
    if max_speakers_raw.isdigit() and int(max_speakers_raw) > 0:
        defaults["azure_speech_max_speakers"] = int(max_speakers_raw)

    llm_azure_endpoint = os.environ.get("LLM_AZURE_ENDPOINT", "").strip()
    if llm_azure_endpoint:
        defaults["llm_azure_endpoint"] = llm_azure_endpoint

    llm_azure_api_key = os.environ.get("LLM_AZURE_API_KEY", "").strip()
    if llm_azure_api_key:
        defaults["llm_azure_api_key"] = llm_azure_api_key

    llm_azure_api_version = os.environ.get("LLM_AZURE_API_VERSION", "").strip()
    if llm_azure_api_version:
        defaults["llm_azure_api_version"] = llm_azure_api_version

    return defaults


class RuntimeSettingsStore:
    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path or Path(__file__).resolve().parents[2] / "runtime_settings.json"

    def load(self) -> ModelSettings:
        defaults = _env_defaults()
        if not self.file_path.exists():
            return ModelSettings(**defaults)
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ModelSettings(**defaults)
        # JSON hat Vorrang – außer bei Strings: leere JSON-Werte werden durch Env-Defaults überschrieben
        merged = {**defaults, **payload}
        for key, env_val in defaults.items():
            if (
                isinstance(env_val, str)
                and env_val
                and isinstance(merged.get(key), str)
                and not merged[key].strip()
            ):
                merged[key] = env_val
        return ModelSettings.model_validate(merged)

    def save(self, settings: ModelSettings) -> ModelSettings:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            settings.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return settings

    def update(self, payload: ModelSettingsUpdate) -> ModelSettings:
        current = self.load()
        next_settings = current.model_copy(update=payload.model_dump(exclude_none=True))
        if next_settings.llm_provider == "azure_openai":
            if not next_settings.llm_azure_endpoint.strip():
                raise ValueError("Fuer Azure OpenAI LLM muss ein Azure-Endpoint gesetzt sein.")
            if not next_settings.llm_azure_api_key.strip():
                raise ValueError("Fuer Azure OpenAI LLM muss ein Bearer-Token oder API-Key gesetzt sein.")
            if not next_settings.llm_model.strip():
                raise ValueError("Fuer Azure OpenAI LLM muss eine Modell-ID bzw. ein Deployment gesetzt sein.")
        return self.save(next_settings)
