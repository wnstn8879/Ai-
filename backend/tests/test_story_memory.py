import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, func
from app.database import Session, Message, MemoryChunk, MemoryCursor, uid, now
from app.security import AIUsage
from app.story_memory import BATCH_SIZE


def seed(room_id, count, special=None):
    rows = [
        {
            "id": uid(),
            "room_id": room_id,
            "position": i,
            "actor": "AI" if i % 2 else "작가",
            "created_at": now(),
            "content": (special or {}).get(
                i, "정거장의 불빛이 보였고 두 사람은 잠시 쉬었다."
            ),
        }
        for i in range(count)
    ]
    with Session.begin() as db:
        db.execute(Message.__table__.insert(), rows)
    return rows


def novel(client):
    return client.post(
        "/rooms",
        json={
            "title": "장편",
            "world_rules": "서연은 별빛 열쇠를 지킨다.",
            "narrative_format": "novel",
        },
    ).json()["id"]


def index_all(client, path):
    for _ in range(100):
        response = client.post(path + "/memory/index")
        assert response.status_code == 200, response.text
        result = response.json()
        if result["ready"]:
            return result
    raise AssertionError("Index did not finish")


def test_3000_record_novel_recalls_old_source_with_bounded_model_input(account):
    a, _ = account()
    b, _ = account()
    rid = novel(a)
    path = "/rooms/" + rid
    promise = "💫 서연은 별빛 열쇠를 동생에게만 맡기겠다고 약속했다."
    rows = seed(rid, 3000, {1: promise})
    # The first pass commits progress, but never spends a model call on incomplete recall.
    with patch("app.story_ai.complete", new_callable=AsyncMock) as provider:
        incomplete = a.post(
            path + "/turns", json={"content": "별빛 열쇠 약속을 떠올려줘"}
        )
    assert incomplete.status_code == 409 and provider.await_count == 0
    assert index_all(a, path)["indexed_messages"] == 3000
    results = a.post(
        path + "/memory/search", json={"query": "서연이 별빛 열쇠를 맡긴 약속"}
    ).json()["results"]
    assert results and any(
        r["message_id"] == rows[1]["id"] and r["quote"] == promise for r in results
    )
    assert b.post(path + "/memory/search", json={"query": "별빛"}).status_code == 404
    assert b.post(path + "/memory/index").status_code == 404
    with patch(
        "app.story_ai.complete",
        new_callable=AsyncMock,
        return_value="서연은 동생에게 했던 약속을 떠올렸다.",
    ) as provider:
        response = a.post(
            path + "/turns",
            json={
                "content": "서연의 별빛 열쇠 약속을 떠올려줘",
                "request_id": "long-turn",
            },
        )
        assert response.status_code == 200, response.text
        first = response.json()
        assert (
            a.post(
                path + "/turns",
                json={
                    "content": "서연의 별빛 열쇠 약속을 떠올려줘",
                    "request_id": "long-turn",
                },
            ).json()
            == first
        )
        assert provider.await_count == 1
    report = first["context_report"]
    prompt = provider.call_args.args[0]
    assert (
        report["total_messages"] == 3000
        and report["input_utf8_bound"] <= report["input_budget"]
    )
    assert promise in prompt[0]["content"]
    assert len(prompt) <= 32
    assert report["history_messages_not_in_recent"] >= 2970
    with Session() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Message).where(Message.room_id == rid)
            )
            == 3002
        )


def test_index_restart_and_concurrent_batches_do_not_duplicate_quotes(account):
    a, _ = account()
    rid = novel(a)
    path = "/rooms/" + rid
    rows = seed(rid, BATCH_SIZE * 2 + 7, {1: "서연은 나침반을 보관했다."})
    # Two real request threads serialize on the same room; new DB sessions see progress.
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: a.post(path + "/memory/index"), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert index_all(a, path)["ready"]
    with Session() as db:
        assert db.get(MemoryCursor, rid).next_position == len(rows)
        assert db.scalar(
            select(func.count())
            .select_from(MemoryChunk)
            .where(MemoryChunk.room_id == rid)
        ) == len(rows)
    before = a.post(path + "/memory/search", json={"query": "나침반"}).json()
    a.post(path + "/memory/index")
    assert a.post(path + "/memory/search", json={"query": "나침반"}).json() == before


def test_branch_and_checkpoint_recall_never_include_parent_future_or_cut_suffix(
    account,
):
    a, _ = account()
    b, _ = account()
    rid = novel(a)
    path = "/rooms/" + rid
    text = "서연은 은빛 나침반을 받았다. 💫 금빛 폭발로 항구가 무너졌다."
    rows = seed(rid, 4, {1: text, 3: "붉은별비밀은 서연이 배신자라는 사실이다."})
    index_all(a, path)
    point = a.post(path + "/saves", json={"label": "과거", "message_index": 2}).json()
    start = text.index("금빛")
    child = a.post(
        path + "/rewrite?compact=true",
        json={
            "title": "항구를 구하는 길",
            "message_id": rows[1]["id"],
            "start": start,
            "end": len(text),
            "selected_text": text[start:],
        },
    ).json()
    child_path = "/rooms/" + child["id"]
    index_all(a, child_path)
    assert not a.post(
        child_path + "/memory/search", json={"query": "붉은별비밀 금빛 폭발"}
    ).json()["results"]
    found = a.post(child_path + "/memory/search", json={"query": "나침반"}).json()[
        "results"
    ]
    assert found and found[0]["quote"] == text[:start]
    assert found[0]["message_id"] != rows[1]["id"]
    assert b.get(child_path + "/chapters").status_code == 404
    restored = a.post("/saves/" + point["id"] + "/resume?compact=true").json()
    restored_path = "/rooms/" + restored["id"]
    index_all(a, restored_path)
    assert not a.post(
        restored_path + "/memory/search", json={"query": "붉은별비밀"}
    ).json()["results"]
    assert a.post(path + "/memory/search", json={"query": "붉은별비밀"}).json()[
        "results"
    ]


def test_oversized_canon_is_not_silently_cut_or_charged(account, monkeypatch):
    a, _ = account()
    rid = novel(a)
    path = "/rooms/" + rid
    state = a.get(path).json()
    state["story_state"]["world_rules"] = "확정한 규칙을 임의로 생략하지 않는다. " * 500
    assert (
        a.put(
            path + "/state", json={"base_revision": 0, "state": state["story_state"]}
        ).status_code
        == 200
    )
    with patch("app.story_ai.complete", new_callable=AsyncMock) as provider:
        response = a.post(path + "/turns", json={"content": "시작해줘"})
    assert response.status_code == 422 and provider.await_count == 0
    assert a.get(path).json()["messages"] == []
    with Session() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(AIUsage).where(AIUsage.room_id == rid)
            )
            == 0
        )
