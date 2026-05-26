#Requires -Version 5.1
<#
.SYNOPSIS
    Aurora Minutes – Windows Installer (Native, ohne Docker)

.DESCRIPTION
    Installiert Aurora Minutes direkt auf Windows:
    - Prüft und installiert Abhängigkeiten (Python 3.11, FFmpeg, Git)
    - Richtet eine virtuelle Python-Umgebung ein
    - Installiert alle Backend-Pakete
    - Erstellt .env aus .env.example (falls noch nicht vorhanden)
    - Generiert SSL-Zertifikate für HTTPS
    - Legt Windows-Startskripte an (start.bat, stop.bat)
    - Optional: Registriert Windows-Dienste via NSSM

.NOTES
    Als Administrator ausführen empfohlen (für Dienst-Registrierung).
    Ohne Admin-Rechte funktioniert alles außer der Dienst-Registrierung.

.EXAMPLE
    # Einfache Installation
    .\install-windows.ps1

    # Installation mit automatischer Dienst-Registrierung
    .\install-windows.ps1 -InstallService

    # Installation mit benutzerdefiniertem Port
    .\install-windows.ps1 -Port 8443
#>

param(
    [switch]$InstallService,
    [int]$Port = 4173,
    [switch]$SkipDependencyCheck,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Farben & Hilfsfunktionen ─────────────────────────────────────────────────

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host ">> $Text" -ForegroundColor Yellow
}

function Write-OK {
    param([string]$Text)
    Write-Host "   [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "   [!]  $Text" -ForegroundColor Magenta
}

function Write-Fail {
    param([string]$Text)
    Write-Host "   [X]  $Text" -ForegroundColor Red
}

function Confirm-Continue {
    param([string]$Question)
    $answer = Read-Host "$Question [j/N]"
    return ($answer -match "^[jJyY]")
}

# ─── Pfade ───────────────────────────────────────────────────────────────────

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$ProxyDir    = Join-Path $ScriptDir "proxy"
$ModelsDir   = Join-Path $ScriptDir "models"
$VenvDir     = Join-Path $ScriptDir ".venv"
$EnvFile     = Join-Path $ScriptDir ".env"
$EnvExample  = Join-Path $ScriptDir ".env.example"
$LogDir      = Join-Path $ScriptDir "logs"

# ─── Banner ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ___                             " -ForegroundColor Cyan
Write-Host " / _ \  _   _  _ __  ___   _ __ ___ " -ForegroundColor Cyan
Write-Host "| | | || | | || '__|/ _ \ | '__/ _  |" -ForegroundColor Cyan
Write-Host "| |_| || |_| || |  | (_) || | | (_| |" -ForegroundColor Cyan
Write-Host " \__\_\ \__,_||_|   \___/ |_|  \__,_|" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Aurora Minutes – Windows Installer" -ForegroundColor White
Write-Host "  Natives Setup (ohne Docker)" -ForegroundColor Gray
Write-Host ""

# ─── Admin-Check ──────────────────────────────────────────────────────────────

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $IsAdmin) {
    Write-Warn "Nicht als Administrator gestartet."
    Write-Warn "Dienst-Registrierung (NSSM) steht nicht zur Verfügung."
    Write-Warn "Alle anderen Schritte funktionieren ohne Admin-Rechte."
    if ($InstallService) {
        Write-Fail "Mit -InstallService ist Admin-Modus erforderlich. Bitte neu starten als Administrator."
        exit 1
    }
}

# ─── 1. Abhängigkeiten prüfen ─────────────────────────────────────────────────

Write-Header "Schritt 1/6 – Abhängigkeiten prüfen"

if (-not $SkipDependencyCheck) {

    # Python 3.11+
    Write-Step "Python prüfen"
    $pythonCmd = $null
    foreach ($cmd in @("python3.11", "python3", "python")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python 3\.(1[1-9]|[2-9]\d)") {
                $pythonCmd = $cmd
                Write-OK "$ver gefunden ($cmd)"
                break
            }
        } catch {}
    }

    if (-not $pythonCmd) {
        Write-Fail "Python 3.11+ nicht gefunden."
        Write-Host ""
        Write-Host "  Bitte Python 3.11 installieren:" -ForegroundColor White
        Write-Host "  https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host "  Wichtig: 'Add Python to PATH' ankreuzen!" -ForegroundColor Yellow
        Write-Host ""
        if (Confirm-Continue "Jetzt Python automatisch via winget installieren?") {
            Write-Step "Installiere Python 3.11 via winget..."
            winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
            $pythonCmd = "python"
            Write-OK "Python installiert. Bitte Terminal neu starten und Skript erneut ausführen."
            exit 0
        }
        exit 1
    }

    # Git
    Write-Step "Git prüfen"
    try {
        $gitVer = & git --version 2>&1
        Write-OK "$gitVer"
    } catch {
        Write-Warn "Git nicht gefunden."
        if (Confirm-Continue "Git via winget installieren?") {
            winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
        }
    }

    # FFmpeg
    Write-Step "FFmpeg prüfen"
    try {
        $ffVer = & ffmpeg -version 2>&1 | Select-String "ffmpeg version" | Select-Object -First 1
        Write-OK $ffVer
    } catch {
        Write-Warn "FFmpeg nicht gefunden."
        Write-Host ""
        Write-Host "  FFmpeg wird für Audiotranskription benötigt." -ForegroundColor White
        Write-Host "  Option A: winget install -e --id Gyan.FFmpeg" -ForegroundColor Cyan
        Write-Host "  Option B: https://ffmpeg.org/download.html" -ForegroundColor Cyan
        if (Confirm-Continue "FFmpeg jetzt via winget installieren?") {
            winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        } else {
            Write-Warn "FFmpeg wird später benötigt – bitte manuell installieren."
        }
    }

    # OpenSSL (für Zertifikate)
    Write-Step "OpenSSL prüfen"
    try {
        $sslVer = & openssl version 2>&1
        Write-OK $sslVer
    } catch {
        Write-Warn "OpenSSL nicht im PATH. Zertifikat-Generierung wird übersprungen."
        Write-Warn "Git for Windows enthält OpenSSL – nach Git-Installation neu starten."
    }

} else {
    Write-Warn "Abhängigkeits-Check übersprungen (-SkipDependencyCheck)"
    $pythonCmd = "python"
}

# ─── 2. Verzeichnisse anlegen ─────────────────────────────────────────────────

Write-Header "Schritt 2/6 – Verzeichnisse anlegen"

$dirs = @(
    (Join-Path $ModelsDir "huggingface"),
    (Join-Path $ModelsDir "torch"),
    (Join-Path $ModelsDir "cache"),
    (Join-Path $ModelsDir "llama_cpp"),
    (Join-Path $ProxyDir "certs"),
    $LogDir
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-OK "Erstellt: $dir"
    } else {
        Write-OK "Vorhanden: $dir"
    }
}

# ─── 3. Virtuelle Umgebung & Python-Pakete ────────────────────────────────────

Write-Header "Schritt 3/6 – Python-Umgebung einrichten"

Write-Step "Virtuelle Umgebung erstellen"
if ((Test-Path $VenvDir) -and -not $Force) {
    Write-OK "Virtuelle Umgebung bereits vorhanden ($VenvDir)"
} else {
    if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
    & $pythonCmd -m venv $VenvDir
    Write-OK "Virtuelle Umgebung erstellt"
}

$PythonVenv = Join-Path $VenvDir "Scripts\python.exe"
$PipVenv    = Join-Path $VenvDir "Scripts\pip.exe"

Write-Step "pip aktualisieren"
& $PythonVenv -m pip install --upgrade pip --quiet
Write-OK "pip aktualisiert"

Write-Step "PyTorch CPU-Version installieren"
Write-Host "   (CPU-only; für GPU-Support siehe install-windows.ps1 --help)" -ForegroundColor Gray
& $PipVenv install torch==2.2.2 torchaudio==2.2.2 `
    --index-url https://download.pytorch.org/whl/cpu `
    --quiet
Write-OK "PyTorch (CPU) installiert"

Write-Step "Backend-Abhängigkeiten installieren"
Write-Host "   Das kann einige Minuten dauern (pyannote, whisperx etc.) ..." -ForegroundColor Gray
$reqFile = Join-Path $BackendDir "requirements.txt"
& $PipVenv install -r $reqFile --quiet
Write-OK "Alle Backend-Pakete installiert"

# ─── 4. .env konfigurieren ────────────────────────────────────────────────────

Write-Header "Schritt 4/6 – Konfiguration (.env)"

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-OK ".env aus .env.example erstellt"
    } else {
        # Minimale .env anlegen
        @"
WHISPER_MODEL=turbo
WHISPER_BATCH_SIZE=4
DIARIZATION_MODEL=auto
SUMMARY_MODEL=gpt-4.1-mini
PYANNOTE_TOKEN=
LLM_PROVIDER=azure_openai
LLM_MODEL=gpt-4.1-mini
LLM_AZURE_ENDPOINT=
LLM_AZURE_API_KEY=
LLM_AZURE_API_VERSION=2025-01-01-preview
LLM_BASE_URL=
LLM_API_KEY=
LLM_COMPLETIONS_PATH=/v1/chat/completions
LLM_LOCAL_MODEL_PATH=
LLM_LOCAL_CONTEXT_SIZE=8192
LLM_LOCAL_GPU_LAYERS=0
MEETING_WEBHOOK_URL=
MEETING_WEBHOOK_TIMEOUT_SECONDS=20
MEETING_WEBHOOK_MAX_RETRIES=3
MEETING_WEBHOOK_BACKOFF_SECONDS=1
MEETING_WEBHOOK_VERIFY_TLS=true
MEETING_WEBHOOK_CA_CERT_PATH=
REVERSE_PROXY_PORT=$Port
API_BASE_URL=
API_PORT=8000
TRANSCRIPTION_MAX_CONCURRENT_JOBS=1
"@ | Set-Content $EnvFile -Encoding UTF8
        Write-OK "Minimale .env erstellt"
    }
    Write-Warn "Bitte .env anpassen (API-Keys, Webhook-URL etc.):"
    Write-Warn "  notepad `"$EnvFile`""
} else {
    Write-OK ".env bereits vorhanden – wird nicht überschrieben"
}

# ─── 5. SSL-Zertifikate ───────────────────────────────────────────────────────

Write-Header "Schritt 5/6 – SSL-Zertifikate"

$CertFile = Join-Path $ProxyDir "certs\server.crt"
$KeyFile  = Join-Path $ProxyDir "certs\server.key"

if ((Test-Path $CertFile) -and (Test-Path $KeyFile) -and -not $Force) {
    Write-OK "Zertifikate bereits vorhanden"
} else {
    try {
        $opensslAvail = & openssl version 2>&1
        Write-Step "Selbstsigniertes Zertifikat erstellen (openssl)"

        $opensslCfg = @"
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
x509_extensions    = v3_req

[dn]
C=DE
ST=Bayern
L=Rosenheim
O=Aurora Minutes
CN=localhost

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = 127.0.0.1
IP.1  = 127.0.0.1
"@
        $cfgPath = Join-Path $env:TEMP "aurora-openssl.cnf"
        $opensslCfg | Set-Content $cfgPath -Encoding ASCII

        & openssl req -x509 -nodes -days 3650 `
            -newkey rsa:2048 `
            -keyout $KeyFile `
            -out $CertFile `
            -config $cfgPath 2>&1 | Out-Null

        Remove-Item $cfgPath -Force
        Write-OK "Zertifikat erstellt (gültig 10 Jahre): $CertFile"

    } catch {
        Write-Warn "OpenSSL nicht verfügbar – Zertifikate können nicht erstellt werden."
        Write-Warn "Für HTTPS bitte manuell Zertifikate in $ProxyDir\certs ablegen:"
        Write-Warn "  server.crt  und  server.key"
        Write-Warn "Alternativ: Git für Windows installieren, dann openssl verfügbar."
    }
}

# ─── 6. Start/Stop-Skripte erstellen ─────────────────────────────────────────

Write-Header "Schritt 6/6 – Startskripte erstellen"

# start.bat
$StartBat = Join-Path $ScriptDir "start.bat"
@"
@echo off
setlocal

echo.
echo  Aurora Minutes starten ...
echo.

cd /d "%~dp0"

REM .env laden
for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" (
        set "%%A=%%B"
    )
)

REM Verzeichnisse
set VENV_PYTHON=%~dp0.venv\Scripts\python.exe
set BACKEND_DIR=%~dp0backend
set FRONTEND_DIR=%~dp0frontend
set LOG_DIR=%~dp0logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Backend starten
echo [1/2] Backend starten (Port 8000) ...
set HF_HOME=%~dp0models\huggingface
set HUGGINGFACE_HUB_CACHE=%~dp0models\huggingface\hub
set TRANSFORMERS_CACHE=%~dp0models\huggingface\transformers
set TORCH_HOME=%~dp0models\torch
set XDG_CACHE_HOME=%~dp0models\cache

start "Aurora Backend" /min cmd /c "cd /d "%BACKEND_DIR%" && "%VENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log > "%LOG_DIR%\backend.log" 2>&1"

REM Kurz warten bis Backend bereit
echo    Warte auf Backend ...
timeout /t 5 /nobreak > nul

REM Frontend-config.js schreiben
echo window.__APP_CONFIG__ = window.__APP_CONFIG__ ^|^| {}; > "%FRONTEND_DIR%\config.js"
echo window.__APP_CONFIG__.API_BASE_URL = "http://localhost:8000"; >> "%FRONTEND_DIR%\config.js"
echo window.__APP_CONFIG__.API_PORT = "8000"; >> "%FRONTEND_DIR%\config.js"

REM Frontend starten
echo [2/2] Frontend starten (Port 3000) ...
start "Aurora Frontend" /min cmd /c "cd /d "%FRONTEND_DIR%" && "%VENV_PYTHON%" -m http.server 3000 > "%LOG_DIR%\frontend.log" 2>&1"

timeout /t 2 /nobreak > nul

echo.
echo  ============================================================
echo   Aurora Minutes laeuft!
echo   Browser oeffnen: http://localhost:3000
echo   Backend API:     http://localhost:8000
echo   Logs:            %LOG_DIR%
echo  ============================================================
echo.

start http://localhost:3000

echo  [Fenster offen lassen oder stop.bat ausfuehren zum Beenden]
pause
"@ | Set-Content $StartBat -Encoding ASCII
Write-OK "start.bat erstellt"

# stop.bat
$StopBat = Join-Path $ScriptDir "stop.bat"
@"
@echo off
echo.
echo  Aurora Minutes wird beendet ...
echo.

taskkill /FI "WindowTitle eq Aurora Backend*" /F >nul 2>&1
taskkill /FI "WindowTitle eq Aurora Frontend*" /F >nul 2>&1

REM Fallback: Port-basiert beenden
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| find ":3000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo  Aurora Minutes beendet.
echo.
pause
"@ | Set-Content $StopBat -Encoding ASCII
Write-OK "stop.bat erstellt"

# PowerShell-Startskript (mit Statusanzeige)
$StartPs1 = Join-Path $ScriptDir "start-aurora.ps1"
@'
#Requires -Version 5.1
<#
.SYNOPSIS
    Aurora Minutes starten (PowerShell-Version mit Statusanzeige)
#>

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython  = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$BackendDir  = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"
$LogDir      = Join-Path $ScriptDir "logs"
$EnvFile     = Join-Path $ScriptDir ".env"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# .env lesen
$env:HF_HOME                   = Join-Path $ScriptDir "models\huggingface"
$env:HUGGINGFACE_HUB_CACHE     = Join-Path $ScriptDir "models\huggingface\hub"
$env:TRANSFORMERS_CACHE        = Join-Path $ScriptDir "models\huggingface\transformers"
$env:TORCH_HOME                = Join-Path $ScriptDir "models\torch"
$env:XDG_CACHE_HOME            = Join-Path $ScriptDir "models\cache"

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#=]+?)\s*=\s*(.*)\s*$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
        }
    }
}

Write-Host ""
Write-Host "  Aurora Minutes wird gestartet ..." -ForegroundColor Cyan
Write-Host ""

# Frontend config.js schreiben
@"
window.__APP_CONFIG__ = window.__APP_CONFIG__ || {};
window.__APP_CONFIG__.API_BASE_URL = "http://localhost:8000";
window.__APP_CONFIG__.API_PORT = "8000";
"@ | Set-Content (Join-Path $FrontendDir "config.js") -Encoding UTF8

# Backend starten
Write-Host "  [1/2] Backend starten ..." -ForegroundColor Yellow
$backendLog = Join-Path $LogDir "backend.log"
$backend = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log" `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError (Join-Path $LogDir "backend-err.log") `
    -PassThru -WindowStyle Hidden

Write-Host "       PID: $($backend.Id)" -ForegroundColor Gray

# Warten bis Backend antwortet
Write-Host "  [?] Warte auf Backend (bis 30s) ..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Write-Host "       ." -NoNewline -ForegroundColor Gray
}
Write-Host ""

if (-not $ready) {
    Write-Host "  [!] Backend antwortet nicht – Logs prüfen: $backendLog" -ForegroundColor Red
}

# Frontend starten
Write-Host "  [2/2] Frontend starten ..." -ForegroundColor Yellow
$frontendLog = Join-Path $LogDir "frontend.log"
$frontend = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "http.server", "3000" `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $frontendLog `
    -RedirectStandardError (Join-Path $LogDir "frontend-err.log") `
    -PassThru -WindowStyle Hidden

Write-Host "       PID: $($frontend.Id)" -ForegroundColor Gray
Start-Sleep -Seconds 1

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "   Aurora Minutes laeuft!" -ForegroundColor Green
Write-Host "   Browser:  http://localhost:3000" -ForegroundColor White
Write-Host "   Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "   Logs:     $LogDir" -ForegroundColor Gray
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

# PIDs speichern fuer stop-aurora.ps1
@{ Backend = $backend.Id; Frontend = $frontend.Id } |
    ConvertTo-Json | Set-Content (Join-Path $ScriptDir ".aurora-pids.json") -Encoding UTF8

Start-Process "http://localhost:3000"

Write-Host "  Druecke ENTER zum Beenden (Prozesse laufen im Hintergrund weiter)" -ForegroundColor Gray
Read-Host | Out-Null
'@ | Set-Content $StartPs1 -Encoding UTF8
Write-OK "start-aurora.ps1 erstellt"

# stop-aurora.ps1
$StopPs1 = Join-Path $ScriptDir "stop-aurora.ps1"
@'
#Requires -Version 5.1
<#
.SYNOPSIS
    Aurora Minutes beenden
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile   = Join-Path $ScriptDir ".aurora-pids.json"

Write-Host ""
Write-Host "  Aurora Minutes wird beendet ..." -ForegroundColor Yellow

if (Test-Path $PidFile) {
    $pids = Get-Content $PidFile | ConvertFrom-Json
    foreach ($pid in @($pids.Backend, $pids.Frontend)) {
        if ($pid) {
            try {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "  Prozess $pid beendet." -ForegroundColor Green
            } catch {}
        }
    }
    Remove-Item $PidFile -Force
} else {
    # Fallback: Port-basiert
    foreach ($port in @(8000, 3000)) {
        $procs = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
                 Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $procs) {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Write-Host "  Prozess auf Port $port (PID $pid) beendet." -ForegroundColor Green
        }
    }
}

Write-Host "  Aurora Minutes gestoppt." -ForegroundColor Green
Write-Host ""
'@ | Set-Content $StopPs1 -Encoding UTF8
Write-OK "stop-aurora.ps1 erstellt"

# ─── Optional: NSSM Dienst-Registrierung ──────────────────────────────────────

if ($InstallService -and $IsAdmin) {
    Write-Header "Optional – Windows-Dienste via NSSM"

    $nssmPath = (Get-Command nssm -ErrorAction SilentlyContinue)?.Source
    if (-not $nssmPath) {
        Write-Warn "NSSM nicht gefunden. Installationsversuch via winget..."
        try {
            winget install -e --id NSSM.NSSM --accept-package-agreements --accept-source-agreements
            $nssmPath = (Get-Command nssm -ErrorAction SilentlyContinue)?.Source
        } catch {}
    }

    if ($nssmPath) {
        Write-Step "Backend als Windows-Dienst registrieren"
        & $nssmPath install AuroraBackend $VenvDir\Scripts\python.exe
        & $nssmPath set AuroraBackend AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log"
        & $nssmPath set AuroraBackend AppDirectory $BackendDir
        & $nssmPath set AuroraBackend AppStdout (Join-Path $LogDir "backend.log")
        & $nssmPath set AuroraBackend AppStderr (Join-Path $LogDir "backend-err.log")
        & $nssmPath set AuroraBackend Start SERVICE_AUTO_START
        & $nssmPath set AuroraBackend DisplayName "Aurora Minutes Backend"
        & $nssmPath set AuroraBackend Description "Aurora Minutes – FastAPI Transkriptions-Backend"

        Write-Step "Frontend als Windows-Dienst registrieren"
        & $nssmPath install AuroraFrontend $VenvDir\Scripts\python.exe
        & $nssmPath set AuroraFrontend AppParameters "-m http.server 3000"
        & $nssmPath set AuroraFrontend AppDirectory $FrontendDir
        & $nssmPath set AuroraFrontend AppStdout (Join-Path $LogDir "frontend.log")
        & $nssmPath set AuroraFrontend AppStderr (Join-Path $LogDir "frontend-err.log")
        & $nssmPath set AuroraFrontend Start SERVICE_AUTO_START
        & $nssmPath set AuroraFrontend DisplayName "Aurora Minutes Frontend"
        & $nssmPath set AuroraFrontend Description "Aurora Minutes – Frontend-Webserver"

        Write-Step "Dienste starten"
        Start-Service AuroraBackend
        Start-Service AuroraFrontend

        Write-OK "Dienste registriert und gestartet"
        Write-OK "Dienste starten automatisch mit Windows"
        Write-Warn "Dienste stoppen: sc stop AuroraBackend; sc stop AuroraFrontend"
        Write-Warn "Dienste entfernen: nssm remove AuroraBackend; nssm remove AuroraFrontend"
    } else {
        Write-Fail "NSSM konnte nicht installiert werden. Bitte manuell von https://nssm.cc installieren."
    }
}

# ─── Fertig ───────────────────────────────────────────────────────────────────

Write-Header "Installation abgeschlossen!"

Write-Host ""
Write-Host "  Naechste Schritte:" -ForegroundColor White
Write-Host ""
Write-Host "  1. .env anpassen (API-Keys, Webhook-URL etc.):" -ForegroundColor Yellow
Write-Host "     notepad `"$EnvFile`"" -ForegroundColor Cyan
Write-Host ""
Write-Host "  2. Aurora starten:" -ForegroundColor Yellow
Write-Host "     start.bat                  (einfach, Doppelklick)" -ForegroundColor Cyan
Write-Host "     .\start-aurora.ps1         (PowerShell, mit Statusanzeige)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  3. Im Browser oeffnen:" -ForegroundColor Yellow
Write-Host "     http://localhost:3000      (Hauptseite)" -ForegroundColor Cyan
Write-Host "     http://localhost:8000/docs (API-Dokumentation)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Beenden:" -ForegroundColor Yellow
Write-Host "     stop.bat  oder  .\stop-aurora.ps1" -ForegroundColor Cyan
Write-Host ""
if ($InstallService -and $IsAdmin) {
    Write-Host "  Windows-Dienste:" -ForegroundColor Yellow
    Write-Host "     Autostart aktiv – Aurora startet mit Windows" -ForegroundColor Green
    Write-Host ""
}
Write-Host "  Logs:" -ForegroundColor Yellow
Write-Host "     $LogDir" -ForegroundColor Cyan
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
