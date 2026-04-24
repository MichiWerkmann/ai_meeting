# Aurora Minutes - API Referenz

Dieses Dokument beschreibt die HTTP-Endpunkte des FastAPI-Backends. Alle Aufrufe erfolgen gegen `http://<dein-host>:8000` (intern) oder via Reverse-Proxy z. B. `https://<dein-host>:4173`.

## Authentifizierung

Derzeit ist keine Authentifizierung aktiviert. Die API sollte deshalb nur in vertrauenswuerdigen Netzen oder hinter einem vorgeschalteten Zugriffsschutz betrieben werden.

## Standardkonfiguration

Der bevorzugte Standard ist jetzt:

- lokales `llama-cpp-python`
- lokales GGUF-Modell
- automatischer Modelldownload ueber die Einstellungs-API

Azure OpenAI Chat Completions ist verfuegbar, wenn `llm_provider=azure_openai` gesetzt ist.
Eine externe OpenAI-kompatible HTTP-API ist optional und wird verwendet, wenn `llm_provider=http` gesetzt ist.

## Endpunkte

### `GET /health`

Liefert Modell-, Hardware- und Laufzeitinformationen.

**Response 200**

```json
{
  "status": "ok",
  "whisper_model": "large-v3",
  "diarization_model": "pyannote/speaker-diarization-3.1",
  "summary_model": "gemma-3-4b-it-qat",
  "llm_model": "gemma-3-4b-it-qat",
  "device": "cpu",
  "gpu_available": false,
  "gpu_memory_gb": 0.0,
  "performance_tier": "low",
  "recommended_execution": "api",
  "performance_message": "Es wurde nur CPU-Verarbeitung erkannt. Fuer deutlich schnellere Ergebnisse ist ein Wechsel auf API-basierte Modelle empfehlenswert."
}
```

### `GET /api/settings/models`

Liefert die aktuellen Runtime-Einstellungen fuer Whisper, Diarisierung und LLM.

**Response 200**

```json
{
  "execution_device": "auto",
  "whisper_model": "auto",
  "diarization_model": "auto",
  "llm_provider": "llama_cpp",
  "llm_model": "gemma-3-4b-it-qat",
  "llm_azure_endpoint": "",
  "llm_azure_api_key": "",
  "llm_azure_api_version": "2025-01-01-preview",
  "llm_base_url": "",
  "llm_api_key": "",
  "llm_completions_path": "/v1/chat/completions",
  "llm_local_model_path": "C:/Users/Example/AppData/Local/AuroraMinutes/models/gemma3-4b/google_gemma-3-4b-it-qat-Q4_0.gguf",
  "llm_local_context_size": 262144,
  "llm_local_gpu_layers": 0,
  "summary_model": "gemma-3-4b-it-qat",
  "summary_llm_base_url": "",
  "summary_llm_api_key": "",
  "summary_llm_completions_path": ""
}
```

### `PUT /api/settings/models`

Aktualisiert die Runtime-Einstellungen.

**Request Body**

```json
{
  "llm_provider": "azure_openai",
  "llm_model": "gpt-4.1-mini",
  "llm_azure_endpoint": "https://example.openai.azure.com",
  "llm_azure_api_key": "Bearer <token>",
  "llm_azure_api_version": "2025-01-01-preview"
}
```

Wenn `llm_provider` auf `azure_openai` gesetzt wird, muessen `llm_azure_endpoint`, `llm_azure_api_key` und `llm_model` befuellt sein.
Wenn `llm_provider` auf `llama_cpp` gesetzt wird, muss `llm_local_model_path` befuellt sein. Andernfalls antwortet der Server mit `400`.

### `POST /api/settings/models/download`

Startet den Hintergrunddownload eines bekannten GGUF-Modells.

**Request Body**

```json
{
  "model_id": "gemma3_4b_gguf"
}
```

**Response 200**

```json
{
  "model_id": "gemma3_4b_gguf",
  "state": "running",
  "provider": "llama_cpp",
  "llm_model": "gemma-3-4b-it-qat",
  "llm_local_model_path": "C:/Users/Example/AppData/Local/AuroraMinutes/models/gemma3-4b/google_gemma-3-4b-it-qat-Q4_0.gguf",
  "bytes_downloaded": 0,
  "total_bytes": 0,
  "downloaded": false,
  "message": "Download wird vorbereitet ..."
}
```

### `GET /api/settings/models/download/{model_id}`

Liefert den aktuellen Downloadstatus. Nach erfolgreichem Abschluss wird das Modell automatisch als lokales Runtime-Modell aktiviert.

**Response 200**

```json
{
  "model_id": "gemma3_4b_gguf",
  "state": "completed",
  "provider": "llama_cpp",
  "llm_model": "gemma-3-4b-it-qat",
  "llm_local_model_path": "C:/Users/Example/AppData/Local/AuroraMinutes/models/gemma3-4b/google_gemma-3-4b-it-qat-Q4_0.gguf",
  "bytes_downloaded": 2540000000,
  "total_bytes": 2540000000,
  "downloaded": true,
  "message": "Modell heruntergeladen."
}
```

### `POST /api/transcribe`

Nimmt eine Audiodatei entgegen und liefert Transkript, Minutes, Sprecherprofile und Laufzeitmetadaten.

**Request**

- `multipart/form-data`
- Feld `audio`: Audiodatei
- optional `diarize`

```bash
curl -X POST \
  -F "audio=@/pfad/meeting.wav" \
  http://localhost:8000/api/transcribe
```

**Response 200**

```json
{
  "transcript": [
    {
      "speaker_id": "A",
      "speaker": "Speaker 1",
      "start": 0.0,
      "end": 8.4,
      "text": "Willkommen zur Sitzung ..."
    }
  ],
  "summary": "Kurze Executive Summary ...",
  "duration_seconds": 523.1,
  "minutes": {
    "summary": "...",
    "agenda": ["Budget", "Risiken"],
    "highlights": [],
    "decisions": [],
    "action_items": [],
    "risks": [],
    "sections": [
      {"title": "Kurzzusammenfassung", "entries": ["..."]},
      {"title": "Agenda", "entries": ["Budget", "Risiken"]},
      {"title": "Highlights", "entries": ["Keine Highlights vorhanden."]},
      {"title": "Entscheidungen", "entries": ["Keine Entscheidungen dokumentiert."]},
      {"title": "Action Items", "entries": ["Keine Action Items erfasst."]},
      {"title": "Risiken & offene Punkte", "entries": ["Keine Risiken oder offenen Punkte dokumentiert."]}
    ],
    "model": "gemma-3-4b-it-qat",
    "chunk_count": 1
  },
  "speakers": [
    {"speaker_id": "A", "label": "Speaker 1"}
  ],
  "session_id": "session-123"
}
```

### `POST /api/analyze`

Flexible API fuer externe Geraete. Liefert nur die angeforderten Teile.

**Query-Parameter**

- `include`
- `include_speakers`

**Request**

```bash
curl -X POST \
  -F "audio=@/pfad/meeting.wav" \
  "http://localhost:8000/api/analyze?include=summary&include=minutes&include_speakers=true"
```

### `POST /api/meetings`

Liefert direkt nur das `MeetingMinutes`-Objekt fuer eine hochgeladene Audiodatei.

### `POST /api/meetings/submit`

Nimmt Audio vom Sensor entgegen, erstellt Minutes und leitet das Ergebnis serverseitig an den konfigurierten Webhook weiter.

**Request**

- `multipart/form-data`
- Feld `audio`: Audiodatei
- Feld `room`: optional, Raumbezeichnung
- Feld `recorded_at`: optional, ISO-8601 UTC Timestamp (z. B. `2026-04-15T05:30:00Z`)
- optional `diarize`

```bash
curl -k -X POST \
  -F "audio=@/pfad/meeting.wav" \
  -F "room=E01-115 SWS" \
  -F "recorded_at=2026-04-15T05:30:00Z" \
  https://localhost:4173/api/meetings/submit
```

**Response 200 (Beispiel)**

```json
{
  "room": "E01-115 SWS",
  "recorded_at": "2026-04-15T05:30:00Z",
  "minutes": {
    "summary": "Kurze Executive Summary ...",
    "agenda": ["Budget", "Risiken"],
    "highlights": [],
    "decisions": [],
    "action_items": [],
    "risks": [],
    "sections": [],
    "model": "gemma-3-4b-it-qat",
    "chunk_count": 1
  },
  "webhook": {
    "delivered": true,
    "url": "https://example.local/webhook/meeting",
    "attempts": 1,
    "status_code": 200,
    "detail": "Webhook erfolgreich zugestellt."
  }
}
```

### `POST /api/meetings/forward`

Leitet bereits vorhandene Minutes serverseitig an den konfigurierten Webhook weiter (ohne erneute Audio-Transkription).

**Request Body**

```json
{
  "room": "E01-115 SWS",
  "recorded_at": "2026-04-15T05:30:00Z",
  "minutes": {
    "summary": "Kurze Executive Summary ...",
    "agenda": ["Budget", "Risiken"],
    "highlights": [],
    "decisions": [],
    "action_items": [],
    "risks": [],
    "sections": [],
    "model": "gemma-3-4b-it-qat",
    "chunk_count": 1
  }
}
```

**Response 200**

Die Response entspricht `POST /api/meetings/submit` und enthaelt `room`, `recorded_at`, `minutes` und den `webhook`-Status.

### `POST /api/minutes/evaluate`

Nimmt manuell eingegebene Segmente entgegen und liefert strukturierte Minutes sowie Zeilenklassifikationen.

**Request Body**

```json
{
  "segments": [
    {"speaker": "Moderator", "text": "Agenda Punkt A", "start": 0},
    {"speaker": "Team", "text": "Wir entscheiden X"}
  ]
}
```

## Hinweise

- Das lokale GGUF-Modell wird standardmaessig unter `%LOCALAPPDATA%\\AuroraMinutes\\models` gespeichert.
- Auf Linux wird stattdessen `XDG_DATA_HOME` oder `~/.local/share/AuroraMinutes/models` verwendet.
- Ohne konfiguriertes LLM erzeugt das Backend heuristische Fallback-Minutes.
- Fuer Diarisierung bleibt `PYANNOTE_TOKEN` erforderlich.
- Fuer `POST /api/meetings/submit` muss `MEETING_WEBHOOK_URL` im Backend gesetzt sein.
