import copy
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch


def create(client, mode="solo"):
    response = client.post(
        "/rooms",
        json={
            "title": "Kingdom",
            "world_rules": "Magic has a cost",
            "characters": ["Knight"],
            "mode": mode,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def state(client, rid):
    return client.get(f"/rooms/{rid}/state").json()


def update(client, rid, current, **changes):
    body = copy.deepcopy(current["state"])
    body.update(changes)
    return client.put(
        f"/rooms/{rid}/state",
        json={"base_revision": current["revision"], "state": body},
    )


def test_checkpoint_pins_exact_state_at_same_message_boundary(account):
    client, _ = account()
    rid = create(client)
    initial = state(client, rid)
    assert initial["state"]["characters"][0]["name"] == "Knight"
    first = update(
        client, rid, initial, location="Castle", summary="The gate is closed"
    ).json()
    saved = client.post(f"/rooms/{rid}/saves", json={}).json()
    latest = update(client, rid, first, location="Forest", summary="A new route").json()
    assert latest["revision"] == 2
    resumed = client.post("/saves/" + saved["id"] + "/resume").json()
    assert resumed["story_state"]["location"] == "Castle"
    assert client.get("/rooms/" + rid).json()["story_state"]["location"] == "Forest"
    assert len(client.get("/rooms/" + resumed["id"] + "/state/history").json()) == 2


def test_forks_restore_historical_memories_and_keep_history(account):
    client, _ = account()
    rid = create(client)
    client.post(
        f"/rooms/{rid}/messages", json={"actor": "Knight", "content": "Visit castle"}
    )
    current = state(client, rid)
    characters = copy.deepcopy(current["state"]["characters"])
    characters[0].update(
        personality="Patient",
        speech_style="Formal",
        goal="Save queen",
        relationships="Queen is an ally",
        condition="Injured",
        memories=["Queen gave me a key"],
    )
    update(client, rid, current, location="Castle", characters=characters)
    client.post(
        f"/rooms/{rid}/messages", json={"actor": "Knight", "content": "Reach forest"}
    )
    current = state(client, rid)
    changed = copy.deepcopy(characters)
    changed[0]["memories"].append("Found a dragon")
    update(client, rid, current, location="Forest", characters=changed)
    child = client.post(
        f"/rooms/{rid}/forks", json={"title": "Alternate", "message_index": 1}
    ).json()
    assert child["story_state"]["location"] == "Castle"
    assert child["story_state"]["characters"][0]["memories"] == ["Queen gave me a key"]
    grandchild = client.post(
        "/rooms/" + child["id"] + "/forks",
        json={"title": "Earlier", "message_index": 0},
    ).json()
    assert grandchild["story_state"]["location"] == ""
    assert grandchild["story_state"]["characters"][0]["memories"] == []
    assert len(client.get("/rooms/" + rid).json()["messages"]) == 2
    assert client.get("/rooms/" + rid).json()["story_state"]["location"] == "Forest"


def test_state_permissions_stale_updates_and_input_validation(account):
    owner, _ = account()
    member, _ = account()
    outsider, _ = account()
    rid = create(owner, "multiplayer")
    current = state(owner, rid)
    assert outsider.get(f"/rooms/{rid}/state").status_code == 404
    assert outsider.get(f"/rooms/{rid}/state/history").status_code == 404
    code = owner.post(f"/rooms/{rid}/invitations").json()["code"]
    member.post("/invitations/join", json={"code": code})
    assert member.get(f"/rooms/{rid}/state").status_code == 200
    assert update(member, rid, current, location="Stolen").status_code == 403
    assert update(owner, rid, current, location="Castle").status_code == 200
    assert update(owner, rid, current, location="Stale").status_code == 409
    fresh = state(owner, rid)
    assert (
        update(
            owner, rid, fresh, characters=[{"name": "Knight"}, {"name": " knight "}]
        ).status_code
        == 422
    )
    assert update(owner, rid, fresh, facts=["x" * 301]).status_code == 422
    assert update(owner, rid, fresh, world_rules=" ").status_code == 422
    personal = member.post(
        f"/rooms/{rid}/forks", json={"title": "Mine", "message_index": 0}
    ).json()
    assert owner.get("/rooms/" + personal["id"] + "/state").status_code == 404
    assert (
        update(
            member, personal["id"], state(member, personal["id"]), location="Personal"
        ).status_code
        == 200
    )
    assert state(owner, rid)["state"]["location"] == "Castle"


def test_concurrent_state_writers_cannot_overwrite_each_other(account):
    client, _ = account()
    rid = create(client)
    current = state(client, rid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda location: update(client, rid, current, location=location),
                ["Castle", "Forest"],
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert len(client.get(f"/rooms/{rid}/state/history").json()) == 2


def test_state_change_during_ai_generation_rejects_stale_response(account):
    client, _ = account()
    rid = create(client)

    async def changed(*args):
        from app.database import Session
        from app.story_state import snapshot_at, add_snapshot

        with Session.begin() as db:
            current = snapshot_at(db, rid)
            data = json.loads(current.state_json)
            data["location"] = "Changed during generation"
            add_snapshot(db, rid, 0, data, current.revision + 1)
        return "Outdated reply"

    with patch("app.story_ai.generate_story", side_effect=changed):
        response = client.post(f"/rooms/{rid}/turns", json={"content": "Start"})
    assert response.status_code == 409
    room = client.get("/rooms/" + rid).json()
    assert room["messages"] == []
    assert room["story_state"]["location"] == "Changed during generation"


def test_ai_receives_character_context_from_restored_snapshot(account, monkeypatch):
    import httpx
    from app.story_ai import httpx as provider_http

    client, _ = account()
    rid = create(client)
    current = state(client, rid)
    characters = current["state"]["characters"]
    characters[0].update(
        speech_style="Speak formally", memories=["Queen gave me a key"]
    )
    update(client, rid, current, characters=characters, location="Castle")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "The knight remembers the key."}}]
            },
        )

    original = provider_http.AsyncClient
    with patch(
        "app.story_ai.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    ):
        result = client.post(
            f"/rooms/{rid}/turns", json={"content": "What do I remember?"}
        )
    assert result.status_code == 200, result.text
    system = payloads[0]["messages"][0]["content"]
    assert (
        "Queen gave me a key" in system
        and "Speak formally" in system
        and "Castle" in system
    )
    assert "Never decide" in system


def test_new_worlds_cannot_create_uneditable_character_state(account):
    client, _ = account()
    for changes in [
        {"characters": ["Knight", " knight "]},
        {"characters": ["x" * 121]},
        {"world_rules": " "},
        {"characters": [" "]},
    ]:
        response = client.post(
            "/rooms",
            json={"title": "Invalid", "world_rules": "Keep continuity", **changes},
        )
        assert response.status_code == 422, response.text
