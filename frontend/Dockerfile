# Aurora Minutes – Frontend Dockerfile (statische Auslieferung)
# Bake statische Dateien ins Image, config.js wird beim Start aus ENV erzeugt.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/frontend

COPY . /app/frontend

RUN chmod +x /app/frontend/start.sh

EXPOSE 4173

CMD ["/bin/bash", "/app/frontend/start.sh"]
