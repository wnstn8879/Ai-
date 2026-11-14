import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.story_ai import generate_story, scene_pacing


@pytest.mark.parametrize("count,beat", [(0, 1), (3, 4), (4, 5), (5, 1), (34, 5)])
def test_scene_pacing_counts_ai_replies_and_allows_continuing(count, beat):
    history = [{"actor": "AI", "content": "장면"} for _ in range(count)] + [
        {"actor": "사용자", "content": "행동"} for _ in range(7)
    ]
    prompt = scene_pacing(history)
    assert f"{beat}/5" in prompt
    assert ("natural pause now" in prompt) == (beat >= 4)
    assert "Never invent a player decision" in prompt
    assert "not a time limit" in prompt
    assert "for as long as they want" in prompt


def test_provider_receives_pacing_from_full_history_and_preserves_user_request(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    room = {
        "title": "출근길 이야기",
        "world_rules": "사용자 선택을 존중한다",
        "characters": ["탐정"],
        "story_state": {"location": "기차역"},
    }
    history = [{"actor": "AI", "content": f"장면 {i}"} for i in range(34)]
    request = "결정하지 않은 행동은 남기고 짧게 마무리해줘"
    response = Mock()
    response.json.return_value = {
        "choices": [{"message": {"content": "잠시 숨을 돌렸다."}}]
    }
    with patch("app.story_ai.httpx.AsyncClient") as factory:
        client = factory.return_value.__aenter__.return_value
        client.post = AsyncMock(return_value=response)
        assert (
            asyncio.run(generate_story(room, history, request)) == "잠시 숨을 돌렸다."
        )
        payload = client.post.call_args.kwargs["json"]
    assert len(payload["messages"]) == 32
    system = payload["messages"][0]["content"]
    assert "5/5" in system
    assert "기차역" in system
    assert "never" in system.lower()
    assert "claim that anything was saved" in system
    assert payload["messages"][-1] == {"role": "user", "content": request}
