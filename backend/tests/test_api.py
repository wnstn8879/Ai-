from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_fork_is_independent():
    parent = client.post('/rooms', json={'title':'Kingdom','world_rules':'No resurrection','characters':['Knight']}).json()
    rid = parent['id']
    client.post(f'/rooms/{rid}/messages', json={'actor':'Knight','content':'Save the queen'})
    child = client.post(f'/rooms/{rid}/forks', json={'title':'Alternate','message_index':1}).json()
    client.post(f"/rooms/{child['id']}/messages", json={'actor':'Knight','content':'Take another path'})
    assert len(client.get(f'/rooms/{rid}').json()['messages']) == 1
    assert len(client.get(f"/rooms/{child['id']}").json()['messages']) == 2
