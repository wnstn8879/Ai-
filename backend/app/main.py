import json
import asyncio
import hashlib
from typing import Literal
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, or_, func

from app.database import (
    Base,
    Session,
    Room,
    Message,
    Save,
    SaveSnapshot,
    SharedCheckpointRoster,
    uid,
    now,
)
from app.story_state import (
    snapshot_at,
    initial_state,
    add_snapshot,
    copy_history,
    StoryState,
)

app = FastAPI(title="IMAGINE API", version="0.3.0")


@app.middleware("http")
async def private_site_gateway(request, call_next):
    import os
    from fastapi.responses import JSONResponse
    from app.site_identity import valid_service_key

    if os.getenv("IMAGINE_WEB_GATEWAY_ONLY") == "1" and request.url.path != "/health":
        if not valid_service_key(request):
            return JSONResponse(
                {"detail": "Private gateway authentication required"}, status_code=401
            )
    return await call_next(request)


from app.security import (
    current_user,
    token_user,
    RoomMember,
    SaveOwner,
    lock_room,
    MessageReceipt,
    reserve_ai_attempt,
)


def require_room(db, room_id, user_id):
    room = db.get(Room, room_id)
    if room is None or db.get(RoomMember, (room_id, user_id)) is None:
        raise HTTPException(404, "Room not found")
    return room


def msgs(db, room_id):
    return db.scalars(
        select(Message).where(Message.room_id == room_id).order_by(Message.position)
    ).all()


def room_out(db, room, include_messages=True):
    import json

    snapshot = snapshot_at(db, room.id)
    state = json.loads(snapshot.state_json)
    return {
        "id": room.id,
        "title": room.title,
        "world_rules": state["world_rules"],
        "characters": [c["name"] for c in state["characters"]],
        "story_state": state,
        "state_revision": snapshot.revision,
        "mode": room.mode,
        "narrative_format": room.narrative_format,
        "parent_room_id": room.parent_room_id,
        "fork_message_index": room.fork_message_index,
        "messages": [
            {
                "id": m.id,
                "position": m.position,
                "actor": m.actor,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in (msgs(db, room.id) if include_messages else [])
        ],
        "created_at": room.created_at,
    }


class RoomCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    world_rules: str = Field(min_length=1, max_length=20000)
    characters: list[str] = Field(default_factory=list, max_length=30)
    mode: str = Field(default="solo", pattern="^(solo|multiplayer)$")
    narrative_format: Literal["roleplay", "novel"] = "roleplay"

    @model_validator(mode="after")
    def valid_initial_state(self):
        validated = StoryState.model_validate(
            initial_state(self.world_rules, self.characters)
        )
        self.world_rules = validated.world_rules
        self.characters = [c.name for c in validated.characters]
        return self


class MessageCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5000)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)


class ForkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    message_index: int = Field(ge=0)


class PassageRewrite(BaseModel):
    message_id: str = Field(min_length=1, max_length=64)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    selected_text: str = Field(min_length=1, max_length=20000)
    title: str = Field(min_length=1, max_length=120)


class SaveCreate(BaseModel):
    label: str = Field(default="저장 지점", min_length=1, max_length=100)
    message_index: int | None = Field(default=None, ge=0)
    scope: str = Field(default="private", pattern="^(private|shared)$")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/rooms")
def list_rooms(user_id: str = Depends(current_user)):
    with Session() as db:
        records = db.execute(
            select(Room, RoomMember)
            .join(RoomMember, RoomMember.room_id == Room.id)
            .where(RoomMember.user_id == user_id)
            .order_by(RoomMember.last_played_at.desc(), Room.created_at.desc())
        ).all()
        return [
            {**room_out(db, r), "role": m.role, "last_played_at": m.last_played_at}
            for r, m in records
        ]


@app.post("/rooms")
def create_room(data: RoomCreate, user_id: str = Depends(current_user)):
    import json

    with Session.begin() as db:
        r = Room(
            id=uid(),
            title=data.title,
            world_rules=data.world_rules,
            characters_json=json.dumps(data.characters, ensure_ascii=False),
            mode=data.mode,
            narrative_format=data.narrative_format,
            created_at=now(),
        )
        db.add(r)
        db.flush()
        add_snapshot(db, r.id, 0, initial_state(data.world_rules, data.characters), 0)
        db.add(RoomMember(room_id=r.id, user_id=user_id, role="owner"))
        db.flush()
        return room_out(db, r)


@app.get("/rooms/{room_id}")
def get_room(room_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        lock_room(db, room_id)
        room = require_room(db, room_id, user_id)
        db.get(RoomMember, (room_id, user_id)).last_played_at = now()
        return room_out(db, room)


@app.post("/rooms/{room_id}/messages")
def add_message(
    room_id: str, data: MessageCreate, user_id: str = Depends(current_user)
):
    with Session.begin() as db:
        lock_room(db, room_id)
        require_room(db, room_id, user_id)
        cached = receipt(db, room_id, user_id, data)
        if cached is not None:
            return cached
        actor = player_actor(db, room_id, user_id, data.actor)
        m = Message(
            id=uid(),
            room_id=room_id,
            position=len(msgs(db, room_id)),
            actor=actor,
            content=data.content,
            created_at=now(),
        )
        db.get(RoomMember, (room_id, user_id)).last_played_at = now()
        db.add(m)
        result = {
            "id": m.id,
            "position": m.position,
            "actor": m.actor,
            "content": m.content,
            "created_at": m.created_at,
        }
        remember(db, room_id, user_id, data, result)
        return result


def branch(
    db,
    parent,
    index,
    title,
    user_id,
    pinned=None,
    shared=False,
    shared_characters=None,
    compact=False,
):
    lock_room(db, parent.id)
    require_room(db, parent.id, user_id)
    total = db.scalar(
        select(func.count()).select_from(Message).where(Message.room_id == parent.id)
    )
    if index > total:
        raise HTTPException(400, "Invalid fork point")
    child = Room(
        id=uid(),
        title=title,
        world_rules=parent.world_rules,
        characters_json=parent.characters_json,
        mode="multiplayer" if shared else "solo",
        narrative_format=parent.narrative_format,
        parent_room_id=parent.id,
        fork_message_index=index,
        created_at=now(),
    )
    db.add(child)
    db.flush()
    restored_state = copy_history(db, parent.id, child.id, index, pinned)
    child.world_rules = restored_state["world_rules"]
    child.characters_json = json.dumps(
        [c["name"] for c in restored_state["characters"]], ensure_ascii=False
    )
    if shared:
        for member in db.scalars(
            select(RoomMember).where(RoomMember.room_id == parent.id)
        ):
            db.add(
                RoomMember(
                    room_id=child.id,
                    user_id=member.user_id,
                    role=member.role,
                    character=(
                        shared_characters.get(member.user_id, "")
                        if shared_characters is not None
                        else member.character
                    ),
                )
            )
    else:
        db.add(RoomMember(room_id=child.id, user_id=user_id, role="owner"))
    # Copy only the selected prefix, in bounded batches within the same transaction.
    for start in range(0, index, 256):
        originals = db.scalars(
            select(Message)
            .where(
                Message.room_id == parent.id,
                Message.position >= start,
                Message.position < min(start + 256, index),
            )
            .order_by(Message.position)
        ).all()
        if originals:
            db.execute(
                Message.__table__.insert(),
                [
                    {
                        "id": uid(),
                        "room_id": child.id,
                        "position": m.position,
                        "actor": m.actor,
                        "content": m.content,
                        "created_at": m.created_at,
                    }
                    for m in originals
                ],
            )
    db.flush()
    if compact:
        from app.story_reader import chapter_page

        return chapter_page(db, child)
    return room_out(db, child)


@app.post("/rooms/{room_id}/forks")
def fork_room(
    room_id: str,
    data: ForkCreate,
    compact: bool = False,
    user_id: str = Depends(current_user),
):
    with Session.begin() as db:
        return branch(
            db,
            require_room(db, room_id, user_id),
            data.message_index,
            data.title,
            user_id,
            compact=compact,
        )


@app.post("/rooms/{room_id}/rewrite")
def rewrite_passage(
    room_id: str,
    data: PassageRewrite,
    compact: bool = False,
    user_id: str = Depends(current_user),
):
    with Session.begin() as db:
        parent = require_room(db, room_id, user_id)
        lock_room(db, room_id)
        if parent.narrative_format != "novel":
            raise HTTPException(400, "Passage rewriting requires a novel")
        selected = db.get(Message, data.message_id)
        if selected is None or selected.room_id != room_id or selected.actor != "AI":
            raise HTTPException(400, "Novel passage not found")
        index = selected.position
        source = selected.content
        if (
            data.end <= data.start
            or data.end > len(source)
            or source[data.start : data.end] != data.selected_text
            or not data.selected_text.strip()
        ):
            raise HTTPException(400, "Selected passage does not match saved text")
        result = branch(db, parent, index, data.title, user_id, compact=True)
        prefix = source[: data.start]
        if prefix.strip():
            db.add(
                Message(
                    id=uid(),
                    room_id=result["id"],
                    position=index,
                    actor="AI",
                    content=prefix,
                    created_at=now(),
                )
            )
            db.flush()
        if compact:
            from app.story_reader import chapter_page

            return chapter_page(db, db.get(Room, result["id"]))
        return room_out(db, db.get(Room, result["id"]))


@app.post("/rooms/{room_id}/saves")
def create_save(room_id: str, data: SaveCreate, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        lock_room(db, room_id)
        require_room(db, room_id, user_id)
        if data.scope == "shared":
            if db.get(Room, room_id).mode != "multiplayer":
                raise HTTPException(400, "Shared checkpoint requires multiplayer")
            if db.get(RoomMember, (room_id, user_id)).role != "owner":
                raise HTTPException(403, "Owner permission required")
        count = len(msgs(db, room_id))
        index = count if data.message_index is None else data.message_index
        if index > count:
            raise HTTPException(400, "Invalid save point")
        s = Save(
            id=uid(),
            room_id=room_id,
            label=data.label,
            scope=data.scope,
            message_index=index,
            created_at=now(),
        )
        db.add(s)
        db.flush()
        db.add(SaveOwner(save_id=s.id, user_id=user_id))
        if data.scope == "shared":
            bindings = {
                m.user_id: m.character
                for m in db.scalars(
                    select(RoomMember).where(RoomMember.room_id == room_id)
                )
            }
            db.add(
                SharedCheckpointRoster(
                    save_id=s.id,
                    characters_json=json.dumps(bindings, ensure_ascii=False),
                )
            )
        db.add(
            SaveSnapshot(save_id=s.id, snapshot_id=snapshot_at(db, room_id, index).id)
        )
        return {
            "id": s.id,
            "room_id": room_id,
            "label": s.label,
            "scope": s.scope,
            "message_index": index,
            "created_at": s.created_at,
        }


@app.get("/rooms/{room_id}/saves")
def list_saves(room_id: str, user_id: str = Depends(current_user)):
    with Session() as db:
        require_room(db, room_id, user_id)
        return [
            {
                "id": s.id,
                "room_id": s.room_id,
                "label": s.label,
                "scope": s.scope,
                "message_index": s.message_index,
                "created_at": s.created_at,
            }
            for s in db.scalars(
                select(Save)
                .join(SaveOwner, SaveOwner.save_id == Save.id)
                .where(
                    Save.room_id == room_id,
                    or_(SaveOwner.user_id == user_id, Save.scope == "shared"),
                )
                .order_by(Save.created_at.desc())
            ).all()
        ]


@app.post("/saves/{save_id}/resume")
def resume_save(
    save_id: str, compact: bool = False, user_id: str = Depends(current_user)
):
    with Session.begin() as db:
        s = db.get(Save, save_id)
        if (
            s is None
            or db.get(SaveOwner, save_id) is None
            or (s.scope != "shared" and db.get(SaveOwner, save_id).user_id != user_id)
        ):
            raise HTTPException(404, "Save not found")
        parent = require_room(db, s.room_id, user_id)
        return branch(
            db,
            parent,
            s.message_index,
            parent.title[:112] + " · 이어하기",
            user_id,
            pinned=db.get(SaveSnapshot, s.id).snapshot_id,
            compact=compact,
        )


class TurnCreate(BaseModel):
    actor: str = Field(default="나", min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5000)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)


@app.post("/rooms/{room_id}/turns")
async def play_turn(
    room_id: str, data: TurnCreate, user_id: str = Depends(current_user)
):
    """Generate before committing both messages; provider failures do not save half a turn."""
    from app.story_ai import generate_story, plan_story
    from app.story_memory import index_batch, message_count, recall

    # Commit only the rebuildable index before generation. Never charge/call the
    # model while old source records are still waiting to be indexed.
    with Session.begin() as db:
        require_room(db, room_id, user_id)
        lock_room(db, room_id)
        cached = receipt(db, room_id, user_id, data)
        if cached is not None:
            return cached
        progress = index_batch(db, room_id)
        room = room_out(db, require_room(db, room_id, user_id), include_messages=False)
        room["message_count"] = message_count(db, room_id)
        room["ai_message_count"] = db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.room_id == room_id, Message.actor == "AI")
        )
        recent = db.scalars(
            select(Message)
            .where(Message.room_id == room_id)
            .order_by(Message.position.desc())
            .limit(30)
        ).all()
        room["messages"] = [
            {"id": m.id, "position": m.position, "actor": m.actor, "content": m.content}
            for m in reversed(recent)
        ]
        actor = player_actor(db, room_id, user_id, data.actor)
        names = " ".join(c["name"] for c in room["story_state"]["characters"])
        room["memory_sources"] = recall(
            db,
            room_id,
            data.content + " " + names,
            before_position=max(0, room["message_count"] - 2),
            limit=16,
        )

    if not progress["ready"]:
        raise HTTPException(
            409, "과거 기록을 정리하고 있습니다. 기억 정리를 마친 뒤 다시 생성해주세요."
        )
    room["prepared_prompt"], context_report = plan_story(
        room, room["messages"], f"{actor}: {data.content}"
    )
    context_report["total_messages"] = room["message_count"]
    context_report["history_messages_not_in_recent"] = (
        room["message_count"] - context_report["recent_messages"]
    )
    reserve_ai_attempt(room_id, user_id)
    reply = await generate_story(room, room["messages"], f"{actor}: {data.content}")
    with Session.begin() as db:
        lock_room(db, room_id)
        require_room(db, room_id, user_id)
        cached = receipt(db, room_id, user_id, data)
        if cached is not None:
            return cached
        if (
            message_count(db, room_id) != room["message_count"]
            or snapshot_at(db, room_id).revision != room["state_revision"]
        ):
            raise HTTPException(409, "Story changed; reload before retrying")
        position = room["message_count"]
        user = Message(
            id=uid(),
            room_id=room_id,
            position=position,
            actor=actor,
            content=data.content,
            created_at=now(),
        )
        ai = Message(
            id=uid(),
            room_id=room_id,
            position=position + 1,
            actor="AI",
            content=reply,
            created_at=now(),
        )
        db.get(RoomMember, (room_id, user_id)).last_played_at = now()
        db.add_all([user, ai])
        db.flush()
        index_batch(db, room_id)
        result = {
            "context_report": context_report,
            "user_message": {
                "id": user.id,
                "actor": user.actor,
                "content": user.content,
            },
            "ai_message": {"id": ai.id, "actor": ai.actor, "content": ai.content},
        }
        remember(db, room_id, user_id, data, result)
        return result


from app.security import router as security_router

app.include_router(security_router)
from app.story_state import router as state_router

app.include_router(state_router)
from app.shared_restores import router as restore_router

app.include_router(restore_router)


def receipt(db, room_id, user_id, data):
    if not data.request_id:
        return None
    row = db.get(MessageReceipt, (room_id, user_id, data.request_id))
    if row is None:
        return None
    if (
        row.payload_hash
        != hashlib.sha256(
            (type(data).__name__ + data.model_dump_json()).encode()
        ).hexdigest()
    ):
        raise HTTPException(409, "Request ID was already used for another message")
    return json.loads(row.result_json)


def remember(db, room_id, user_id, data, result):
    if data.request_id:
        db.add(
            MessageReceipt(
                room_id=room_id,
                user_id=user_id,
                request_id=data.request_id,
                payload_hash=hashlib.sha256(
                    (type(data).__name__ + data.model_dump_json()).encode()
                ).hexdigest(),
                result_json=json.dumps(result),
            )
        )


@app.websocket("/rooms/{room_id}/live")
async def live_room(socket: WebSocket, room_id: str):
    # Token is sent in the first frame, never in URLs/access logs.
    from fastapi.security import HTTPAuthorizationCredentials

    await socket.accept()
    try:
        auth = await asyncio.wait_for(socket.receive_json(), timeout=10)
        user_id = token_user(
            HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=auth.get("access_token", "")
            )
        )
        previous = None
        while True:
            # Re-check revocation, expiry and membership on every update, across workers.
            token_user(
                HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials=auth.get("access_token", "")
                )
            )
            with Session() as db:
                snapshot = room_out(db, require_room(db, room_id, user_id))
            encoded = json.dumps(snapshot, ensure_ascii=False)
            if encoded != previous:
                await socket.send_json({"type": "snapshot", "room": snapshot})
                previous = encoded
            try:
                await asyncio.wait_for(socket.receive_text(), timeout=1)
            except asyncio.TimeoutError:
                pass
    except HTTPException as exc:
        await socket.close(code=4403 if exc.status_code in (403, 404) else 4401)
    except (asyncio.TimeoutError, ValueError, TypeError, AttributeError):
        await socket.close(code=4400)
    except WebSocketDisconnect:
        pass


def player_actor(db, room_id, user_id, requested):
    if db.get(Room, room_id).mode == "solo":
        return requested
    from app.security import User

    member = db.get(RoomMember, (room_id, user_id))
    return member.character or db.get(User, user_id).display_name


from app.story_memory import router as memory_router

app.include_router(memory_router)
from app.story_reader import router as reader_router

app.include_router(reader_router)
from app.novel_writer import router as writer_router

app.include_router(writer_router)
