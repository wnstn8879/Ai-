from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_ai_turn_is_persisted_and_branchable(account):
    client, _ = account()
    room = client.post(
        "/rooms", json={"title": "AI Story", "world_rules": "No time travel"}
    ).json()
    with patch(
        "app.story_ai.generate_story",
        new_callable=AsyncMock,
        return_value="문이 열렸다.",
    ) as mock:
        result = client.post(
            f"/rooms/{room['id']}/turns", json={"actor": "나", "content": "문을 연다"}
        )
    assert result.status_code == 200, result.text
    assert result.json()["ai_message"]["content"] == "문이 열렸다."
    assert mock.await_count == 1
    history = client.get(f"/rooms/{room['id']}").json()["messages"]
    assert [m["actor"] for m in history] == ["나", "AI"]
    checkpoint = client.post(
        f"/rooms/{room['id']}/saves", json={"label": "AI reply", "message_index": 2}
    ).json()
    restored = client.post(f"/saves/{checkpoint['id']}/resume").json()
    assert len(restored["messages"]) == 2


def test_failed_ai_does_not_commit_user_turn(account):
    client, _ = account()
    from fastapi import HTTPException

    room = client.post(
        "/rooms", json={"title": "Failure", "world_rules": "Keep history"}
    ).json()
    with patch(
        "app.story_ai.generate_story",
        new_callable=AsyncMock,
        side_effect=HTTPException(503, "Not configured"),
    ):
        result = client.post(
            f"/rooms/{room['id']}/turns", json={"actor": "나", "content": "시작"}
        )
    assert result.status_code == 503
    assert client.get(f"/rooms/{room['id']}").json()["messages"] == []


def test_daily_quota_and_completed_retry(account, monkeypatch):
    client, _ = account()
    monkeypatch.setenv("AI_USER_DAILY_LIMIT", "1")
    room = client.post(
        "/rooms", json={"title": "Budget", "world_rules": "Keep story"}
    ).json()
    body = {"content": "Start", "request_id": "one-turn"}
    with patch(
        "app.story_ai.generate_story", new_callable=AsyncMock, return_value="Reply"
    ) as provider:
        first = client.post(f"/rooms/{room['id']}/turns", json=body)
        assert first.status_code == 200
        assert (
            client.post(f"/rooms/{room['id']}/turns", json=body).json() == first.json()
        )
        assert provider.await_count == 1
        assert (
            client.post(
                f"/rooms/{room['id']}/turns",
                json={"content": "Again", "request_id": "another"},
            ).status_code
            == 429
        )
    assert len(client.get(f"/rooms/{room['id']}").json()["messages"]) == 2


def test_ai_response_rejected_if_story_changed(account):
    client, _ = account()
    room = client.post(
        "/rooms", json={"title": "Concurrent", "world_rules": "Keep continuity"}
    ).json()

    async def changed(*args):
        # A second writer commits while the external model is generating.
        from app.main import Session, Message, uid, now

        with Session.begin() as db:
            db.add(
                Message(
                    id=uid(),
                    room_id=room["id"],
                    position=0,
                    actor="Other",
                    content="New event",
                    created_at=now(),
                )
            )
        return "Stale response"

    with patch("app.story_ai.generate_story", side_effect=changed):
        response = client.post(f"/rooms/{room['id']}/turns", json={"content": "Start"})
    assert response.status_code == 409
    assert len(client.get(f"/rooms/{room['id']}").json()["messages"]) == 1
