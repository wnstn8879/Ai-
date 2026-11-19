"""Rebuildable, room-scoped lexical recall. Quotes are source text, never AI summaries."""

import re
import unicodedata
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, case
from app.database import (
    Session,
    Message,
    MemoryChunk,
    MemoryTerm,
    MemoryCursor,
    uid,
)
from app.security import current_user, lock_room
from app.story_state import require_state_access

BATCH_SIZE = 128
CHUNK_SIZE = 480
OVERLAP = 60


def terms(text):
    """Korean bigrams handle particles without a model or external data transfer."""
    result = set()
    for word in re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()):
        result.add("w:" + word[:64])
        for hangul in re.findall(r"[가-힣]+", word):
            result.update("g:" + hangul[i : i + 2] for i in range(len(hangul) - 1))
    return result


def message_count(db, room_id):
    return db.scalar(
        select(func.count()).select_from(Message).where(Message.room_id == room_id)
    )


def status(db, room_id):
    cursor = db.get(MemoryCursor, room_id)
    total = message_count(db, room_id)
    indexed = cursor.next_position if cursor else 0
    return {
        "indexed_messages": indexed,
        "total_messages": total,
        "ready": indexed == total,
    }


def index_batch(db, room_id):
    """Caller holds the room lock; cursor and index commit atomically, no model call."""
    cursor = db.get(MemoryCursor, room_id)
    if cursor is None:
        cursor = MemoryCursor(room_id=room_id, next_position=0)
        db.add(cursor)
        db.flush()
    rows = db.scalars(
        select(Message)
        .where(
            Message.room_id == room_id,
            Message.position >= cursor.next_position,
        )
        .order_by(Message.position)
        .limit(BATCH_SIZE)
    ).all()
    for message in rows:
        if message.position != cursor.next_position:
            raise HTTPException(409, "Message order needs repair before indexing")
        for number, start in enumerate(
            range(0, len(message.content), CHUNK_SIZE - OVERLAP)
        ):
            end = min(start + CHUNK_SIZE, len(message.content))
            chunk = MemoryChunk(
                id=uid(),
                room_id=room_id,
                message_id=message.id,
                position=message.position,
                segment=number,
                start=start,
                end=end,
            )
            db.add(chunk)
            db.flush()
            tokens = terms(message.content[start:end])
            if tokens:
                db.execute(
                    MemoryTerm.__table__.insert(),
                    [
                        {"chunk_id": chunk.id, "room_id": room_id, "term": term}
                        for term in sorted(tokens)
                    ],
                )
            if end == len(message.content):
                break
        cursor.next_position = message.position + 1
    db.flush()
    return status(db, room_id)


def recall(db, room_id, query, before_position=None, limit=8):
    tokens = terms(query)
    # Bounded bind count. Exact words outrank subword matches. This is lexical,
    # not a claim to retrieve every semantic/paraphrased reference.
    selected = (
        sorted(t for t in tokens if t.startswith("w:"))[:32]
        + sorted(t for t in tokens if t.startswith("g:"))[:32]
    )
    if not selected:
        return []
    score = func.sum(case((MemoryTerm.term.like("w:%"), 4), else_=1))
    query = (
        select(MemoryChunk, score.label("score"))
        .join(
            MemoryTerm,
            MemoryTerm.chunk_id == MemoryChunk.id,
        )
        .where(
            MemoryTerm.room_id == room_id,
            MemoryChunk.room_id == room_id,
            MemoryTerm.term.in_(selected),
        )
    )
    if before_position is not None:
        query = query.where(MemoryChunk.position < before_position)
    candidates = db.execute(
        query.group_by(MemoryChunk.id)
        .order_by(
            score.desc(),
            MemoryChunk.position.desc(),
            MemoryChunk.segment,
        )
        .limit(limit * 3)
    ).all()
    found = []
    seen = set()
    for chunk, weight in candidates:
        if chunk.message_id in seen:
            continue
        source = db.get(Message, chunk.message_id)
        if source is None or source.room_id != room_id:
            continue
        seen.add(chunk.message_id)
        found.append(
            {
                "message_id": source.id,
                "position": source.position,
                "actor": source.actor,
                "start": chunk.start,
                "end": chunk.end,
                "quote": source.content[chunk.start : chunk.end],
                "score": int(weight),
            }
        )
        if len(found) == limit:
            break
    return found


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


router = APIRouter()


@router.post("/rooms/{room_id}/memory/index")
def prepare_memory(room_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        require_state_access(db, room_id, user_id)
        lock_room(db, room_id)
        return index_batch(db, room_id)


@router.post("/rooms/{room_id}/memory/search")
def search_memory(room_id: str, body: Search, user_id: str = Depends(current_user)):
    with Session() as db:
        require_state_access(db, room_id, user_id)
        progress = status(db, room_id)
        return {
            **progress,
            "results": recall(db, room_id, body.query),
            "method": "lexical_source_quotes",
        }
