import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from app import llm

ORIGINAL_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    for name in [
        "AI_PROVIDER",
        "AI_MODEL",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_REQUEST_TIMEOUT_SECONDS",
        "AI_MAX_OUTPUT_TOKENS",
        "AI_OLLAMA_NUM_THREADS",
        "IMAGINE_WEB_GATEWAY_ONLY",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)


def transport(monkeypatch, handler):
    original = ORIGINAL_CLIENT
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_ollama_native_contract_never_forwards_openai_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")

    def handler(req):
        assert str(req.url) == "http://127.0.0.1:11434/api/chat"
        assert "Authorization" not in req.headers
        body = json.loads(req.content)
        assert body["model"] == "qwen3:4b-instruct"
        assert body["stream"] is False and body["think"] is False
        assert body["options"]["num_predict"] == 500
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": " 문이 열렸다. ",
                    "thinking": "private reasoning",
                },
                "done": True,
                "done_reason": "stop",
            },
        )

    transport(monkeypatch, handler)
    assert (
        asyncio.run(llm.complete([{"role": "user", "content": "문을 살핀다"}]))
        == "문이 열렸다."
    )


def test_compatible_server_and_existing_openai_contract(monkeypatch):
    for provider, base, model, key in [
        ("openai", "https://api.openai.com/v1", "gpt-4o-mini", "openai-test"),
        (
            "openai_compatible",
            "http://127.0.0.1:8001/v1",
            "Qwen/Qwen3-4B-Instruct-2507",
            "local-test",
        ),
    ]:
        monkeypatch.setenv("AI_PROVIDER", provider)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
        if provider != "openai":
            monkeypatch.setenv("AI_BASE_URL", base + "/")
            monkeypatch.setenv("AI_MODEL", model)
            monkeypatch.setenv("AI_API_KEY", key)

        def handler(req):
            assert str(req.url) == base + "/chat/completions"
            assert req.headers["Authorization"] == "Bearer " + key
            assert json.loads(req.content)["model"] == model
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": "한국어 이야기"},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        transport(monkeypatch, handler)
        assert asyncio.run(llm.complete([])) == "한국어 이야기"


@pytest.mark.parametrize(
    "body",
    [
        {"message": {"content": "unfinished"}, "done": False},
        {"message": {"content": "unfinished"}, "done": True, "done_reason": "length"},
        {"message": {"content": " "}, "done": True},
        {"message": {"content": "<think>private</think>story"}, "done": True},
        {"message": None, "done": True},
    ],
)
def test_invalid_or_incomplete_ollama_response_fails_without_fallback(
    monkeypatch, body
):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=body)

    transport(monkeypatch, handler)
    with pytest.raises(HTTPException) as e:
        asyncio.run(llm.complete([]))
    assert e.value.status_code == 502 and len(calls) == 1


@pytest.mark.parametrize(
    "values",
    [
        {"AI_PROVIDER": "unknown"},
        {"AI_PROVIDER": "openai"},
        {"AI_PROVIDER": "openai_compatible", "AI_MODEL": "qwen"},
        {"AI_PROVIDER": "ollama", "AI_BASE_URL": "file:///tmp/model"},
        {"AI_PROVIDER": "ollama", "AI_BASE_URL": "http://user:secret@localhost:11434"},
        {"AI_PROVIDER": "ollama", "AI_REQUEST_TIMEOUT_SECONDS": "999"},
    ],
)
def test_bad_server_config_fails_before_http(monkeypatch, values):
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(HTTPException) as e:
        llm.configuration()
    assert e.value.status_code == 503


def test_real_adapter_path_preserves_api_atomicity_and_branching(account, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")

    def handler(req):
        return httpx.Response(
            200,
            json={
                "message": {"content": "낡은 문 너머에서 빛이 새어 나온다."},
                "done": True,
            },
        )

    transport(monkeypatch, handler)
    client, _ = account()
    r = client.post(
        "/rooms",
        json={
            "title": "Qwen World",
            "world_rules": "플레이어의 행동은 확정하지 않는다",
        },
    ).json()
    path = f"/rooms/{r['id']}"
    body = {"content": "문을 살핀다", "request_id": "ollama-one"}
    result = client.post(path + "/turns", json=body)
    assert result.status_code == 200, result.text
    assert client.post(path + "/turns", json=body).json() == result.json()
    assert len(client.get(path).json()["messages"]) == 2
    saved = client.post(
        path + "/saves", json={"label": "Qwen 응답 뒤", "message_index": 2}
    ).json()
    child = client.post(f"/saves/{saved['id']}/resume").json()
    assert child["messages"][-1]["content"] == result.json()["ai_message"]["content"]

    def broken(req):
        return httpx.Response(503, json={"error": "private internal details"})

    # Restore the class before installing a second transport.
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    transport(monkeypatch, broken)
    failed = client.post(
        path + "/turns", json={"content": "다음 행동", "request_id": "ollama-two"}
    )
    assert failed.status_code == 502 and "private internal details" not in failed.text
    assert len(client.get(path).json()["messages"]) == 2


def test_extended_timeout_only_in_explicit_private_web_gateway(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_REQUEST_TIMEOUT_SECONDS", "180")
    with pytest.raises(HTTPException):
        llm.configuration()
    monkeypatch.setenv("IMAGINE_WEB_GATEWAY_ONLY", "1")
    assert llm.configuration().timeout == 180


def test_ollama_cpu_quota_setting_reaches_model_without_affecting_other_providers(
    monkeypatch,
):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("AI_OLLAMA_NUM_THREADS", "2")

    def handler(req):
        assert json.loads(req.content)["options"]["num_thread"] == 2
        return httpx.Response(
            200, json={"message": {"content": "첫 장면."}, "done": True}
        )

    transport(monkeypatch, handler)
    assert asyncio.run(llm.complete([])) == "첫 장면."
    monkeypatch.setenv("AI_OLLAMA_NUM_THREADS", "0")
    with pytest.raises(HTTPException):
        llm.configuration()
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    assert llm.configuration().threads is None
