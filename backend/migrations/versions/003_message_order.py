"""Enforce message order uniqueness without rewriting legacy data."""

from alembic import op

revision = "003_message_order"
down_revision = "002_identity"
branch_labels = None
depends_on = None


def upgrade():
    # If legacy duplicates exist, stop here for explicit administrator remediation.
    op.create_index(
        "uq_message_room_position", "messages", ["room_id", "position"], unique=True
    )


def downgrade():
    op.drop_index("uq_message_room_position", table_name="messages")
