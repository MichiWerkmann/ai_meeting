from __future__ import annotations

import json
from pathlib import Path

from ..schemas import ModelSettings, ModelSettingsUpdate


class RuntimeSettingsStore:
    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = file_path or Path(__file__).resolve().parents[2] / "runtime_settings.json"

    def load(self) -> ModelSettings:
        if not self.file_path.exists():
            return ModelSettings()
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ModelSettings()
        return ModelSettings.model_validate(payload)

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
