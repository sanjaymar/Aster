"""Project reading preferences and immutable text anchors."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reading_states",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("sources.id"), primary_key=True),
        sa.Column("reading_status", sa.String(20), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("last_scroll", sa.Float(), nullable=False),
        sa.Column(
            "last_version_id", sa.String(32), sa.ForeignKey("source_versions.id"), nullable=True
        ),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "reading_status IN ('unread','reading','read')", name="reading_status_valid"
        ),
    )
    op.create_table(
        "annotations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False, index=True
        ),
        sa.Column(
            "source_version_id",
            sa.String(32),
            sa.ForeignKey("source_versions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_span_id", sa.String(32), sa.ForeignKey("source_spans.id"), nullable=False
        ),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("rectangles", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table("annotations")
    op.drop_table("reading_states")
