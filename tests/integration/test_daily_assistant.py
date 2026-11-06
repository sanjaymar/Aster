"""Provider routing, optional retrieval and knowledge/skill isolation regressions."""

import io
import json
import stat
import time
import zipfile
from dataclasses import replace
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
import test_platform as fixtures

from aster.agent.assistant import AssistantTools, SearchKnowledge, ReadEvidence
from aster.agent.trace import PipelineTrace
from mini_harness.agent import MiniHarnessAgent

client = fixtures.client


def test_cloud_api_requires_model_and_rejects_credentials_in_url(client):
    body = {
        "name": "Cloud",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "auto",
    }
    assert client.post("/api/models/profiles", json=body).status_code == 422
    body.update(model="test-model", base_url="https://user:secret@example.org/v1")
    assert client.post("/api/models/profiles", json=body).status_code == 422


def test_profiles_separate_reader_defaults_and_never_export_keys(client, monkeypatch):
    pid = fixtures.project(client)
    initial = client.get("/api/models/profiles").json()
    assert initial["defaults"] == {"assistant": "local", "reader": "local"}
    secret = "synthetic-test-key-not-a-real-secret"
    body = {
        "name": "Reading API",
        "provider": "compatible",
        "base_url": "http://127.0.0.1:1/v1",
        "model": "test-model",
        "api_key": secret,
    }
    response = client.post("/api/models/profiles", json=body)
    assert response.status_code == 201, response.text
    key = response.json()["profiles"][-1]["id"]
    assert secret not in response.text and response.json()["profiles"][-1]["has_key"]
    manager = client.app.state.manager
    assert stat.S_IMODE(manager.profiles.key_path.stat().st_mode) == 0o600
    assert manager.profiles.key(manager.profiles.get(key)) == secret
    defaults = client.put("/api/models/defaults", json={"assistant": "local", "reader": key})
    assert defaults.status_code == 200
    assert client.delete("/api/models/profiles/" + key).status_code == 409
    monkeypatch.setattr(manager, "_submit", lambda _: None)
    source = fixtures.source(client, pid)
    version = client.get(f"/api/projects/{pid}/sources/{source['id']}/pages").json()["version"][
        "id"
    ]
    run = client.post(
        f"/api/projects/{pid}/runs",
        json={"prompt": "test", "source_ids": [source["id"]], "source_version_ids": [version]},
    ).json()
    assert run["context"]["model_config"]["id"] == key
    assert secret not in json.dumps(run)
    archive = client.get(f"/api/projects/{pid}/export").content
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert secret.encode() not in z.read("manifest.json")
        assert not any("model-keys" in f for f in z.namelist())
    body.pop("api_key")
    assert client.put("/api/models/profiles/" + key, json=body).status_code == 200
    assert manager.profiles.key(manager.profiles.get(key)) == secret
    assert (
        client.put("/api/models/profiles/" + key, json={**body, "clear_key": True}).status_code
        == 200
    )
    assert secret not in manager.profiles.key_path.read_text()
    client.put("/api/models/defaults", json={"assistant": "local", "reader": "local"})
    assert client.delete("/api/models/profiles/" + key).status_code == 200


def test_knowledge_preferences_and_related_notes_survive_backup(client):
    prefs = {
        "subject": "Astronomy",
        "terminology": "ULB ultralight boson",
        "instructions": "State assumptions",
        "language": "en",
    }
    response = client.post(
        "/api/projects",
        json={"title": "Custom knowledge", "domain": "research", "knowledge": prefs},
    )
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    a = fixtures.note(
        client, pid, "A", fields={"note_type": "idea", "tags": ["test"], "pinned": True}
    )
    b = fixtures.note(client, pid, "B", fields={"related_record_ids": [a["id"]]})
    other = fixtures.project(client, "private")
    assert (
        client.post(
            f"/api/projects/{other}/artifacts",
            json={"title": "invalid", "content": "x", "fields": {"related_record_ids": [a["id"]]}},
        ).status_code
        == 404
    )
    content = client.get(f"/api/projects/{pid}/export").content
    restored = client.post(
        "/api/restore", files={"file": ("project.zip", content, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["knowledge"] == prefs
    rows = client.get(f"/api/projects/{restored.json()['id']}/artifacts").json()
    new_a = next(r for r in rows if r["version"]["content"] == "A")
    new_b = next(r for r in rows if r["version"]["content"] == "B")
    assert new_a["version"]["fields"]["tags"] == ["test"]
    assert new_b["version"]["fields"]["related_record_ids"] == [new_a["id"]]
    assert new_b["id"] != b["id"]


def test_skill_snapshots_do_not_change_after_edit_or_enable_disabled_skill(client, monkeypatch):
    pid = fixtures.project(client)
    body = {
        "name": "My method",
        "description": "For test",
        "instructions": "Version one",
        "enabled": True,
    }
    skill = client.post("/api/skills", json=body).json()
    manager = client.app.state.manager
    monkeypatch.setattr(manager, "_submit", lambda _: None)
    run = client.post(
        f"/api/projects/{pid}/runs", json={"prompt": "discuss", "skill_id": skill["id"]}
    ).json()
    client.put(
        "/api/skills/" + skill["id"], json={**body, "instructions": "Version two", "enabled": False}
    )
    stored = client.get("/api/runs/" + run["id"]).json()
    assert (
        next(s for s in stored["context"]["skills"] if s["id"] == skill["id"])["instructions"]
        == "Version one"
    )
    assert (
        client.post(
            f"/api/projects/{pid}/runs", json={"prompt": "discuss", "skill_id": skill["id"]}
        ).status_code
        == 404
    )
    assert client.delete("/api/skills/" + skill["id"]).status_code == 200


def test_empty_knowledge_base_can_discuss_without_forcing_retrieval(client, monkeypatch):
    pid = fixtures.project(client)

    def response(agent, _client, cfg):
        names = set(agent.regis)
        assert names == {"search_knowledge", "read_evidence", "list_papers", "load_skill"}
        assert "RAG是查资料的工具" in agent.message[0]["content"]
        text = "可以先把你的想法写成一个可证伪的假设，再列出对照和需要记录的观察。"
        agent._emit("text", text=text)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=ChatCompletionMessage(role="assistant", content=text))
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30),
        ), None

    monkeypatch.setattr(MiniHarnessAgent, "_request_agent", response)
    monkeypatch.setattr(
        client.app.state.manager.retriever,
        "search",
        lambda *_a, **_k: pytest.fail("Discussion must not force retrieval"),
    )
    run = client.post(
        f"/api/projects/{pid}/runs",
        json={"prompt": "我有一个实验想法，先聊聊应该如何记录", "retrieval_scope": "project"},
    ).json()
    for _ in range(200):
        row = client.get("/api/runs/" + run["id"]).json()
        if row["status"] not in {"queued", "running"}:
            break
        time.sleep(0.02)
    assert row["status"] == "completed", row
    assert row["result"]["engine"] == "assistant" and not row["result"]["calls_by_tool"]
    assert not row["result"]["artifact_ids"]
    trace = client.get("/api/runs/" + run["id"] + "/trace").json()
    assert {s["name"] for s in trace["stages"]} == {"Assistant", "Memory"}
    assert trace["turn"]["usage"] == {"prompt_tokens": 100, "completion_tokens": 30}
    events = client.get("/api/runs/" + run["id"] + "/events").text
    assert '"kind": "text"' not in events and '"kind": "answer_verified"' in events


def test_optional_rag_respects_pinned_versions_and_project_boundaries(client, monkeypatch):
    pid, other = fixtures.project(client), fixtures.project(client, "private")
    source = fixtures.source(client, pid, "Original pooled QC injections every five samples.")
    first = client.get(f"/api/projects/{pid}/sources/{source['id']}/pages").json()
    fixtures.source(client, pid, "Changed: no pooled QC injections.", source["id"])
    foreign = fixtures.source(client, other, "Secret other project.")
    span = client.get(f"/api/projects/{other}/sources/{foreign['id']}/pages").json()["pages"][0]
    manager = client.app.state.manager
    manager.retriever.settings = replace(manager.retriever.settings, retrieval_mode="lexical")
    monkeypatch.setattr(manager, "_submit", lambda _: None)
    run = client.post(
        f"/api/projects/{pid}/runs",
        json={
            "prompt": "QC",
            "source_ids": [source["id"]],
            "source_version_ids": [first["version"]["id"]],
        },
    ).json()
    trace = PipelineTrace(manager.db, run["id"], lambda *_: None)
    tools = AssistantTools(
        manager.service, manager.retriever, pid, run["context"]["corpus_snapshot"], [], trace
    )
    hits = json.loads(tools.search(SearchKnowledge(query="pooled QC injections")))["hits"]
    assert hits and all(h["version_id"] == first["version"]["id"] for h in hits)
    assert "Original" in hits[0]["text"]
    with pytest.raises(Exception, match="范围"):
        tools.read(ReadEvidence(kind="S", id=span["id"]))
    with pytest.raises(Exception, match="引用"):
        tools.validate_citations("Fabricated [[S:" + span["id"] + "]]")
    tools.validate_citations(hits[0]["citation"])
    tools.validate_citations("Nested source reference [[S:" + first["pages"][0]["id"] + "]]")
