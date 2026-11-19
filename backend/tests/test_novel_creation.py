from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.story_ai import generate_story


@pytest.mark.parametrize(
    "concept",
    [
        "김치 발효로 내공을 쌓는 무협 세계에서 총을 쓰는 좀비가 우주 던전을 탐험한다. 주인공은 잃어버린 동생을 찾고 싶다.",
        "기억을 화폐로 쓰는 해저 도시에 사는 별의 정원사. 장르는 아직 이름이 없다.",
        "매주 목요일 중력이 편지가 되는 마을의 로맨스. 결말은 아직 정하지 않는다.",
    ],
)
def test_free_concept_reaches_prose_prompt_without_genre_or_short_game_template(
    concept,
):
    room = {
        "title": "새로운 상상",
        "world_rules": concept,
        "characters": [],
        "story_state": {},
        "narrative_format": "novel",
    }
    import asyncio

    with patch(
        "app.story_ai.complete",
        new_callable=AsyncMock,
        return_value="이야기가 시작됐다.",
    ) as model:
        assert (
            asyncio.run(generate_story(room, [], "첫 장면을 써줘"))
            == "이야기가 시작됐다."
        )
    messages = model.call_args.args[0]
    assert concept in messages[0]["content"]
    assert "preserve every unusual combination" in messages[0]["content"]
    assert "emotional consequences" in messages[0]["content"]
    assert "five AI replies" not in messages[0]["content"]
    assert "3-6 short" not in messages[0]["content"]
    assert messages[-1]["content"] == "첫 장면을 써줘"


def test_novel_concept_chapters_saves_and_format_are_private_and_branchable(account):
    a, _ = account("Author")
    b, _ = account("Other")
    concept = "김치 마스터와 총을 쏘는 좀비가 우주 무림을 탐험한다. 낯선 조합을 없애지 않는다."
    r = a.post(
        "/rooms",
        json={
            "title": "우주 무림의 김치",
            "world_rules": concept,
            "narrative_format": "novel",
        },
    ).json()
    path = "/rooms/" + r["id"]
    assert r["narrative_format"] == "novel" and r["world_rules"] == concept
    assert b.get(path).status_code == 404
    assert b.get("/rooms").json() == []
    with patch(
        "app.story_ai.complete",
        new_callable=AsyncMock,
        return_value="발효통의 진동 속에서 서연은 동생의 목소리를 들었다.\n\n좀비가 총구를 내렸다.",
    ):
        reply = a.post(
            path + "/turns",
            json={
                "content": "첫 소설 장면을 써줘",
                "actor": "작가",
                "request_id": "novel-first",
            },
        )
    assert reply.status_code == 200, reply.text
    point = a.post(
        path + "/saves", json={"label": "첫 장면 뒤", "message_index": 2}
    ).json()
    child = a.post("/saves/" + point["id"] + "/resume").json()
    assert child["narrative_format"] == "novel"
    assert child["world_rules"] == concept
    assert child["messages"][-1]["content"] == reply.json()["ai_message"]["content"]
    assert b.get("/rooms/" + child["id"]).status_code == 404
    with patch(
        "app.story_ai.complete",
        new_callable=AsyncMock,
        return_value="다른 로맨스 장면.",
    ):
        assert (
            a.post(
                "/rooms/" + child["id"] + "/turns",
                json={"content": "좀비와 서연의 신뢰가 로맨스로 이어지게 해줘"},
            ).status_code
            == 200
        )
    assert len(a.get(path).json()["messages"]) == 2
    assert len(a.get("/rooms/" + child["id"]).json()["messages"]) == 4


def test_failed_novel_generation_preserves_concept_without_partial_chapter(account):
    a, _ = account()
    r = a.post(
        "/rooms",
        json={
            "title": "상상",
            "world_rules": "이름 없는 장르의 세계",
            "narrative_format": "novel",
        },
    ).json()
    with patch(
        "app.story_ai.complete",
        new_callable=AsyncMock,
        side_effect=HTTPException(502, "model unavailable"),
    ):
        assert (
            a.post(
                "/rooms/" + r["id"] + "/turns", json={"content": "첫 장면"}
            ).status_code
            == 502
        )
    saved = a.get("/rooms/" + r["id"]).json()
    assert saved["world_rules"] == r["world_rules"] and saved["messages"] == []


def test_existing_room_format_defaults_to_roleplay_and_unknown_formats_are_rejected(
    account,
):
    a, _ = account()
    assert (
        a.post("/rooms", json={"title": "기존방", "world_rules": "규칙"}).json()[
            "narrative_format"
        ]
        == "roleplay"
    )
    assert (
        a.post(
            "/rooms",
            json={"title": "방", "world_rules": "규칙", "narrative_format": "unknown"},
        ).status_code
        == 422
    )
