"""Foreground automatic authoring with durable streamed drafts and explicit pauses."""

import asyncio
import json
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from app.database import Session, NovelWriter, Message, uid, now
from app.security import current_user, RoomMember, lock_room, reserve_ai_attempt
from app.story_state import snapshot_at
from app.story_memory import index_batch, message_count, recall
from app.story_ai import plan_story
from app.llm import stream_complete, writer_output_tokens

router = APIRouter()
_tasks = {}
MARKER = "[IMAGINE_BRANCH]"
LEASE_SECONDS = 90


def split_draft(raw):
    if MARKER in raw:
        body, question = raw.split(MARKER, 1)
        return body.rstrip(), question.strip()[:500]
    # Withhold partial marker prefixes from the prose preview.
    for length in range(len(MARKER) - 1, 0, -1):
        if raw.endswith(MARKER[:length]):
            return raw[:-length].rstrip(), ""
    return raw, ""


def access(db, room_id, user_id):
    from app.main import require_room

    room = require_room(db, room_id, user_id)
    member = db.get(RoomMember, (room_id, user_id))
    if member.role != "owner":
        raise HTTPException(403, "자동 집필은 작품 소유자만 시작할 수 있습니다.")
    if room.narrative_format != "novel" or room.mode != "solo":
        raise HTTPException(400, "자동 집필은 개인 소설에서 사용할 수 있습니다.")
    return room


def output(run):
    if run is None:
        return {
            "status": "idle",
            "draft": "",
            "question": "",
            "completed": 0,
            "pending_direction": "",
            "message_count": 0,
            "run_id": "",
            "error": "",
        }
    draft, _ = split_draft(run.draft)
    return {
        "status": run.status,
        "draft": draft,
        "question": run.question,
        "completed": run.completed,
        "message_count": run.message_count,
        "pending_direction": run.pending_direction,
        "run_id": run.owner_token,
        "error": run.error,
        "context_report": json.loads(run.context_json),
    }


def recover_stale(run):
    if (
        run
        and run.status == "writing"
        and (
            run.lease_until < int(time.time()) or run.heartbeat < int(time.time()) - 45
        )
    ):
        run.status = "paused"
        run.error = (
            "읽기 연결이 멈춰 집필을 쉬고 있습니다. 저장된 초안에서 이어갈 수 있습니다."
        )


class Start(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    direction: str = Field(default="", max_length=4000)
    sections: int = Field(default=4, ge=1, le=6)
    continuous: bool = False


class Direction(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=4000)


class Control(BaseModel):
    run_id: str = Field(default="", max_length=36)


@router.get("/rooms/{room_id}/writer")
def writer_status(room_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        access(db, room_id, user_id)
        lock_room(db, room_id)
        run = db.get(NovelWriter, room_id)
        recover_stale(run)
        return output(run)


@router.post("/rooms/{room_id}/writer/start")
async def start_writer(room_id: str, body: Start, user_id: str = Depends(current_user)):
    from app.main import receipt, remember

    token = None
    with Session.begin() as db:
        access(db, room_id, user_id)
        lock_room(db, room_id)
        run = db.get(NovelWriter, room_id)
        if receipt(db, room_id, user_id, body) is not None:
            return output(run)
        progress = index_batch(db, room_id)
        if progress["ready"]:
            if run is None:
                run = NovelWriter(room_id=room_id, user_id=user_id)
                db.add(run)
                db.flush()
            recover_stale(run)
            if body.direction.strip():
                run.pending_direction = body.direction.strip()
            if run.status != "writing":
                token = uid()
                run.owner_token, run.status = token, "writing"
                run.completed, run.batch_limit = 0, (
                    0 if body.continuous else body.sections
                )
                run.message_count = message_count(db, room_id)
                run.error, run.question = "", ""
                run.lease_until = int(time.time()) + LEASE_SECONDS
                run.heartbeat = int(time.time())
            remember(db, room_id, user_id, body, {"writer_started": True})
            result = output(run)
    if not progress["ready"]:
        raise HTTPException(409, "과거 기록 정리를 마친 뒤 자동 집필을 시작해주세요.")
    if token:
        task = asyncio.create_task(author(room_id, user_id, token))
        _tasks[room_id] = (token, task)
        task.add_done_callback(lambda done: _remove_task(room_id, token))
    return result


def _remove_task(room_id, token):
    if _tasks.get(room_id, (None,))[0] == token:
        _tasks.pop(room_id, None)


@router.post("/rooms/{room_id}/writer/pause")
async def pause_writer(
    room_id: str, body: Control, user_id: str = Depends(current_user)
):
    with Session.begin() as db:
        access(db, room_id, user_id)
        lock_room(db, room_id)
        run = db.get(NovelWriter, room_id)
        if run:
            if body.run_id and run.owner_token != body.run_id:
                raise HTTPException(
                    409, "다른 집필 작업이 시작됐습니다. 상태를 새로 확인해주세요."
                )
            run.status = "paused"
            run.lease_until = 0
        result = output(run)
    entry = _tasks.get(room_id)
    if entry and (not body.run_id or entry[0] == body.run_id):
        entry[1].cancel()
    return result


@router.post("/rooms/{room_id}/writer/keepalive")
def keepalive(room_id: str, body: Control, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        access(db, room_id, user_id)
        lock_room(db, room_id)
        run = db.get(NovelWriter, room_id)
        recover_stale(run)
        if run and run.status == "writing" and run.owner_token == body.run_id:
            run.lease_until = int(time.time()) + LEASE_SECONDS
        return output(run)


@router.post("/rooms/{room_id}/writer/direction")
def change_direction(
    room_id: str, body: Direction, user_id: str = Depends(current_user)
):
    from app.main import receipt, remember

    if not body.content.strip():
        raise HTTPException(422, "바꾸고 싶은 방향을 적어주세요.")
    with Session.begin() as db:
        access(db, room_id, user_id)
        lock_room(db, room_id)
        run = db.get(NovelWriter, room_id)
        if run is None:
            run = NovelWriter(room_id=room_id, user_id=user_id)
            db.add(run)
            db.flush()
        if receipt(db, room_id, user_id, body) is None:
            run.pending_direction = body.content.strip()
            remember(db, room_id, user_id, body, {"direction_saved": True})
        return output(run)


async def watchdog(room_id, user_id, token, task):
    while True:
        await asyncio.sleep(5)
        with Session.begin() as db:
            lock_room(db, room_id)
            run = db.get(NovelWriter, room_id)
            if run is None or run.owner_token != token or run.status != "writing":
                task.cancel()
                return
            try:
                access(db, room_id, user_id)
            except HTTPException:
                run.status = "error"
                run.error = "작품 접근 권한이 바뀌어 집필을 멈췄습니다."
                task.cancel()
                return
            if run.lease_until < int(time.time()):
                run.status = "paused"
                run.error = "읽기 연결이 멈춰 쉬고 있습니다. 초안은 저장했습니다."
                task.cancel()
                return
            run.heartbeat = int(time.time())


def prepare(db, room_id, user_id, run):
    from app.main import room_out

    room = access(db, room_id, user_id)
    room = room_out(db, room, include_messages=False)
    count = message_count(db, room_id)
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
    history = [
        {"id": m.id, "position": m.position, "actor": m.actor, "content": m.content}
        for m in reversed(recent)
    ]
    used_direction = run.pending_direction or run.active_direction
    instruction = (
        used_direction
        or "현재 상황과 인물의 목표를 이어서, 다음 사건과 대사·감정을 스스로 전개해줘."
    )
    if run.draft:
        history.append(
            {"position": count, "actor": "AI", "content": split_draft(run.draft)[0]}
        )
        instruction += "\n마지막 assistant 본문은 작성 중인 초안이다. 앞부분을 반복하지 말고 끝난 지점의 다음 글부터 이어 써줘."
    room["writer_mode"] = True
    room["writer_output_tokens"] = writer_output_tokens()
    names = " ".join(c["name"] for c in room["story_state"]["characters"])
    room["memory_sources"] = recall(
        db,
        room_id,
        instruction + " " + names,
        before_position=max(0, count - 2),
        limit=16,
    )
    prompt, report = plan_story(room, history, instruction)
    report["total_messages"] = count
    run.active_direction = used_direction
    run.context_json = json.dumps(report, ensure_ascii=False)
    return prompt, count, room["state_revision"], used_direction


async def author(room_id, user_id, token):
    watch = asyncio.create_task(
        watchdog(room_id, user_id, token, asyncio.current_task())
    )
    continuation_rounds = 0
    try:
        while True:
            with Session.begin() as db:
                lock_room(db, room_id)
                run = db.get(NovelWriter, room_id)
                if run is None or run.owner_token != token or run.status != "writing":
                    return
                prompt, count, revision, direction = prepare(db, room_id, user_id, run)
                raw = run.draft
            reserve_ai_attempt(room_id, user_id)
            reason = None
            # A streaming response can be read while generating. It never occupies
            # one long Sites relay request or needs the old 40-second mobile timeout.
            async with asyncio.timeout(600):
                async for part in stream_complete(prompt):
                    if "text" in part:
                        raw += part["text"]
                        if len(raw) > 20000:
                            raise HTTPException(
                                422,
                                "초안이 길어져 집필을 멈췄습니다. 저장된 글을 확인해주세요.",
                            )
                        with Session.begin() as db:
                            lock_room(db, room_id)
                            run = db.get(NovelWriter, room_id)
                            if run.owner_token != token or run.status != "writing":
                                return
                            access(db, room_id, user_id)
                            run.draft = raw
                            run.heartbeat = int(time.time())
                    reason = part.get("finish_reason", reason)
            prose, question = split_draft(raw)
            if not prose.strip():
                raise HTTPException(502, "본문이 비어 있어 집필을 멈췄습니다.")
            with Session.begin() as db:
                lock_room(db, room_id)
                access(db, room_id, user_id)
                run = db.get(NovelWriter, room_id)
                if run.owner_token != token or run.status != "writing":
                    return
                if (
                    count != message_count(db, room_id)
                    or revision != snapshot_at(db, room_id).revision
                ):
                    raise HTTPException(
                        409,
                        "다른 진행이나 설정이 바뀌었습니다. 초안은 보존했으니 원문과 비교해주세요.",
                    )
                if reason == "length":
                    continuation_rounds += 1
                    if continuation_rounds >= 3:
                        run.status = "paused"
                        run.error = "긴 초안을 저장했습니다. 자동으로 이어 읽기를 누르면 계속 집필합니다."
                        return
                    continue
                if reason != "stop":
                    raise HTTPException(
                        502, "완료 신호를 확인하지 못했습니다. 초안은 보존했습니다."
                    )
                db.add_all(
                    [
                        Message(
                            id=uid(),
                            room_id=room_id,
                            position=count,
                            actor="작가" if direction else "자동 집필 지시",
                            content=direction
                            or "설정과 앞선 상황을 바탕으로 자동 이어 쓰기",
                            created_at=now(),
                        ),
                        Message(
                            id=uid(),
                            room_id=room_id,
                            position=count + 1,
                            actor="AI",
                            content=prose.strip(),
                            created_at=now(),
                        ),
                    ]
                )
                db.flush()
                index_batch(db, room_id)
                db.get(RoomMember, (room_id, user_id)).last_played_at = now()
                run.completed += 1
                run.message_count = count + 2
                run.draft, run.active_direction = "", ""
                if run.pending_direction == direction:
                    run.pending_direction = ""
                run.question = question
                if question:
                    run.status = "choice"
                elif run.batch_limit and run.completed >= run.batch_limit:
                    run.status = "paused"
                    run.error = "읽을 분량을 이어 썼습니다. 원하면 같은 이야기로 계속 읽을 수 있습니다."
                if run.status != "writing":
                    return
            continuation_rounds = 0
    except asyncio.CancelledError:
        # Every previewed fragment was already committed to the durable draft.
        with Session.begin() as db:
            lock_room(db, room_id)
            run = db.get(NovelWriter, room_id)
            if run and run.owner_token == token and run.status == "writing":
                run.status = "paused"
        raise
    except Exception as error:
        with Session.begin() as db:
            lock_room(db, room_id)
            run = db.get(NovelWriter, room_id)
            if run and run.owner_token == token and run.status == "writing":
                run.status = "error"
                run.error = (
                    "오늘 집필 한도에 도달했습니다. 저장한 글은 계속 읽을 수 있습니다."
                    if isinstance(error, HTTPException) and error.status_code == 429
                    else (
                        error.detail
                        if isinstance(error, HTTPException)
                        else "집필 연결이 멈췄습니다. 저장된 초안에서 다시 시작할 수 있습니다."
                    )
                )
    finally:
        watch.cancel()
