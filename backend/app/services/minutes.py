from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Sequence
from urllib.parse import urlparse

import httpx

from ..defaults import MAX_LLM_CONTEXT_SIZE
from ..schemas import (
    MeetingMinutes,
    MinutesActionItem,
    MinutesDecision,
    MinutesSection,
    SegmentPrediction,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

LLMCallable = Callable[[str], str]
CONTENT_TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9_-]{2,}")
GROUNDING_STOPWORDS = {
    "aber",
    "als",
    "also",
    "am",
    "an",
    "auch",
    "auf",
    "aus",
    "bei",
    "bereits",
    "bis",
    "das",
    "dass",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "dies",
    "diese",
    "diesem",
    "dieser",
    "dieses",
    "doch",
    "dort",
    "drei",
    "durch",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "eines",
    "er",
    "es",
    "etwa",
    "fuer",
    "hat",
    "hier",
    "hin",
    "hinter",
    "ich",
    "ihr",
    "ihre",
    "im",
    "in",
    "ist",
    "ja",
    "jede",
    "jeder",
    "jedes",
    "kann",
    "kein",
    "keine",
    "mit",
    "nach",
    "nicht",
    "noch",
    "nur",
    "oder",
    "pro",
    "schon",
    "sehr",
    "sein",
    "sich",
    "sie",
    "sind",
    "soll",
    "sollen",
    "später",
    "ueber",
    "um",
    "und",
    "uns",
    "unter",
    "vom",
    "von",
    "vor",
    "war",
    "waren",
    "wichtig",
    "wird",
    "wir",
    "wurde",
    "zu",
    "zum",
    "zur",
}


# -------------------- HTTP LLM Client --------------------


@dataclass
class HTTPCompletionClient:
    base_url: str
    model: str
    api_key: str | None = None
    completions_path: str = "/v1/chat/completions"
    timeout: int = 120

    num_ctx: int = MAX_LLM_CONTEXT_SIZE
    temperature: float = 0.0

    def __call__(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Du bist ein Meeting-Analyst. Antworte praezise."},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
            "format": "json",
            "options": {"num_ctx": int(self.num_ctx)},
        }

        bases = [item.strip() for item in self.base_url.split(",") if item.strip()]
        errors: list[Exception] = []

        with httpx.Client(timeout=self.timeout) as client:
            for base in bases or [self.base_url]:
                url = self._build_url(base)
                try:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    content = self._read_response_content(response)
                    if not content:
                        raise RuntimeError("LLM response enthaelt keinen content")
                    return content
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)
                    continue

        if errors:
            raise errors[-1]
        raise RuntimeError("LLM request fehlgeschlagen")

    def _build_url(self, base: str | None = None) -> str:
        if self.completions_path.startswith("http"):
            return self._ensure_scheme(self.completions_path)
        base_value = base or self.base_url
        base_value = self._ensure_scheme(base_value)
        path = self.completions_path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base_value.rstrip('/')}{path}"

    @staticmethod
    def _ensure_scheme(url: str | None) -> str:
        if not url:
            raise RuntimeError("Keine LLM-URL konfiguriert")
        parsed = urlparse(url)
        if parsed.scheme and "://" in url:
            return url
        return f"http://{url.lstrip('/')}"

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str | None:
        # OpenAI-style
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if message and message.get("content"):
                return str(message.get("content")).strip()

        # Some OpenAI-compatible local servers return content in message
        message_block = data.get("message")
        if isinstance(message_block, dict) and message_block.get("content"):
            return str(message_block.get("content")).strip()

        # Some backends
        if data.get("response"):
            return str(data.get("response")).strip()

        if isinstance(data, (list, dict)):
            try:
                return json.dumps(data)
            except Exception:
                return str(data)

        return None

    def _read_response_content(self, response: httpx.Response) -> str | None:
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            return self._consume_stream(response)
        data = response.json()
        return self._extract_content(data)

    def _consume_stream(self, response: httpx.Response) -> str:
        parts: List[str] = []
        for line in response.iter_lines():
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = payload.get("message")
            if message and message.get("content"):
                parts.append(str(message.get("content")))
            if payload.get("done") is True:
                break
        return "".join(parts).strip()


@dataclass
class AzureOpenAICompletionClient:
    endpoint: str
    model: str
    api_key: str | None = None
    api_version: str = "2025-01-01-preview"
    timeout: int = 120
    temperature: float = 0.0
    expect_json: bool = True

    def __call__(self, prompt: str) -> str:
        headers = self._build_headers()
        payload = {
            "messages": [
                {"role": "system", "content": "Du bist ein Meeting-Analyst. Antworte praezise."},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        if self.expect_json:
            payload["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=self.timeout) as client:
            url = self._build_url()
            response = client.post(
                url,
                headers=headers,
                params={"api-version": self.api_version.strip() or "2025-01-01-preview"},
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(self._build_error_message(exc, response, url)) from exc
            return self._read_response_content(response)

    def _build_url(self) -> str:
        endpoint = HTTPCompletionClient._ensure_scheme(self.endpoint).rstrip("/")
        if endpoint.endswith("/openai/v1"):
            endpoint = endpoint[: -len("/openai/v1")]
        elif endpoint.endswith("/openai"):
            endpoint = endpoint[: -len("/openai")]
        deployment = self.model.strip()
        if not deployment:
            raise RuntimeError("Keine Azure-OpenAI-Modell-ID konfiguriert")
        return f"{endpoint}/openai/deployments/{deployment}/chat/completions"

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        credential = (self.api_key or "").strip()
        if not credential:
            return headers
        if credential.lower().startswith("bearer "):
            headers["Authorization"] = credential
        elif credential.count(".") >= 2 and " " not in credential:
            headers["Authorization"] = f"Bearer {credential}"
        else:
            headers["api-key"] = credential
        return headers

    def _read_response_content(self, response: httpx.Response) -> str:
        data = response.json()
        content = HTTPCompletionClient._extract_content(data)
        if not content:
            raise RuntimeError("Azure OpenAI response enthaelt keinen content")
        return content

    @staticmethod
    def _build_error_message(exc: httpx.HTTPStatusError, response: httpx.Response, url: str) -> str:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = error.get("message") or error.get("code") or detail
        except Exception:
            pass
        detail_text = str(detail).strip() or str(exc)
        return f"Azure OpenAI Request fehlgeschlagen ({response.status_code}) fuer {url}: {detail_text}"


# -------------------- Minutes Generator --------------------


class MinutesGroundingError(ValueError):
    """Raised when generated minutes cannot be grounded in the transcript."""


class LLMMinutesGenerator:
    """Erzeugt strukturierte Minutes direkt aus dem vollstaendigen Transkript."""

    def __init__(
        self,
        model: str | None = None,
        azure_endpoint: str | None = None,
        azure_api_key: str | None = None,
        azure_api_version: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        completions_path: str | None = None,
        llm_client: LLMCallable | None = None,
        llm_num_ctx: int | None = None,
        llm_temperature: float | None = None,
        enable_json_repair: bool | None = None,
        allow_fallback: bool | None = None,
        provider: str | None = None,
        local_model_path: str | None = None,
        local_context_size: int | None = None,
        local_gpu_layers: int | None = None,
    ) -> None:
        configured_provider = provider or os.getenv("LLM_PROVIDER", "azure_openai")
        self.provider = self._normalize_provider(configured_provider)
        self.model = model or os.getenv("LLM_MODEL", "gpt-4.1-mini")
        self.azure_endpoint = azure_endpoint or os.getenv("LLM_AZURE_ENDPOINT", "")
        self.azure_api_key = azure_api_key or os.getenv("LLM_AZURE_API_KEY") or os.getenv("LLM_API_KEY")
        self.azure_api_version = azure_api_version or os.getenv("LLM_AZURE_API_VERSION", "2025-01-01-preview")
        default_base = ""
        self.base_url = base_url or os.getenv("LLM_BASE_URL", default_base)
        self.api_key = api_key or os.getenv("LLM_API_KEY")

        configured_path = (
            completions_path
            if completions_path is not None
            else os.getenv("LLM_COMPLETIONS_PATH")
        )
        if not configured_path or configured_path.strip() in {"", "/"}:
            configured_path = "/v1/chat/completions"
        self.completions_path = configured_path.strip()
        self.local_model_path = local_model_path or os.getenv("LLM_LOCAL_MODEL_PATH", "")
        self.local_context_size = max(
            512,
            int(os.getenv("LLM_LOCAL_CONTEXT_SIZE", local_context_size or MAX_LLM_CONTEXT_SIZE)),
        )
        self.local_gpu_layers = int(os.getenv("LLM_LOCAL_GPU_LAYERS", local_gpu_layers or 0))

        self.llm_num_ctx = max(512, int(os.getenv("LLM_NUM_CTX", llm_num_ctx or MAX_LLM_CONTEXT_SIZE)))
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", llm_temperature or 0.0))
        self.enable_json_repair = (
            (os.getenv("LLM_ENABLE_JSON_REPAIR", "1") == "1")
            if enable_json_repair is None
            else bool(enable_json_repair)
        )
        allow_fallback_env = os.getenv("LLM_ALLOW_FALLBACK")
        if allow_fallback is not None:
            self.allow_fallback = allow_fallback
        elif allow_fallback_env is not None:
            self.allow_fallback = allow_fallback_env == "1"
        else:
            self.allow_fallback = True

        self._client = llm_client

    def export_settings(self) -> dict[str, str]:
        return {
            "llm_provider": self.provider,
            "llm_model": self.model,
            "llm_azure_endpoint": self.azure_endpoint,
            "llm_azure_api_key": self.azure_api_key or "",
            "llm_azure_api_version": self.azure_api_version,
            "llm_base_url": self.base_url,
            "llm_api_key": self.api_key or "",
            "llm_completions_path": self.completions_path,
            "llm_local_model_path": self.local_model_path,
            "llm_local_context_size": str(self.local_context_size),
            "llm_local_gpu_layers": str(self.local_gpu_layers),
        }

    def apply_settings(
        self,
        *,
        model: str | None = None,
        azure_endpoint: str | None = None,
        azure_api_key: str | None = None,
        azure_api_version: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        completions_path: str | None = None,
        provider: str | None = None,
        local_model_path: str | None = None,
        local_context_size: int | None = None,
        local_gpu_layers: int | None = None,
    ) -> None:
        if provider is not None:
            self.provider = self._normalize_provider(provider)
        if model is not None:
            self.model = model.strip() or "gpt-4.1-mini"
        if azure_endpoint is not None:
            self.azure_endpoint = azure_endpoint.strip()
        if azure_api_key is not None:
            self.azure_api_key = azure_api_key.strip() or None
        if azure_api_version is not None:
            self.azure_api_version = azure_api_version.strip() or "2025-01-01-preview"
        if base_url is not None:
            self.base_url = base_url.strip() or ""
        if api_key is not None:
            self.api_key = api_key.strip() or None
        if completions_path is not None:
            normalized_path = completions_path.strip()
            self.completions_path = normalized_path if normalized_path not in {"", "/"} else "/v1/chat/completions"
        if local_model_path is not None:
            self.local_model_path = local_model_path.strip()
        if local_context_size is not None:
            self.local_context_size = max(512, int(local_context_size))
        if local_gpu_layers is not None:
            self.local_gpu_layers = max(0, int(local_gpu_layers))
        self._client = None

    # ------------------ public API ------------------

    def build_minutes(self, segments: Sequence[TranscriptSegment]) -> MeetingMinutes:
        transcript_text = self._segments_to_text(segments)
        if not transcript_text.strip():
            return self.ensure_sections(self._empty_minutes())

        try:
            minutes_output = self._call_llm(self._minutes_prompt(transcript_text))
            minutes = self._parse_minutes(minutes_output, chunk_count=1)
            issues = self._collect_grounding_issues(minutes, transcript_text)
            blocking_issues = [issue for issue in issues if issue != "summary"]
            if blocking_issues:
                raise MinutesGroundingError(
                    f"Minutes sind nicht ausreichend im Transkript verankert: {', '.join(blocking_issues)}"
                )
            minutes.chunk_count = minutes.chunk_count or 1
            minutes.model = minutes.model or self.model
            return self.ensure_sections(minutes)
        except MinutesGroundingError as exc:
            logger.debug("LLM-Minutes verworfen, nutze Fallback: %s", exc)
            if self.allow_fallback:
                fallback = self._fallback_minutes()
                return self.ensure_sections(fallback)
            raise
        except Exception as exc:
            logger.warning("LLM-Minutes fehlgeschlagen, nutze Fallback: %s", exc)
            if self.allow_fallback:
                fallback = self._fallback_minutes()
                return self.ensure_sections(fallback)
            raise

    def label_segments(self, segments: Sequence[TranscriptSegment]) -> List[SegmentPrediction]:
        if not segments:
            return []
        prompt = self._label_prompt(segments)
        try:
            raw_output = self._call_llm(prompt)
            return self._parse_segment_labels(raw_output, total=len(segments))
        except Exception as exc:  # pragma: no cover
            logger.warning("Segmentlabeling fehlgeschlagen, nutze Fallback: %s", exc)
            if self.allow_fallback:
                return self._fallback_labels(segments)
            raise

    # ------------------ internals ------------------

    def _call_llm(self, prompt: str) -> str:
        client = self._client or self._build_client()
        if client is None:
            raise RuntimeError("Kein LLM konfiguriert")
        return client(prompt)

    def _build_client(self) -> LLMCallable | None:
        if self.provider == "azure_openai":
            if not self.azure_endpoint or not self.model:
                return None
            self._client = AzureOpenAICompletionClient(
                endpoint=self.azure_endpoint,
                model=self.model,
                api_key=self.azure_api_key,
                api_version=self.azure_api_version,
                temperature=self.llm_temperature,
            )
            return self._client
        if not self.base_url:
            return None
        self._client = HTTPCompletionClient(
            base_url=self.base_url,
            model=self.model,
            api_key=self.api_key,
            completions_path=self.completions_path,
            num_ctx=self.llm_num_ctx,
            temperature=self.llm_temperature,
        )
        return self._client

    @staticmethod
    def _normalize_provider(provider: str | None) -> str:
        normalized = (provider or "").strip().lower()
        if normalized in {"llama_cpp", "llama-cpp", "llama-cpp-python"}:
            # Legacy migration: treat removed local provider as generic HTTP provider.
            return "http"
        if normalized in {"azure", "azure_openai", "azure-openai"}:
            return "azure_openai"
        return "http"

    # ------------------ sections helpers ------------------

    def ensure_sections(self, minutes: MeetingMinutes) -> MeetingMinutes:
        """Attach human-readable section blocks with the desired headings."""
        minutes.sections = self._build_section_blocks(minutes)
        return minutes

    def _build_section_blocks(self, minutes: MeetingMinutes) -> List[MinutesSection]:
        return [
            self._make_section(
                "Kurzzusammenfassung",
                self._wrap_summary(minutes.summary),
                "Keine Kurzzusammenfassung vorhanden.",
            ),
            self._make_section("Agenda", minutes.agenda, "Keine Agenda erkannt."),
            self._make_section("Highlights", minutes.highlights, "Keine Highlights vorhanden."),
            self._make_section(
                "Entscheidungen",
                self._format_decision_entries(minutes.decisions),
                "Keine Entscheidungen dokumentiert.",
            ),
            self._make_section(
                "Action Items",
                self._format_action_entries(minutes.action_items),
                "Keine Action Items erfasst.",
            ),
            self._make_section(
                "Risiken & offene Punkte",
                minutes.risks,
                "Keine Risiken oder offenen Punkte dokumentiert.",
            ),
        ]

    @staticmethod
    def _wrap_summary(summary: str) -> List[str]:
        text = summary.strip()
        return [text] if text else []

    @staticmethod
    def _format_decision_entries(decisions: Sequence[MinutesDecision]) -> List[str]:
        entries: List[str] = []
        for item in decisions:
            title = (item.title or "Entscheidung").strip()
            details = (item.details or "").strip()
            if title and details:
                entries.append(f"{title}: {details}")
            elif title:
                entries.append(title)
            elif details:
                entries.append(details)
        return entries

    @staticmethod
    def _format_action_entries(action_items: Sequence[MinutesActionItem]) -> List[str]:
        entries: List[str] = []
        for item in action_items:
            owner = (item.owner or "Unbekannt").strip()
            description = (item.description or "Aufgabe offen").strip()
            due = f" (faellig: {item.due_date.strip()})" if item.due_date else ""
            entries.append(f"{owner}: {description}{due}".strip())
        return entries

    @staticmethod
    def _make_section(title: str, entries: Sequence[str], fallback_entry: str) -> MinutesSection:
        normalized = [str(entry).strip() for entry in entries if str(entry).strip()]
        if not normalized:
            normalized = [fallback_entry]
        return MinutesSection(title=title, entries=list(normalized))

    @staticmethod
    def _segments_to_text(segments: Sequence[TranscriptSegment]) -> str:
        lines = []
        for segment in segments:
            lines.append(
                f"[{segment.start:0.2f}-{segment.end:0.2f}] {segment.speaker}: {segment.text.strip()}"
            )
        return "\n".join(lines)

    def _minutes_prompt(self, context: str) -> str:
        schema = {
            "summary": "string",
            "agenda": "list[str]",
            "highlights": "list[str]",
            "decisions": "list[{title, details}]",
            "action_items": "list[{owner, description, due_date}]",
            "risks": "list[str]",
        }
        instructions = (
            "Du bist Meeting-Analyst. Lies das komplette Transkript und gib GENAU ein JSON-Objekt zurueck."
            " Fuelle jedes Feld: summary = Kurzzusammenfassung (2-3 Saetze), agenda = Liste der Themen,"
            " highlights = praegnante Stichpunkte, decisions = Liste von Objekten mit title & details,"
            " action_items = Liste von Objekten mit owner, description, optional due_date,"
            " risks = Liste von Risiken bzw. offenen Punkten. Nutze ausschliesslich Informationen aus dem Transkript."
        )
        return (
            f"{instructions}\nNur JSON ausgeben.\n"
            f"SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n"
            f"TRANSKRIPT:\n{context}"
        )

    def _label_prompt(self, segments: Sequence[TranscriptSegment]) -> str:
        rows = []
        for idx, segment in enumerate(segments, start=1):
            rows.append(f"{idx}. {segment.speaker}: {segment.text}")

        return (
            "Klassifiziere jede Zeile. Rueckgabe NUR als JSON-Array.\n"
            'Format: [{"row":1,"label":"Entscheidung|Aufgabe|Risiko|Info","rationale":"..."}]\n'
            f"ZEILEN:\n{chr(10).join(rows)}"
        )

    # ------------------ parsing / json handling ------------------

    def _parse_minutes(self, raw_output: str, chunk_count: int) -> MeetingMinutes:
        # Expect object JSON
        data = self._safe_json_load(raw_output, expect="object")

        decisions = [
            MinutesDecision(
                title=str(item.get("title", "")) or "Entscheidung",
                details=str(item.get("details", "")).strip(),
            )
            for item in (data.get("decisions") or [])
            if isinstance(item, dict)
        ]
        action_items = [
            MinutesActionItem(
                owner=str(item.get("owner", "Unbekannt")),
                description=str(item.get("description", "")).strip(),
                due_date=(str(item.get("due_date")) if item.get("due_date") else None),
            )
            for item in (data.get("action_items") or [])
            if isinstance(item, dict)
        ]

        return MeetingMinutes(
            summary=str(data.get("summary", "")).strip(),
            agenda=[str(x).strip() for x in (data.get("agenda") or []) if str(x).strip()],
            highlights=[str(x).strip() for x in (data.get("highlights") or []) if str(x).strip()],
            decisions=decisions,
            action_items=action_items,
            risks=[str(x).strip() for x in (data.get("risks") or []) if str(x).strip()],
            model=self.model,
            chunk_count=chunk_count,
        )

    def _parse_segment_labels(self, raw_output: str, total: int) -> List[SegmentPrediction]:
        data = self._safe_json_load(raw_output, expect="array")

        predictions: List[SegmentPrediction] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                row = int(item.get("row"))
            except Exception:
                continue
            if not (1 <= row <= total):
                continue
            label = str(item.get("label", "")) or "Info"
            rationale = item.get("rationale")
            predictions.append(
                SegmentPrediction(row_index=row, label=label.strip(), rationale=(rationale or None))
            )

        # fill missing
        if len(predictions) < total:
            missing = {idx for idx in range(1, total + 1)} - {p.row_index for p in predictions}
            for idx in sorted(missing):
                predictions.append(SegmentPrediction(row_index=idx, label="Info", rationale="Fallback"))

        return sorted(predictions, key=lambda p: p.row_index)

    def _safe_json_load(self, raw_output: str, expect: str) -> Any:
        """
        Robust JSON parsing:
        - strips code fences
        - extracts first balanced JSON object or array
        - optionally tries repair via LLM (short)
        """
        try:
            blob = self._extract_json_any(raw_output)
            data = json.loads(blob)
        except Exception as exc:
            if self.enable_json_repair:
                try:
                    repaired = self._call_llm(self._json_repair_prompt(raw_output, expect))
                    blob2 = self._extract_json_any(repaired)
                    data = json.loads(blob2)
                except Exception:
                    raise exc
            else:
                raise exc

        if expect == "object" and not isinstance(data, dict):
            raise ValueError("JSON ist kein Objekt")
        if expect == "array" and not isinstance(data, list):
            raise ValueError("JSON ist kein Array")
        return data

    @staticmethod
    def _extract_json_any(raw_output: str) -> str:
        s = (raw_output or "").strip()

        # remove code fences
        if "```" in s:
            s = s.replace("```json", "").replace("```JSON", "").replace("```", "").strip()

        starts = sorted({idx for idx, char in enumerate(s) if char in {"{", "["}})
        if not starts:
            raise ValueError("LLM output enthaelt kein JSON")

        for start in starts:
            candidate = LLMMinutesGenerator._extract_balanced_json(s, start)
            if candidate is None:
                continue
            # Prefix markers like "[draft]" can be balanced but are not valid JSON.
            try:
                json.loads(candidate)
            except json.JSONDecodeError:
                continue
            return candidate

        raise ValueError("LLM output enthaelt kein vollstaendiges JSON")

    @staticmethod
    def _extract_balanced_json(value: str, start: int) -> str | None:
        opening = value[start]
        if opening not in {"{", "["}:
            return None

        matching = {"{": "}", "[": "]"}
        stack = [matching[opening]]
        in_string = False
        escaped = False

        for idx in range(start + 1, len(value)):
            char = value[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in matching:
                stack.append(matching[char])
            elif char in {"}", "]"}:
                if not stack or char != stack[-1]:
                    return None
                stack.pop()
                if not stack:
                    return value[start : idx + 1]

        return None

    @staticmethod
    def _json_repair_prompt(raw_output: str, expect: str) -> str:
        if expect == "array":
            target = "ein valides JSON-Array"
        else:
            target = "ein valides JSON-Objekt"
        return (
            f"Der folgende Text enthaelt unvollstaendiges/ungueltiges JSON. "
            f"Repariere es und gib NUR {target} zurueck. Keine Erklaerungen.\n"
            f"TEXT:\n{raw_output}"
        )

    @classmethod
    def is_text_grounded(cls, transcript_text: str, text: str) -> bool:
        return not cls._text_has_grounding_issue(text, cls._transcript_vocabulary(transcript_text))

    @classmethod
    def _collect_grounding_issues(cls, minutes: MeetingMinutes, transcript_text: str) -> List[str]:
        transcript_vocabulary = cls._transcript_vocabulary(transcript_text)
        issues: List[str] = []

        if cls._text_has_grounding_issue(minutes.summary, transcript_vocabulary):
            issues.append("summary")

        for index, item in enumerate(minutes.agenda, start=1):
            if cls._text_has_grounding_issue(item, transcript_vocabulary):
                issues.append(f"agenda[{index}]")

        for index, item in enumerate(minutes.highlights, start=1):
            if cls._text_has_grounding_issue(item, transcript_vocabulary):
                issues.append(f"highlights[{index}]")

        for index, item in enumerate(minutes.decisions, start=1):
            if cls._text_has_grounding_issue(f"{item.title} {item.details}", transcript_vocabulary):
                issues.append(f"decisions[{index}]")

        for index, item in enumerate(minutes.action_items, start=1):
            if cls._text_has_grounding_issue(
                f"{item.owner} {item.description} {item.due_date or ''}", transcript_vocabulary
            ):
                issues.append(f"action_items[{index}]")

        for index, item in enumerate(minutes.risks, start=1):
            if cls._text_has_grounding_issue(item, transcript_vocabulary):
                issues.append(f"risks[{index}]")

        return issues

    @classmethod
    def _text_has_grounding_issue(cls, text: str, transcript_vocabulary: set[str]) -> bool:
        tokens = cls._content_tokens(text)
        if len(tokens) < 4:
            return False

        overlap = [token for token in tokens if token in transcript_vocabulary]
        unsupported = [token for token in tokens if token not in transcript_vocabulary]
        unsupported_ratio = len(unsupported) / len(tokens)

        if len(unsupported) >= 4 and unsupported_ratio >= 0.6:
            return True
        if len(tokens) >= 7 and len(overlap) <= 2 and unsupported_ratio >= 0.5:
            return True
        return False

    @classmethod
    def _transcript_vocabulary(cls, transcript_text: str) -> set[str]:
        return set(cls._content_tokens(transcript_text))

    @classmethod
    def _content_tokens(cls, text: str) -> List[str]:
        tokens: List[str] = []
        for match in CONTENT_TOKEN_RE.findall((text or "").casefold()):
            if match in GROUNDING_STOPWORDS or match.isdigit():
                continue
            tokens.append(match)
        return tokens

    # ------------------ fallbacks ------------------

    def _fallback_minutes(self) -> MeetingMinutes:
        return MeetingMinutes(
            summary="",
            agenda=[],
            highlights=[],
            decisions=[],
            action_items=[],
            risks=[],
            model=f"{self.model} (fallback)",
            chunk_count=1,
        )

    def _empty_minutes(self) -> MeetingMinutes:
        return MeetingMinutes(summary="", chunk_count=0, model=self.model)

    @staticmethod
    def _fallback_labels(segments: Sequence[TranscriptSegment]) -> List[SegmentPrediction]:
        predictions: List[SegmentPrediction] = []
        for idx, segment in enumerate(segments, start=1):
            text_lower = segment.text.lower()
            if any(k in text_lower for k in ["beschluss", "entscheidung", "approve"]):
                label = "Entscheidung"
            elif any(k in text_lower for k in ["to-do", "aufgabe", "bitte", "follow-up"]):
                label = "Aufgabe"
            elif any(k in text_lower for k in ["risiko", "risk", "problem"]):
                label = "Risiko"
            else:
                label = "Info"
            predictions.append(
                SegmentPrediction(row_index=idx, label=label, rationale="regelbasierter Fallback")
            )
        return predictions
