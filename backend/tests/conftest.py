import os
import tempfile
from pathlib import Path
from uuid import uuid4

_tmp = tempfile.TemporaryDirectory(prefix="storyverse-tests-")
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or "sqlite:///" + str(
    Path(_tmp.name) / "test.db"
)
from alembic import command
from alembic.config import Config

command.upgrade(Config("alembic.ini"), "head")
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.security import _attempts


@pytest.fixture(autouse=True)
def clear_throttle():
    _attempts.clear()


@pytest.fixture
def account():
    def make(name="Player"):
        c = TestClient(app)
        response = c.post(
            "/auth/register",
            json={
                "email": str(uuid4()) + "@example.com",
                "password": "test-password-123",
                "display_name": name,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        c.headers["Authorization"] = "Bearer " + data["access_token"]
        return c, data

    return make
