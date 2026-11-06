from sqlalchemy import select

from aster.domain.models import (
    EvaluationRun,
)
from aster.domain.schemas import (
    RetrievalInput,
)
from aster.domain.service import Problem, plain, required
from aster.agent.trace import trace_report


def configure(app):
    service = app.state.service
    db = app.state.db
    manager = app.state.manager

    @app.get("/api/collections")
    def collections():
        from aster.data.sources import collection_status

        return collection_status(service)

    @app.get("/api/runs/{run_id}/trace")
    def run_trace(run_id: str):
        return trace_report(service, run_id)

    @app.get("/api/retrieval/status")
    def retrieval_status():
        return manager.retriever.status()

    @app.get("/api/projects/{project_id}/corpus")
    def corpus(project_id: str):
        return {
            **manager.retriever.corpus.overview(project_id),
            "retrieval": manager.retriever.status(),
        }

    @app.post("/api/projects/{project_id}/retrieve")
    def retrieve(project_id: str, body: RetrievalInput):
        if not body.query.strip():
            raise Problem("请填写检索问题")
        snapshot = manager.retriever.corpus.snapshot(
            project_id, body.source_ids, body.artifact_ids, body.scope
        )
        hits, metadata = manager.retriever.search(
            project_id, snapshot, body.query, body.top_k, body.strategy, body.rerank
        )
        return {"hits": [h.public() for h in hits], "metadata": metadata, "snapshot": snapshot}

    @app.post("/api/projects/{project_id}/index")
    def index(project_id: str, body: RetrievalInput):
        snapshot = manager.retriever.corpus.snapshot(
            project_id, body.source_ids, body.artifact_ids, body.scope
        )
        _, metadata = manager.retriever.search(
            project_id, snapshot, "索引检查 index preparation", top_k=1, rerank=False
        )
        return {"status": "ready", **metadata}

    @app.get("/api/projects/{project_id}/memory")
    def memory(project_id: str, conversation_id: str | None = None):
        return manager.pipeline.memory.inspect(project_id, conversation_id)

    @app.get("/api/projects/{project_id}/evaluations")
    def evaluations(project_id: str, summary: bool = False):
        with db.session() as s:
            service.project(s, project_id)
            return [
                {k: v for k, v in plain(r).items() if not summary or k != "results"}
                for r in s.scalars(
                    select(EvaluationRun)
                    .where(EvaluationRun.project_id == project_id)
                    .order_by(EvaluationRun.created_at.desc())
                )
            ]

    @app.get("/api/evaluations/{evaluation_id}")
    def evaluation(evaluation_id: str):
        with db.session() as session:
            row = required(session, EvaluationRun, evaluation_id)
            service.project(session, row.project_id)
            return plain(row)

    @app.get("/api/benchmarks")
    def benchmarks():
        from aster.evaluation.benchmarks import read_benchmarks

        return read_benchmarks()
