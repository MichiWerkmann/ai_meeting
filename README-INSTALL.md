# Aurora Minutes – Installationsanleitung

Zwei Installationswege stehen zur Wahl: **Docker** (empfohlen, portabel) oder **Windows nativ** (kein Docker erforderlich).

---

## Variante A – Docker

### Voraussetzungen

- [Docker Desktop für Windows](https://www.docker.com/products/docker-desktop/) installiert und gestartet
- Für GPU-Beschleunigung: NVIDIA-Treiber + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### Schritt 1 – Konfiguration

```bat
copy .env.example .env
notepad .env
```

Mindestens eintragen: `PYANNOTE_TOKEN`, `LLM_AZURE_API_KEY` oder andere LLM-Zugangsdaten.

### Schritt 2 – SSL-Zertifikate (einmalig)

```bat
cd proxy\certs
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout server.key -out server.crt -subj "/CN=localhost"
cd ..\..
```

> Git für Windows enthält OpenSSL. Alternativ: Zertifikate manuell erzeugen und hier ablegen.

### Schritt 3 – Starten

**Mit NVIDIA-GPU:**
```bat
docker compose -f docker-compose.gpu.yml up -d
```

**Ohne GPU (CPU-only):**
```bat
docker compose -f docker-compose.cpu.yml up -d
```

**Original (bisherige Datei, GPU mit optionalem Fallback):**
```bat
docker compose up -d
```

Die App ist erreichbar unter: **https://localhost:4173**

> Der Browser zeigt eine Zertifikatswarnung (selbstsigniert) – einmalig bestätigen.

### Befehle

```bat
# Status prüfen
docker compose -f docker-compose.gpu.yml ps

# Logs anzeigen
docker compose -f docker-compose.gpu.yml logs -f backend

# Stoppen
docker compose -f docker-compose.gpu.yml down

# Neu bauen (nach Code-Änderungen)
docker compose -f docker-compose.gpu.yml build --no-cache
docker compose -f docker-compose.gpu.yml up -d
```

### Docker-Dateien Übersicht

| Datei | Beschreibung |
|---|---|
| `docker-compose.gpu.yml` | NVIDIA GPU, CUDA-Backend |
| `docker-compose.cpu.yml` | CPU-only, kein NVIDIA erforderlich |
| `docker-compose.yml` | Original (GPU, wie bisher) |
| `backend/Dockerfile` | Backend-Image mit CUDA |
| `backend/Dockerfile.cpu` | Backend-Image ohne CUDA (~2 GB kleiner) |

---

## Variante B – Windows nativ (ohne Docker)

### Voraussetzungen

- Windows 10/11 (64-bit)
- Internetverbindung für den ersten Download

Der Installer prüft und installiert fehlende Abhängigkeiten automatisch via `winget`.

### Schritt 1 – Installer ausführen

PowerShell als **normaler Benutzer** öffnen:

```powershell
cd "C:\Pfad\zu\ai_meeting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install-windows.ps1
```

Mit automatischem **Windows-Dienst** (Autostart, als Administrator):

```powershell
.\install-windows.ps1 -InstallService
```

Der Installer erledigt automatisch:
- Python 3.11 prüfen/installieren
- FFmpeg prüfen/installieren
- Virtuelle Python-Umgebung anlegen (`.venv`)
- Alle Pakete installieren (PyTorch CPU + Backend-Abhängigkeiten)
- `.env` aus `.env.example` erstellen
- SSL-Zertifikate generieren
- `start.bat`, `stop.bat`, `start-aurora.ps1`, `stop-aurora.ps1` erstellen

### Schritt 2 – Konfiguration anpassen

```bat
notepad .env
```

### Schritt 3 – Starten

```bat
start.bat
```

Oder in PowerShell mit Statusanzeige:

```powershell
.\start-aurora.ps1
```

Die App ist erreichbar unter: **http://localhost:3000**  
Backend API (Swagger): **http://localhost:8000/docs**

### Stoppen

```bat
stop.bat
```

```powershell
.\stop-aurora.ps1
```

### Installer-Optionen

```powershell
# Übersicht aller Optionen
Get-Help .\install-windows.ps1 -Detailed

# Neu installieren (überschreibt .venv)
.\install-windows.ps1 -Force

# Ohne Abhängigkeits-Check (schneller, wenn alles schon installiert)
.\install-windows.ps1 -SkipDependencyCheck

# Anderen Port (Standard: 4173 für Docker, 3000 für nativ)
.\install-windows.ps1 -Port 8080

# Windows-Dienste (Autostart) registrieren
.\install-windows.ps1 -InstallService
```

---

## Konfiguration (.env)

Die wichtigsten Einstellungen:

| Variable | Beschreibung | Beispiel |
|---|---|---|
| `PYANNOTE_TOKEN` | Hugging Face Token für Sprechertrennung | `hf_abc...` |
| `LLM_PROVIDER` | LLM-Backend | `azure_openai`, `http`, `llama_cpp` |
| `LLM_AZURE_ENDPOINT` | Azure OpenAI Endpunkt | `https://xxx.openai.azure.com` |
| `LLM_AZURE_API_KEY` | Azure API-Key | `Bearer ...` |
| `MEETING_WEBHOOK_URL` | Ziel-URL für Minutes-Versand | `https://...` |
| `WHISPER_MODEL` | Transkriptionsmodell | `turbo`, `large-v3` |
| `REVERSE_PROXY_PORT` | Browser-Port (Docker) | `4173` |

Vollständige Beschreibung aller Variablen: `.env.example`

---

## Modellverzeichnisse

Modelle werden beim ersten Start automatisch heruntergeladen und gecacht:

```
models/
├── huggingface/    # Whisper, pyannote-Modelle (~2–8 GB)
├── torch/          # PyTorch-Cache
├── cache/          # Allgemeiner Cache
└── llama_cpp/      # Lokale GGUF-Modelle (optional)
```

> Beim ersten Start kann es 5–15 Minuten dauern, bis alle Modelle geladen sind.

---

## Ports

| Service | Docker | Windows nativ |
|---|---|---|
| Browser (App) | https://localhost:4173 | http://localhost:3000 |
| Backend API | intern (via Proxy) | http://localhost:8000 |
| API-Docs | https://localhost:4173/docs | http://localhost:8000/docs |
