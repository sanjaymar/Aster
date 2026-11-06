"""Recoverable project-scoped deletion; immutable evidence stays intact."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trash_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False, index=True
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("object_id", sa.String(32), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("batch", sa.String(32), nullable=False, index=True),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("project_id", "kind", "object_id"),
    )


def downgrade():
    op.drop_table("trash_items")
