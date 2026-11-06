import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from openai.types.chat import ChatCompletionMessage
from sqlalchemy import select, inspect

from mini_harness.config import Config
from aster.retrieval.corpus import windows
from aster.storage.database import Database
from aster.domain.models import (
    Conversation,
    AgentRun,
    PipelineStage,
    MemorySnapshot,
    AnswerClaim,
    EvidenceLink,
)
from aster.agent.pipeline import ResearchPipeline
from aster.agent.llm import (
    QueryPlan,
    EvidenceDecision,
    AnswerAudit,
    ClaimCheck,
    ModelGateway,
    GeneratedAnswer,
)
from aster.retrieval.engine import Retriever, bm25, rrf
from aster.domain.schemas import RunInput
from aster.domain.service import Service, Problem
from aster.app.settings import Settings


@pytest.fixture
def env(tmp_path):
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'pipeline.db'}",
        retrieval_mode="lexical",
    )
    db = Database(settings.database_url, tmp_path)
    db.migrate()
    service = Service(db)
    project = service.save_project("分阶段问答测试")
    a = service.import_source(
        project["id"],
        "a.md",
        "## Methods\n\nMethod Alpha uses a fixed random seed and a shared data split. The baseline is BM25.\n\n## Results\n\nNo clinical measurements are reported.".encode(),
        title="Alpha study",
    )
    b = service.import_source(
        project["id"],
        "b.md",
        "## Methods\n\nMethod Beta compares late interaction with dense retrieval. It uses a separate data split.".encode(),
        title="Beta study",
    )
    retriever = Retriever(service, settings)
    return SimpleNamespace(
        settings=settings,
        db=db,
        service=service,
        project=project["id"],
        a=a,
        b=b,
        retriever=retriever,
    )


def start_run(
    env,
    prompt="How does Alpha control its experiment?",
    mode="chat",
    snapshot=None,
    conversation=None,
):
    snapshot = snapshot or env.retriever.corpus.snapshot(env.project, [env.a["id"]], [])
    with env.db.session() as s:
        c = (
            s.get(Conversation, conversation)
            if conversation
            else Conversation(project_id=env.project, title="test")
        )
        if not conversation:
            s.add(c)
            s.flush()
        r = AgentRun(
            project_id=env.project,
            conversation_id=c.id,
            prompt=prompt,
            mode=mode,
            context={"corpus_snapshot": snapshot},
        )
        s.add(r)
        s.flush()
        return r.id, c.id


class Gateway:
    def __init__(self, env, decision="answer", ambiguous=False, unsupported=False):
        self.env, self.decision, self.ambiguous, self.unsupported = (
            env,
            decision,
            ambiguous,
            unsupported,
        )
        self.calls = []

    def structured(self, schema, instruction, payload, maximum=1000):
        self.calls.append(schema.__name__)
        if schema is QueryPlan:
            return QueryPlan(
                intent="lookup",
                standalone_query="Alpha fixed random seed shared data split",
                queries=["Alpha fixed random seed shared data split"],
                targets=[self.env.a["id"]],
                resolved_entities=["Method Alpha"],
                constraints=["固定随机种子"] if "固定随机种子" in payload["question"] else [],
                needs_clarification=self.ambiguous,
                clarification="你指的是 Alpha 还是 Beta？" if self.ambiguous else "",
            ), {}
        if schema is EvidenceDecision:
            return EvidenceDecision(
                action=self.decision,
                reason="test evidence decision",
                missing_facets=["clinical data"] if self.decision == "retrieve_more" else [],
                queries=["clinical data in Alpha"],
            ), {}
        if schema is GeneratedAnswer:
            return GeneratedAnswer(
                answer="Alpha uses a fixed random seed and shared data split. "
                + payload["evidence"][0]["citation"],
                citations=[payload["evidence"][0]["citation"]],
            ), {}
        evidence = payload["evidence"][0]
        ref = evidence["citation"]
        if self.unsupported:
            ref = "[[C:" + "f" * 32 + "]]"
        return AnswerAudit(
            claims=[
                ClaimCheck(
                    text="Alpha uses a fixed random seed and shared data split. " + ref,
                    citations=[ref],
                    verdict="supported",
                    reason="explicit in the source",
                )
            ],
            summary="audit result",
        ), {}


def stub_generation(monkeypatch):
    from mini_harness.agent import MiniHarnessAgent

    def request(self, client, cfg):
        content = json.loads(self.message[-1]["content"])
        ref = content["evidence"][0]["citation"]
        text = "Alpha uses a fixed random seed and shared data split. " + ref
        self._emit("text", text=text)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=ChatCompletionMessage(role="assistant", content=text))
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30),
        ), None

    monkeypatch.setattr(MiniHarnessAgent, "_request_agent", request)


def test_windows_exact_offsets_overlap_and_determinism(env):
    text = "## Methods\n\n" + ("scientific paragraph " * 180) + "\n\nConclusions."
    parts = windows(text)
    assert len(parts) >= 3
    assert all(0 <= a < b <= len(text) and b - a <= 1400 for a, b in parts)
    assert any(parts[i][1] > parts[i + 1][0] for i in range(len(parts) - 1))
    snap = env.retriever.corpus.snapshot(env.project, [env.a["id"]], [])
    one = env.retriever.corpus.items(env.project, snap)
    two = env.retriever.corpus.items(env.project, snap)
    assert [i.id for i in one] == [i.id for i in two]
    with env.db.session() as s:
        from aster.domain.models import SourceChunk, SourceSpan

        for chunk in s.scalars(select(SourceChunk)):
            span = s.get(SourceSpan, chunk.source_span_id)
            assert chunk.text == span.text[chunk.char_start : chunk.char_end]


def test_bm25_small_corpus_chinese_and_rrf():
    scores = bm25("实验方案", ["实验方案需要固定随机种子。", "和科研完全无关。"])
    assert scores[0] > scores[1] and np.isfinite(scores).all()
    assert bm25("shared", ["shared shared", "shared"])[0] > 0
    combined = rrf([["a", "b"], ["b", "c"]])
    assert combined["b"] > combined["a"] and combined["c"] > 0


def test_structured_output_retries_truncation_with_larger_budget():
    calls = []
    plan = QueryPlan(intent="lookup", standalone_query="Alpha", queries=["Alpha"])

    def create(**options):
        calls.append(options)
        text = '{"intent":' if len(calls) == 1 else plan.model_dump_json()
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length" if len(calls) == 1 else "stop",
                    message=SimpleNamespace(content=text),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    value, usage = ModelGateway(
        client,
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda: False,
    ).structured(QueryPlan, "test", {"question": "Alpha"}, 1000)
    assert value == plan and usage["completion_tokens"] == 20
    assert calls[0]["max_tokens"] == 1000 and calls[1]["max_tokens"] == 2000
    assert "json_invalid" in calls[1]["messages"][-1]["content"]


def test_final_answer_rejects_unparsed_tool_markup():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="最终回答不能包含工具调用"):
        GeneratedAnswer(answer="<tool_call><function=read_chunk>...</function></tool_call>")


def test_out_of_scope_turn_does_not_add_research_constraints(env):
    from aster.agent.memory import Memory

    run_id, conversation = start_run(env, prompt="天气如何？请给出实时数值")
    plan = QueryPlan(
        intent="out_of_scope",
        standalone_query="天气",
        queries=["天气"],
        resolved_entities=["天气"],
        constraints=["请给出实时数值"],
    )
    value = Memory(env.service).update(
        env.project,
        conversation,
        run_id,
        "天气如何？请给出实时数值",
        plan,
        EvidenceDecision(action="refuse", reason="out of scope"),
        [],
        set(),
    )
    assert value["constraints"] == [] and value["focus"] == []


def test_recovery_closes_interrupted_stages_and_rejects_unsupported_scope(env):
    from aster.app.runtime import RunManager

    run_id, _ = start_run(env)
    with env.db.session() as s:
        s.get(AgentRun, run_id).status = "running"
        s.add(PipelineStage(run_id=run_id, number=1, name="NLU"))
    manager = RunManager(env.service, env.settings)
    try:
        manager.recover()
        with env.db.session() as s:
            assert s.get(AgentRun, run_id).status == "interrupted"
            stage = s.scalar(select(PipelineStage).where(PipelineStage.run_id == run_id))
            assert stage.status == "interrupted" and stage.finished_at
        with pytest.raises(Problem, match="基础助手仅支持"):
            manager.create(
                env.project, RunInput(prompt="test", engine="harness", retrieval_scope="project")
            )
    finally:
        manager.shutdown()


def test_nonempty_v1_upgrade_preserves_old_citations(env):
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.migration import MigrationContext
    from alembic.autogenerate import compare_metadata
    from aster.domain.models import Base, SourceSpan

    with env.db.session() as s:
        span = s.scalar(select(SourceSpan))
        old_id = span.id
    note = env.service.save_record(
        env.project, title="v1 note", kind="note", content=f"[[S:{old_id}]]"
    )
    cfg = AlembicConfig()
    cfg.set_main_option(
        "script_location", str(Path(__file__).parents[2] / "src/aster/storage/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", env.db.url)
    with env.db.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0001")
        assert "source_chunks" not in inspect(connection).get_table_names()
    env.db.migrate()
    with env.db.session() as s:
        evidence = env.service.evidence(s, env.project, "S", old_id)
        link = s.scalar(
            select(EvidenceLink).where(EvidenceLink.artifact_version_id == note["version"]["id"])
        )
        assert (
            evidence["content"] and link.source_span_id == old_id and link.source_chunk_id is None
        )
    with env.db.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_selection_applied_before_top_k_and_snapshot_pinned(env):
    for i in range(40):
        env.service.import_source(
            env.project, f"noise{i}.txt", b"baseline BM25 common noise", title=f"noise-{i}"
        )
    snap = env.retriever.corpus.snapshot(env.project, [env.a["id"]], [])
    hits, metadata = env.retriever.search(
        env.project, snap, "baseline BM25", top_k=5, strategy="bm25", rerank=False
    )
    assert hits and all(h.evidence.source_id == env.a["id"] for h in hits)
    env.service.import_source(
        env.project, "new.md", b"New unrelated revision", source_id=env.a["id"]
    )
    pinned = env.retriever.corpus.items(env.project, snap)
    assert all(i.version == 1 and "BM25" in i.text for i in pinned)


def test_chunk_citations_roundtrip_export_restore(env):
    item = env.retriever.corpus.items(
        env.project, env.retriever.corpus.snapshot(env.project, [env.a["id"]], [])
    )[0]
    record = env.service.save_record(
        env.project, title="Chunk citation", kind="note", content="Read " + item.citation
    )
    with env.db.session() as s:
        link = s.scalar(
            select(EvidenceLink).where(EvidenceLink.artifact_version_id == record["version"]["id"])
        )
        assert link.source_chunk_id == item.id
    restored = env.service.restore(env.service.export(env.project))
    copied = env.service.artifacts(restored["id"])[0]
    assert item.id not in copied["version"]["content"]
    from aster.domain.service import CITATION

    typ, key = CITATION.findall(copied["version"]["content"])[0]
    with env.db.session() as s:
        assert env.service.evidence(s, restored["id"], typ, key)["content"] == item.text


def test_seven_stages_use_harness_then_verify_before_save(env, monkeypatch):
    stub_generation(monkeypatch)
    run_id, conversation = start_run(env, mode="writing")
    events = []
    pipeline = ResearchPipeline(env.service, env.retriever)
    result = pipeline.run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda kind, data: events.append((kind, data)),
        gateway=Gateway(env),
    )
    assert result["answerability"] == "answer" and result["artifact_ids"]
    assert any(e[0] == "draft_text" for e in events) and any(
        e[0] == "answer_verified" for e in events
    )
    with env.db.session() as s:
        names = list(
            s.scalars(
                select(PipelineStage.name)
                .where(PipelineStage.run_id == run_id)
                .order_by(PipelineStage.number)
            )
        )
        assert names == ["Guardrails", "NLU", "Retrieve", "Rerank", "Reflect", "Generate", "Memory"]
        assert (
            s.scalar(select(AnswerClaim).where(AnswerClaim.run_id == run_id)).verdict == "supported"
        )
        assert s.scalar(select(MemorySnapshot).where(MemorySnapshot.run_id == run_id)).state[
            "focus"
        ] == ["Method Alpha"]


def test_generation_forces_answer_after_two_tool_rounds(env, monkeypatch):
    from mini_harness.agent import MiniHarnessAgent

    choices = []

    def request(self, client, cfg):
        material = json.loads(self.message[1]["content"])
        evidence = material["evidence"][0]
        choices.append("tools_available")
        message = {"role": "assistant", "content": None}
        if len(choices) < 3:
            message["tool_calls"] = [
                {
                    "id": f"read-{len(choices)}",
                    "type": "function",
                    "function": {
                        "name": "read_chunk",
                        "arguments": json.dumps({"id": evidence["id"]}),
                    },
                }
            ]
        else:
            message["content"] = (
                "Alpha uses a fixed random seed and shared data split. " + evidence["citation"]
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=ChatCompletionMessage.model_validate(message))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30),
        ), None

    monkeypatch.setattr(MiniHarnessAgent, "_request_agent", request)
    run_id, _ = start_run(env)
    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=Gateway(env),
    )
    assert choices == ["tools_available", "tools_available"]
    assert result["answerability"] == "answer" and result["harness"]["calls"] == 2


def test_reflection_is_bounded_and_never_generates_with_missing_evidence(env):
    run_id, _ = start_run(env)
    gateway = Gateway(env, decision="retrieve_more")
    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=gateway,
    )
    assert result["answerability"] == "refuse" and not result["artifact_ids"]
    assert gateway.calls.count("EvidenceDecision") == 2
    with env.db.session() as s:
        stages = list(s.scalars(select(PipelineStage).where(PipelineStage.run_id == run_id)))
        assert sum(row.name == "Retrieve" for row in stages) == 2
        assert next(row for row in stages if row.name == "Generate").status == "skipped"


def test_ambiguous_reference_clarifies_before_retrieval(env):
    run_id, _ = start_run(env, prompt="它更好吗？")
    gateway = Gateway(env, ambiguous=True)
    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=gateway,
    )
    assert result["answerability"] == "clarify" and gateway.calls == ["QueryPlan"]


def test_false_citation_rejected_even_if_judge_says_supported(env, monkeypatch):
    stub_generation(monkeypatch)
    run_id, _ = start_run(env, mode="writing")
    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=Gateway(env, unsupported=True),
    )
    assert result["answerability"] == "refuse" and not result["artifact_ids"]
    assert result["claims"][0]["verdict"] == "unsupported"


def test_vague_reference_without_history_overrides_confident_model(env):
    snapshot = env.retriever.corpus.snapshot(env.project, [env.a["id"], env.b["id"]], [])
    run_id, _ = start_run(env, prompt="它和另一个方法相比怎么样？", snapshot=snapshot)
    gateway = Gateway(env, ambiguous=False)
    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=gateway,
    )
    assert result["answerability"] == "clarify" and gateway.calls == ["QueryPlan"]


def test_constraints_survive_compaction_and_scope_does_not_expand(env):
    from aster.agent.memory import Memory

    memory = Memory(env.service, budget=160)
    plan = QueryPlan(
        intent="lookup",
        standalone_query="Alpha",
        queries=["Alpha"],
        resolved_entities=["Alpha"],
        constraints=["固定随机种子"],
    )
    decision = EvidenceDecision(action="answer", reason="test")
    run_id, conv = start_run(env)
    first = memory.update(
        env.project, conv, run_id, "固定随机种子", plan, decision, ["[[C:" + "a" * 32 + "]]"], set()
    )
    assert first["evidence_refs"] == []
    for i in range(8):
        run_id, _ = start_run(env, prompt="长问题" * 100, conversation=conv)
        last = memory.update(env.project, conv, run_id, "长问题" * 100, plan, decision, [], set())
    assert last["constraints"] == ["固定随机种子"] and last["compacted"] and last["turns"] == 9


def test_empty_scope_needs_no_model_and_all_stages_are_visible(env):
    run_id, _ = start_run(env, snapshot={"source_version_ids": [], "artifact_version_ids": []})
    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(provider="local", model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=Gateway(env),
    )
    assert result["answerability"] == "clarify" and result["stages"] == 7


def test_retrieval_evaluation_defines_recall_separately_from_hit():
    from aster.evaluation.retrieval import retrieval_metrics

    value = retrieval_metrics(["a", "x", "y"], ["a", "b"])
    assert value["hit@5"] == 1 and value["recall@5"] == 0.5 and value["mrr@10"] == 1


@pytest.mark.parametrize("discussion", [False, True])
def test_research_proposals_require_explicit_discussion_and_never_become_observed_results(
    env, monkeypatch, discussion
):
    stub_generation(monkeypatch)
    run_id, _ = start_run(env, mode="reading")
    with env.db.session() as session:
        row = session.get(AgentRun, run_id)
        row.context = {**row.context, "response_style": "discussion" if discussion else "grounded"}

    class ProposalGateway(Gateway):
        def structured(self, schema, instruction, payload, maximum=1000):
            if schema is AnswerAudit:
                return AnswerAudit(
                    claims=[
                        ClaimCheck(
                            text="建议固定数据划分后比较方法，效果仍待验证。",
                            citations=[],
                            verdict="inference",
                            reason="future design proposal",
                        ),
                        ClaimCheck(
                            text="实验已证明准确率达到99.9%。",
                            citations=[],
                            verdict="unsupported",
                            reason="no such experiment",
                        ),
                    ],
                    summary="proposal and fabricated result",
                ), {}
            return super().structured(schema, instruction, payload, maximum)

    result = ResearchPipeline(env.service, env.retriever).run(
        run_id,
        object(),
        Config(model_main="offline-fixture", model_sub="offline-fixture"),
        lambda *_: None,
        gateway=ProposalGateway(env),
    )
    assert "99.9%" not in result["answer"]
    if discussion:
        assert result["answerability"] == "answer" and "待验证的分析与建议" in result["answer"]
        assert len(result["artifact_ids"]) == 1
    else:
        assert result["answerability"] == "refuse" and not result["artifact_ids"]
