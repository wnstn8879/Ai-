"""Immutable state history shared by checkpoints, branches and AI context."""

import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.database import Session, SceneState, uid, now
from app.security import RoomMember, current_user, lock_room

ShortMemory = Annotated[str, Field(min_length=1, max_length=300)]


class CharacterState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    personality: str = Field(default="", max_length=500)
    speech_style: str = Field(default="", max_length=300)
    goal: str = Field(default="", max_length=500)
    relationships: str = Field(default="", max_length=1000)
    condition: str = Field(default="", max_length=500)
    memories: list[ShortMemory] = Field(default_factory=list, max_length=20)


class StoryState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    world_rules: str = Field(min_length=1, max_length=20000)
    location: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=2000)
    facts: list[ShortMemory] = Field(default_factory=list, max_length=30)
    characters: list[CharacterState] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def bounded_unique_characters(self):
        names = [c.name.casefold() for c in self.characters]
        if len(names) != len(set(names)):
            raise ValueError("Character names must be unique")
        if len(self.model_dump_json().encode()) > 120000:
            raise ValueError("Story state is too large")
        return self


class StateUpdate(BaseModel):
    base_revision: int = Field(ge=0)
    state: StoryState


def initial_state(world_rules, characters):
    return {
        "world_rules": world_rules,
        "location": "",
        "summary": "",
        "facts": [],
        "characters": [
            {
                "name": name,
                "personality": "",
                "speech_style": "",
                "goal": "",
                "relationships": "",
                "condition": "",
                "memories": [],
            }
            for name in characters
        ],
    }


def snapshot_at(db, room_id, index=None):
    query = select(SceneState).where(SceneState.room_id == room_id)
    if index is not None:
        query = query.where(SceneState.message_index <= index)
    snapshot = db.scalar(query.order_by(SceneState.revision.desc()).limit(1))
    if snapshot is None:
        raise HTTPException(
            500, "Story state is unavailable; verify database migrations"
        )
    return snapshot


def add_snapshot(db, room_id, index, state, revision):
    snapshot = SceneState(
        id=uid(),
        room_id=room_id,
        revision=revision,
        message_index=index,
        state_json=json.dumps(state, ensure_ascii=False),
        created_at=now(),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def snapshot_out(snapshot):
    return {
        "id": snapshot.id,
        "revision": snapshot.revision,
        "message_index": snapshot.message_index,
        "state": json.loads(snapshot.state_json),
        "created_at": snapshot.created_at,
    }


def copy_history(db, parent_id, child_id, index, pinned=None):
    selected = (
        db.get(SceneState, pinned) if pinned else snapshot_at(db, parent_id, index)
    )
    if (
        selected is None
        or selected.room_id != parent_id
        or selected.message_index > index
    ):
        raise HTTPException(409, "Checkpoint state is unavailable")
    history = db.scalars(
        select(SceneState)
        .where(
            SceneState.room_id == parent_id,
            SceneState.message_index <= index,
            SceneState.revision <= selected.revision,
        )
        .order_by(SceneState.revision)
    ).all()
    for revision, snapshot in enumerate(history):
        add_snapshot(
            db,
            child_id,
            snapshot.message_index,
            json.loads(snapshot.state_json),
            revision,
        )
    return json.loads(selected.state_json)


def require_state_access(db, room_id, user_id):
    member = db.get(RoomMember, (room_id, user_id))
    if member is None:
        raise HTTPException(404, "Room not found")
    return member


router = APIRouter()


@router.get("/rooms/{room_id}/state")
def get_state(room_id: str, user_id: str = Depends(current_user)):
    with Session() as db:
        require_state_access(db, room_id, user_id)
        return snapshot_out(snapshot_at(db, room_id))


@router.put("/rooms/{room_id}/state")
def update_state(room_id: str, data: StateUpdate, user_id: str = Depends(current_user)):
    from sqlalchemy import func
    from app.database import Message

    with Session.begin() as db:
        require_state_access(db, room_id, user_id)
        lock_room(db, room_id)
        member = require_state_access(db, room_id, user_id)
        if member.role != "owner":
            raise HTTPException(403, "Owner permission required")
        current = snapshot_at(db, room_id)
        if data.base_revision != current.revision:
            raise HTTPException(409, "Story state changed; reload before editing")
        state = data.state.model_dump()
        if state == json.loads(current.state_json):
            return snapshot_out(current)
        index = db.scalar(
            select(func.count()).select_from(Message).where(Message.room_id == room_id)
        )
        member.last_played_at = now()
        return snapshot_out(
            add_snapshot(db, room_id, index, state, current.revision + 1)
        )


@router.get("/rooms/{room_id}/state/history")
def state_history(
    room_id: str,
    before_revision: int | None = None,
    user_id: str = Depends(current_user),
):
    with Session() as db:
        require_state_access(db, room_id, user_id)
        query = select(SceneState).where(SceneState.room_id == room_id)
        if before_revision is not None:
            query = query.where(SceneState.revision < before_revision)
        return [
            snapshot_out(s)
            for s in db.scalars(query.order_by(SceneState.revision.desc()).limit(50))
        ]
