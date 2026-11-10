"""Opaque bearer sessions: only token hashes are persisted; refresh rotates atomically."""

import os
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from threading import Lock
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, Text, ForeignKey, Integer, select, update, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, Session, Room, uid, now


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    access_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    access_expires: Mapped[int] = mapped_column(Integer)
    refresh_expires: Mapped[int] = mapped_column(Integer)


class RoomMember(Base):
    __tablename__ = "room_members"
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(12))
    character: Mapped[str] = mapped_column(String(120), default="")
    last_played_at: Mapped[str] = mapped_column(String(40), default=now)


class SaveOwner(Base):
    __tablename__ = "save_owners"
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class Friendship(Base):
    __tablename__ = "friendships"
    first_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    second_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")


class Invitation(Base):
    __tablename__ = "invitations"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    expires: Mapped[int] = mapped_column(Integer)
    used_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(value):
    salt = secrets.token_hex(16)
    return (
        salt
        + ":"
        + hashlib.scrypt(
            value.encode(), salt=salt.encode(), n=32768, r=8, p=3, maxmem=67108864
        ).hex()
    )


def password_matches(value, stored):
    salt, expected = stored.split(":")
    return hmac.compare_digest(
        hashlib.scrypt(
            value.encode(), salt=salt.encode(), n=32768, r=8, p=3, maxmem=67108864
        ).hex(),
        expected,
    )


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(
            401, "Login required", headers={"WWW-Authenticate": "Bearer"}
        )
    with Session() as db:
        session = db.scalar(
            select(UserSession).where(
                UserSession.access_hash == digest(credentials.credentials),
                UserSession.access_expires > int(time.time()),
            )
        )
        if session is None:
            raise HTTPException(
                401, "Session expired", headers={"WWW-Authenticate": "Bearer"}
            )
        return session.user_id


def lock_room(db, room_id):
    # An UPDATE obtains a database write lock until transaction commit on both engines.
    db.execute(update(Room).where(Room.id == room_id).values(title=Room.title))


def profile(user):
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


def tokens(db, user_id):
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    db.add(
        UserSession(
            id=uid(),
            user_id=user_id,
            access_hash=digest(access),
            refresh_hash=digest(refresh),
            access_expires=int(time.time()) + 900,
            refresh_expires=int(time.time()) + 2592000,
        )
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 900,
        "token_type": "bearer",
    }


# Bounded process-local abuse guard; deployments need a shared edge limit as documented.
_attempts = defaultdict(deque)
_guard = Lock()


def throttle(request: Request):
    key = request.client.host if request.client else "unknown"
    with _guard:
        t = time.monotonic()
        for old in list(_attempts):
            if not _attempts[old] or _attempts[old][-1] < t - 60:
                del _attempts[old]
        q = _attempts[key]
        while q and q[0] < t - 60:
            q.popleft()
        if len(q) >= 30:
            raise HTTPException(429, "Try again later", headers={"Retry-After": "60"})
        q.append(t)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if (
            value.count("@") != 1
            or not all(value.split("@"))
            or any(c.isspace() for c in value)
        ):
            raise ValueError("Invalid email")
        return value


class Registration(Credentials):
    display_name: str = Field(min_length=1, max_length=80)


class Refresh(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=200)


@router.post("/auth/register", dependencies=[Depends(throttle)])
def register(data: Registration):
    try:
        with Session.begin() as db:
            user = User(
                id=uid(),
                email=data.email,
                display_name=data.display_name,
                password_hash=password_hash(data.password),
            )
            db.add(user)
            db.flush()
            return {**tokens(db, user.id), "user": profile(user)}
    except IntegrityError:
        raise HTTPException(409, "Email already registered")


@router.post("/auth/login", dependencies=[Depends(throttle)])
def login(data: Credentials):
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.email == data.email))
        # Equal password work for nonexistent accounts.
        stored = user.password_hash if user else "0" * 32 + ":" + "0" * 128
        if not password_matches(data.password, stored):
            raise HTTPException(401, "Invalid credentials")
        return {**tokens(db, user.id), "user": profile(user)}


@router.post("/auth/refresh", dependencies=[Depends(throttle)])
def refresh(data: Refresh):
    with Session.begin() as db:
        session = db.scalar(
            select(UserSession).where(
                UserSession.refresh_hash == digest(data.refresh_token)
            )
        )
        if session is None or session.refresh_expires <= int(time.time()):
            raise HTTPException(401, "Session expired")
        deleted = db.execute(
            UserSession.__table__.delete().where(
                UserSession.id == session.id,
                UserSession.refresh_hash == digest(data.refresh_token),
            )
        )
        if deleted.rowcount != 1:
            raise HTTPException(401, "Refresh already used")
        return {
            **tokens(db, session.user_id),
            "user": profile(db.get(User, session.user_id)),
        }


@router.post("/auth/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    user_id: str = Depends(current_user),
):
    with Session.begin() as db:
        db.execute(
            UserSession.__table__.delete().where(
                UserSession.access_hash == digest(credentials.credentials)
            )
        )
    return {"ok": True}


@router.get("/auth/me")
def me(user_id: str = Depends(current_user)):
    with Session() as db:
        return profile(db.get(User, user_id))


@router.get("/users")
def search_users(q: str = "", user_id: str = Depends(current_user)):
    if len(q.strip()) < 3:
        return []
    with Session() as db:
        # Search display names/IDs only; do not expose account emails.
        users = db.scalars(
            select(User)
            .where(
                User.id != user_id,
                or_(
                    User.display_name.contains(q.strip(), autoescape=True), User.id == q
                ),
            )
            .limit(20)
        ).all()
        return [{"id": u.id, "display_name": u.display_name} for u in users]


class FriendRequest(BaseModel):
    user_id: str


class Decision(BaseModel):
    accept: bool


@router.post("/friends/requests")
def request_friend(data: FriendRequest, user_id: str = Depends(current_user)):
    if data.user_id == user_id:
        raise HTTPException(400, "Cannot add yourself")
    pair = tuple(sorted([user_id, data.user_id]))
    try:
        with Session.begin() as db:
            if db.get(User, data.user_id) is None:
                raise HTTPException(404, "User not found")
            if db.get(Friendship, pair):
                raise HTTPException(409, "Request already exists")
            db.add(
                Friendship(
                    first_id=pair[0],
                    second_id=pair[1],
                    sender_id=user_id,
                    status="pending",
                )
            )
    except IntegrityError:
        raise HTTPException(409, "Request already exists")
    return {"ok": True}


@router.post("/friends/requests/{other_id}/respond")
def respond_friend(other_id: str, data: Decision, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        f = db.get(Friendship, tuple(sorted([user_id, other_id])))
        if f is None or f.sender_id == user_id or f.status != "pending":
            raise HTTPException(404, "Request not found")
        if data.accept:
            f.status = "accepted"
        else:
            db.delete(f)
    return {"ok": True}


@router.get("/friends")
def friends(user_id: str = Depends(current_user)):
    with Session() as db:
        fs = db.scalars(
            select(Friendship).where(
                or_(Friendship.first_id == user_id, Friendship.second_id == user_id)
            )
        ).all()
        return [
            {
                "user_id": (
                    other := f.second_id if f.first_id == user_id else f.first_id
                ),
                "display_name": db.get(User, other).display_name,
                "status": f.status,
                "incoming": f.sender_id != user_id,
            }
            for f in fs
        ]


@router.post("/rooms/{room_id}/invitations")
def invite(room_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        member = db.get(RoomMember, (room_id, user_id))
        if member is None or member.role != "owner":
            raise HTTPException(403, "Owner permission required")
        if db.get(Room, room_id).mode != "multiplayer":
            raise HTTPException(400, "Multiplayer room required")
        code = secrets.token_urlsafe(24)
        db.add(
            Invitation(
                code_hash=digest(code),
                room_id=room_id,
                expires=int(time.time()) + 86400,
            )
        )
        return {"code": code, "expires_in": 86400}


class Join(BaseModel):
    code: str = Field(min_length=1, max_length=200)


@router.post("/invitations/join")
def join(data: Join, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        inv = db.get(Invitation, digest(data.code))
        if inv is None or inv.used_by or inv.expires <= int(time.time()):
            raise HTTPException(404, "Invalid invitation")
        lock_room(db, inv.room_id)
        used = db.execute(
            update(Invitation)
            .where(Invitation.code_hash == inv.code_hash, Invitation.used_by.is_(None))
            .values(used_by=user_id)
        )
        if used.rowcount != 1:
            raise HTTPException(409, "Invitation already used")
        if db.get(RoomMember, (inv.room_id, user_id)) is None:
            db.add(RoomMember(room_id=inv.room_id, user_id=user_id, role="participant"))
        return {"room_id": inv.room_id}


@router.get("/rooms/{room_id}/members")
def members(room_id: str, user_id: str = Depends(current_user)):
    with Session() as db:
        if db.get(RoomMember, (room_id, user_id)) is None:
            raise HTTPException(404, "Room not found")
        return [
            {
                "user_id": m.user_id,
                "display_name": db.get(User, m.user_id).display_name,
                "role": m.role,
                "character": m.character,
            }
            for m in db.scalars(select(RoomMember).where(RoomMember.room_id == room_id))
        ]


class CharacterAssignment(BaseModel):
    character: str = Field(max_length=120)


@router.put("/rooms/{room_id}/members/{member_id}")
def assign(
    room_id: str,
    member_id: str,
    data: CharacterAssignment,
    user_id: str = Depends(current_user),
):
    with Session.begin() as db:
        owner = db.get(RoomMember, (room_id, user_id))
        if owner is None or owner.role != "owner":
            raise HTTPException(403, "Owner permission required")
        member = db.get(RoomMember, (room_id, member_id))
        if member is None:
            raise HTTPException(404, "Member not found")
        member.character = data.character
    return {"ok": True}


@router.post("/rooms/{room_id}/leave")
def leave(room_id: str, user_id: str = Depends(current_user)):
    with Session.begin() as db:
        member = db.get(RoomMember, (room_id, user_id))
        if member is None:
            raise HTTPException(404, "Room not found")
        if member.role == "owner":
            raise HTTPException(
                409, "Owner cannot leave; ownership transfer is not implemented"
            )
        db.delete(member)
    return {"ok": True}


class MessageReceipt(Base):
    __tablename__ = "message_receipts"
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class AIUsage(Base):
    __tablename__ = "ai_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)


def reserve_ai_attempt(room_id, user_id):
    """Count attempts conservatively, including provider failures; no story is written."""
    from sqlalchemy import func

    day = datetime.now(timezone.utc).date().isoformat()
    with Session.begin() as db:
        # Lock in fixed user->room order for worker-safe daily quotas.
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(display_name=User.display_name)
        )
        lock_room(db, room_id)
        if db.get(RoomMember, (room_id, user_id)) is None:
            raise HTTPException(404, "Room not found")
        user_count = db.scalar(
            select(func.count())
            .select_from(AIUsage)
            .where(AIUsage.user_id == user_id, AIUsage.day == day)
        )
        room_count = db.scalar(
            select(func.count())
            .select_from(AIUsage)
            .where(AIUsage.room_id == room_id, AIUsage.day == day)
        )
        if user_count >= int(
            os.getenv("AI_USER_DAILY_LIMIT", "100")
        ) or room_count >= int(os.getenv("AI_ROOM_DAILY_LIMIT", "300")):
            raise HTTPException(429, "Daily AI request allowance exceeded")
        db.add(AIUsage(id=uid(), user_id=user_id, room_id=room_id, day=day))
