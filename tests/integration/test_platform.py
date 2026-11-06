import io
import json
import os
import time
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import inspect, select

from aster.app.api import create_app
from aster.domain.models import AgentRun, EvidenceLink
from aster.app.settings import Settings


@pytest.fixture(params=["sqlite", "postgres"])
def client(tmp_path, request):
    url = (
        os.getenv("ZHIXU_TEST_POSTGRES_URL")
        if request.param == "postgres"
        else f"sqlite:///{tmp_path / 'test.db'}"
    )
    if not url:
        pytest.skip("set ZHIXU_TEST_POSTGRES_URL to exercise PostgreSQL")
    settings = Settings(
        tmp_path, url, "http://127.0.0.1:1/v1", "test-qwen", "local", "", tmp_path / "static"
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    if request.param == "postgres":
        from aster.domain.models import Base

        Base.metadata.drop_all(app.state.db.engine)
        with app.state.db.engine.begin() as connection:
            from sqlalchemy import text

            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    app.state.db.engine.dispose()


def project(c, title="可复现研究", domain="research"):
    response = c.post("/api/projects", json={"title": title, "domain": domain})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def source(c, pid, text="控制变量与实验数据需要分别记录。", source_id=None):
    data = {"title": "方法研究 A"}
    if source_id:
        data["source_id"] = source_id
    response = c.post(
        f"/api/projects/{pid}/sources",
        data=data,
        files={"file": ("paper.txt", text.encode(), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def note(c, pid, content, **kwargs):
    response = c.post(
        f"/api/projects/{pid}/artifacts",
        json={"title": "我的理解", "kind": "note", "content": content, **kwargs},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_migrations_project_extensions_and_no_model_dependency(client):
    assert len(inspect(client.app.state.db.engine).get_table_names()) == 28
    pid = project(client)
    assert client.get(f"/api/projects/{pid}/overview").json()["counts"]["sources"] == 0
    general = project(client, "课程研究", "general")
    r = client.post(f"/api/projects/{general}/experiments", json={"title": "不能创建实验"})
    assert r.status_code == 404
    assert client.get("/api/health").json()["status"] == "ok"


def test_source_revisions_and_immutable_evidence(client):
    pid = project(client)
    src = source(client, pid, "原文 v1：对照组使用相同的数据划分。")
    span = client.get(f"/api/projects/{pid}/sources/{src['id']}/pages").json()["pages"][0]
    record = note(client, pid, "原文依据 [[S:" + span["id"] + "]]")
    source(client, pid, "原文 v2：修改了数据划分。", src["id"])
    old = client.get(f"/api/projects/{pid}/evidence/S/{span['id']}").json()
    assert old["version"] == 1 and "相同的数据划分" in old["content"]
    updated = client.put(
        f"/api/projects/{pid}/artifacts/{record['id']}",
        json={
            "title": "我的理解",
            "kind": "note",
            "content": "更新后的笔记",
            "expected_revision": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    history = client.get(f"/api/projects/{pid}/artifacts/{record['id']}/history").json()["versions"]
    assert len(history) == 2 and history[1]["content"] == record["version"]["content"]
    stale = client.put(
        f"/api/projects/{pid}/artifacts/{record['id']}",
        json={"title": "过期保存", "kind": "note", "content": "冲突", "expected_revision": 1},
    )
    assert stale.status_code == 409


def test_invalid_and_cross_project_citations_are_rolled_back(client):
    p1, p2 = project(client), project(client, "另一个项目")
    src = source(client, p1)
    span = client.get(f"/api/projects/{p1}/sources/{src['id']}/pages").json()["pages"][0]
    r = client.post(
        f"/api/projects/{p2}/artifacts",
        json={"title": "错误引用", "content": "[[S:" + span["id"] + "]]", "kind": "note"},
    )
    assert r.status_code == 404
    r = client.post(
        f"/api/projects/{p2}/artifacts",
        json={"title": "虚构引用", "content": "[[V:" + "a" * 32 + "]]", "kind": "note"},
    )
    assert r.status_code == 404
    assert client.get(f"/api/projects/{p2}/artifacts").json() == []
    note(client, p1, "有效 [[S:" + span["id"] + "]]")
    with client.app.state.db.session() as s:
        assert len(list(s.scalars(select(EvidenceLink)))) == 1


def test_csv_and_chinese_search(client):
    pid = project(client)
    source(client, pid, "实验数据 100%_可靠 需要核对。")
    note(client, pid, "比较实验数据，不能混淆样本量与观测数。")
    found = client.get(f"/api/projects/{pid}/search", params={"q": "实验数据"}).json()
    assert {f["kind"] for f in found} == {"S", "V"}
    assert client.get(f"/api/projects/{pid}/search", params={"q": "%_"}).json()[0]["kind"] == "S"
    asset = client.post(
        f"/api/projects/{pid}/assets",
        files={"file": ("metrics.csv", b"method,value\nA,1\nB,3\nC,NaN\nD,inf\n", "text/csv")},
    ).json()
    preview = client.get(f"/api/projects/{pid}/assets/{asset['id']}/csv").json()
    assert preview["numeric"]["value"] == {"count": 2, "min": 1, "max": 3, "mean": 2}


def test_pdf_retains_pages_and_rejects_bad_formats(client):
    pid = project(client)
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    content = io.BytesIO()
    writer.write(content)
    r = client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("scan.pdf", content.getvalue(), "application/pdf")},
    )
    assert r.status_code == 201 and r.json()["page_count"] == 2 and not r.json()["text_available"]
    r = client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("bad.exe", b"not a paper", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_backup_restore_rewrites_references_and_checks_blobs(client):
    pid = project(client)
    src = source(client, pid, "复现实验原始说明。")
    span = client.get(f"/api/projects/{pid}/sources/{src['id']}/pages").json()["pages"][0]
    first = note(client, pid, "来源 [[S:" + span["id"] + "]]")
    note(client, pid, "依据 [[V:" + first["version"]["id"] + "]]")
    backup = client.get(f"/api/projects/{pid}/export")
    assert backup.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(backup.content))
    assert "references.bib" in archive.namelist()
    restored = client.post(
        "/api/restore", files={"file": ("backup.zip", backup.content, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    new_id = restored.json()["id"]
    assert new_id != pid
    notes = client.get(f"/api/projects/{new_id}/artifacts").json()
    assert len(notes) == 2 and all(span["id"] not in n["version"]["content"] for n in notes)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as tampered:
        for name in archive.namelist():
            tampered.writestr(name, b"corrupt" if name.startswith("files/") else archive.read(name))
    assert (
        client.post(
            "/api/restore", files={"file": ("bad.zip", out.getvalue(), "application/zip")}
        ).status_code
        == 400
    )


def test_harness_task_events_drafts_and_recovery(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage
    import aster.app.runtime as runtime

    pid = project(client)
    src = source(client, pid)
    span = client.get(f"/api/projects/{pid}/sources/{src['id']}/pages").json()["pages"][0]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.http = kwargs.get("http_client")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            if self.http:
                self.http.close()

    def response(self, client, cfg):
        assert self.message[0]["role"] == "system"
        assert sum(m["role"] == "system" for m in self.message) == 1
        text = "根据原文，应分别记录控制变量与实验数据。[[S:" + span["id"] + "]]"
        self._emit("text", text=text)
        m = ChatCompletionMessage(role="assistant", content=text)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=m)],
            usage=SimpleNamespace(prompt_tokens=200, completion_tokens=30),
        ), None

    from aster.models import clients

    monkeypatch.setattr(clients, "OpenAI", FakeClient)
    from mini_harness.agent import MiniHarnessAgent
    from aster.agent.llm import ModelGateway, QueryPlan, EvidenceDecision, AnswerAudit, ClaimCheck

    def structured(self, schema, instruction, payload, maximum=1200):
        if schema is QueryPlan:
            return QueryPlan(
                route="context", intent="explain", standalone_query="整理笔记", queries=["控制变量"]
            ), {}
        if schema is EvidenceDecision:
            return EvidenceDecision(action="answer", reason="选段充分"), {}
        if schema is AnswerAudit:
            return AnswerAudit(
                claims=[
                    ClaimCheck(
                        text="应分别记录控制变量与实验数据",
                        citations=["[[S:" + span["id"] + "]]"],
                        verdict="supported",
                        reason="原文说明",
                    )
                ],
                summary="supported",
            ), {}
        raise AssertionError(schema)

    monkeypatch.setattr(ModelGateway, "structured", structured)
    monkeypatch.setattr(MiniHarnessAgent, "_request_agent", response)
    manager = client.app.state.manager
    manager.save_model_settings(
        {
            "base_url": "http://127.0.0.1:1/v1",
            "model": "test-qwen",
            "max_tokens": 512,
            "timeout": 15,
        }
    )
    r = client.post(
        f"/api/projects/{pid}/runs",
        json={
            "prompt": "整理这份资料的笔记 [[S:" + span["id"] + "]]",
            "engine": "pipeline",
            "retrieval_policy": "off",
            "mode": "reading",
            "source_ids": [src["id"]],
        },
    )
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    for _ in range(200):
        row = client.get("/api/runs/" + run_id).json()
        if row["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert row["status"] == "completed", row
    assert row["result"]["pipeline"]["stages"] == 7
    assert len(row["result"]["artifact_ids"]) == 1
    events = client.get("/api/runs/" + run_id + "/events").text
    assert "stage_start" in events and "artifact" in events and "event: finished" in events
    records = client.get(f"/api/projects/{pid}/artifacts").json()
    assert records[0]["version"]["author"] == "assistant" and records[0]["status"] == "draft"
    conv = r.json()["conversation_id"]
    with client.app.state.db.session() as s:
        interrupted = AgentRun(
            project_id=pid, conversation_id=conv, prompt="中断的任务", status="running"
        )
        s.add(interrupted)
        s.flush()
        interrupted_id = interrupted.id
    manager.recover()
    assert client.get("/api/runs/" + interrupted_id).json()["status"] == "interrupted"
    archive = client.get(f"/api/projects/{pid}/export").content
    restored = client.post(
        "/api/restore", files={"file": ("with-history.zip", archive, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    restored_runs = client.get(f"/api/projects/{restored.json()['id']}/runs").json()
    assert len(restored_runs) == 2
    assert {r["status"] for r in restored_runs} == {"completed", "interrupted"}


def test_access_token_cookie_and_cross_origin_mutations(tmp_path):
    app = create_app(
        Settings(
            tmp_path,
            f"sqlite:///{tmp_path / 'auth.db'}",
            "http://127.0.0.1:1/v1",
            "qwen",
            "local",
            "test-access-token",
            tmp_path / "static",
        )
    )
    with TestClient(app) as c:
        assert c.get("/api/projects").status_code == 401
        assert c.post("/api/session", json={"token": "incorrect"}).status_code == 401
        assert (
            c.post(
                "/api/session",
                json={"token": "test-access-token"},
                headers={"Origin": "http://malicious.invalid"},
            ).status_code
            == 403
        )
        assert c.post("/api/session", json={"token": "test-access-token"}).status_code == 200
        assert c.get("/api/projects").status_code == 200
        assert (
            c.post(
                "/api/projects",
                json={"title": "bad"},
                headers={"Origin": "http://malicious.invalid"},
            ).status_code
            == 403
        )
        assert c.delete("/api/session").status_code == 200
        assert c.get("/api/projects").status_code == 401


def test_harness_injected_workspace_and_legacy_custom_tools(tmp_path):
    from mini_harness.config import Config
    from mini_harness.tool.box import ToolExecution, TOOLS, ToolDefinition
    from openai.types.chat import ChatCompletionMessageToolCall
    from pydantic import BaseModel

    (tmp_path / "sandbox").mkdir()
    cfg = Config(work_space=tmp_path, track_files=False)
    registry = {t.name: t for t in TOOLS}
    execute = ToolExecution(registry, lambda *_a, **_k: False, cfg=cfg)
    call = ChatCompletionMessageToolCall(
        id="test",
        type="function",
        function={
            "name": "write_file",
            "arguments": json.dumps(
                {"file_path": "sandbox/injected.txt", "content": "correct workspace"}
            ),
        },
    )
    assert execute.execute_tool(call).ok
    assert (tmp_path / "sandbox/injected.txt").read_text() == "correct workspace"

    class Args(BaseModel):
        text: str

    t = ToolDefinition("legacy", "count", Args, lambda args: str(len(args.text)), False)
    execute = ToolExecution({"legacy": t}, lambda *_a, **_k: False, cfg=cfg)
    call = ChatCompletionMessageToolCall(
        id="legacy", type="function", function={"name": "legacy", "arguments": '{"text":"abc"}'}
    )
    assert execute.execute_tool(call).content == "3"


def test_stream_length_limit_preserves_all_received_text():
    from mini_harness.agent import MiniHarnessAgent
    from mini_harness.config import Config
    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion

    completion = ChatCompletion(
        id="cutoff",
        created=0,
        model="qwen",
        object="chat.completion",
        choices=[
            {
                "index": 0,
                "finish_reason": "length",
                "message": {"role": "assistant", "content": "完整的部分输出"},
            }
        ],
        usage={"prompt_tokens": 30, "completion_tokens": 8, "total_tokens": 38},
    )

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            yield SimpleNamespace(type="content.delta", delta="完整的")
            yield SimpleNamespace(type="content.delta", delta="部分输出")
            raise LengthFinishReasonError(completion=completion)

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(stream=lambda **kwargs: Stream()))
    )
    agent = MiniHarnessAgent([], cfg=Config(provider="local"))
    response, truncated = agent._request_agent(client, cfg=Config(provider="local"))
    assert response is None and truncated == "完整的部分输出"
    assert agent.last_usage.completion_tokens == 8
