"""Bounded browser reading/library endpoints; legacy mobile responses stay compatible."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, and_
from app.database import Session, Room, Message
from app.security import current_user, RoomMember
from app.story_memory import message_count

router = APIRouter()


def chapter_page(db, room, before_position=None):
    from app.main import room_out

    query = select(Message).where(Message.room_id == room.id)
    if before_position is not None:
        query = query.where(Message.position < before_position)
    records = list(
        reversed(db.scalars(query.order_by(Message.position.desc()).limit(30)).all())
    )
    result = room_out(db, room, include_messages=False)
    result.update(
        messages=[
            {
                "id": m.id,
                "position": m.position,
                "actor": m.actor,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in records
        ],
        message_count=message_count(db, room.id),
        ai_message_count=db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.room_id == room.id, Message.actor == "AI")
        ),
        next_before=(
            records[0].position if records and records[0].position > 0 else None
        ),
    )
    return result


@router.get("/rooms/{room_id}/chapters")
def read_chapters(
    room_id: str,
    before_position: int | None = Query(default=None, ge=0),
    user_id: str = Depends(current_user),
):
    from app.main import require_room

    with Session() as db:
        return chapter_page(db, require_room(db, room_id, user_id), before_position)


@router.get("/library")
def library(
    cursor: str | None = Query(default=None, max_length=36),
    user_id: str = Depends(current_user),
):
    from app.main import require_room

    with Session() as db:
        query = (
            select(Room)
            .join(RoomMember, RoomMember.room_id == Room.id)
            .where(RoomMember.user_id == user_id, Room.narrative_format == "novel")
        )
        if cursor:
            previous = require_room(db, cursor, user_id)
            query = query.where(
                or_(
                    Room.created_at < previous.created_at,
                    and_(Room.created_at == previous.created_at, Room.id < previous.id),
                )
            )
        rooms = db.scalars(
            query.order_by(Room.created_at.desc(), Room.id.desc()).limit(21)
        ).all()
        items = []
        for room in rooms[:20]:
            last = db.scalar(
                select(Message)
                .where(Message.room_id == room.id, Message.actor == "AI")
                .order_by(Message.position.desc())
                .limit(1)
            )
            items.append(
                {
                    "id": room.id,
                    "title": room.title,
                    "parent_room_id": room.parent_room_id,
                    "created_at": room.created_at,
                    "excerpt": last.content[:160] if last else "",
                    "message_count": message_count(db, room.id),
                }
            )
        return {
            "items": items,
            "next_cursor": rooms[19].id if len(rooms) > 20 else None,
        }
