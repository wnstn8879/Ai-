from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4

app = FastAPI(title='StoryVerse AI API', version='0.1.0')
rooms = {}

class RoomCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    world_rules: str = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)

class MessageCreate(BaseModel):
    actor: str
    content: str = Field(min_length=1)

class ForkCreate(BaseModel):
    title: str
    message_index: int = Field(ge=0)

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/rooms')
def create_room(data: RoomCreate):
    room_id = str(uuid4())
    rooms[room_id] = {'id': room_id, 'title': data.title, 'world_rules': data.world_rules, 'characters': data.characters, 'parent_room_id': None, 'messages': [], 'mode': 'solo'}
    return rooms[room_id]

@app.get('/rooms/{room_id}')
def get_room(room_id: str):
    if room_id not in rooms:
        raise HTTPException(404, 'Room not found')
    return rooms[room_id]

@app.post('/rooms/{room_id}/messages')
def add_message(room_id: str, data: MessageCreate):
    room = get_room(room_id)
    msg = {'id': str(uuid4()), **data.model_dump()}
    room['messages'].append(msg)
    return msg

@app.post('/rooms/{room_id}/forks')
def fork_room(room_id: str, data: ForkCreate):
    parent = get_room(room_id)
    if data.message_index > len(parent['messages']):
        raise HTTPException(400, 'Invalid fork point')
    child_id = str(uuid4())
    child = {**parent, 'id': child_id, 'title': data.title, 'parent_room_id': room_id, 'fork_message_index': data.message_index, 'messages': [m.copy() for m in parent['messages'][:data.message_index]], 'mode': 'solo'}
    rooms[child_id] = child
    return child
