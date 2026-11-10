import os
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    create_engine,
    String,
    Text,
    Integer,
    Boolean,
    ForeignKey,
    select,
    event,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./storyverse.db")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=(
        {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    ),
)
Session = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    world_rules: Mapped[str] = mapped_column(Text)
    characters_json: Mapped[str] = mapped_column(Text, default="[]")
    mode: Mapped[str] = mapped_column(String(20), default="solo")
    parent_room_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fork_message_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("uq_message_room_position", "room_id", "position", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class Save(Base):
    __tablename__ = "saves"
    scope: Mapped[str] = mapped_column(
        String(12), default="private", server_default="private"
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    message_index: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_integrity(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")


class SceneState(Base):
    """Append-only world/character state at a message boundary."""

    __tablename__ = "scene_states"
    __table_args__ = (
        Index("uq_scene_room_revision", "room_id", "revision", unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    message_index: Mapped[int] = mapped_column(Integer)
    state_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class SaveSnapshot(Base):
    __tablename__ = "save_snapshots"
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id"), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("scene_states.id"), index=True)


class RoomRoster(Base):
    __tablename__ = "room_rosters"
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)


class RestoreProposal(Base):
    __tablename__ = "restore_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id"))
    initiator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    message_count: Mapped[int] = mapped_column(Integer)
    state_revision: Mapped[int] = mapped_column(Integer)
    roster_fingerprint: Mapped[str] = mapped_column(String(64))
    eligible_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    expires_at: Mapped[int] = mapped_column(Integer)
    result_room_id: Mapped[str | None] = mapped_column(
        ForeignKey("rooms.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(40))


class RestoreVote(Base):
    __tablename__ = "restore_votes"
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("restore_proposals.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    accept: Mapped[bool] = mapped_column(Boolean)
    voted_at: Mapped[str] = mapped_column(String(40))


class SharedCheckpointRoster(Base):
    __tablename__ = "shared_checkpoint_rosters"
    save_id: Mapped[str] = mapped_column(ForeignKey("saves.id"), primary_key=True)
    characters_json: Mapped[str] = mapped_column(Text)
