import json
import asyncio
import hashlib
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import Base, Session, Room, Message, Save, uid, now

app = FastAPI(title="StoryVerse AI API", version="0.3.0")
from app.security import (
    current_user,
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


def room_out(db, room):
    import json

    return {
        "id": room.id,
        "title": room.title,
        "world_rules": room.world_rules,
        "characters": json.loads(room.characters_json),
        "mode": room.mode,
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
            for m in msgs(db, room.id)
        ],
        "created_at": room.created_at,
    }


class RoomCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    world_rules: str = Field(min_length=1, max_length=20000)
    characters: list[str] = Field(default_factory=list, max_length=30)
    mode: str = Field(default="solo", pattern="^(solo|multiplayer)$")


class MessageCreate(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5000)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)


class ForkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    message_index: int = Field(ge=0)


class SaveCreate(BaseModel):
    label: str = Field(default="저장 지점", min_length=1, max_length=100)
    message_index: int | None = Field(default=None, ge=0)


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
            created_at=now(),
        )
        db.add(r)
        db.flush()
        db.add(RoomMember(room_id=r.id, user_id=user_id, role="owner"))
        db.flush()
        return room_out(db, r)


@app.get("/rooms/{room_id}")
def get_room(room_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        room = require_room(db, room_id, user_id)
        db.get(RoomMember, (room_id, user_id)).last_played_at = now()
        return room_out(db, room)


@app.post("/rooms/{room_id}/messages")
def add_message(
    room_id: str, data: MessageCreate, user_id: str = Depends(current_user)
):
    with Session.begin() as db:
        require_room(db, room_id, user_id)
        lock_room(db, room_id)
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


def branch(db, parent, index, title, user_id):
    originals = msgs(db, parent.id)
    if index > len(originals):
        raise HTTPException(400, "Invalid fork point")
    child = Room(
        id=uid(),
        title=title,
        world_rules=parent.world_rules,
        characters_json=parent.characters_json,
        mode="solo",
        parent_room_id=parent.id,
        fork_message_index=index,
        created_at=now(),
    )
    db.add(child)
    db.flush()
    db.add(RoomMember(room_id=child.id, user_id=user_id, role="owner"))
    for i, m in enumerate(originals[:index]):
        db.add(
            Message(
                id=uid(),
                room_id=child.id,
                position=i,
                actor=m.actor,
                content=m.content,
                created_at=m.created_at,
            )
        )
    db.flush()
    return room_out(db, child)


@app.post("/rooms/{room_id}/forks")
def fork_room(room_id: str, data: ForkCreate, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        return branch(
            db,
            require_room(db, room_id, user_id),
            data.message_index,
            data.title,
            user_id,
        )


@app.post("/rooms/{room_id}/saves")
def create_save(room_id: str, data: SaveCreate, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        require_room(db, room_id, user_id)
        count = len(msgs(db, room_id))
        index = count if data.message_index is None else data.message_index
        if index > count:
            raise HTTPException(400, "Invalid save point")
        s = Save(
            id=uid(),
            room_id=room_id,
            label=data.label,
            message_index=index,
            created_at=now(),
        )
        db.add(s)
        db.flush()
        db.add(SaveOwner(save_id=s.id, user_id=user_id))
        return {
            "id": s.id,
            "room_id": room_id,
            "label": s.label,
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
                "message_index": s.message_index,
                "created_at": s.created_at,
            }
            for s in db.scalars(
                select(Save)
                .join(SaveOwner, SaveOwner.save_id == Save.id)
                .where(Save.room_id == room_id, SaveOwner.user_id == user_id)
                .order_by(Save.created_at.desc())
            ).all()
        ]


@app.post("/saves/{save_id}/resume")
def resume_save(save_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        s = db.get(Save, save_id)
        if (
            s is None
            or db.get(SaveOwner, save_id) is None
            or db.get(SaveOwner, save_id).user_id != user_id
        ):
            raise HTTPException(404, "Save not found")
        parent = require_room(db, s.room_id, user_id)
        return branch(
            db, parent, s.message_index, parent.title + " · 이어하기", user_id
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
    from app.story_ai import generate_story

    with Session() as db:
        require_room(db, room_id, user_id)
        cached = receipt(db, room_id, user_id, data)
        if cached is not None:
            return cached
        room = room_out(db, require_room(db, room_id, user_id))
        actor = player_actor(db, room_id, user_id, data.actor)
    reserve_ai_attempt(room_id, user_id)
    reply = await generate_story(room, room["messages"], f"{actor}: {data.content}")
    with Session.begin() as db:
        require_room(db, room_id, user_id)
        lock_room(db, room_id)
        cached = receipt(db, room_id, user_id, data)
        if cached is not None:
            return cached
        if len(msgs(db, room_id)) != len(room["messages"]):
            raise HTTPException(409, "Story changed; reload before retrying")
        position = len(msgs(db, room_id))
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
        result = {
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
        user_id = current_user(
            HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=auth.get("access_token", "")
            )
        )
        previous = None
        while True:
            # Re-check revocation, expiry and membership on every update, across workers.
            current_user(
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
    except HTTPException:
        await socket.close(code=4401)
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
