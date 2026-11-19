"""Unanimous, non-destructive multiplayer restores with an immutable consent roster."""

import json
import time
import hashlib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from app.database import (
    Session,
    Room,
    Save,
    SaveSnapshot,
    SharedCheckpointRoster,
    Message,
    RoomRoster,
    RestoreProposal,
    RestoreVote,
    uid,
    now,
)
from app.security import RoomMember, User, current_user, lock_room
from app.story_state import snapshot_at

router = APIRouter()


def roster(db, room_id):
    members = db.scalars(
        select(RoomMember)
        .where(RoomMember.room_id == room_id)
        .order_by(RoomMember.user_id)
    ).all()
    version = db.get(RoomRoster, room_id)
    digest = hashlib.sha256(
        json.dumps(
            {
                "generation": version.generation if version else 0,
                "members": [(m.user_id, m.role, m.character) for m in members],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return members, digest


def require_member(db, room_id, user_id, owner=False):
    member = db.get(RoomMember, (room_id, user_id), populate_existing=True)
    if member is None:
        raise HTTPException(404, "Room not found")
    if owner and member.role != "owner":
        raise HTTPException(403, "Owner permission required")
    if db.get(Room, room_id).mode != "multiplayer":
        raise HTTPException(400, "Multiplayer room required")
    return member


def effective_status(db, proposal):
    if proposal.status not in ("pending", "approved"):
        return proposal.status
    if proposal.expires_at <= int(time.time()):
        return "expired"
    _, fingerprint = roster(db, proposal.room_id)
    count = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.room_id == proposal.room_id)
    )
    if (
        fingerprint != proposal.roster_fingerprint
        or count != proposal.message_count
        or snapshot_at(db, proposal.room_id).revision != proposal.state_revision
    ):
        return "stale"
    return proposal.status


def out(db, proposal):
    votes = db.scalars(
        select(RestoreVote).where(RestoreVote.proposal_id == proposal.id)
    ).all()
    return {
        "id": proposal.id,
        "room_id": proposal.room_id,
        "save_id": proposal.save_id,
        "label": db.get(Save, proposal.save_id).label,
        "message_index": db.get(Save, proposal.save_id).message_index,
        "status": effective_status(db, proposal),
        "eligible": json.loads(proposal.eligible_json),
        "votes": [
            {"user_id": v.user_id, "accept": v.accept, "voted_at": v.voted_at}
            for v in votes
        ],
        "expires_at": proposal.expires_at,
        "created_at": proposal.created_at,
        "result_room_id": proposal.result_room_id,
    }


def load_locked(db, room_id, proposal_id, user_id, owner=False):
    require_member(db, room_id, user_id, owner)
    lock_room(db, room_id)
    require_member(db, room_id, user_id, owner)
    proposal = db.get(RestoreProposal, proposal_id)
    if proposal is None or proposal.room_id != room_id:
        raise HTTPException(404, "Proposal not found")
    return proposal


class ProposalCreate(BaseModel):
    save_id: str


class VoteCreate(BaseModel):
    accept: bool


@router.get("/rooms/{room_id}/restore-proposals")
def list_proposals(room_id: str, user_id: str = Depends(current_user)):
    with Session() as db:
        require_member(db, room_id, user_id)
        return [
            out(db, p)
            for p in db.scalars(
                select(RestoreProposal)
                .where(RestoreProposal.room_id == room_id)
                .order_by(RestoreProposal.created_at.desc())
                .limit(20)
            )
        ]


@router.post("/rooms/{room_id}/restore-proposals")
def propose(room_id: str, data: ProposalCreate, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        require_member(db, room_id, user_id, True)
        lock_room(db, room_id)
        require_member(db, room_id, user_id, True)
        save = db.get(Save, data.save_id)
        if save is None or save.room_id != room_id or save.scope != "shared":
            raise HTTPException(404, "Shared checkpoint not found")
        active = db.scalars(
            select(RestoreProposal).where(
                RestoreProposal.room_id == room_id,
                RestoreProposal.status.in_(["pending", "approved"]),
            )
        ).all()
        for previous in active:
            status = effective_status(db, previous)
            if status in ("pending", "approved"):
                raise HTTPException(409, "A restore vote is already active")
            previous.status = status
        members, fingerprint = roster(db, room_id)
        bindings = json.loads(db.get(SharedCheckpointRoster, save.id).characters_json)
        proposal = RestoreProposal(
            id=uid(),
            room_id=room_id,
            save_id=save.id,
            initiator_id=user_id,
            message_count=db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.room_id == room_id)
            ),
            state_revision=snapshot_at(db, room_id).revision,
            roster_fingerprint=fingerprint,
            eligible_json=json.dumps(
                [
                    {
                        "user_id": m.user_id,
                        "display_name": db.get(User, m.user_id).display_name,
                        "character": bindings.get(m.user_id, ""),
                    }
                    for m in members
                ],
                ensure_ascii=False,
            ),
            status="approved" if len(members) == 1 else "pending",
            expires_at=int(time.time()) + 900,
            created_at=now(),
        )
        db.add(proposal)
        db.flush()
        # Creating a proposal explicitly counts as the owner's agreement, shown in the UI.
        db.add(
            RestoreVote(
                proposal_id=proposal.id, user_id=user_id, accept=True, voted_at=now()
            )
        )
        db.flush()
        return out(db, proposal)


@router.post("/rooms/{room_id}/restore-proposals/{proposal_id}/vote")
def vote(
    room_id: str,
    proposal_id: str,
    data: VoteCreate,
    user_id: str = Depends(current_user),
):
    with Session.begin() as db:
        proposal = load_locked(db, room_id, proposal_id, user_id)
        status = effective_status(db, proposal)
        if status not in ("pending", "approved"):
            raise HTTPException(409, "Restore proposal is no longer active")
        eligible = {m["user_id"] for m in json.loads(proposal.eligible_json)}
        if user_id not in eligible:
            raise HTTPException(403, "Not eligible for this vote")
        previous = db.get(RestoreVote, (proposal_id, user_id))
        if previous:
            if previous.accept != data.accept:
                if data.accept:
                    raise HTTPException(409, "Rejected vote cannot be changed")
                previous.accept = False
                previous.voted_at = now()
                proposal.status = "rejected"
            return out(db, proposal)
        db.add(
            RestoreVote(
                proposal_id=proposal.id,
                user_id=user_id,
                accept=data.accept,
                voted_at=now(),
            )
        )
        db.flush()
        if not data.accept:
            proposal.status = "rejected"
        elif db.scalar(
            select(func.count())
            .select_from(RestoreVote)
            .where(RestoreVote.proposal_id == proposal_id, RestoreVote.accept.is_(True))
        ) == len(eligible):
            proposal.status = "approved"
        return out(db, proposal)


@router.post("/rooms/{room_id}/restore-proposals/{proposal_id}/cancel")
def cancel(room_id: str, proposal_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        proposal = load_locked(db, room_id, proposal_id, user_id, True)
        if proposal.status == "cancelled":
            return out(db, proposal)
        if effective_status(db, proposal) not in ("pending", "approved"):
            raise HTTPException(409, "Proposal cannot be cancelled")
        proposal.status = "cancelled"
        return out(db, proposal)


@router.post("/rooms/{room_id}/restore-proposals/{proposal_id}/apply")
def apply_restore(room_id: str, proposal_id: str, user_id: str = Depends(current_user)):
    from app.main import branch

    with Session.begin() as db:
        proposal = load_locked(db, room_id, proposal_id, user_id, True)
        if proposal.status == "applied":
            return {"room_id": proposal.result_room_id, "proposal_id": proposal.id}
        if effective_status(db, proposal) != "approved":
            raise HTTPException(
                409, "All current participants must approve an unchanged story"
            )
        # Re-check the actual consent rows before creating any child room.
        eligible = {m["user_id"] for m in json.loads(proposal.eligible_json)}
        accepted = set(
            db.scalars(
                select(RestoreVote.user_id).where(
                    RestoreVote.proposal_id == proposal_id, RestoreVote.accept.is_(True)
                )
            )
        )
        if accepted != eligible:
            raise HTTPException(409, "Unanimous approval required")
        save = db.get(Save, proposal.save_id)
        parent = db.get(Room, room_id)
        child = branch(
            db,
            parent,
            save.message_index,
            parent.title[:108] + " · 공용 복원",
            user_id,
            pinned=db.get(SaveSnapshot, save.id).snapshot_id,
            shared=True,
            shared_characters=json.loads(
                db.get(SharedCheckpointRoster, save.id).characters_json
            ),
        )
        proposal.result_room_id = child["id"]
        proposal.status = "applied"
        return {"room_id": child["id"], "proposal_id": proposal.id}
