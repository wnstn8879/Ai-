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
            == "003_message_order"
        )
