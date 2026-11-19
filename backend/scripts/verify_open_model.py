"""Opt-in real model smoke; isolated DB, never prints credentials or tokens."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("AI_PROVIDER") not in {"ollama", "openai_compatible"}:
        raise SystemExit("Explicit AI_PROVIDER=ollama or openai_compatible is required")
    with tempfile.TemporaryDirectory(prefix="imagine-real-model-") as temp:
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temp) / "smoke.db")
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
        from fastapi.testclient import TestClient
        from app.main import app
        from app.llm import configuration

        config = configuration()
        client = TestClient(app)
        account = client.post(
            "/auth/register",
            json={
                "email": str(uuid.uuid4()) + "@example.com",
                "password": "smoke-only-password-123",
                "display_name": "탐험가",
            },
        )
        assert account.status_code == 200, account.text
        client.headers["Authorization"] = "Bearer " + account.json()["access_token"]
        room = client.post(
            "/rooms",
            json={
                "title": "IMAGINE — 봉인된 역",
                "world_rules": "배경: 비가 내리는 오래된 역. 마법은 존재하지 않는다. 사용자가 고르지 않은 행동은 결정하지 않는다.",
                "characters": ["역무원"],
            },
        ).json()
        path = "/rooms/" + room["id"]
        body = {
            "request_id": "real-model-first",
            "content": "문 밖에서 들리는 발소리를 듣고 누구인지 묻는다. 한국어의 짧은 세 문장으로 이어줘.",
        }
        started = time.monotonic()
        turn = client.post(path + "/turns", json=body)
        elapsed = time.monotonic() - started
        assert turn.status_code == 200, turn.text
        original = client.get(path).json()
        assert len(original["messages"]) == 2
        assert client.post(path + "/turns", json=body).json() == turn.json()
        point = client.post(
            path + "/saves", json={"label": "실제 모델 응답 뒤", "message_index": 2}
        ).json()
        child = client.post("/saves/" + point["id"] + "/resume").json()
        assert len(child["messages"]) == 2
        assert child["messages"][-1]["content"] == original["messages"][-1]["content"]
        client.post(
            "/rooms/" + child["id"] + "/messages", json={"content": "다른 길로 간다"}
        )
        assert len(client.get(path).json()["messages"]) == 2
        report = {
            "success": True,
            "provider": config.name,
            "model": config.model,
            "elapsed_seconds": round(elapsed, 2),
            "reply": turn.json()["ai_message"]["content"],
            "checks": [
                "real inference through authenticated turns API",
                "atomic user + AI persistence",
                "same request id returns stored result",
                "checkpoint + branch preserve model response",
                "original history unchanged",
            ],
            "public_deployment": False,
            "mobile_device_tested": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
