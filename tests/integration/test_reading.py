"""Reading anchors, personal documents and backups must survive revisions and projects."""

import test_platform as fixtures

client = fixtures.client


def test_reading_preferences_are_partial_and_project_scoped(client):
    pid, other = fixtures.project(client), fixtures.project(client, "other")
    source = fixtures.source(client, pid)
    base = f"/api/projects/{pid}/sources/{source['id']}"
    assert (
        client.patch(
            base + "/reading", json={"starred": True, "tags": ["QC", "QC", "  批次  "]}
        ).status_code
        == 200
    )
    result = client.patch(base + "/reading", json={"reading_status": "reading"}).json()
    assert result["starred"] is True and result["tags"] == ["QC", "批次"]
    assert (
        client.get(f"/api/projects/{pid}/sources").json()[0]["reading"]["reading_status"]
        == "reading"
    )
    assert (
        client.patch(base.replace(pid, other) + "/reading", json={"starred": False}).status_code
        == 404
    )
    assert client.patch(base + "/reading", json={"last_scroll": 1.2}).status_code == 422


def test_annotation_positions_validate_unicode_and_keep_original_version(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid, "研究🔬中，pooled QC samples用于质量控制。")
    base = f"/api/projects/{pid}/sources/{source['id']}"
    span = client.get(base + "/pages").json()["pages"][0]
    text = span["text"]
    start = text.index("pooled")
    quote = "pooled QC samples"
    payload = {
        "source_span_id": span["id"],
        "start_offset": start,
        "end_offset": start + len(quote),
        "quote": quote,
        "comment": "需要关注",
        "rectangles": [[0.1, 0.2, 0.3, 0.04]],
    }
    response = client.post(base + "/annotations", json=payload)
    assert response.status_code == 201, response.text
    annotation = response.json()
    assert (
        client.post(base + "/annotations", json={**payload, "quote": "伪造原文"}).status_code == 400
    )
    assert (
        client.post(base + "/annotations", json={**payload, "start_offset": start - 1}).status_code
        == 400
    )
    fixtures.source(client, pid, "完全不同的新版本。", source["id"])
    assert client.get(base + "/annotations").json()[0]["quote"] == quote
    assert (
        client.get(base + "/annotations").json()[0]["source_version_id"]
        == span["source_version_id"]
    )
    assert client.delete(base + f"/annotations/{annotation['id']}").status_code == 200
    assert client.get(base + "/annotations").json() == []


def test_notes_annotations_and_reading_position_survive_backup(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid, "原文方法需要验证。")
    base = f"/api/projects/{pid}/sources/{source['id']}"
    span = client.get(base + "/pages").json()["pages"][0]
    annotation = client.post(
        base + "/annotations",
        json={
            "source_span_id": span["id"],
            "start_offset": 0,
            "end_offset": 4,
            "quote": span["text"][:4],
        },
    ).json()
    client.patch(
        base + "/reading",
        json={
            "reading_status": "read",
            "last_version_id": span["source_version_id"],
            "last_scroll": 0.42,
        },
    )
    # A free personal note stays linked even when its body has no quotation marker.
    note = fixtures.note(client, pid, "这是我的研究想法。", fields={"source_id": source["id"]})
    assert client.get(base + "/notes").json()[0]["id"] == note["id"]
    archive = client.get(f"/api/projects/{pid}/export").content
    restored = client.post(
        "/api/restore", files={"file": ("backup.zip", archive, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    new_pid = restored.json()["id"]
    new_source = client.get(f"/api/projects/{new_pid}/sources").json()[0]
    new_base = f"/api/projects/{new_pid}/sources/{new_source['id']}"
    assert new_source["reading"]["last_scroll"] == 0.42
    assert new_source["reading"]["last_version_id"] != span["source_version_id"]
    assert client.get(new_base + "/annotations").json()[0]["quote"] == annotation["quote"]
    restored_note = client.get(new_base + "/notes").json()[0]
    assert restored_note["version"]["fields"]["source_id"] == new_source["id"]


def test_reader_can_pin_an_old_version_without_crossing_project_scope(client, monkeypatch):
    pid, other = fixtures.project(client), fixtures.project(client, "private")
    source = fixtures.source(client, pid, "旧版原文。")
    first = client.get(f"/api/projects/{pid}/sources/{source['id']}/pages").json()["version"]["id"]
    fixtures.source(client, pid, "新版原文。", source["id"])
    foreign = fixtures.source(client, other, "其他项目原文。")
    foreign_version = client.get(f"/api/projects/{other}/sources/{foreign['id']}/pages").json()[
        "version"
    ]["id"]
    monkeypatch.setattr(client.app.state.manager, "_submit", lambda _: None)
    body = {
        "prompt": "依据我正在阅读的版本回答",
        "source_ids": [source["id"]],
        "source_version_ids": [first],
    }
    response = client.post(f"/api/projects/{pid}/runs", json=body)
    assert response.status_code == 202, response.text
    assert response.json()["context"]["corpus_snapshot"]["source_version_ids"] == [first]
    assert (
        client.post(
            f"/api/projects/{pid}/runs", json={**body, "source_version_ids": [foreign_version]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/projects/{pid}/runs", json={**body, "retrieval_scope": "project"}
        ).status_code
        == 400
    )


def test_lab_notes_and_plan_attachments_store_tables_without_running_experiments(client):
    pid = fixtures.project(client)
    matrix = "| 条件 | 峰面积 |\n| --- | --- |\n| QC | 1.2300e-8 |"
    note = fixtures.note(client, pid, matrix, kind="labnote")
    assert note["kind"] == "labnote" and note["version"]["content"] == matrix
    asset = client.post(
        f"/api/projects/{pid}/assets",
        files={"file": ("matrix.csv", b"condition,area\nQC,1.2300e-8", "text/csv")},
    ).json()
    plan = client.post(
        f"/api/projects/{pid}/experiments",
        json={"title": "QC design", "content": matrix, "asset_ids": [asset["id"]]},
    )
    assert plan.status_code == 201, plan.text
    assert plan.json()["plan"]["attachments"][0]["id"] == asset["id"]
    assert client.get(f"/api/projects/{pid}/experiments").json()[0]["runs"] == []


def test_conversation_can_reconnect_without_loading_task_history(client, monkeypatch):
    from aster.domain.models import AgentRun

    pid = fixtures.project(client)
    monkeypatch.setattr(client.app.state.manager, "_submit", lambda _: None)
    done = client.post(f"/api/projects/{pid}/runs", json={"prompt": "previous"}).json()
    with client.app.state.db.session() as session:
        session.get(AgentRun, done["id"]).status = "completed"
    pending = client.post(f"/api/projects/{pid}/runs", json={"prompt": "pending"}).json()
    assert len(client.get(f"/api/projects/{pid}/runs").json()) == 2
    active = client.get(f"/api/projects/{pid}/runs?active_only=true").json()
    assert [row["id"] for row in active] == [pending["id"]]
    assert "transcript" not in active[0] and "context" not in active[0]
