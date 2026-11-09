import os
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, String, Text, Integer, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./storyverse.db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
class Save(Base):
    __tablename__ = "saves"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    message_index: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
Base.metadata.create_all(engine)
app = FastAPI(title="StoryVerse AI API", version="0.3.0")
def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return str(uuid4())
def require_room(db, room_id):
    room = db.get(Room, room_id)
    if room is None: raise HTTPException(404, "Room not found")
    return room
def msgs(db, room_id):
    return db.scalars(select(Message).where(Message.room_id == room_id).order_by(Message.position)).all()
def room_out(db, room):
    import json
    return {"id":room.id,"title":room.title,"world_rules":room.world_rules,"characters":json.loads(room.characters_json),"mode":room.mode,"parent_room_id":room.parent_room_id,"fork_message_index":room.fork_message_index,"messages":[{"id":m.id,"actor":m.actor,"content":m.content,"created_at":m.created_at} for m in msgs(db,room.id)],"created_at":room.created_at}
class RoomCreate(BaseModel):
    title: str = Field(min_length=1,max_length=120)
    world_rules: str = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)
    mode: str = Field(default="solo",pattern="^(solo|multiplayer)$")
class MessageCreate(BaseModel):
    actor: str = Field(min_length=1)
    content: str = Field(min_length=1)
class ForkCreate(BaseModel):
    title: str = Field(min_length=1)
    message_index: int = Field(ge=0)
class SaveCreate(BaseModel):
    label: str = Field(default="저장 지점",min_length=1,max_length=100)
    message_index: int | None = Field(default=None,ge=0)
@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/rooms")
def list_rooms():
    with Session() as db: return [room_out(db,r) for r in db.scalars(select(Room).order_by(Room.created_at.desc())).all()]
@app.post("/rooms")
def create_room(data:RoomCreate):
    import json
    with Session.begin() as db:
        r=Room(id=uid(),title=data.title,world_rules=data.world_rules,characters_json=json.dumps(data.characters,ensure_ascii=False),mode=data.mode,created_at=now())
        db.add(r);db.flush();return room_out(db,r)
@app.get("/rooms/{room_id}")
def get_room(room_id:str):
    with Session() as db: return room_out(db,require_room(db,room_id))
@app.post("/rooms/{room_id}/messages")
def add_message(room_id:str,data:MessageCreate):
    with Session.begin() as db:
        require_room(db,room_id)
        m=Message(id=uid(),room_id=room_id,position=len(msgs(db,room_id)),actor=data.actor,content=data.content,created_at=now())
        db.add(m);return {"id":m.id,"actor":m.actor,"content":m.content,"created_at":m.created_at}
def branch(db,parent,index,title):
    originals=msgs(db,parent.id)
    if index>len(originals): raise HTTPException(400,"Invalid fork point")
    child=Room(id=uid(),title=title,world_rules=parent.world_rules,characters_json=parent.characters_json,mode=parent.mode,parent_room_id=parent.id,fork_message_index=index,created_at=now())
    db.add(child);db.flush()
    for i,m in enumerate(originals[:index]):
        db.add(Message(id=uid(),room_id=child.id,position=i,actor=m.actor,content=m.content,created_at=m.created_at))
    db.flush();return room_out(db,child)
@app.post("/rooms/{room_id}/forks")
def fork_room(room_id:str,data:ForkCreate):
    with Session.begin() as db: return branch(db,require_room(db,room_id),data.message_index,data.title)
@app.post("/rooms/{room_id}/saves")
def create_save(room_id:str,data:SaveCreate):
    with Session.begin() as db:
        require_room(db,room_id)
        count=len(msgs(db,room_id))
        index=count if data.message_index is None else data.message_index
        if index>count: raise HTTPException(400,"Invalid save point")
        s=Save(id=uid(),room_id=room_id,label=data.label,message_index=index,created_at=now())
        db.add(s);return {"id":s.id,"room_id":room_id,"label":s.label,"message_index":index,"created_at":s.created_at}
@app.get("/rooms/{room_id}/saves")
def list_saves(room_id:str):
    with Session() as db:
        require_room(db,room_id)
        return [{"id":s.id,"room_id":s.room_id,"label":s.label,"message_index":s.message_index,"created_at":s.created_at} for s in db.scalars(select(Save).where(Save.room_id==room_id).order_by(Save.created_at.desc())).all()]
@app.post("/saves/{save_id}/resume")
def resume_save(save_id:str):
    with Session.begin() as db:
        s=db.get(Save,save_id)
        if s is None: raise HTTPException(404,"Save not found")
        parent=require_room(db,s.room_id)
        return branch(db,parent,s.message_index,parent.title+" · 이어하기")

class TurnCreate(BaseModel):
    actor: str = Field(default="나", min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5000)

@app.post("/rooms/{room_id}/turns")
async def play_turn(room_id: str, data: TurnCreate):
    """Generate before committing both messages; provider failures do not save half a turn."""
    from app.story_ai import generate_story
    with Session() as db:
        room = room_out(db, require_room(db, room_id))
    reply = await generate_story(room, room["messages"], f"{data.actor}: {data.content}")
    with Session.begin() as db:
        require_room(db, room_id)
        position = len(msgs(db, room_id))
        user = Message(id=uid(), room_id=room_id, position=position,
                       actor=data.actor, content=data.content, created_at=now())
        ai = Message(id=uid(), room_id=room_id, position=position + 1,
                     actor="AI", content=reply, created_at=now())
        db.add_all([user, ai])
        return {"user_message": {"id": user.id, "actor": user.actor, "content": user.content},
                "ai_message": {"id": ai.id, "actor": ai.actor, "content": ai.content}}
