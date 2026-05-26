# Aurora Minutes – Backend Dockerfile (Azure-only, schlank)
# Final ~250 MB statt 8 GB. Keine lokalen ML-Modelle, alles über Azure.

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ffmpeg für Audio-Konvertierung (webm/mp3/m4a -> WAV für Azure Speech).
# tini für sauberes Signal-Handling, curl für Healthchecks/Debug.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
# RELEASE.json kommt aus dem 'release-info' Build-Context (Repo-Root).
COPY --from=release-info RELEASE.json /app/RELEASE.json

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
