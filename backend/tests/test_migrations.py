import os
import subprocess
import sys
import sqlite3


def test_adopt_legacy_database_preserves_private_records(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE rooms (id VARCHAR(36) PRIMARY KEY, title VARCHAR(120),world_rules TEXT,characters_json TEXT,mode VARCHAR(20),parent_room_id VARCHAR(36),fork_message_index INTEGER,created_at VARCHAR(40))"
        )
        db.execute(
            "INSERT INTO rooms VALUES ('legacy','Old world','Keep me','[]','solo',NULL,NULL,'2026-01-01')"
        )
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(path), PYTHONPATH=".")
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title FROM rooms").fetchone()[0] == "Old world"
        assert db.execute("SELECT count(*) FROM room_members").fetchone()[0] == 0
        assert (
            db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "004_scene_snapshots"
        )


def test_upgrade_existing_checkpoints_pins_legacy_world_state(tmp_path):
    path = tmp_path / "upgrade.db"
    env = dict(os.environ, DATABASE_URL="sqlite:///" + str(path), PYTHONPATH=".")
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "upgrade", "003_message_order"], env=env
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO rooms VALUES ('room','Old world','Keep magic cost','[\"Knight\"]','solo',NULL,NULL,'2026-01-01')"
        )
        db.execute(
            "INSERT INTO messages VALUES ('message','room',0,'Knight','Keep my choice','2026-01-01')"
        )
        db.execute(
            "INSERT INTO saves VALUES ('save','room','Old checkpoint',1,'2026-01-01')"
        )
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
    import json

    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT content FROM messages").fetchone()[0] == "Keep my choice"
        )
        assert db.execute("SELECT message_index FROM saves").fetchone()[0] == 1
        raw = db.execute(
            "SELECT state_json FROM scene_states JOIN save_snapshots ON snapshot_id=scene_states.id WHERE save_id='save'"
        ).fetchone()[0]
        state = json.loads(raw)
        assert state["world_rules"] == "Keep magic cost"
        assert state["characters"][0]["name"] == "Knight"
        assert db.execute("SELECT count(*) FROM room_members").fetchone()[0] == 0
