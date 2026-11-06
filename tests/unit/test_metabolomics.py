import json
from dataclasses import replace
import numpy as np
import pytest

from mini_harness.agent import MiniHarnessAgent, DeepSeekAgent
from aster.data.sources import article_text, save_json, sha
from aster.storage.database import Database
from aster.evaluation.suite import classification_metrics, pipeline_metrics
from aster.domain.models import AgentRun, PipelineStage, RunEvent, Conversation, SourceVersion
from aster.retrieval.engine import BM25Index, Retriever, bm25
from aster.domain.service import Service
from aster.app.settings import Settings
from aster.agent.trace import trace_report
from sqlalchemy import select, func


def test_provider_neutral_name_preserves_upstream_imports():
    assert MiniHarnessAgent is DeepSeekAgent


def test_public_fulltext_requires_body_and_preserves_source():
    metadata = {
        "title": "Metabolomics fixture",
        "url": "https://example.org/article",
        "doi": "10.1/example",
    }
    with pytest.raises(ValueError, match="no article body"):
        article_text(b"<article><front/></article>", metadata)
    paragraph = "Metabolomics methods use pooled quality-control samples. " * 60
    xml = f"<article><front><article-meta><permissions><license>CC BY</license></permissions></article-meta></front><body><sec><title>Methods</title><p>{paragraph}</p></sec></body></article>".encode()
    text, license_text = article_text(xml, metadata)
    assert paragraph.strip() in text and "## Methods" in text and metadata["url"] in text
    assert license_text == "CC BY" and "not PDF page numbers" in text


def test_cached_bm25_ranks_rare_terms_and_is_reusable():
    documents = [
        "mass spectrometry pooled QC",
        "mass spectrometry batch drift",
        "plasma sample sample",
        "独立质量控制样本",
    ]
    index = BM25Index(documents)
    assert np.argmax(index.score("batch drift")) == 1
    assert np.argmax(index.score("质量控制")) == 3
    assert not index.score("unseen term").any()
    assert np.allclose(index.score("sample"), bm25("sample", documents))
    assert np.argmax(index.score("batch drift")) == 1


def test_failure_rows_stay_in_quality_denominators():
    rows = [
        {"expected": "lookup", "actual": "lookup"},
        {"expected": "lookup", "actual": "error", "error": "timeout"},
    ]
    assert classification_metrics(rows)["accuracy"] == 0.5
    result = pipeline_metrics(
        [
            {
                "expected": "answer",
                "actual": "answer",
                "status": "completed",
                "pipeline_pass": True,
            },
            {
                "expected": "refuse",
                "actual": None,
                "status": "failed",
                "pipeline_pass": False,
                "category": "insufficient_evidence",
            },
        ]
    )
    assert result["pipeline_success_rate"] == 0.5
    assert result["refusal_accuracy"] == 0 and result["insufficient_evidence_refusal_accuracy"] == 0
    assert result["citation_validity"] is None


def test_new_env_names_keep_legacy_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTER_HOME", str(tmp_path / "new"))
    monkeypatch.setenv("ZHIXU_DATA_DIR", str(tmp_path / "old"))
    monkeypatch.setenv("ASTER_DATA_DIR", str(tmp_path / "new"))
    monkeypatch.setenv("ASTER_MODEL", "test-qwen")
    settings = Settings.from_env()
    assert settings.data_dir == tmp_path / "new" and settings.model_name == "test-qwen"


def test_turn_trace_links_tool_calls_to_stage_and_duration(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/db.sqlite", tmp_path)
    db.migrate()
    service = Service(db)
    project = service.save_project("Trace fixture")
    with db.session() as session:
        conversation = Conversation(project_id=project["id"], title="fixture")
        session.add(conversation)
        session.flush()
        run = AgentRun(
            project_id=project["id"],
            conversation_id=conversation.id,
            prompt="test",
            status="completed",
            created_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:02+00:00",
            context={"model_config": {"model": "qwen"}},
        )
        session.add(run)
        session.flush()
        run_id = run.id
        stage = PipelineStage(run_id=run_id, number=1, name="Generate", status="completed")
        session.add(stage)
        session.flush()
        for number, (kind, payload, timestamp) in enumerate(
            [
                ("stage_start", {"id": stage.id}, "2026-01-01T00:00:00+00:00"),
                (
                    "tool_start",
                    {"id": "call1", "name": "read_chunk", "arguments": '{"id":"chunk1"}'},
                    "2026-01-01T00:00:00+00:00",
                ),
                (
                    "tool_end",
                    {"id": "call1", "ok": True, "content": "evidence"},
                    "2026-01-01T00:00:01+00:00",
                ),
                ("stage_end", {"id": stage.id}, "2026-01-01T00:00:02+00:00"),
            ],
            1,
        ):
            session.add(
                RunEvent(
                    run_id=run_id, number=number, kind=kind, payload=payload, created_at=timestamp
                )
            )
    report = trace_report(service, run_id, project["id"])
    assert report["turn"]["duration_ms"] == 2000
    call = report["turn"]["tool_calls"][0]
    assert call["stage_id"] == report["stages"][0]["id"] and call["duration_ms"] == 1000
    assert call["result"]["content"] == "evidence"


def test_large_corpus_ownership_is_checked_without_one_query_per_chunk(tmp_path):
    from sqlalchemy import event
    from aster.retrieval.corpus import Corpus
    from aster.domain.service import Problem

    db = Database(f"sqlite:///{tmp_path}/db.sqlite", tmp_path)
    db.migrate()
    service = Service(db)
    project = service.save_project("Many chunks")
    other = service.save_project("Other project")
    text = "\n\n".join(
        f"Paragraph {i}: " + "metabolomics chromatography quality control. " * 28 for i in range(80)
    )
    service.import_source(project["id"], "paper.md", text.encode())
    foreign = service.import_source(other["id"], "private.md", b"private text")
    corpus = Corpus(service)
    snapshot = corpus.snapshot(project["id"], scope="project")
    corpus.items(project["id"], snapshot)
    statements = []

    def capture(*args):
        statements.append(1)

    event.listen(db.engine, "before_cursor_execute", capture)
    items = corpus.items(project["id"], snapshot)
    event.remove(db.engine, "before_cursor_execute", capture)
    assert len(items) > 60 and len(statements) < 20
    with pytest.raises(Problem, match="不属于当前项目"):
        corpus.items(project["id"], {**snapshot, "source_version_ids": [foreign["version_id"]]})


def test_console_slash_commands_share_real_corpus_and_memory(tmp_path):
    from aster.app.console import diagnostic_console

    db = Database(f"sqlite:///{tmp_path}/db.sqlite", tmp_path)
    db.migrate()
    service = Service(db)
    project = service.save_project("Console fixture")
    settings = replace(Settings.from_env(), data_dir=tmp_path, retrieval_mode="lexical")
    commands = iter(["/corpus", "/memory", "/quit"])
    output = []
    diagnostic_console(
        service,
        Retriever(service, settings),
        project["id"],
        read=lambda _: next(commands),
        write=output.append,
    )
    assert "/trace RUN_ID" in output[0]
    assert json.loads(output[1])["sources"] == 0
    assert json.loads(output[2]) == []


def test_coding_cli_defaults_to_local_and_resolves_actual_model(monkeypatch):
    import os
    from types import SimpleNamespace
    from mini_harness.config import build_config

    for name in list(os.environ):
        if name.startswith("MINI_HARNESS_"):
            monkeypatch.delenv(name)
    cfg = build_config()
    assert cfg.provider == "local" and cfg.model_main == "auto"
    client = SimpleNamespace(
        models=SimpleNamespace(
            list=lambda: SimpleNamespace(data=[SimpleNamespace(id="local-qwen")])
        )
    )
    resolved = cfg.resolve_model(client)
    assert resolved.model_main == resolved.model_sub == "local-qwen"
    monkeypatch.setenv("MINI_HARNESS_MODEL", "local/qwen-custom")
    assert build_config().model_main == "qwen-custom"


def test_citation_review_does_not_count_unreviewed_or_uncertain_as_correct():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "citation_review", "scripts/evaluation/citation_review.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {"review_id": "a", "supported": "", "reviewer": ""},
        {"review_id": "b", "supported": "yes", "reviewer": "independent"},
        {"review_id": "c", "supported": "uncertain", "reviewer": "independent"},
    ]
    result = module.score_reviews(rows)
    assert result["reviewed"] == 2 and result["reviewed_citation_support_accuracy"] == 0.5
    rows[0]["supported"] = "yes"
    with pytest.raises(ValueError, match="reviewer"):
        module.score_reviews(rows)


def test_benchmark_history_keeps_zero_scores_and_separates_environment_errors(tmp_path):
    from aster.evaluation.benchmarks import read_benchmarks

    old = tmp_path / "qwen-swe-old/2026-01-01__00-00-00"
    new = tmp_path / "aster-qwen-swe-final/2026-11-05__00-00-00"
    for directory, date in [(old, "2026-01-01"), (new, "2026-11-05")]:
        directory.mkdir(parents=True)
        save_json(
            directory / "result.json",
            {"started_at": date, "finished_at": date, "n_total_trials": 2},
        )
    save_json(old / "graded/result.json", {"verifier_result": {"rewards": {"reward": 0}}})
    save_json(
        old / "environment/result.json", {"exception_info": {"exception_type": "RuntimeError"}}
    )
    save_json(new / "graded/result.json", {"verifier_result": {"rewards": {"reward": 1}}})
    rows = read_benchmarks(tmp_path)
    assert rows[0]["resolved"] == rows[0]["graded"] == 1
    assert rows[1]["score"] == 0 and rows[1]["exceptions"] == 1 and rows[1]["graded"] == 1
