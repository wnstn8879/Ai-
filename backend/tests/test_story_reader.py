from unittest.mock import AsyncMock, patch
from app.database import Session, Room
from test_story_memory import seed, novel


def test_paged_reading_and_compact_branch_preserve_order_without_loading_whole_book(
    account,
):
    a, _ = account()
    b, _ = account()
    rid = novel(a)
    path = "/rooms/" + rid
    rows = seed(rid, 121)
    latest = a.get(path + "/chapters").json()
    assert latest["message_count"] == 121 and len(latest["messages"]) == 30
    positions = [m["position"] for m in latest["messages"]]
    cursor = latest["next_before"]
    while cursor is not None:
        page = a.get(path + "/chapters", params={"before_position": cursor}).json()
        positions = [m["position"] for m in page["messages"]] + positions
        cursor = page["next_before"]
    assert positions == list(range(121))
    assert b.get(path + "/chapters").status_code == 404
    save = a.post(path + "/saves", json={"label": "저장", "message_index": 120}).json()
    child = a.post("/saves/" + save["id"] + "/resume?compact=true").json()
    assert child["message_count"] == 120 and len(child["messages"]) == 30
    assert a.get(path).json()["messages"][-1]["id"] == rows[-1]["id"]


def test_library_cursor_is_private_and_returns_summaries_not_entire_histories(account):
    a, _ = account()
    b, _ = account()
    ids = [novel(a) for _ in range(23)]
    seed(ids[0], 50)
    # Same creation timestamps must still page deterministically by room ID.
    with Session.begin() as db:
        for rid in ids:
            db.get(Room, rid).created_at = "2026-01-01T00:00:00"
    first = a.get("/library").json()
    assert len(first["items"]) == 20
    second = a.get("/library", params={"cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 3 and second["next_cursor"] is None
    all_items = first["items"] + second["items"]
    assert {r["id"] for r in all_items} == set(ids)
    assert all("messages" not in r and len(r["excerpt"]) <= 160 for r in all_items)
    assert b.get("/library").json()["items"] == []
    assert b.get("/library", params={"cursor": ids[0]}).status_code == 404
