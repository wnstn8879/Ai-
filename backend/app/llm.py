"""Server-owned provider configuration. Never accept URLs or keys from players."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    base_url: str
    key: str
    timeout: float
    tokens: int


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
        if not valid or not model or not 1 <= timeout <= 40 or not 64 <= tokens <= 1000:
            raise ValueError("Invalid provider config")
        if name == "openai" and not key.strip():
            raise ValueError("Missing OpenAI key")
    except (ValueError, TypeError):
        raise HTTPException(503, "AI service is not configured correctly") from None
    return Provider(name, model, base, key, timeout, tokens)


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
            "options": {"temperature": 0.8, "num_predict": cfg.tokens, "num_ctx": 8192},
        }
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
