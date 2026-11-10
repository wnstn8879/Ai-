import time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app, Session, Message
from app.security import User, UserSession, digest


def room(c):
    return c.post(
        "/rooms",
        json={"title": "Private", "world_rules": "Keep choices", "mode": "multiplayer"},
    ).json()


def test_isolation_and_branch(account):
    a, _ = account("Alice")
    b, _ = account("Bob")
    rid = room(a)["id"]
    assert TestClient(app).get("/rooms").status_code == 401
    assert b.get("/rooms").json() == []
    for path, method, body in [
        (f"/rooms/{rid}", "GET", None),
        (f"/rooms/{rid}/messages", "POST", {"actor": "B", "content": "intrusion"}),
        (f"/rooms/{rid}/saves", "GET", None),
        (f"/rooms/{rid}/forks", "POST", {"title": "stolen", "message_index": 0}),
        (f"/rooms/{rid}/turns", "POST", {"content": "stolen"}),
    ]:
        assert b.request(method, path, json=body).status_code == 404
    a.post(f"/rooms/{rid}/messages", json={"actor": "A", "content": "original"})
    save = a.post(f"/rooms/{rid}/saves", json={}).json()
    assert b.post("/saves/" + save["id"] + "/resume").status_code == 404
    code = a.post(f"/rooms/{rid}/invitations").json()["code"]
    assert b.post("/invitations/join", json={"code": code}).status_code == 200
    assert b.post("/invitations/join", json={"code": code}).status_code == 404
    assert b.post(f"/rooms/{rid}/invitations").status_code == 403
    assert b.get(f"/rooms/{rid}/saves").json() == []
    fork = b.post(
        f"/rooms/{rid}/forks", json={"title": "Personal", "message_index": 1}
    ).json()
    assert fork["mode"] == "solo"
    assert a.get("/rooms/" + fork["id"]).status_code == 404
    b.post(
        "/rooms/" + fork["id"] + "/messages",
        json={"actor": "B", "content": "different"},
    )
    assert len(a.get("/rooms/" + rid).json()["messages"]) == 1
    assert b.post(f"/rooms/{rid}/leave").status_code == 200
    assert b.get(f"/rooms/{rid}").status_code == 404


def test_sessions(account):
    c, data = account()
    with Session() as db:
        u = db.get(User, data["user"]["id"])
        assert u.password_hash != "test-password-123"
        s = db.scalar(select(UserSession).where(UserSession.user_id == u.id))
        assert s.access_hash == digest(data["access_token"])
        assert s.refresh_hash != data["refresh_token"]
    new = c.post("/auth/refresh", json={"refresh_token": data["refresh_token"]}).json()
    assert c.get("/auth/me").status_code == 401
    assert (
        c.post(
            "/auth/refresh", json={"refresh_token": data["refresh_token"]}
        ).status_code
        == 401
    )
    c.headers["Authorization"] = "Bearer " + new["access_token"]
    assert c.get("/auth/me").status_code == 200
    assert c.post("/auth/logout").status_code == 200
    assert c.get("/auth/me").status_code == 401
    assert (
        c.post(
            "/auth/refresh", json={"refresh_token": new["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        c.post(
            "/auth/login",
            json={"email": data["user"]["email"], "password": "wrong-password"},
        ).status_code
        == 401
    )
    login = c.post(
        "/auth/login",
        json={"email": data["user"]["email"].upper(), "password": "test-password-123"},
    ).json()
    c.headers["Authorization"] = "Bearer " + login["access_token"]
    with Session.begin() as db:
        s = db.scalar(
            select(UserSession).where(
                UserSession.access_hash == digest(login["access_token"])
            )
        )
        s.access_expires = int(time.time()) - 1
    assert c.get("/auth/me").status_code == 401


def test_friend_and_owner_permissions(account):
    a, alice = account("Alice")
    b, bob = account("Bob")
    c, _ = account("Carol")
    bid = bob["user"]["id"]
    aid = alice["user"]["id"]
    assert a.post("/friends/requests", json={"user_id": aid}).status_code == 400
    assert a.post("/friends/requests", json={"user_id": bid}).status_code == 200
    assert (
        a.post(
            "/friends/requests/" + bid + "/respond", json={"accept": True}
        ).status_code
        == 404
    )
    assert (
        c.post(
            "/friends/requests/" + aid + "/respond", json={"accept": True}
        ).status_code
        == 404
    )
    assert b.get("/friends").json()[0]["incoming"]
    assert (
        b.post(
            "/friends/requests/" + aid + "/respond", json={"accept": True}
        ).status_code
        == 200
    )
    assert a.get("/friends").json()[0]["status"] == "accepted"
    assert "email" not in a.get("/users?q=Bob").json()[0]
    rid = room(a)["id"]
    code = a.post(f"/rooms/{rid}/invitations").json()["code"]
    b.post("/invitations/join", json={"code": code})
    assert (
        b.put(f"/rooms/{rid}/members/{aid}", json={"character": "King"}).status_code
        == 403
    )
    assert (
        a.put(f"/rooms/{rid}/members/{bid}", json={"character": "Knight"}).status_code
        == 200
    )
    assert any(
        m["character"] == "Knight" for m in b.get(f"/rooms/{rid}/members").json()
    )


def test_concurrent_order(account):
    a, _ = account()
    rid = room(a)["id"]

    def send(i):
        return a.post(f"/rooms/{rid}/messages", json={"actor": "A", "content": str(i)})

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert all(r.status_code == 200 for r in pool.map(send, range(12)))
    with Session() as db:
        messages = db.scalars(
            select(Message).where(Message.room_id == rid).order_by(Message.position)
        ).all()
        assert [m.position for m in messages] == list(range(12))


def test_idempotent_message_and_conflicting_reuse(account):
    a, _ = account()
    rid = room(a)["id"]
    body = {"actor": "A", "content": "Once", "request_id": "retry-1"}
    first = a.post(f"/rooms/{rid}/messages", json=body)
    assert first.status_code == 200
    assert a.post(f"/rooms/{rid}/messages", json=body).json() == first.json()
    assert (
        a.post(
            f"/rooms/{rid}/messages", json={**body, "content": "Changed"}
        ).status_code
        == 409
    )
    assert len(a.get(f"/rooms/{rid}").json()["messages"]) == 1


def test_websocket_auth_snapshot_and_logout(account):
    from starlette.websockets import WebSocketDisconnect
    import pytest

    a, data = account()
    b, other = account()
    rid = room(a)["id"]
    with a.websocket_connect(f"/rooms/{rid}/live") as socket:
        socket.send_json({"access_token": data["access_token"]})
        assert socket.receive_json()["room"]["id"] == rid
        a.post(f"/rooms/{rid}/messages", json={"actor": "A", "content": "Live"})
        socket.send_text("sync")
        assert len(socket.receive_json()["room"]["messages"]) == 1
        a.post("/auth/logout")
        socket.send_text("sync")
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    with b.websocket_connect(f"/rooms/{rid}/live") as socket:
        socket.send_json({"access_token": other["access_token"]})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


def test_recent_rooms_and_multiplayer_actor_are_account_scoped(account):
    a, alice = account("Alice")
    b, bob = account("Bob")
    first = room(a)["id"]
    second = room(a)["id"]
    a.get("/rooms/" + first)
    assert a.get("/rooms").json()[0]["id"] == first
    code = a.post(f"/rooms/{first}/invitations").json()["code"]
    b.post("/invitations/join", json={"code": code})
    result = b.post(
        f"/rooms/{first}/messages",
        json={"actor": "Alice", "content": "Cannot impersonate"},
    )
    assert result.json()["actor"] == "Bob"
    assert [r["id"] for r in b.get("/rooms").json()] == [first]
