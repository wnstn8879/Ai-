from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_ai_turn_is_persisted_and_branchable():
    room = client.post("/rooms", json={"title":"AI Story","world_rules":"No time travel"}).json()
    with patch("app.story_ai.generate_story", new_callable=AsyncMock, return_value="문이 열렸다.") as mock:
        result = client.post(f"/rooms/{room['id']}/turns", json={"actor":"나","content":"문을 연다"})
    assert result.status_code == 200, result.text
    assert result.json()["ai_message"]["content"] == "문이 열렸다."
    assert mock.await_count == 1
    history = client.get(f"/rooms/{room['id']}").json()["messages"]
    assert [m["actor"] for m in history] == ["나","AI"]
    checkpoint = client.post(f"/rooms/{room['id']}/saves",json={"label":"AI reply","message_index":2}).json()
    restored = client.post(f"/saves/{checkpoint['id']}/resume").json()
    assert len(restored["messages"]) == 2

def test_failed_ai_does_not_commit_user_turn():
    from fastapi import HTTPException
    room = client.post("/rooms", json={"title":"Failure","world_rules":"Keep history"}).json()
    with patch("app.story_ai.generate_story", new_callable=AsyncMock, side_effect=HTTPException(503,"Not configured")):
        result = client.post(f"/rooms/{room['id']}/turns", json={"actor":"나","content":"시작"})
    assert result.status_code == 503
    assert client.get(f"/rooms/{room['id']}").json()["messages"] == []
