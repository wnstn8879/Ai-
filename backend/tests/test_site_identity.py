from fastapi.testclient import TestClient
from app.main import app


def test_bridge_requires_secret_and_keeps_visitors_separate(monkeypatch):
    monkeypatch.setenv(
        "IMAGINE_SITE_SERVICE_KEY", "test-site-service-key-with-at-least-32-bytes"
    )
    monkeypatch.setenv("IMAGINE_SITE_ID", "test-private-site")
    a = TestClient(app)
    b = TestClient(app)
    a.headers.update(
        {
            "x-imagine-service-key": "test-site-service-key-with-at-least-32-bytes",
            "x-imagine-visitor": "alice",
        }
    )
    b.headers.update(
        {
            "x-imagine-service-key": "test-site-service-key-with-at-least-32-bytes",
            "x-imagine-visitor": "bob",
        }
    )
    assert (
        TestClient(app)
        .get("/rooms", headers={"x-imagine-visitor": "alice"})
        .status_code
        == 401
    )
    room = a.post(
        "/rooms",
        json={
            "title": "Private novel",
            "world_rules": "Original concept",
            "narrative_format": "novel",
        },
    ).json()
    assert a.get("/rooms/" + room["id"]).status_code == 200
    assert b.get("/rooms/" + room["id"]).status_code == 404
    assert b.get("/rooms").json() == []
    c = TestClient(app)
    c.headers.update(a.headers)
    assert c.get("/rooms").json()[0]["id"] == room["id"]


def test_gateway_mode_blocks_public_registration_and_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("IMAGINE_WEB_GATEWAY_ONLY", "1")
    monkeypatch.setenv(
        "IMAGINE_SITE_SERVICE_KEY", "test-site-service-key-with-at-least-32-bytes"
    )
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.post("/auth/register", json={}).status_code == 401
    assert c.get("/rooms", headers={"x-imagine-visitor": "alice"}).status_code == 401
