from funktionen_audio.led import blue, green, orange

import datetime as dt
import queue
import time
from pathlib import Path

import requests
import sounddevice as sd
import soundfile as sf
import urllib3
from gpiozero import DigitalInputDevice

# === GPIO / Trigger ===
GPIO_PIN = 16
ACTIVE_HIGH = True
PULL_UP = True

# === Sensor / API ===
ROOM = "E01-115 SWS"
API_URL = "https://192.168.11.75:4173/api/meetings/submit"
VERIFY_TLS = False  # Bei self-signed Zertifikat: False
API_TIMEOUT_SECONDS = 900
DIARIZE = True

# === Audio ===
SAMPLERATE = 16000
CHANNELS = 1
INPUT_DEVICE = 1  # ggf. auf None oder anderes Device setzen
FILENAME = "recording.flac"

if not VERIFY_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


inp = DigitalInputDevice(GPIO_PIN, pull_up=PULL_UP)


def is_active() -> bool:
    return inp.value == 1 if ACTIVE_HIGH else inp.value == 0


def record_while_active(filename: str) -> str:
    q: queue.Queue = queue.Queue()
    recorded_at = iso_utc_now()

    def callback(indata, frames, time_info, status):
        if status:
            print(status)
        q.put(indata.copy())

    print(f"Aufnahme START (recorded_at={recorded_at})")

    with sf.SoundFile(
        filename,
        mode="w",
        samplerate=SAMPLERATE,
        channels=CHANNELS,
        format="FLAC",
        subtype="PCM_16",
    ) as file:
        with sd.InputStream(
            samplerate=SAMPLERATE,
            channels=CHANNELS,
            device=INPUT_DEVICE,
            callback=callback,
        ):
            while is_active():
                try:
                    file.write(q.get(timeout=0.5))
                except queue.Empty:
                    pass

    print("Aufnahme STOP")
    return recorded_at


def post_audio_to_api(filename: str, room: str, recorded_at: str) -> dict:
    print("POST: Sende Audio an /api/meetings/submit ...")
    with open(filename, "rb") as f:
        response = requests.post(
            API_URL,
            files={"audio": (Path(filename).name, f, "audio/flac")},
            data={
                "room": room,
                "recorded_at": recorded_at,
                "diarize": str(DIARIZE).lower(),
            },
            timeout=API_TIMEOUT_SECONDS,
            verify=VERIFY_TLS,
        )
    response.raise_for_status()
    return response.json()


print(
    "Bereit. Warte auf Trigger... (HIGH startet, LOW stoppt)"
    if ACTIVE_HIGH
    else "Bereit. Warte auf Trigger... (LOW startet, HIGH stoppt)"
)

while True:
    while not is_active():
        orange()
        time.sleep(0.01)

    green()
    recorded_at = record_while_active(FILENAME)
    blue()

    try:
        api_resp = post_audio_to_api(FILENAME, ROOM, recorded_at)
        minutes = api_resp.get("minutes", {})
        webhook = api_resp.get("webhook", {})

        print("Minutes summary:", minutes.get("summary", ""))
        print("Webhook delivered:", webhook.get("delivered"))
        print("Webhook detail:", webhook.get("detail", ""))
    except requests.RequestException as exc:
        print(f"HTTP-Fehler: {exc}")
        if getattr(exc, "response", None) is not None:
            print("Response:", exc.response.text)

    print("Runde fertig. Warte erneut auf Trigger...")
