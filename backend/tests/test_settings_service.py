from __future__ import annotations

import json
import uuid
from pathlib import Path

from backend.app.services.settings import RuntimeSettingsStore, _env_defaults


def test_env_defaults_accepts_azure_speech_api_key_alias(monkeypatch):
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.setenv("AZURE_SPEECH_API_KEY", "speech-key-from-alias")

    defaults = _env_defaults()

    assert defaults["azure_transcription_api_key"] == "speech-key-from-alias"


def test_runtime_settings_load_applies_env_defaults_without_settings_file(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "speech-key-from-env")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "germanywestcentral")

    test_dir = Path(__file__).resolve().parents[2] / "tmp" / f"settings-test-{uuid.uuid4().hex}"
    test_dir.mkdir(parents=True, exist_ok=True)
    settings_path = test_dir / "runtime_settings.json"
    store = RuntimeSettingsStore(file_path=settings_path)

    try:
        settings = store.load()
    finally:
        if settings_path.exists():
            settings_path.unlink()
        test_dir.rmdir()

    assert settings.azure_transcription_api_key == "speech-key-from-env"
    assert settings.azure_speech_region == "germanywestcentral"


def test_env_defaults_reads_llm_azure_fields(monkeypatch):
    monkeypatch.setenv("LLM_AZURE_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("LLM_AZURE_API_KEY", "llm-azure-key")
    monkeypatch.setenv("LLM_AZURE_API_VERSION", "2025-01-01-preview")

    defaults = _env_defaults()

    assert defaults["llm_azure_endpoint"] == "https://example.openai.azure.com"
    assert defaults["llm_azure_api_key"] == "llm-azure-key"
    assert defaults["llm_azure_api_version"] == "2025-01-01-preview"


def test_runtime_settings_load_overrides_empty_llm_fields_with_env(monkeypatch):
    monkeypatch.setenv("LLM_AZURE_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("LLM_AZURE_API_KEY", "llm-azure-key")
    monkeypatch.setenv("LLM_AZURE_API_VERSION", "2025-01-01-preview")

    test_dir = Path(__file__).resolve().parents[2] / "tmp" / f"settings-test-{uuid.uuid4().hex}"
    test_dir.mkdir(parents=True, exist_ok=True)
    settings_path = test_dir / "runtime_settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "llm_azure_endpoint": "",
                "llm_azure_api_key": "",
                "llm_azure_api_version": "",
            }
        ),
        encoding="utf-8",
    )
    store = RuntimeSettingsStore(file_path=settings_path)

    try:
        settings = store.load()
    finally:
        if settings_path.exists():
            settings_path.unlink()
        test_dir.rmdir()

    assert settings.llm_azure_endpoint == "https://example.openai.azure.com"
    assert settings.llm_azure_api_key == "llm-azure-key"
    assert settings.llm_azure_api_version == "2025-01-01-preview"
