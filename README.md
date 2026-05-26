# Aurora Minutes

Aurora Minutes ist eine Meeting-App fuer Audioaufnahme, Transkription und automatische Minutes.
Transkription und LLM-Auswertung laufen ueber **Azure Speech** und **Azure OpenAI**. Lokale ML-Modelle (whisper, pyannote, llama-cpp) sind nicht enthalten – das Backend-Image ist schlank (~250 MB).

## Projektaufbau

- `backend/`: FastAPI-Service, leitet Audio an Azure Speech weiter und erzeugt Minutes via Azure OpenAI.
- `frontend/`: Statische Web-App mit Recorder, Upload, Minutes und Einstellungen.

## Lokaler Start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export AZURE_SPEECH_KEY="..."
export LLM_AZURE_API_KEY="..."
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

## Release & Auto-Update

Aurora Minutes nutzt einen **Registry-basierten Update-Flow**: Du baust lokal, pushst zu `ghcr.io`, und alle Remote-Deployments ziehen die neue Version automatisch per [Watchtower](https://containrrr.dev/watchtower/).

### Komponenten

- `RELEASE.json` (Repo-Root): Single Source of Truth für Versionsnummer, Datum und Changelog-Einträge (Icon + Text).
- `scripts/release.ps1`: Build- & Push-Skript für deinen Entwicklungs-Rechner.
- `.github/workflows/release.yml`: GitHub Actions Pipeline, baut & pusht automatisch bei `git tag v*.*.*`.
- `docker-compose.prod.yml`: Compose-Stack für Remote-Maschinen mit Watchtower-Service.
- Backend-Endpoint `GET /api/release/current`: liefert `RELEASE.json` aus dem Image.
- Frontend `release-popup.js`: zeigt einmalig pro Version ein Modal mit Confetti, dismiss wird in `localStorage` gespeichert.

### Workflow für ein neues Release

1. **Changelog editieren** – `RELEASE.json` anpassen:

   ```json
   {
     "version": "1.1.0",
     "date": "2026-06-01",
     "title": "Sprecher-Erkennung 2.0",
     "subtitle": "Bessere Trennung in Mehrpersonen-Meetings",
     "highlights": [
       { "icon": "mic", "text": "Verbesserte Sprechererkennung in lauten Räumen" },
       { "icon": "bug", "text": "Fix: Action-Item-Mails wurden doppelt versendet" },
       { "icon": "zap", "text": "Transkription jetzt 30 % schneller" }
     ]
   }
   ```

   Unterstützte Icon-Keys: `sparkles`, `rocket`, `bug`, `wrench`, `zap`, `lock`, `party`, `star`, `gear`, `chart`, `shield`, `speech`, `mic`, `cloud`, `docs`, `fire`. Alternativ kann auch ein Emoji direkt als `icon` angegeben werden (`"icon": "🎤"`).

2. **Lokal builden & pushen**:

   ```powershell
   # Einmalig: bei ghcr.io anmelden (PAT mit write:packages benötigt)
   $env:CR_PAT = "ghp_..."
   $env:CR_PAT | docker login ghcr.io -u michiwerkmann --password-stdin

   # Patch-Release inkl. Git-Tag
   ./scripts/release.ps1 -BumpVersion patch -Tag

   # Oder ohne Bump (RELEASE.json wurde manuell editiert)
   ./scripts/release.ps1
   ```

3. **Alternative: GitHub Actions** – einfach pushen und taggen, der Workflow baut automatisch:

   ```bash
   git add RELEASE.json
   git commit -m "release: 1.1.0"
   git tag v1.1.0
   git push origin master --tags
   ```

### Remote-Deployment einrichten

Auf jedem Zielrechner einmalig:

```bash
git clone <repo> aurora-minutes   # oder nur die Compose- und Proxy-Dateien kopieren
cd aurora-minutes
cp .env.prod.example .env.prod    # und Werte eintragen
docker login ghcr.io              # falls Image privat
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Ab da übernimmt Watchtower:

- Pollt `ghcr.io` alle `WATCHTOWER_POLL_INTERVAL` Sekunden (Default 300 = 5 min).
- Zieht `:latest`-Tags von `ai-meeting-backend` und `ai-meeting-frontend`.
- Recreate-Order respektiert den Healthcheck (`backend` muss gesund sein, bevor das Frontend ersetzt wird).
- Reverse-Proxy hat das Label `watchtower.enable=false` und bleibt stabil.

### Release-Popup-Verhalten

- Beim Laden der Webseite fragt das Frontend `/api/release/current`.
- Liegt die geantwortete `version` über der in `localStorage` (`aurora-last-seen-release-v1`) gespeicherten Version, erscheint das Modal mit Confetti-Kanone.
- Nach Klick auf **Verstanden** wird die Version weggespeichert → kein erneutes Popup bis zum nächsten Release.
- Im Dev-Mode (Backend findet keine `RELEASE.json` → `version = 0.0.0-dev`) wird das Popup übersprungen.

## Azure-Setup

### Transkription: Azure Speech

- `TRANSCRIPTION_PROVIDER=azure_speech`
- `AZURE_SPEECH_KEY=<key>`
- `AZURE_SPEECH_REGION=germanywestcentral` (oder anderer Endpoint/Region)
- `AZURE_SPEECH_ENDPOINT=https://<region>.api.cognitive.microsoft.com/` (optional, sonst aus Region abgeleitet)
- `AZURE_SPEECH_LOCALES` und `AZURE_SPEECH_MAX_SPEAKERS` optional

### Minutes-LLM: Azure OpenAI

- `LLM_PROVIDER=azure_openai`
- `LLM_AZURE_ENDPOINT=https://<resource>.openai.azure.com`
- `LLM_AZURE_API_KEY=<key>` (Bearer-Token oder roher API Key)
- `LLM_AZURE_API_VERSION=2025-01-01-preview`
- `LLM_MODEL=<deployment-oder-modell-id>`

### Optional: generische OpenAI-kompatible HTTP-API

Wenn du eine andere OpenAI-kompatible API nutzen willst (z. B. Ollama, ein Proxy, eine andere Cloud):

- `LLM_PROVIDER=http`
- `LLM_BASE_URL=https://...`
- `LLM_MODEL=<dein-modell>`
- optional `LLM_API_KEY`
- optional `LLM_COMPLETIONS_PATH=/v1/chat/completions`

## Wichtige Variablen

- `TRANSCRIPTION_PROVIDER`: `azure_speech` (Default)
- `LLM_PROVIDER`: `azure_openai` (Default) oder `http`
- `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` / `AZURE_SPEECH_ENDPOINT`
- `LLM_AZURE_ENDPOINT` / `LLM_AZURE_API_KEY` / `LLM_AZURE_API_VERSION` / `LLM_MODEL`
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_COMPLETIONS_PATH`: nur fuer HTTP-Modus
- `REVERSE_PROXY_PORT`: Host-Port fuer HTTPS-Reverse-Proxy (Default `9443`)
- `MEETING_WEBHOOK_URL`: Ziel-URL fuer serverseitiges Weiterleiten der Minutes
- `MEETING_WEBHOOK_TIMEOUT_SECONDS`: HTTP-Timeout fuer Webhook-Zustellung
- `MEETING_WEBHOOK_MAX_RETRIES`: Anzahl Zustellversuche bei Fehlern
- `MEETING_WEBHOOK_BACKOFF_SECONDS`: Backoff-Basis zwischen Retries
- `MEETING_WEBHOOK_VERIFY_TLS`: TLS-Pruefung (`true`/`false`)
- `MEETING_WEBHOOK_CA_CERT_PATH`: Optionaler CA-Pfad fuer TLS-Pruefung
- `ACTION_ITEM_EMAIL_ENABLED`: Action-Item-E-Mails aktivieren (`true`/`false`)
- `ACTION_ITEM_OWNER_EMAIL_MAP`: JSON-Mapping Owner -> E-Mail (z. B. `{"Dennis":"dennis@example.com"}`)
- `ACTION_ITEM_DEFAULT_EMAIL_DOMAIN`: Optionaler Fallback fuer Owner ohne Mapping
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: SMTP-Server fuer E-Mail-Versand
- `SMTP_FROM`, `SMTP_FROM_NAME`, `SMTP_USE_TLS`: Absender- und TLS-Konfiguration fuer Action-Item-E-Mails

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

- Ohne konfiguriertes LLM liefert das Backend heuristische Fallback-Minutes.
- Sprechertrennung kommt aus Azure Speech (`AZURE_SPEECH_MAX_SPEAKERS`), nicht aus pyannote.
- Weitere API-Details stehen in `backend/README_API.md`.
