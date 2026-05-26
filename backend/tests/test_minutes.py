import json
import logging

import httpx

from backend.app.schemas import MeetingMinutes, TranscriptSegment
from backend.app.services.minutes import AzureOpenAICompletionClient, HTTPCompletionClient, LLMMinutesGenerator


class DummyLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if prompt.startswith("Du bist Meeting-Analyst"):
            return (
                '{"summary": "Anna und Ben besprechen Budget und Zeitplan fuer das Projekt Apollo. '
                'Anna dokumentiert die Freigabe und Ben uebernimmt das Follow-up.", '
                '"agenda": ["Budget", "Zeitplan"], "highlights": '
                '["Projekt Apollo wird priorisiert"], '
                '"decisions": [{"title": "Budget freigegeben", "details": "Anna bestaetigt das Budget fuer Projekt Apollo"}], '
                '"action_items": [{"owner": "Ben", "description": "Follow-up zum Zeitplan"}], '
                '"risks": ["Lieferverzug beim Zeitplan"]}'
            )

        return json.dumps(
            {
                "bullets": [f"Chunk {len(self.calls)}"],
                "decisions": [],
                "actions": [],
                "risks": [],
            },
            ensure_ascii=False,
        )


class EmptySectionsLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        return json.dumps(
            {
                "summary": "",
                "agenda": [],
                "highlights": [],
                "decisions": [],
                "action_items": [],
                "risks": [],
            }
        )


class HallucinatingLLM:
    def __call__(self, prompt: str) -> str:
        return json.dumps(
            {
                "summary": (
                    "Das Meeting drehte sich um Produktionsauftraege, Roboterarme und akustische "
                    "Ueberwachung in einer Halle."
                ),
                "agenda": ["Maschinenfreigabe"],
                "highlights": ["Vanillequalitaet pruefen"],
                "decisions": [{"title": "Maschine freigegeben", "details": "Defekte Anlage bleibt aktiv"}],
                "action_items": [{"owner": "Claudia", "description": "Kooperationsvertrag pruefen"}],
                "risks": ["Roboterarm faellt aus"],
            }
        )


def make_segments() -> list[TranscriptSegment]:
    segments = []
    texts = [
        "Anna bespricht das Budget fuer Projekt Apollo.",
        "Ben geht den Zeitplan fuer Projekt Apollo durch.",
        "Anna bestaetigt das Budget und priorisiert Projekt Apollo.",
        "Ben uebernimmt das Follow-up zum Zeitplan.",
        "Es gibt ein Risiko fuer Lieferverzug im Zeitplan.",
    ]
    for idx, text in enumerate(texts):
        speaker_id = "speaker_a" if idx % 2 == 0 else "speaker_b"
        segments.append(
            TranscriptSegment(
                speaker_id=speaker_id,
                speaker="Speaker A" if idx % 2 == 0 else "Speaker B",
                start=float(idx * 5),
                end=float(idx * 5 + 4),
                text=text,
            )
        )
    return segments


def test_minutes_generator_creates_minutes_in_single_pass():
    llm = DummyLLM()
    generator = LLMMinutesGenerator(llm_client=llm)
    minutes = generator.build_minutes(make_segments())
    assert "Budget" in minutes.summary
    assert minutes.agenda == ["Budget", "Zeitplan"]
    assert minutes.chunk_count == 1
    assert minutes.decisions[0].title == "Budget freigegeben"
    assert minutes.action_items[0].owner == "Ben"
    assert len(llm.calls) == 1
    assert "TRANSKRIPT:" in llm.calls[0]
    assert "Du bist Meeting-Analyst" in llm.calls[0]
    titles = [section.title for section in minutes.sections]
    assert titles == [
        "Kurzzusammenfassung",
        "Agenda",
        "Highlights",
        "Entscheidungen",
        "Action Items",
        "Risiken & offene Punkte",
    ]
    assert "Projekt Apollo" in minutes.sections[0].entries[0]


def test_minutes_generator_fallback_without_llm():
    generator = LLMMinutesGenerator(base_url=None, llm_client=None)
    minutes = generator.build_minutes(make_segments())
    assert minutes.model.endswith("(fallback)")
    assert minutes.summary == ""
    assert minutes.agenda == []
    assert minutes.highlights == []
    assert minutes.decisions == []
    assert minutes.action_items == []
    assert minutes.risks == []
    assert minutes.sections[0].title == "Kurzzusammenfassung"
    assert minutes.sections[0].entries[0] == "Keine Kurzzusammenfassung vorhanden."
    assert minutes.sections[-1].title == "Risiken & offene Punkte"
    assert minutes.sections[-1].entries[0] == "Keine Risiken oder offenen Punkte dokumentiert."


def test_http_client_extracts_message_response():
    payload = {
        "model": "gpt-oss:20b",
        "message": {"role": "assistant", "content": "Antwort"},
        "done": True,
    }
    assert HTTPCompletionClient._extract_content(payload) == "Antwort"


def test_http_client_extracts_openai_response():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Chunk summary",
                }
            }
        ]
    }
    assert HTTPCompletionClient._extract_content(payload) == "Chunk summary"


def test_http_client_builds_url_without_scheme():
    client = HTTPCompletionClient(
        base_url="local-api:8080",
        model="gpt-oss:20b",
        completions_path="v1/chat/completions",
    )
    assert client._build_url() == "http://local-api:8080/v1/chat/completions"


def test_azure_openai_client_builds_deployment_url():
    client = AzureOpenAICompletionClient(
        endpoint="https://example.openai.azure.com",
        model="gpt-4.1-mini",
    )

    assert (
        client._build_url()
        == "https://example.openai.azure.com/openai/deployments/gpt-4.1-mini/chat/completions"
    )


def test_azure_openai_client_uses_bearer_header_for_prefixed_token():
    client = AzureOpenAICompletionClient(
        endpoint="https://example.openai.azure.com",
        model="gpt-4.1-mini",
        api_key="Bearer azure-token",
    )

    headers = client._build_headers()

    assert headers["Authorization"] == "Bearer azure-token"
    assert "api-key" not in headers


def test_azure_openai_client_uses_api_key_header_for_plain_secret():
    client = AzureOpenAICompletionClient(
        endpoint="https://example.openai.azure.com",
        model="gpt-4.1-mini",
        api_key="plain-secret",
    )

    headers = client._build_headers()

    assert headers["api-key"] == "plain-secret"
    assert "Authorization" not in headers


def test_azure_openai_client_omits_response_format_when_json_not_expected(monkeypatch):
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Antwort"}}]}

    class DummyClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers=None, params=None, json=None):
            captured["json"] = json
            return DummyResponse()

    monkeypatch.setattr("httpx.Client", lambda timeout: DummyClient(timeout))
    client = AzureOpenAICompletionClient(
        endpoint="https://example.openai.azure.com",
        model="gpt-4.1-mini",
        expect_json=False,
    )

    result = client("Bitte fasse das Meeting zusammen.")

    assert result == "Antwort"
    assert "response_format" not in captured["json"]


def test_minutes_generator_normalizes_empty_completions_path():
    generator = LLMMinutesGenerator(completions_path="", llm_client=DummyLLM())
    assert generator.completions_path == "/v1/chat/completions"


def test_http_client_tries_multiple_base_urls(monkeypatch):
    calls: list[str] = []

    class DummyResponse:
        headers = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "Erfolg"}}]}

    class DummyClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, headers, json):
            calls.append(url)
            if "localhost" in url:
                raise httpx.ConnectError("boom", request=None)
            return DummyResponse()

    monkeypatch.setattr("httpx.Client", lambda timeout: DummyClient(timeout))
    client = HTTPCompletionClient(
        base_url="http://localhost:8080,http://host.docker.internal:8080",
        model="gpt-oss:20b",
        completions_path="/v1/chat/completions",
    )

    result = client("Prompt")

    assert result == "Erfolg"
    assert len(calls) == 2
    assert calls[0].startswith("http://localhost:8080")
    assert calls[1].startswith("http://host.docker.internal:8080")


def test_http_client_consumes_streaming_response(monkeypatch):
    class DummyStreamResponse:
        headers = {"Content-Type": "text/event-stream"}

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield '{"message": {"content": "Bitte"}, "done": false}'
            yield '{"message": {"content": " arbeiten"}, "done": false}'
            yield '{"message": {"content": " weiter"}, "done": true}'

    class DummyClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url: str, headers, json):
            return DummyStreamResponse()

    monkeypatch.setattr("httpx.Client", lambda timeout: DummyClient(timeout))
    client = HTTPCompletionClient(
        base_url="http://local-api:8080",
        model="gpt-oss:20b",
        completions_path="/v1/chat/completions",
    )

    result = client("Prompt")

    assert result == "Bitte arbeiten weiter"
def test_minutes_generator_only_sends_final_prompt():
    llm = DummyLLM()
    generator = LLMMinutesGenerator(llm_client=llm)
    generator.build_minutes(make_segments())
    assert llm.calls
    assert all(prompt.startswith("Du bist Meeting-Analyst") for prompt in llm.calls)


def test_minutes_generator_fills_missing_sections_with_fallbacks():
    llm = EmptySectionsLLM()
    generator = LLMMinutesGenerator(llm_client=llm)
    minutes = generator.build_minutes(make_segments())
    assert minutes.summary == ""
    assert minutes.agenda == []
    assert minutes.highlights == []
    assert minutes.decisions == []
    assert minutes.action_items == []
    assert minutes.risks == []
    assert all(section.entries for section in minutes.sections)


def test_minutes_section_placeholders_for_empty_minutes():
    generator = LLMMinutesGenerator(base_url=None, llm_client=None)
    empty_minutes = MeetingMinutes()
    generator.ensure_sections(empty_minutes)
    assert empty_minutes.sections[0].entries[0] == "Keine Kurzzusammenfassung vorhanden."
    assert empty_minutes.sections[1].entries[0] == "Keine Agenda erkannt."


def test_extract_json_any_skips_non_json_prefix_brackets():
    raw_output = '[draft]\n{"summary":"ok","agenda":[],"highlights":[],"decisions":[],"action_items":[],"risks":[]}\nDone.'

    extracted = LLMMinutesGenerator._extract_json_any(raw_output)

    assert extracted.startswith("{")
    assert json.loads(extracted)["summary"] == "ok"


def test_minutes_generator_rejects_ungrounded_minutes():
    generator = LLMMinutesGenerator(llm_client=HallucinatingLLM())

    minutes = generator.build_minutes(make_segments())

    assert minutes.model.endswith("(fallback)")
    assert minutes.summary == ""
    assert minutes.decisions == []


def test_minutes_generator_does_not_warn_for_ungrounded_minutes(caplog):
    generator = LLMMinutesGenerator(llm_client=HallucinatingLLM())

    with caplog.at_level(logging.WARNING, logger="backend.app.services.minutes"):
        generator.build_minutes(make_segments())

    assert "LLM-Minutes fehlgeschlagen" not in caplog.text
