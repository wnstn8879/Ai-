"""Adopt existing prototype tables without deleting records."""

from alembic import op
import sqlalchemy as sa

revision = "001_legacy"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "rooms" not in existing:
        op.create_table(
            "rooms",
            sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("world_rules", sa.Text(), nullable=False),
            sa.Column("characters_json", sa.Text(), nullable=False),
            sa.Column("mode", sa.String(length=20), nullable=False),
            sa.Column("parent_room_id", sa.String(length=36), nullable=True),
            sa.Column("fork_message_index", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )
    if "messages" not in existing:
        op.create_table(
            "messages",
            sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
            sa.Column(
                "room_id",
                sa.String(length=36),
                sa.ForeignKey("rooms.id"),
                nullable=False,
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("actor", sa.String(length=120), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )
        op.create_index("ix_messages_room_id", "messages", ["room_id"], unique=False)
    if "saves" not in existing:
        op.create_table(
            "saves",
            sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
            sa.Column(
                "room_id",
                sa.String(length=36),
                sa.ForeignKey("rooms.id"),
                nullable=False,
            ),
            sa.Column("label", sa.String(length=100), nullable=False),
            sa.Column("message_index", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )
        op.create_index("ix_saves_room_id", "saves", ["room_id"], unique=False)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade disabled; restore an approved backup instead"
    )
