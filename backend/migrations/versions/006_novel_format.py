"""Separate prose creation/reading from roleplay without rewriting saved stories."""

from alembic import op
import sqlalchemy as sa

revision = "006_novel_format"
down_revision = "005_shared_restores"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "rooms",
        sa.Column(
            "narrative_format", sa.String(16), nullable=False, server_default="roleplay"
        ),
    )


def downgrade():
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("narrative_format")
