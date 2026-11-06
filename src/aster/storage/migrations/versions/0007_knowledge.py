"""Project-specific knowledge base preferences, without moving existing sources."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects", sa.Column("knowledge", sa.JSON(), nullable=False, server_default="{}")
    )


def downgrade():
    op.drop_column("projects", "knowledge")
