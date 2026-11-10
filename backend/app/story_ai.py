"""Server-side story generation. Never expose OPENAI_API_KEY to the mobile app."""

import os
import httpx
from fastapi import HTTPException


async def generate_story(room, messages, instruction):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="AI service is not configured")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    characters = ", ".join(room["characters"]) or "Narrator"
    system = (
        "You are a collaborative interactive fiction narrator. Reply in Korean. "
        "Respect the established world rules and continuity. "
        "Never decide the human player's actions. Keep replies concise, vivid, and safe. "
        f"Story: {room['title']}\nWorld rules: {room['world_rules']}\nCharacters: {characters}"
    )
    history = [
        {
            "role": "assistant" if m["actor"] == "AI" else "user",
            "content": f"{m['actor']}: {m['content']}",
        }
        for m in messages[-30:]
    ]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            *history,
            {"role": "user", "content": instruction},
        ],
        "temperature": 0.8,
        "max_tokens": 500,
    }
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty model response")
            return content.strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="AI generation failed") from exc
