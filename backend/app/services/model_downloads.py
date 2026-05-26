from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx


def hf_hub_url(repo_id: str, filename: str, revision: str = "main") -> str:
    """Build a direct Hugging Face download URL without huggingface_hub dependency."""
    return f"https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"


@dataclass(frozen=True)
class DownloadableModel:
    model_id: str
    provider: str
    llm_model: str
    repo_id: str
    filename: str
    target_subdir: str


@dataclass
class DownloadStatus:
    model_id: str
    state: str = "idle"
    message: str = ""
    provider: str = ""
    llm_model: str = ""
    llm_local_model_path: str = ""
    bytes_downloaded: int = 0
    total_bytes: int = 0


DEFAULT_MODELS: dict[str, DownloadableModel] = {
    "gemma3_4b_gguf": DownloadableModel(
        model_id="gemma3_4b_gguf",
        provider="http",
        llm_model="gemma-3-4b-it-qat",
        repo_id="bartowski/google_gemma-3-4b-it-qat-GGUF",
        filename="google_gemma-3-4b-it-qat-Q4_0.gguf",
        target_subdir="gemma3-4b",
    )
}


class ModelDownloadService:
    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = self._default_base_dir()
        self.base_dir = base_dir
        self._lock = threading.Lock()
        self._status_by_model_id: dict[str, DownloadStatus] = {}

    def start_download(self, model_id: str) -> DownloadStatus:
        model = self._get_model(model_id)
        target_path = self._target_path(model)

        with self._lock:
            current = self._status_by_model_id.get(model_id)
            if current and current.state == "running":
                return current
            if target_path.exists():
                status = DownloadStatus(
                    model_id=model.model_id,
                    state="completed",
                    message="Modell ist bereits vorhanden.",
                    provider=model.provider,
                    llm_model=model.llm_model,
                    llm_local_model_path=str(target_path),
                    bytes_downloaded=target_path.stat().st_size,
                    total_bytes=target_path.stat().st_size,
                )
                self._status_by_model_id[model_id] = status
                return status

            status = DownloadStatus(
                model_id=model.model_id,
                state="running",
                message="Download wird vorbereitet ...",
                provider=model.provider,
                llm_model=model.llm_model,
                llm_local_model_path=str(target_path),
            )
            self._status_by_model_id[model_id] = status

        worker = threading.Thread(
            target=self._download_worker,
            args=(model,),
            daemon=True,
            name=f"model-download-{model.model_id}",
        )
        worker.start()
        return status

    def get_status(self, model_id: str) -> DownloadStatus:
        model = self._get_model(model_id)
        target_path = self._target_path(model)
        with self._lock:
            status = self._status_by_model_id.get(model_id)
            if status is not None:
                return status
        if target_path.exists():
            return DownloadStatus(
                model_id=model.model_id,
                state="completed",
                message="Modell ist bereits vorhanden.",
                provider=model.provider,
                llm_model=model.llm_model,
                llm_local_model_path=str(target_path),
                bytes_downloaded=target_path.stat().st_size,
                total_bytes=target_path.stat().st_size,
            )
        return DownloadStatus(
            model_id=model.model_id,
            state="idle",
            message="Noch kein Download gestartet.",
            provider=model.provider,
            llm_model=model.llm_model,
            llm_local_model_path=str(target_path),
        )

    def _download_worker(self, model: DownloadableModel) -> None:
        target_path = self._target_path(model)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(target_path.suffix + ".part")
        url = hf_hub_url(repo_id=model.repo_id, filename=model.filename)

        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=None) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or "0")
                self._update_status(
                    model.model_id,
                    state="running",
                    message="Download laeuft ...",
                    total_bytes=total,
                    bytes_downloaded=0,
                )
                downloaded = 0
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        self._update_status(
                            model.model_id,
                            state="running",
                            message="Download laeuft ...",
                            total_bytes=total,
                            bytes_downloaded=downloaded,
                        )
            temp_path.replace(target_path)
            final_size = target_path.stat().st_size
            self._update_status(
                model.model_id,
                state="completed",
                message="Modell heruntergeladen.",
                total_bytes=final_size,
                bytes_downloaded=final_size,
            )
        except Exception as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._update_status(
                model.model_id,
                state="failed",
                message=f"Download fehlgeschlagen: {exc}",
            )

    def _update_status(self, model_id: str, **updates: object) -> None:
        with self._lock:
            status = self._status_by_model_id[model_id]
            for key, value in updates.items():
                setattr(status, key, value)

    def _get_model(self, model_id: str) -> DownloadableModel:
        model = DEFAULT_MODELS.get(model_id)
        if model is None:
            raise ValueError(f"Unbekanntes Download-Modell: {model_id}")
        return model

    def _target_path(self, model: DownloadableModel) -> Path:
        return self.base_dir / model.target_subdir / model.filename

    @staticmethod
    def _default_base_dir() -> Path:
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "AuroraMinutes" / "models"
        xdg_data_home = os.getenv("XDG_DATA_HOME")
        if xdg_data_home:
            return Path(xdg_data_home) / "AuroraMinutes" / "models"
        return Path.home() / ".local" / "share" / "AuroraMinutes" / "models"
