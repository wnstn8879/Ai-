"""Add immutable state history and pin each checkpoint to its exact snapshot."""

import json
from uuid import uuid4
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = "004_scene_snapshots"
down_revision = "003_message_order"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scene_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("message_index", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_scene_states_room_id", "scene_states", ["room_id"])
    op.create_index(
        "uq_scene_room_revision", "scene_states", ["room_id", "revision"], unique=True
    )
    op.create_table(
        "save_snapshots",
        sa.Column(
            "save_id", sa.String(36), sa.ForeignKey("saves.id"), primary_key=True
        ),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("scene_states.id"),
            nullable=False,
        ),
    )
    op.create_index("ix_save_snapshots_snapshot_id", "save_snapshots", ["snapshot_id"])
    connection = op.get_bind()
    # Existing records had only static rules and character names; preserve them as revision 0.
    snapshots = {}
    for room in connection.execute(
        sa.text("SELECT id,world_rules,characters_json,created_at FROM rooms")
    ).mappings():
        snapshot_id = str(uuid4())
        snapshots[room["id"]] = snapshot_id
        state = {
            "world_rules": room["world_rules"],
            "location": "",
            "summary": "",
            "facts": [],
            "characters": [
                {
                    "name": name,
                    "personality": "",
                    "speech_style": "",
                    "goal": "",
                    "relationships": "",
                    "condition": "",
                    "memories": [],
                }
                for name in json.loads(room["characters_json"])
            ],
        }
        connection.execute(
            sa.text(
                "INSERT INTO scene_states (id,room_id,revision,message_index,state_json,created_at) VALUES (:id,:room,0,0,:state,:time)"
            ),
            {
                "id": snapshot_id,
                "room": room["id"],
                "state": json.dumps(state, ensure_ascii=False),
                "time": room["created_at"] or datetime.now(timezone.utc).isoformat(),
            },
        )
    for save in connection.execute(sa.text("SELECT id,room_id FROM saves")).mappings():
        if save["room_id"] in snapshots:
            connection.execute(
                sa.text(
                    "INSERT INTO save_snapshots (save_id,snapshot_id) VALUES (:save,:snapshot)"
                ),
                {"save": save["id"], "snapshot": snapshots[save["room_id"]]},
            )


def downgrade():
    raise RuntimeError(
        "Snapshot history is preserved; restore an approved backup instead"
    )
