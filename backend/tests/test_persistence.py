import os
import subprocess
import sys
import textwrap


def test_records_survive_new_process(tmp_path):
    db_path = tmp_path / "persistent.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(db_path))
    script = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        auth = client.post('/auth/register', json={'email':'persist@example.com','password':'persistent-password','display_name':'Player'}).json()
        client.headers['Authorization'] = 'Bearer '+auth['access_token']
        room = client.post('/rooms', json={'title':'Persistent','world_rules':'Remember choices'}).json()
        client.post(f"/rooms/{room['id']}/messages", json={'actor':'Hero','content':'A choice'})
        save = client.post(f"/rooms/{room['id']}/saves", json={'label':'Checkpoint'}).json()
        print(room['id'] + ',' + save['id'])
    """)
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    created = subprocess.check_output(
        [sys.executable, "-c", script],
        env=env,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    ).strip()
    room_id, save_id = created.split(",")
    verify = textwrap.dedent(f"""
        from fastapi.testclient import TestClient
        from app.main import app
        c=TestClient(app)
        auth=c.post('/auth/login', json={{'email':'persist@example.com','password':'persistent-password'}}).json()
        c.headers['Authorization']='Bearer '+auth['access_token']
        assert len(c.get('/rooms/{room_id}').json()['messages']) == 1
        assert len(c.get('/rooms/{room_id}/saves').json()) == 1
        branch=c.post('/saves/{save_id}/resume').json()
        assert len(branch['messages']) == 1
        assert branch['parent_room_id'] == '{room_id}'
    """)
    subprocess.check_call(
        [sys.executable, "-c", verify],
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
