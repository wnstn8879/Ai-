"""Add rebuildable source recall without changing any story text or snapshot."""

from alembic import op
import sqlalchemy as sa

revision = "007_story_memory"
down_revision = "006_novel_format"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_cursors",
        sa.Column(
            "room_id", sa.String(36), sa.ForeignKey("rooms.id"), primary_key=True
        ),
        sa.Column("next_position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "memory_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column(
            "message_id", sa.String(36), sa.ForeignKey("messages.id"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("segment", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
    )
    op.create_index(
        "uq_memory_message_segment",
        "memory_chunks",
        ["message_id", "segment"],
        unique=True,
    )
    op.create_index("ix_memory_room_position", "memory_chunks", ["room_id", "position"])
    op.create_table(
        "memory_terms",
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("memory_chunks.id"),
            primary_key=True,
        ),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("term", sa.String(66), primary_key=True),
    )
    op.create_index("ix_memory_room_term", "memory_terms", ["room_id", "term"])


def downgrade():
    op.drop_table("memory_terms")
    op.drop_table("memory_chunks")
    op.drop_table("memory_cursors")
