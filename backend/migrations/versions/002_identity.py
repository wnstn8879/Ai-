"""Add identity, private membership, friends, invitations and idempotency."""

from alembic import op
import sqlalchemy as sa

revision = "002_identity"
down_revision = "001_legacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "room_id", sa.String(length=36), sa.ForeignKey("rooms.id"), nullable=False
        ),
        sa.Column("day", sa.String(length=10), nullable=False),
    )
    op.create_index("ix_ai_usage_day", "ai_usage", ["day"], unique=False)
    op.create_index("ix_ai_usage_room_id", "ai_usage", ["room_id"], unique=False)
    op.create_index("ix_ai_usage_user_id", "ai_usage", ["user_id"], unique=False)
    op.create_table(
        "friendships",
        sa.Column(
            "first_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "second_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "sender_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(length=12), nullable=False),
    )
    op.create_table(
        "invitations",
        sa.Column("code_hash", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column(
            "room_id", sa.String(length=36), sa.ForeignKey("rooms.id"), nullable=False
        ),
        sa.Column("expires", sa.Integer(), nullable=False),
        sa.Column(
            "used_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
        ),
    )
    op.create_index("ix_invitations_room_id", "invitations", ["room_id"], unique=False)
    op.create_table(
        "message_receipts",
        sa.Column(
            "room_id",
            sa.String(length=36),
            sa.ForeignKey("rooms.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "room_members",
        sa.Column(
            "room_id",
            sa.String(length=36),
            sa.ForeignKey("rooms.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("role", sa.String(length=12), nullable=False),
        sa.Column("character", sa.String(length=120), nullable=False),
        sa.Column("last_played_at", sa.String(length=40), nullable=False),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("access_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("refresh_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("access_expires", sa.Integer(), nullable=False),
        sa.Column("refresh_expires", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "save_owners",
        sa.Column(
            "save_id",
            sa.String(length=36),
            sa.ForeignKey("saves.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
    )
    op.create_index("ix_save_owners_user_id", "save_owners", ["user_id"], unique=False)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade disabled; restore an approved backup instead"
    )
