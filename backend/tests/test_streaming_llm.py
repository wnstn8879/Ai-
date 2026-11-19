import asyncio
import json
import httpx
import pytest
from fastapi import HTTPException
from app import llm


def stream(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )


def collect():
    async def run():
        return [
            part
            async for part in llm.stream_complete(
                [{"role": "user", "content": "이어 써줘"}]
            )
        ]

    return asyncio.run(run())


def test_ollama_stream_keeps_visible_content_and_reports_token_boundary(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward")

    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is True and body["think"] is False
        assert (
            body["options"]["num_predict"] == 1200
            and "Authorization" not in req.headers
        )
        lines = [
            {
                "message": {
                    "content": "조용한 밤의 이야기가 흐른다.",
                    "thinking": "private",
                }
            },
            {"message": {"content": " 그리고 다음 사건이 일어났다."}},
            {"done": True, "done_reason": "length"},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    stream(monkeypatch, handler)
    parts = collect()
    assert (
        "".join(x.get("text", "") for x in parts)
        == "조용한 밤의 이야기가 흐른다. 그리고 다음 사건이 일어났다."
    )
    assert parts[-1] == {"finish_reason": "length"}


def test_openai_stream_contract_and_missing_finish_are_not_retried(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    calls = []

    def handler(req):
        calls.append(req)
        assert req.headers["Authorization"] == "Bearer test-only"
        return httpx.Response(
            200,
            text="data: "
            + json.dumps({"choices": [{"delta": {"content": "긴 본문이 흐릅니다."}}]})
            + "\n\ndata: [DONE]\n",
        )

    stream(monkeypatch, handler)
    with pytest.raises(HTTPException):
        collect()
    assert len(calls) == 1


def test_split_thinking_tags_are_never_exposed_as_prose(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")

    def handler(req):
        return httpx.Response(
            200,
            text="\n".join(
                json.dumps(x)
                for x in [
                    {"message": {"content": "<thi"}},
                    {"message": {"content": "nk>private reasoning"}},
                    {"done": True},
                ]
            ),
        )

    stream(monkeypatch, handler)
    with pytest.raises(HTTPException):
        collect()
