#!/bin/sh
set -eu

: "${API_BASE_URL:=}"
: "${API_PORT:=8000}"
: "${MEETING_WEBHOOK_URL:=}"
: "${UI_THEME:=aurora}"
: "${SPEAKER_RECOGNITION_ENABLED:=true}"
: "${SEND_ENABLED:=true}"
cat <<EOCONFIG > /app/frontend/config.js
window.__APP_CONFIG__ = window.__APP_CONFIG__ || {};
window.__APP_CONFIG__.API_BASE_URL = "${API_BASE_URL}";
window.__APP_CONFIG__.API_PORT = "${API_PORT}";
window.__APP_CONFIG__.MEETING_WEBHOOK_URL = "${MEETING_WEBHOOK_URL}";
window.__APP_CONFIG__.UI_THEME = "${UI_THEME}";
window.__APP_CONFIG__.SPEAKER_RECOGNITION_ENABLED = "${SPEAKER_RECOGNITION_ENABLED}";
window.__APP_CONFIG__.SEND_ENABLED = "${SEND_ENABLED}";
EOCONFIG

if [ "${API_BASE_URL}" = "same-origin" ]; then
  printf '[frontend] Serving static files with same-origin API base\n' >&2
elif [ -n "${API_BASE_URL}" ]; then
  printf '[frontend] Serving static files with API base %s\n' "${API_BASE_URL}" >&2
else
  printf '[frontend] Serving static files with inferred host and port %s\n' "${API_PORT}" >&2
fi
exec python -m http.server 4173
