"""Persist automatic novel writing, draft recovery and the reading lease."""

from alembic import op
import sqlalchemy as sa

revision = "008_novel_writer"
down_revision = "007_story_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "novel_writers",
        sa.Column(
            "room_id", sa.String(36), sa.ForeignKey("rooms.id"), primary_key=True
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        *[
            sa.Column(
                key, sa.Text() if kind == "text" else sa.String(kind), nullable=False
            )
            for key, kind in [
                ("owner_token", 36),
                ("status", 20),
                ("draft", "text"),
                ("pending_direction", "text"),
                ("active_direction", "text"),
                ("question", "text"),
                ("error", "text"),
                ("context_json", "text"),
            ]
        ],
        *[
            sa.Column(key, sa.Integer(), nullable=False)
            for key in [
                "completed",
                "batch_limit",
                "message_count",
                "lease_until",
                "heartbeat",
            ]
        ]
    )


def downgrade():
    op.drop_table("novel_writers")
