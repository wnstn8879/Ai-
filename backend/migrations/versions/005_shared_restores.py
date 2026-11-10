"""Shared checkpoints and audited unanimous non-destructive restores."""

from alembic import op
import sqlalchemy as sa

revision = "005_shared_restores"
down_revision = "004_scene_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "saves",
        sa.Column("scope", sa.String(12), nullable=False, server_default="private"),
    )
    op.create_table(
        "shared_checkpoint_rosters",
        sa.Column(
            "save_id", sa.String(36), sa.ForeignKey("saves.id"), primary_key=True
        ),
        sa.Column("characters_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "room_rosters",
        sa.Column(
            "room_id", sa.String(36), sa.ForeignKey("rooms.id"), primary_key=True
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
    )
    op.create_table(
        "restore_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("save_id", sa.String(36), sa.ForeignKey("saves.id"), nullable=False),
        sa.Column(
            "initiator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("roster_fingerprint", sa.String(64), nullable=False),
        sa.Column("eligible_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column(
            "result_room_id", sa.String(36), sa.ForeignKey("rooms.id"), nullable=True
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_restore_proposals_room_id", "restore_proposals", ["room_id"])
    op.create_table(
        "restore_votes",
        sa.Column(
            "proposal_id",
            sa.String(36),
            sa.ForeignKey("restore_proposals.id"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("accept", sa.Boolean(), nullable=False),
        sa.Column("voted_at", sa.String(40), nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Checkpoint and consent history is preserved; restore an approved backup instead"
    )
