"""Resumable component/pipeline evaluation with explicit draft-label provenance.

All first outcomes, including failures, remain in the denominator. Source validity,
source agreement, and automated behavior are not called human citation correctness.
"""

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time
import sqlite3

import httpx
from openai import OpenAI
from sqlalchemy import select

from mini_harness.config import Config
from aster.data.sources import save_json, utc_now
from aster.storage.database import Database
from aster.evaluation.retrieval import retrieval_metrics, normalize
from aster.agent.llm import ModelGateway, QueryPlan, NLU_PROMPT
from aster.agent.memory import compact_state
from aster.domain.models import AgentRun, EvaluationRun, PipelineStage, MemorySnapshot
from aster.app.runtime import RunManager
from aster.domain.schemas import RunInput
from aster.domain.service import Service, plain, CITATION
from aster.app.settings import Settings

VARIANTS = {
    "full": {},
    "no-rewrite": {"rewrite": False},
    "no-reflect": {"reflect": False},
    "no-rerank": {"rerank": False},
    "no-memory": {"memory": False},
}


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def classification_metrics(rows):
    correct = sum(r.get("actual") == r["expected"] and not r.get("error") for r in rows)
    labels = sorted({r["expected"] for r in rows})
    return {
        "cases": len(rows),
        "correct": correct,
        "accuracy": ratio(correct, len(rows)),
        "confusion": {
            label: dict(Counter(r.get("actual", "error") for r in rows if r["expected"] == label))
            for label in labels
        },
    }


def pipeline_metrics(rows):
    answer = [r for r in rows if r["expected"] == "answer"]
    citations = [c for r in answer for c in r.get("citations", [])]
    refusals = [r for r in rows if r["expected"] == "refuse"]
    memories = [r for r in rows if r.get("memory_checked")]
    insufficient = [r for r in rows if r.get("category") == "insufficient_evidence"]
    return {
        "cases": len(rows),
        "completed": sum(r.get("status") == "completed" for r in rows),
        "action_accuracy": ratio(sum(r.get("actual") == r["expected"] for r in rows), len(rows)),
        "pipeline_success_rate": ratio(sum(r.get("pipeline_pass", False) for r in rows), len(rows)),
        "refusal_accuracy": ratio(
            sum(r.get("actual") == "refuse" for r in refusals), len(refusals)
        ),
        "refusal_cases": len(refusals),
        "insufficient_evidence_refusal_accuracy": ratio(
            sum(r.get("actual") == "refuse" for r in insufficient), len(insufficient)
        ),
        "insufficient_evidence_cases": len(insufficient),
        "citation_validity": ratio(sum(c["valid"] for c in citations), len(citations)),
        "citation_source_agreement": ratio(
            sum(c["matches_reference_source"] for c in citations), len(citations)
        ),
        "citation_count": len(citations),
        "memory_constraint_consistency": ratio(
            sum(r.get("memory_consistent", False) for r in memories), len(memories)
        ),
        "memory_cases": len(memories),
        "mean_total_tokens": ratio(sum(sum(r.get("usage", {}).values()) for r in rows), len(rows)),
        "mean_seconds": ratio(sum(r.get("seconds", 0) for r in rows), len(rows)),
    }


class Suite:
    def __init__(self, settings, dataset_dir, output):
        self.settings = settings
        self.directory = Path(dataset_dir)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.datasets = {
            name: json.loads((self.directory / f"{name}.json").read_text())
            for name in ["intent", "rewrite", "retrieval", "boundary", "dialogues", "e2e"]
        }
        self.project_id = self.datasets["intent"]["corpus_project_id"]
        self.publish_db = Database(settings.database_url, settings.data_dir)
        self.publish_db.migrate()
        if self.publish_db.engine.dialect.name == "sqlite":
            evaluation_db = self.output.parent / "evaluation.db"
            if not evaluation_db.exists():
                with (
                    sqlite3.connect(self.publish_db.engine.url.database) as original,
                    sqlite3.connect(evaluation_db) as copied,
                ):
                    original.backup(copied)
            settings = replace(settings, database_url=f"sqlite:///{evaluation_db.resolve()}")
        self.db = Database(settings.database_url, settings.data_dir)
        self.db.migrate()
        self.service = Service(self.db)
        self.manager = RunManager(self.service, settings)
        model = self.manager.model_settings()
        if model["model"] == "auto":
            model["model"] = httpx.get(
                settings.model_url + "/models", trust_env=False, timeout=15
            ).json()["data"][0]["id"]
        self.model = model["model"]
        self.manager.model_override = {**model, "max_tokens": 1100, "timeout": 240}
        self.config = Config(
            provider="local",
            model_main=self.model,
            model_sub=self.model,
            base_url=model["base_url"],
            api_key_value=settings.model_key,
            max_tokens_main=1000,
            max_retry=1,
            rate_retry=1,
            retry_base=1,
            rate_base=1,
            temp_set=0,
        )
        self.client = OpenAI(
            base_url=model["base_url"],
            api_key=settings.model_key,
            max_retries=0,
            timeout=180,
            http_client=httpx.Client(trust_env=False, timeout=180),
        )
        self.gateway = ModelGateway(self.client, self.config, lambda: False)
        self.snapshot = self.manager.retriever.corpus.snapshot(self.project_id, scope="project")
        self.items = self.manager.retriever.corpus.items(self.project_id, self.snapshot)
        self.by_id = {item.id: item for item in self.items}
        self.catalog = list(
            {
                item.source_id: {
                    "source_id": item.source_id,
                    "title": item.title,
                    "authority": item.authority,
                    "version": item.version,
                }
                for item in self.items
            }.values()
        )[:8]
        self.base = {
            "model": self.model,
            "model_url": model["base_url"],
            "harness": "mini-harness",
            "created_at": utc_now(),
            "annotation": "author/model-assisted drafts; pending independent human review",
            "metric_scope": "engineering behavior and source agreement, not expert-judged scientific correctness",
            "dataset_hashes": {
                name: hashlib.sha256((self.directory / f"{name}.json").read_bytes()).hexdigest()
                for name in self.datasets
            },
            "retrieval": self.manager.retriever.status(),
            "corpus_sources": len({i.source_id for i in self.items}),
            "corpus_chunks": len(self.items),
        }
        self.reports = {}

    def report(self, name):
        if name not in self.reports:
            path = self.output / f"{name}.json"
            report = (
                json.loads(path.read_text())
                if path.exists()
                else {**self.base, "suite": name, "rows": [], "status": "running"}
            )
            if (
                report.get("dataset_hashes") != self.base["dataset_hashes"]
                or report.get("model") != self.model
            ):
                raise ValueError(
                    "Dataset/model changed; use a new output directory to preserve previous results"
                )
            self.reports[name] = report
        return self.reports[name]

    def persist(self, name, metrics):
        report = self.report(name)
        report["metrics"] = metrics
        report["updated_at"] = utc_now()
        save_json(self.output / f"{name}.json", report)
        with self.db.session() as session:
            row = session.get(EvaluationRun, report.get("evaluation_id", ""))
            if row is None:
                row = EvaluationRun(
                    project_id=self.project_id,
                    dataset=name,
                    config={k: v for k, v in report.items() if k not in {"rows", "metrics"}},
                    metrics=metrics,
                    results=report["rows"],
                )
                session.add(row)
                session.flush()
                report["evaluation_id"] = row.id
            else:
                row.config = {k: v for k, v in report.items() if k not in {"rows", "metrics"}}
                row.metrics = metrics
                row.results = report["rows"].copy()
        # Publish reports without mixing evaluation conversations into personal chat history.
        with self.publish_db.session() as session:
            session.merge(
                EvaluationRun(
                    id=report["evaluation_id"],
                    project_id=self.project_id,
                    dataset=name,
                    config={k: v for k, v in report.items() if k not in {"rows", "metrics"}},
                    metrics=metrics,
                    results=report["rows"].copy(),
                )
            )
        save_json(self.output / f"{name}.json", report)

    def nlu(self, name):
        report = self.report(name)
        report["expected_cases"] = len(self.datasets[name]["cases"])
        done = {r["case_id"] for r in report["rows"]}
        for case in self.datasets[name]["cases"]:
            if case["id"] in done:
                continue
            started = time.monotonic()
            row = {"case_id": case["id"], "question": case["question"], "split": case["split"]}
            try:
                plan, usage = self.gateway.structured(
                    QueryPlan,
                    NLU_PROMPT,
                    {
                        "question": case["question"],
                        "scope": "project",
                        "catalog": self.catalog,
                        "memory": case.get("memory", {}),
                    },
                    750,
                )
                row.update(actual=plan.intent, plan=plan.model_dump(), usage=usage)
                if name == "intent":
                    row["expected"] = case["intent"]
                else:
                    text = " ".join([plan.standalone_query, *plan.queries]).casefold()
                    row["entities_preserved"] = (
                        all(entity.casefold() in text for entity in case["expected_entities"])
                        and not plan.needs_clarification
                    )
            except Exception as error:
                row.update(
                    error=str(error)[:700],
                    actual="error",
                    expected=case.get("intent"),
                    entities_preserved=False,
                )
            row["seconds"] = time.monotonic() - started
            report["rows"].append(row)
            metrics = (
                classification_metrics(report["rows"])
                if name == "intent"
                else {
                    "cases": len(report["rows"]),
                    "rewrite_entity_accuracy": ratio(
                        sum(r.get("entities_preserved", False) for r in report["rows"]),
                        len(report["rows"]),
                    ),
                }
            )
            report["status"] = (
                "complete"
                if len(report["rows"]) == len(self.datasets[name]["cases"])
                else "running"
            )
            self.persist(name, metrics)
            print(name, case["id"], row.get("actual"), flush=True)

    def retrieval(self):
        report = self.report("retrieval")
        report["expected_cases"] = len(self.datasets["retrieval"]["cases"]) * 4
        done = {r["key"] for r in report["rows"]}
        configurations = {
            "bm25": ("bm25", False),
            "dense": ("dense", False),
            "hybrid": ("hybrid", False),
            "hybrid-rerank": ("hybrid", True),
        }
        for strategy, (method, rerank) in configurations.items():
            for case in self.datasets["retrieval"]["cases"]:
                key = strategy + ":" + case["id"]
                if key in done:
                    continue
                gold = [
                    item.id
                    for item in self.items
                    if item.source_id == case["paper"]
                    and any(normalize(anchor) in normalize(item.text) for anchor in case["anchors"])
                ]
                row = {
                    "key": key,
                    "case_id": case["id"],
                    "strategy": strategy,
                    "gold": gold,
                    "split": case["split"],
                }
                started = time.monotonic()
                try:
                    if not gold:
                        raise ValueError("No source anchor matches the indexed corpus")
                    hits, meta = self.manager.retriever.search(
                        self.project_id,
                        self.snapshot,
                        case["query"],
                        top_k=10,
                        strategy=method,
                        rerank=rerank,
                    )
                    row.update(ranking=[hit.evidence.id for hit in hits], retrieval=meta)
                    row["metrics"] = retrieval_metrics(row["ranking"], gold)
                except Exception as error:
                    row.update(
                        error=str(error)[:500],
                        metrics={"recall@5": 0.0, "recall@10": 0.0, "hit@5": 0.0, "mrr@10": 0.0},
                    )
                row["seconds"] = time.monotonic() - started
                report["rows"].append(row)
                metrics = {}
                for label in configurations:
                    rows = [r for r in report["rows"] if r["strategy"] == label]
                    if rows:
                        metrics[label] = {
                            "cases": len(rows),
                            **{
                                metric: sum(r["metrics"][metric] for r in rows) / len(rows)
                                for metric in rows[0]["metrics"]
                            },
                        }
                report["status"] = "complete" if len(report["rows"]) == 400 else "running"
                self.persist("retrieval", metrics)
                print("retrieval", key, flush=True)

    def run_case(self, case, conversation=None):
        start = time.monotonic()
        request = RunInput(
            engine="pipeline",
            prompt=case["question"],
            source_ids=case.get("source_ids") or [item["source_id"] for item in self.catalog[:2]],
            conversation_id=conversation,
        )
        run = self.manager.create(self.project_id, request)
        while time.monotonic() - start < 720:
            with self.db.session() as session:
                current = plain(session.get(AgentRun, run["id"]))
            if current["status"] not in {"queued", "running"}:
                break
            time.sleep(0.25)
        else:
            self.manager.cancel(run["id"])
            current = {"status": "timeout", "result": {}, "error": "case deadline exceeded"}
        result = current.get("result", {})
        pipeline = result.get("pipeline", {})
        answer = pipeline.get("answer", "")
        required = case.get("required_source_ids", [])
        citations = []
        for kind, key in CITATION.findall(answer):
            evidence = self.by_id.get(key) if kind == "C" else None
            if evidence and evidence.source_id not in request.source_ids:
                evidence = None
            citations.append(
                {
                    "kind": kind,
                    "id": key,
                    "valid": evidence is not None,
                    "source_id": evidence.source_id if evidence else None,
                    "matches_reference_source": evidence is not None
                    and (not required or evidence.source_id in required),
                }
            )
        with self.db.session() as session:
            memory = session.scalar(
                select(MemorySnapshot).where(MemorySnapshot.run_id == run["id"])
            )
            stages = [
                plain(stage)
                for stage in session.scalars(
                    select(PipelineStage)
                    .where(PipelineStage.run_id == run["id"])
                    .order_by(PipelineStage.number)
                )
            ]
            constraints = case.get("constraints", [])
            consistent = bool(memory) and all(
                any(constraint in saved for saved in memory.state.get("constraints", []))
                for constraint in constraints
            )
        actual = result.get("answerability")
        coverage = set(required).issubset({c["source_id"] for c in citations})
        success = current["status"] == "completed" and actual == case["expected_action"]
        if case["expected_action"] == "answer":
            success = (
                success and bool(citations) and all(c["valid"] for c in citations) and coverage
            )
        body = re.sub(r"\s+", "", CITATION.sub("", answer).removeprefix("根据目前可核对的证据："))
        return {
            "case_id": case["id"],
            "run_id": run["id"],
            "conversation_id": run["conversation_id"],
            "question": case["question"],
            "split": case.get("split"),
            "category": case.get("category"),
            "expected": case["expected_action"],
            "actual": actual,
            "status": current["status"],
            "pipeline_pass": bool(success),
            "answer": answer,
            "citations": citations,
            "source_coverage": coverage,
            "memory_checked": bool(constraints),
            "memory_consistent": consistent,
            "answer_characters": len(body),
            "within_requested_length": len(body) <= 80 if "80字以内" in constraints else None,
            "usage": pipeline.get("usage", {}),
            "seconds": time.monotonic() - start,
            "error": current.get("error", ""),
            "stage_summary": [
                {
                    "name": s["name"],
                    "attempt": s["attempt"],
                    "status": s["status"],
                    "duration_ms": s["duration_ms"],
                }
                for s in stages
            ],
        }

    def pipeline(self, name, variant="full", limit=None):
        label = name if variant == "full" else name + "-" + variant
        report = self.report(label)
        self.manager.evaluation_options = VARIANTS[variant]
        done = {r["case_id"]: r for r in report["rows"]}
        if name == "boundary":
            cases = self.datasets[name]["cases"]
        else:
            cases = [
                {**turn, "dialogue_id": dialogue["id"], "split": dialogue["split"]}
                for dialogue in self.datasets["dialogues"]["dialogues"]
                for turn in dialogue["turns"]
            ]
        if name == "boundary" and variant != "full":
            cases = [case for case in cases if case.get("category") == "insufficient_evidence"]
        elif limit:
            cases = cases[:limit]
        report["expected_cases"] = len(cases)
        conversation_by_group = {}
        for case in cases:
            group = case.get("dialogue_id")
            if case["id"] in done:
                if group:
                    conversation_by_group[group] = done[case["id"]]["conversation_id"]
                continue
            try:
                row = self.run_case(case, conversation_by_group.get(group) if group else None)
            except Exception as error:
                row = {
                    "case_id": case["id"],
                    "expected": case["expected_action"],
                    "actual": "error",
                    "status": "failed",
                    "error": str(error)[:700],
                    "pipeline_pass": False,
                    "split": case.get("split"),
                }
            if group and row.get("conversation_id"):
                conversation_by_group[group] = row["conversation_id"]
            report["rows"].append(row)
            report["status"] = "complete" if len(report["rows"]) == len(cases) else "running"
            metrics = pipeline_metrics(report["rows"])
            metrics["variant"] = variant
            if name == "dialogues":
                keys = {case["id"] for case in self.datasets["e2e"]["cases"]}
                metrics["e2e_70"] = pipeline_metrics(
                    [row for row in report["rows"] if row["case_id"] in keys]
                )
            self.persist(label, metrics)
            print(label, case["id"], row["status"], row["actual"], flush=True)

    def memory(self):
        report = self.report("memory")
        report["expected_cases"] = 20
        done = {r["case_id"] for r in report["rows"]}
        for case in self.datasets["rewrite"]["cases"][:20]:
            if case["id"] in done:
                continue
            full = {
                **case["memory"],
                "recent_questions": [
                    f"文献阅读记录 {index}: {case['expected_entities'][0]}。"
                    + "请核对实验条件、来源和限制。" * 12
                    for index in range(35)
                ],
                "evidence_refs": [],
                "compacted": False,
            }
            compact = compact_state(full, 1000)
            row = {
                "case_id": case["id"],
                "constraints_preserved": compact["constraints"] == full["constraints"],
                "focus_preserved": compact["focus"] == full["focus"],
                "usage": {},
            }
            for name, state in [("uncompressed", full), ("compressed", compact)]:
                try:
                    plan, usage = self.gateway.structured(
                        QueryPlan,
                        NLU_PROMPT,
                        {
                            "question": case["question"],
                            "memory": state,
                            "catalog": self.catalog,
                            "scope": "project",
                        },
                        750,
                    )
                    row[name] = {
                        "usage": usage,
                        "entity_retained": all(
                            e.casefold()
                            in (plan.standalone_query + " " + " ".join(plan.queries)).casefold()
                            for e in case["expected_entities"]
                        ),
                    }
                except Exception as error:
                    row[name] = {"error": str(error)[:500], "usage": {}, "entity_retained": False}
            report["rows"].append(row)
            before = sum(r["uncompressed"]["usage"].get("prompt_tokens", 0) for r in report["rows"])
            after = sum(r["compressed"]["usage"].get("prompt_tokens", 0) for r in report["rows"])
            report["status"] = "complete" if len(report["rows"]) == 20 else "running"
            self.persist(
                "memory",
                {
                    "cases": len(report["rows"]),
                    "constraint_consistency": sum(
                        r["constraints_preserved"] for r in report["rows"]
                    )
                    / len(report["rows"]),
                    "nlu_entity_consistency": sum(
                        r["compressed"]["entity_retained"] for r in report["rows"]
                    )
                    / len(report["rows"]),
                    "nlu_prompt_token_reduction": 1 - after / before if before else None,
                    "uncompressed_prompt_tokens": before,
                    "compressed_prompt_tokens": after,
                    "scope": "paired NLU component with synthetic long history; not whole-agent token savings",
                },
            )
            print("memory", case["id"], flush=True)

    def close(self):
        self.manager.shutdown()
        self.client.close()
        self.db.engine.dispose()
        self.publish_db.engine.dispose()

    def ablation_summary(self):
        comparisons = []
        for family in ["boundary", "dialogues"]:
            base_path = self.output / f"{family}.json"
            if not base_path.exists():
                continue
            base = json.loads(base_path.read_text())
            baseline = {r["case_id"]: r for r in base["rows"]}
            for path in sorted(self.output.glob(f"{family}-no-*.json")):
                variant = json.loads(path.read_text())
                rows = [r for r in variant["rows"] if r["case_id"] in baseline]
                if not rows:
                    continue
                control = [baseline[r["case_id"]] for r in rows]
                normal, ablated = pipeline_metrics(control), pipeline_metrics(rows)
                comparisons.append(
                    {
                        "variant": path.stem,
                        "paired_cases": len(rows),
                        "case_ids": [r["case_id"] for r in rows],
                        "complete": base["status"] == "complete"
                        and variant["status"] == "complete",
                        "baseline": normal,
                        "ablated": ablated,
                        "pipeline_gain_points": 100
                        * (normal["pipeline_success_rate"] - ablated["pipeline_success_rate"]),
                        "refusal_gain_points": 100
                        * (normal["refusal_accuracy"] - ablated["refusal_accuracy"])
                        if normal["refusal_accuracy"] is not None
                        else None,
                        "token_change_fraction": 1
                        - ablated["mean_total_tokens"] / normal["mean_total_tokens"]
                        if normal["mean_total_tokens"]
                        else None,
                    }
                )
        report = self.report("ablations")
        report["rows"] = comparisons
        report["status"] = (
            "complete" if comparisons and all(row["complete"] for row in comparisons) else "running"
        )
        self.persist(
            "ablations",
            {
                "comparisons": len(comparisons),
                "scope": "paired case intersections; failures included",
            },
        )


def main():
    parser = argparse.ArgumentParser(description="Aster metabolomics evaluation")
    parser.add_argument("--dataset-dir", default=".local/metabolomics/eval")
    parser.add_argument("--output", default=".local/metabolomics/evaluation/run-20261105")
    parser.add_argument("--suites", default="intent,rewrite,retrieval,boundary,dialogues,memory")
    parser.add_argument("--variants", default="full")
    parser.add_argument("--ablation-turns", type=int, default=12)
    args = parser.parse_args()
    suite = Suite(Settings.from_env(), args.dataset_dir, args.output)
    try:
        for name in args.suites.split(","):
            if name in {"intent", "rewrite"}:
                suite.nlu(name)
            elif name == "retrieval":
                suite.retrieval()
            elif name in {"boundary", "dialogues"}:
                for variant in args.variants.split(","):
                    if name == "boundary" and variant not in {"full", "no-reflect"}:
                        continue
                    suite.pipeline(
                        name, variant, None if variant == "full" else args.ablation_turns
                    )
            elif name == "memory":
                suite.memory()
            else:
                raise ValueError("unknown suite: " + name)
    finally:
        try:
            suite.ablation_summary()
        finally:
            suite.close()


if __name__ == "__main__":
    main()
