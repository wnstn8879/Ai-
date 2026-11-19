import time
from concurrent.futures import ThreadPoolExecutor
import pytest


def setup_group(account, extra=1):
    owner, owner_data = account("Owner")
    rid = owner.post(
        "/rooms",
        json={
            "title": "Shared Kingdom",
            "world_rules": "Keep original",
            "characters": ["Knight"],
            "mode": "multiplayer",
        },
    ).json()["id"]
    participants = []
    for index in range(extra):
        client, data = account("Player" + str(index))
        code = owner.post(f"/rooms/{rid}/invitations").json()["code"]
        assert client.post("/invitations/join", json={"code": code}).status_code == 200
        participants.append((client, data))
    return owner, owner_data, rid, participants


def save(owner, rid, scope="shared"):
    response = owner.post(
        f"/rooms/{rid}/saves", json={"label": "Before choice", "scope": scope}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def propose(owner, rid, sid):
    response = owner.post(f"/rooms/{rid}/restore-proposals", json={"save_id": sid})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def vote(client, rid, pid, accept=True):
    return client.post(
        f"/rooms/{rid}/restore-proposals/{pid}/vote", json={"accept": accept}
    )


def apply(owner, rid, pid):
    return owner.post(f"/rooms/{rid}/restore-proposals/{pid}/apply")


def test_shared_checkpoint_permissions_and_private_forks(account):
    owner, _, rid, participants = setup_group(account)
    member, _ = participants[0]
    outsider, _ = account()
    private = save(owner, rid, "private")
    shared = save(owner, rid)
    assert (
        member.post(f"/rooms/{rid}/saves", json={"scope": "shared"}).status_code == 403
    )
    visible = member.get(f"/rooms/{rid}/saves").json()
    assert [s["id"] for s in visible] == [shared]
    assert visible[0]["scope"] == "shared"
    assert outsider.get(f"/rooms/{rid}/saves").status_code == 404
    assert member.post("/saves/" + private + "/resume").status_code == 404
    child = member.post("/saves/" + shared + "/resume").json()
    assert child["mode"] == "solo"
    assert owner.get("/rooms/" + child["id"]).status_code == 404
    assert outsider.post("/saves/" + shared + "/resume").status_code == 404
    assert (
        owner.post(
            f"/rooms/{rid}/restore-proposals", json={"save_id": private}
        ).status_code
        == 404
    )
    assert (
        member.post(
            f"/rooms/{rid}/restore-proposals", json={"save_id": shared}
        ).status_code
        == 403
    )


def test_unanimous_restore_preserves_original_and_checkpoint_bindings(account):
    owner, owner_data, rid, participants = setup_group(account)
    member, member_data = participants[0]
    mid = member_data["user"]["id"]
    owner.put(f"/rooms/{rid}/members/{mid}", json={"character": "Knight"})
    current = owner.get(f"/rooms/{rid}/state").json()
    current["state"]["location"] = "Castle"
    owner.put(
        f"/rooms/{rid}/state",
        json={"base_revision": current["revision"], "state": current["state"]},
    )
    owner.post(f"/rooms/{rid}/messages", json={"actor": "Owner", "content": "Before"})
    sid = save(owner, rid)
    owner.put(f"/rooms/{rid}/members/{mid}", json={"character": "Mage"})
    current = owner.get(f"/rooms/{rid}/state").json()
    current["state"]["location"] = "Forest"
    owner.put(
        f"/rooms/{rid}/state",
        json={"base_revision": current["revision"], "state": current["state"]},
    )
    owner.post(f"/rooms/{rid}/messages", json={"actor": "Owner", "content": "After"})
    pid = propose(owner, rid, sid)
    assert apply(owner, rid, pid).status_code == 409
    assert vote(member, rid, pid).json()["status"] == "approved"
    assert apply(member, rid, pid).status_code == 403
    result = apply(owner, rid, pid)
    assert result.status_code == 200, result.text
    child_id = result.json()["room_id"]
    assert apply(owner, rid, pid).json()["room_id"] == child_id
    child = member.get("/rooms/" + child_id).json()
    original = owner.get("/rooms/" + rid).json()
    assert child["mode"] == "multiplayer" and child["parent_room_id"] == rid
    assert child["story_state"]["location"] == "Castle" and len(child["messages"]) == 1
    assert (
        original["story_state"]["location"] == "Forest"
        and len(original["messages"]) == 2
    )
    bindings = member.get(f"/rooms/{child_id}/members").json()
    assert next(m for m in bindings if m["user_id"] == mid)["character"] == "Knight"
    assert (
        next(m for m in bindings if m["user_id"] == owner_data["user"]["id"])["role"]
        == "owner"
    )
    member.post(
        f"/rooms/{child_id}/messages", json={"actor": "Knight", "content": "New route"}
    )
    assert len(owner.get("/rooms/" + rid).json()["messages"]) == 2


@pytest.mark.parametrize(
    "change", ["message", "state", "assignment", "new_member", "leave_rejoin"]
)
def test_changed_story_or_roster_invalidates_old_consents(account, change):
    owner, _, rid, participants = setup_group(account)
    member, data = participants[0]
    sid = save(owner, rid)
    pid = propose(owner, rid, sid)
    assert vote(member, rid, pid).status_code == 200
    if change == "message":
        owner.post(f"/rooms/{rid}/messages", json={"actor": "O", "content": "Progress"})
    elif change == "state":
        current = owner.get(f"/rooms/{rid}/state").json()
        current["state"]["location"] = "Changed"
        owner.put(
            f"/rooms/{rid}/state",
            json={"base_revision": current["revision"], "state": current["state"]},
        )
    elif change == "assignment":
        owner.put(
            f"/rooms/{rid}/members/" + data["user"]["id"], json={"character": "Changed"}
        )
    else:
        target = account()[0] if change == "new_member" else member
        if change == "leave_rejoin":
            assert member.post(f"/rooms/{rid}/leave").status_code == 200
        code = owner.post(f"/rooms/{rid}/invitations").json()["code"]
        target.post("/invitations/join", json={"code": code})
    assert owner.get(f"/rooms/{rid}/restore-proposals").json()[0]["status"] == "stale"
    assert apply(owner, rid, pid).status_code == 409
    assert vote(member, rid, pid).status_code == 409
    assert propose(owner, rid, sid) != pid


def test_decline_withdrawal_expiry_and_cancellation(account):
    owner, _, rid, participants = setup_group(account)
    member, _ = participants[0]
    sid = save(owner, rid)
    pid = propose(owner, rid, sid)
    assert vote(member, rid, pid).json()["status"] == "approved"
    assert vote(member, rid, pid, False).json()["status"] == "rejected"
    assert apply(owner, rid, pid).status_code == 409
    pid = propose(owner, rid, sid)
    assert (
        member.post(f"/rooms/{rid}/restore-proposals/{pid}/cancel").status_code == 403
    )
    assert (
        owner.post(f"/rooms/{rid}/restore-proposals/{pid}/cancel").json()["status"]
        == "cancelled"
    )
    assert apply(owner, rid, pid).status_code == 409
    pid = propose(owner, rid, sid)
    from app.database import Session, RestoreProposal

    with Session.begin() as db:
        db.get(RestoreProposal, pid).expires_at = int(time.time()) - 1
    assert owner.get(f"/rooms/{rid}/restore-proposals").json()[0]["status"] == "expired"
    assert vote(member, rid, pid).status_code == 409
    assert apply(owner, rid, pid).status_code == 409


def test_concurrent_votes_and_repeated_execution_create_one_child(account):
    owner, _, rid, participants = setup_group(account, extra=2)
    sid = save(owner, rid)
    pid = propose(owner, rid, sid)
    assert (
        owner.post(f"/rooms/{rid}/restore-proposals", json={"save_id": sid}).status_code
        == 409
    )
    # Reading a story must not invalidate existing consent.
    for member, _ in participants:
        member.get("/rooms/" + rid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(
            r.status_code == 200
            for r in pool.map(lambda entry: vote(entry[0], rid, pid), participants)
        )
    assert vote(participants[0][0], rid, pid).json()["status"] == "approved"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(owner, rid, pid), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert results[0].json()["room_id"] == results[1].json()["room_id"]
    assert (
        len([r for r in owner.get("/rooms").json() if r["parent_room_id"] == rid]) == 1
    )


def test_outsiders_and_cross_room_proposals_are_blocked(account):
    owner, _, rid, participants = setup_group(account)
    outsider, _ = account()
    sid = save(owner, rid)
    pid = propose(owner, rid, sid)
    assert outsider.get(f"/rooms/{rid}/restore-proposals").status_code == 404
    assert vote(outsider, rid, pid).status_code == 404
    other = owner.post(
        "/rooms",
        json={"title": "Other", "world_rules": "Separate", "mode": "multiplayer"},
    ).json()["id"]
    assert apply(owner, other, pid).status_code == 404
    assert (
        owner.post(
            f"/rooms/{other}/restore-proposals", json={"save_id": sid}
        ).status_code
        == 404
    )
