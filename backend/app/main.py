from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4
from copy import deepcopy
from datetime import datetime, timezone

app = FastAPI(title="StoryVerse AI API", version="0.2.0")
rooms = {}
saves = {}

def now():
    return datetime.now(timezone.utc).isoformat()

class RoomCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    world_rules: str = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)
    mode: str = Field(default="solo", pattern="^(solo|multiplayer)$")

class MessageCreate(BaseModel):
    actor: str = Field(min_length=1)
    content: str = Field(min_length=1)

class ForkCreate(BaseModel):
    title: str = Field(min_length=1)
    message_index: int = Field(ge=0)

class SaveCreate(BaseModel):
    label: str = Field(default="저장 지점", min_length=1, max_length=100)
    message_index: int | None = Field(default=None, ge=0)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/rooms")
def create_room(data: RoomCreate):
    rid = str(uuid4())
    rooms[rid] = {"id": rid, "title": data.title, "world_rules": data.world_rules,
                  "characters": data.characters, "mode": data.mode, "parent_room_id": None,
                  "messages": [], "created_at": now()}
    return rooms[rid]

@app.get("/rooms/{room_id}")
def get_room(room_id: str):
    if room_id not in rooms:
        raise HTTPException(404, "Room not found")
    return rooms[room_id]

@app.post("/rooms/{room_id}/messages")
def add_message(room_id: str, data: MessageCreate):
    room = get_room(room_id)
    msg = {"id": str(uuid4()), **data.model_dump(), "created_at": now()}
    room["messages"].append(msg)
    return msg

def create_branch(parent, index, title):
    if index > len(parent["messages"]):
        raise HTTPException(400, "Invalid fork point")
    child = deepcopy(parent)
    child["id"] = str(uuid4())
    child["title"] = title
    child["parent_room_id"] = parent["id"]
    child["fork_message_index"] = index
    child["messages"] = deepcopy(parent["messages"][:index])
    child["created_at"] = now()
    rooms[child["id"]] = child
    return child

@app.post("/rooms/{room_id}/forks")
def fork_room(room_id: str, data: ForkCreate):
    return create_branch(get_room(room_id), data.message_index, data.title)

@app.post("/rooms/{room_id}/saves")
def create_save(room_id: str, data: SaveCreate):
    room = get_room(room_id)
    index = len(room["messages"]) if data.message_index is None else data.message_index
    if index > len(room["messages"]):
        raise HTTPException(400, "Invalid save point")
    save = {"id": str(uuid4()), "room_id": room_id, "label": data.label,
            "message_index": index, "snapshot": deepcopy(room["messages"][:index]),
            "world_rules": room["world_rules"], "characters": deepcopy(room["characters"]),
            "created_at": now()}
    saves[save["id"]] = save
    return {k: v for k, v in save.items() if k != "snapshot"}

@app.get("/rooms/{room_id}/saves")
def list_saves(room_id: str):
    get_room(room_id)
    return [{k: v for k, v in s.items() if k != "snapshot"} for s in saves.values() if s["room_id"] == room_id]

@app.post("/saves/{save_id}/resume")
def resume_save(save_id: str):
    if save_id not in saves:
        raise HTTPException(404, "Save not found")
    save = saves[save_id]
    parent = get_room(save["room_id"])
    child = create_branch(parent, save["message_index"], parent["title"] + " · 이어하기")
    child["messages"] = deepcopy(save["snapshot"])
    child["world_rules"] = save["world_rules"]
    child["characters"] = deepcopy(save["characters"])
    child["source_save_id"] = save_id
    return child
