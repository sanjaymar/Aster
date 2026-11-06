"""Keep readable original PDFs when a page cannot be converted into text."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "source_spans",
        sa.Column("extraction_error", sa.String(500), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("source_spans", "extraction_error")
