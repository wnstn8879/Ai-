from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_fork_is_independent(account):
    client, _ = account()
    parent = client.post(
        "/rooms",
        json={
            "title": "Kingdom",
            "world_rules": "No resurrection",
            "characters": ["Knight"],
        },
    ).json()
    rid = parent["id"]
    client.post(
        f"/rooms/{rid}/messages", json={"actor": "Knight", "content": "Save the queen"}
    )
    child = client.post(
        f"/rooms/{rid}/forks", json={"title": "Alternate", "message_index": 1}
    ).json()
    client.post(
        f"/rooms/{child['id']}/messages",
        json={"actor": "Knight", "content": "Take another path"},
    )
    assert len(client.get(f"/rooms/{rid}").json()["messages"]) == 1
    assert len(client.get(f"/rooms/{child['id']}").json()["messages"]) == 2


def test_save_resume_from_earlier_point_preserves_original(account):
    client, _ = account()
    room = client.post(
        "/rooms",
        json={
            "title": "Shared",
            "world_rules": "Keep continuity",
            "mode": "multiplayer",
        },
    ).json()
    rid = room["id"]
    client.post(f"/rooms/{rid}/messages", json={"actor": "A", "content": "first"})
    client.post(f"/rooms/{rid}/messages", json={"actor": "B", "content": "second"})
    save = client.post(
        f"/rooms/{rid}/saves", json={"label": "before choice", "message_index": 1}
    ).json()
    assert save["message_index"] == 1
    assert len(client.get(f"/rooms/{rid}/saves").json()) == 1
    resumed = client.post(f"/saves/{save['id']}/resume").json()
    assert resumed["parent_room_id"] == rid
    assert len(resumed["messages"]) == 1
    client.post(
        f"/rooms/{resumed['id']}/messages", json={"actor": "A", "content": "alternate"}
    )
    assert len(client.get(f"/rooms/{rid}").json()["messages"]) == 2
    assert len(client.get(f"/rooms/{resumed['id']}").json()["messages"]) == 2
