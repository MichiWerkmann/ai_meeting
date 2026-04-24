# Aurora Minutes

Aurora Minutes ist eine Meeting-App fuer lokale Audioaufnahme, Transkription, Sprechererkennung und automatische Minutes.
Der Standardpfad fuer LLM-Auswertung ist jetzt lokal ueber `llama-cpp-python` mit einem GGUF-Modell. HTTP-APIs sind optional.

## Projektaufbau

- `backend/`: FastAPI-Service mit Transkriptionspipeline und LLM-Anbindung.
- `frontend/`: Statische Web-App mit Recorder, Upload, Minutes und Einstellungen.
- `models/`: Lokale Modellverzeichnisse fuer WhisperX, Torch, Cache und GGUF-Dateien.

## Lokaler Start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYANNOTE_TOKEN="hf_..."
uvicorn app.main:app --reload
```

Danach das Frontend separat starten:

```bash
cd frontend
python -m http.server 3000
```

Die App ist dann unter `http://localhost:3000` erreichbar, das Backend unter `http://localhost:8000`.

## Docker-Deployment

Der Compose-Stack startet `backend`, `frontend` und zusaetzlich einen vorgeschalteten Nginx-Reverse-Proxy mit HTTPS. Es gibt keinen eingebauten Ollama-Dienst mehr.

```bash
docker compose up --build
```

- Reverse Proxy: `https://localhost:9443` (oder `https://localhost:${REVERSE_PROXY_PORT}`)
- Backend intern: `backend:8000`
- Frontend intern: `frontend:4173`

### Selbstsigniertes Zertifikat

Das Repository enthaelt ein selbstsigniertes Zertifikat fuer lokale Nutzung:

- Zertifikat: `proxy/certs/server.crt`
- Schluessel: `proxy/certs/server.key`
- OpenSSL-Konfiguration: `proxy/certs/openssl.cnf`

Beim ersten Aufruf im Browser erscheint eine Zertifikatswarnung, weil das Zertifikat nicht von einer oeffentlichen CA signiert ist. Fuer lokale Tests kannst du eine Ausnahme fuer `https://localhost:9443` hinterlegen oder das Zertifikat in den lokalen Trust Store importieren.

## LLM-Setup

### Standard: lokal per llama-cpp-python

Empfohlener Standard:

- `LLM_PROVIDER=llama_cpp`
- `LLM_MODEL=gemma-3-4b-it-qat`
- `LLM_LOCAL_MODEL_PATH=/app/models/llama_cpp/gemma3-4b/google_gemma-3-4b-it-qat-Q4_0.gguf`

Das GGUF-Modell kannst du direkt in der Einstellungsseite herunterladen. Nach dem Download wird der lokale Pfad automatisch in den Runtime-Settings gesetzt.

### Optional: Azure OpenAI Chat Completions

Wenn du dein Minutes-LLM direkt ueber Azure anbinden willst:

- `LLM_PROVIDER=azure_openai`
- `LLM_AZURE_ENDPOINT=https://<resource>.openai.azure.com`
- `LLM_AZURE_API_KEY=Bearer <token>` oder ein roher Azure API Key
- `LLM_AZURE_API_VERSION=2025-01-01-preview`
- `LLM_MODEL=<deployment-oder-modell-id>`

Das Feld `LLM_MODEL` entspricht in diesem Modus deiner Azure-Modell-ID bzw. deinem Deployment-Namen.

### Optional: externe HTTP-API

Wenn du statt lokalem `llama-cpp-python` eine generische OpenAI-kompatible API verwenden willst:

- `LLM_PROVIDER=http`
- `LLM_BASE_URL=https://...`
- `LLM_MODEL=<dein-modell>`
- optional `LLM_API_KEY`
- optional `LLM_COMPLETIONS_PATH=/v1/chat/completions`

Ollama ist damit nur noch ein optionaler Spezialfall einer OpenAI-kompatiblen HTTP-API, aber kein Teil des Standard-Setups mehr.

## Wichtige Variablen

- `WHISPER_MODEL`: `auto`, `small`, `medium`, `large-v3`
- `DIARIZATION_MODEL`: Standard `pyannote/speaker-diarization-3.1`
- `WHISPER_DEVICE`: `auto`, `cpu`, `cuda`
- `WHISPER_COMPUTE_TYPE`: optionaler Override fuer WhisperX
- `LLM_PROVIDER`: `llama_cpp`, `azure_openai` oder `http`
- `LLM_AZURE_ENDPOINT`: nur fuer Azure-OpenAI-LLM
- `LLM_AZURE_API_KEY`: Bearer-Token oder API Key fuer Azure-OpenAI-LLM
- `LLM_AZURE_API_VERSION`: API-Version fuer Azure-OpenAI-LLM
- `LLM_LOCAL_MODEL_PATH`: GGUF-Datei fuer lokalen Modus
- `LLM_LOCAL_CONTEXT_SIZE`: Kontextfenster fuer `llama-cpp-python`
- `LLM_LOCAL_GPU_LAYERS`: GPU-Offload fuer `llama-cpp-python`
- `LLM_BASE_URL`: nur fuer optionalen HTTP-Modus
- `LLM_MODEL`: Modellname fuer lokalen oder HTTP-Modus
- `LLM_API_KEY`: nur fuer geschuetzte HTTP-Endpunkte
- `LLM_COMPLETIONS_PATH`: nur fuer HTTP-Modus relevant
- `REVERSE_PROXY_PORT`: Host-Port fuer HTTPS-Reverse-Proxy (Default `9443`)
- `MEETING_WEBHOOK_URL`: Ziel-URL fuer serverseitiges Weiterleiten der Minutes
- `MEETING_WEBHOOK_TIMEOUT_SECONDS`: HTTP-Timeout fuer Webhook-Zustellung
- `MEETING_WEBHOOK_MAX_RETRIES`: Anzahl Zustellversuche bei Fehlern
- `MEETING_WEBHOOK_BACKOFF_SECONDS`: Backoff-Basis zwischen Retries
- `MEETING_WEBHOOK_VERIFY_TLS`: TLS-Pruefung (`true`/`false`)
- `MEETING_WEBHOOK_CA_CERT_PATH`: Optionaler CA-Pfad fuer TLS-Pruefung

## API-Endpunkte

- `GET /health`
- `GET /api/settings/models`
- `PUT /api/settings/models`
- `POST /api/settings/models/download`
- `GET /api/settings/models/download/{model_id}`
- `POST /api/transcribe`
- `POST /api/analyze`
- `POST /api/transcribe/diarize`
- `POST /api/minutes/evaluate`
- `POST /api/meetings/submit`
- `POST /api/meetings/forward`

## Hinweise

- Ohne konfiguriertes LLM liefert das Backend weiterhin heuristische Fallback-Minutes.
- Fuer Diarisierung bleibt `PYANNOTE_TOKEN` noetig.
- Weitere API-Details stehen in `backend/README_API.md`.
