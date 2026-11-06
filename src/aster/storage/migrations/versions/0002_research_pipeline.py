"""Immutable chunks, scoped indexes, stage traces, claims and memory snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "source_version_id", sa.String(32), sa.ForeignKey("source_versions.id"), nullable=False
        ),
        sa.Column(
            "source_span_id", sa.String(32), sa.ForeignKey("source_spans.id"), nullable=False
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(500), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("chunker_version", sa.String(80), nullable=False),
        sa.UniqueConstraint("source_version_id", "chunker_version", "ordinal"),
    )
    op.create_index("ix_source_chunks_source_version_id", "source_chunks", ["source_version_id"])
    with op.batch_alter_table("evidence_links") as batch:
        batch.add_column(sa.Column("source_chunk_id", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_evidence_chunk", "source_chunks", ["source_chunk_id"], ["id"])
        batch.drop_constraint("one_evidence_target", type_="check")
        batch.create_check_constraint(
            "one_evidence_target",
            "(CASE WHEN source_span_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN target_version_id IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN source_chunk_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
    op.create_table(
        "index_manifests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_index_manifests_project_id", "index_manifests", ["project_id"])
    op.create_table(
        "pipeline_stages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.UniqueConstraint("run_id", "number"),
    )
    op.create_index("ix_pipeline_stages_run_id", "pipeline_stages", ["run_id"])
    op.create_table(
        "memory_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "conversation_id", sa.String(32), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_memory_snapshots_project_id", "memory_snapshots", ["project_id"])
    op.create_index("ix_memory_snapshots_conversation_id", "memory_snapshots", ["conversation_id"])
    op.create_table(
        "answer_claims",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_answer_claims_run_id", "answer_claims", ["run_id"])
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("dataset", sa.String(300), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_evaluation_runs_project_id", "evaluation_runs", ["project_id"])


def downgrade():
    for name in [
        "evaluation_runs",
        "answer_claims",
        "memory_snapshots",
        "pipeline_stages",
        "index_manifests",
    ]:
        op.drop_table(name)
    with op.batch_alter_table("evidence_links") as batch:
        batch.drop_constraint("one_evidence_target", type_="check")
        batch.drop_constraint("fk_evidence_chunk", type_="foreignkey")
        batch.drop_column("source_chunk_id")
        batch.create_check_constraint(
            "one_evidence_target",
            "(source_span_id IS NOT NULL AND target_version_id IS NULL) OR (source_span_id IS NULL AND target_version_id IS NOT NULL)",
        )
    op.drop_table("source_chunks")
