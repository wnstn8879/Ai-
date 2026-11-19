"""Server-owned provider configuration. Never accept URLs or keys from players."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from app.context_budget import window_tokens


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    base_url: str
    key: str
    timeout: float
    tokens: int
    threads: int | None = None


def configuration():
    name = os.getenv("AI_PROVIDER", "openai").strip().lower()
    if name not in {"openai", "ollama", "openai_compatible"}:
        raise HTTPException(503, "Unsupported AI provider")
    key = (
        os.getenv("OPENAI_API_KEY", "")
        if name == "openai"
        else os.getenv("AI_API_KEY", "")
    )
    model = os.getenv("AI_MODEL", "").strip() or (
        os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        if name == "openai"
        else "qwen3:4b-instruct" if name == "ollama" else ""
    )
    base = (
        "https://api.openai.com/v1"
        if name == "openai"
        else os.getenv(
            "AI_BASE_URL", "http://127.0.0.1:11434" if name == "ollama" else ""
        )
        .strip()
        .rstrip("/")
    )
    try:
        url = urlsplit(base)
        valid = (
            url.scheme in {"http", "https"}
            and url.hostname
            and not (url.username or url.password or url.query or url.fragment)
        )
        timeout = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "40"))
        tokens = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "500"))
        threads = (
            int(os.environ["AI_OLLAMA_NUM_THREADS"])
            if name == "ollama" and os.getenv("AI_OLLAMA_NUM_THREADS")
            else None
        )
        if (
            not valid
            or not model
            or not 1
            <= timeout
            <= (180 if os.getenv("IMAGINE_WEB_GATEWAY_ONLY") == "1" else 40)
            or not 64 <= tokens <= 1000
            or (threads is not None and not 1 <= threads <= 128)
        ):
            raise ValueError("Invalid provider config")
        if name == "openai" and not key.strip():
            raise ValueError("Missing OpenAI key")
    except (ValueError, TypeError):
        raise HTTPException(503, "AI service is not configured correctly") from None
    return Provider(name, model, base, key, timeout, tokens, threads)


async def complete(messages):
    cfg = configuration()
    headers = {"Authorization": "Bearer " + cfg.key} if cfg.key else {}
    if cfg.name == "ollama":
        endpoint = cfg.base_url + "/api/chat"
        payload = {
            "model": cfg.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.8,
                "num_predict": cfg.tokens,
                "num_ctx": window_tokens(),
            },
        }
        if cfg.threads is not None:
            payload["options"]["num_thread"] = cfg.threads
    else:
        endpoint = cfg.base_url + "/chat/completions"
        payload = {
            "model": cfg.model,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": cfg.tokens,
            "stream": False,
        }
    # No automatic retries/fallback: another generation can cost money or differ.
    try:
        async with httpx.AsyncClient(
            timeout=cfg.timeout, follow_redirects=False
        ) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if cfg.name == "ollama":
                content = data["message"]["content"]
                if data.get("done") is not True or data.get("done_reason") == "length":
                    raise ValueError("Incomplete generation")
            else:
                choice = data["choices"][0]
                if choice.get("finish_reason") in {
                    "length",
                    "content_filter",
                    "tool_calls",
                }:
                    raise ValueError("Incomplete generation")
                content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty generation")
            # Thinking output must never appear as narrator dialogue.
            if "<think>" in content or "</think>" in content:
                raise ValueError("Unexpected reasoning output")
            return content.strip()
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        raise HTTPException(
            502, "AI generation failed; check the configured model service"
        ) from None


def writer_output_tokens():
    try:
        value = int(os.getenv("AI_WRITER_OUTPUT_TOKENS", "1200"))
        if not 256 <= value <= 2400:
            raise ValueError
        return value
    except ValueError:
        raise HTTPException(503, "Invalid novel writer output allowance") from None


async def stream_complete(messages):
    """Stream only prose content; the caller persists drafts and controls cancellation.

    Finish reason 'length' is explicit so the writer can continue a saved draft.
    The legacy complete() contract still rejects incomplete turns.
    """
    import json

    cfg = configuration()
    tokens = writer_output_tokens()
    headers = {"Authorization": "Bearer " + cfg.key} if cfg.key else {}
    if cfg.name == "ollama":
        endpoint = cfg.base_url + "/api/chat"
        payload = {
            "model": cfg.model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": {
                "temperature": 0.8,
                "num_predict": tokens,
                "num_ctx": window_tokens(),
            },
        }
        if cfg.threads is not None:
            payload["options"]["num_thread"] = cfg.threads
    else:
        endpoint = cfg.base_url + "/chat/completions"
        payload = {
            "model": cfg.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.8,
            "max_tokens": tokens,
        }
    tail = ""
    reason = None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(90, connect=10), follow_redirects=False
        ) as client:
            async with client.stream(
                "POST", endpoint, headers=headers, json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    if cfg.name == "ollama":
                        data = json.loads(line)
                        if data.get("error"):
                            raise ValueError("Provider failed")
                        piece = data.get("message", {}).get("content", "")
                        if data.get("done"):
                            reason = data.get("done_reason", "stop")
                    else:
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        data = json.loads(raw)
                        if data.get("error"):
                            raise ValueError("Provider failed")
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        piece = choices[0].get("delta", {}).get("content") or ""
                        reason = choices[0].get("finish_reason") or reason
                    if not isinstance(piece, str):
                        raise ValueError("Invalid stream content")
                    tail += piece
                    if "<think>" in tail or "</think>" in tail:
                        raise ValueError("Unexpected reasoning output")
                    # Keep enough overlap to catch thinking tags split across chunks.
                    if len(tail) > 16:
                        yield {"text": tail[:-16]}
                        tail = tail[-16:]
                if reason not in {"stop", "length"}:
                    raise ValueError("Stream ended without a valid finish")
                if tail:
                    yield {"text": tail}
                yield {"finish_reason": reason}
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        raise HTTPException(
            502, "이야기 생성 연결이 끊겼습니다. 작성된 초안은 보존했습니다."
        ) from None
