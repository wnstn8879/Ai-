from unittest.mock import AsyncMock, patch


def test_passage_fork_cuts_before_selected_text_and_keeps_original_and_format(account):
    a, _ = account()
    b, _ = account()
    r = a.post(
        "/rooms",
        json={
            "title": "다른 가능성",
            "world_rules": "새로운 우주 무림",
            "narrative_format": "novel",
        },
    ).json()
    prose = "달은 붉었다. 💫\n그는 죽었다.\n마을은 불탔다."
    with patch("app.story_ai.complete", new_callable=AsyncMock, return_value=prose):
        result = a.post(
            "/rooms/" + r["id"] + "/turns", json={"content": "첫 장면"}
        ).json()
    start = prose.index("그는")
    quote = "그는 죽었다."
    body = {
        "message_id": result["ai_message"]["id"],
        "start": start,
        "end": start + len(quote),
        "selected_text": quote,
        "title": "그를 살리는 분기",
    }
    assert b.post("/rooms/" + r["id"] + "/rewrite", json=body).status_code == 404
    child = a.post("/rooms/" + r["id"] + "/rewrite", json=body)
    assert child.status_code == 200, child.text
    child = child.json()
    assert child["narrative_format"] == "novel"
    assert child["messages"][-1]["content"] == prose[:start]
    assert a.get("/rooms/" + r["id"]).json()["messages"][-1]["content"] == prose
    assert child["parent_room_id"] == r["id"]
    assert b.get("/rooms/" + child["id"]).status_code == 404
    bad = {**body, "selected_text": "not the saved passage"}
    assert a.post("/rooms/" + r["id"] + "/rewrite", json=bad).status_code == 400
    assert len(a.get("/rooms").json()) == 2


def test_rewrite_at_start_does_not_copy_later_death_or_accept_user_instruction_as_prose(
    account,
):
    a, _ = account()
    r = a.post(
        "/rooms",
        json={"title": "시작", "world_rules": "상상", "narrative_format": "novel"},
    ).json()
    with patch(
        "app.story_ai.complete", new_callable=AsyncMock, return_value="사라진 인물."
    ):
        result = a.post(
            "/rooms/" + r["id"] + "/turns", json={"content": "작가 지시"}
        ).json()
    body = {
        "message_id": result["ai_message"]["id"],
        "start": 0,
        "end": len("사라진 인물."),
        "selected_text": "사라진 인물.",
        "title": "새 이야기",
    }
    child = a.post("/rooms/" + r["id"] + "/rewrite", json=body).json()
    assert all(m["actor"] != "AI" for m in child["messages"])
    user_id = result["user_message"]["id"]
    assert (
        a.post(
            "/rooms/" + r["id"] + "/rewrite", json={**body, "message_id": user_id}
        ).status_code
        == 400
    )
