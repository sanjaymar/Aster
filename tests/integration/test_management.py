"""CRUD must preserve provenance, project boundaries and immutable evidence."""

import io
import pytest
from pypdf import PdfWriter
import test_platform as fixtures
from aster.domain.models import AgentRun, Source
from aster.retrieval.corpus import Corpus

client = fixtures.client


def test_source_edit_delete_restore_and_shared_project_scope(client):
    first, other, outsider = (
        fixtures.project(client),
        fixtures.project(client, "other"),
        fixtures.project(client, "private"),
    )
    source = fixtures.source(client, first, "Shared original evidence remains immutable.")
    sid = source["id"]
    assert (
        client.post(
            f"/api/projects/{first}/sources/{sid}/link", json={"target_project_id": other}
        ).status_code
        == 201
    )
    payload = {
        "title": "Updated title",
        "authors": "Researcher",
        "year": "2026",
        "doi": "10.test/example",
    }
    assert client.put(f"/api/projects/{outsider}/sources/{sid}", json=payload).status_code == 404
    assert client.put(f"/api/projects/{first}/sources/{sid}", json=payload).status_code == 200
    span = client.get(f"/api/projects/{first}/sources/{sid}/pages").json()["pages"][0]
    assert client.delete(f"/api/projects/{first}/sources/{sid}").status_code == 200
    assert client.get(f"/api/projects/{first}/sources").json() == []
    assert client.get(f"/api/projects/{other}/sources").json()[0]["id"] == sid
    assert client.get(f"/api/projects/{first}/sources/{sid}/pages").status_code == 404
    assert (
        client.get(f"/api/projects/{first}/evidence/S/{span['id']}").json()["content"]
        == span["text"]
    )
    snapshot = Corpus(client.app.state.service).snapshot(first, scope="project")
    assert snapshot["source_version_ids"] == []
    item = client.get(f"/api/trash?project_id={first}").json()[0]
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert client.get(f"/api/projects/{first}/sources").json()[0]["title"] == payload["title"]


@pytest.mark.parametrize("kind", ["note"])
def test_personal_document_crud_preserves_cited_versions(client, kind):
    pid = fixtures.project(client)
    row = fixtures.note(client, pid, "Original idea.", kind=kind)
    updated = client.put(
        f"/api/projects/{pid}/artifacts/{row['id']}",
        json={"kind": kind, "title": "Revised", "content": "Revised idea.", "expected_revision": 1},
    )
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    assert client.delete(f"/api/projects/{pid}/artifacts/{row['id']}").status_code == 200
    assert client.get(f"/api/projects/{pid}/artifacts").json() == []
    assert (
        client.get(f"/api/projects/{pid}/evidence/V/{row['version']['id']}").json()["content"]
        == "Original idea."
    )
    trash = client.get(f"/api/trash?project_id={pid}").json()[0]
    assert client.post(f"/api/trash/{trash['id']}/restore").status_code == 200
    assert client.get(f"/api/projects/{pid}/artifacts").json()[0]["revision"] == 2


def test_project_recycle_and_active_task_protection(client, monkeypatch):
    pid, other = fixtures.project(client), fixtures.project(client, "other")
    monkeypatch.setattr(client.app.state.manager, "_submit", lambda _: None)
    run = client.post(f"/api/projects/{pid}/runs", json={"prompt": "pending"}).json()
    assert client.delete(f"/api/projects/{pid}").status_code == 409
    with client.app.state.db.session() as session:
        session.get(AgentRun, run["id"]).status = "completed"
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert [row["id"] for row in client.get("/api/projects").json()] == [other]
    assert client.get(f"/api/projects/{pid}/overview").status_code == 404
    item = client.get("/api/trash").json()[0]
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert client.get(f"/api/projects/{pid}/overview").status_code == 200


def test_pdf_version_and_recycle_survive_streamed_backup(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid, "Original XML text representation.")
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf = client.post(
        f"/api/projects/{pid}/sources",
        data={"source_id": source["id"], "title": "Original paper"},
        files={"file": ("original.pdf", buffer.getvalue(), "application/pdf")},
    ).json()
    with client.app.state.db.session() as session:
        session.get(Source, source["id"]).provenance = {
            "original_pdf": {"source_version_id": pdf["version_id"]}
        }
    assert client.delete(f"/api/projects/{pid}/sources/{source['id']}").status_code == 200
    archive = client.get(f"/api/projects/{pid}/export")
    restored = client.post(
        "/api/restore", files={"file": ("backup.zip", archive.content, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    new_pid = restored.json()["id"]
    assert client.get(f"/api/projects/{new_pid}/sources").json() == []
    item = client.get(f"/api/trash?project_id={new_pid}").json()[0]
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    paper = client.get(f"/api/projects/{new_pid}/sources").json()[0]
    assert paper["content_type"] == "application/pdf"
    assert paper["original_pdf"]["source_version_id"] == paper["version_id"]
    assert paper["version_id"] != pdf["version_id"]


def test_annotation_comments_edit_without_moving_original_anchor(client):
    pid, other = fixtures.project(client), fixtures.project(client, "other")
    source = fixtures.source(client, pid, "Exact original quotation.")
    base = f"/api/projects/{pid}/sources/{source['id']}"
    span = client.get(base + "/pages").json()["pages"][0]
    mark = client.post(
        base + "/annotations",
        json={"source_span_id": span["id"], "start_offset": 0, "end_offset": 5, "quote": "Exact"},
    ).json()
    path = base + f"/annotations/{mark['id']}"
    assert client.patch(path.replace(pid, other), json={"comment": "foreign"}).status_code == 404
    assert client.patch(path, json={"comment": "Revised thought"}).status_code == 200
    edited = client.get(base + "/annotations").json()[0]
    assert (
        edited["comment"] == "Revised thought"
        and edited["quote"] == "Exact"
        and edited["start_offset"] == 0
    )


def test_original_pdf_can_be_read_while_default_retrieval_keeps_xml(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid, "Full XML text retained for indexing.")
    old_id = source["version_id"]
    fixtures.source(client, pid, "PDF representation text.", source["id"])
    with client.app.state.db.session() as session:
        session.get(Source, source["id"]).provenance = {"retrieval_version_id": old_id}
    corpus = Corpus(client.app.state.service)
    assert corpus.snapshot(pid, scope="project")["source_version_ids"] == [old_id]
    current = client.get(f"/api/projects/{pid}/sources").json()[0]
    assert corpus.snapshot(pid, [source["id"]], source_version_ids=[current["version_id"]])[
        "source_version_ids"
    ] == [current["version_id"]]
    fixtures.source(client, pid, "An intentional replacement uploaded later.", source["id"])
    assert corpus.snapshot(pid, scope="project")["source_version_ids"] != [old_id]


def test_a_readable_pdf_is_kept_when_one_page_exceeds_text_parser_limits(client, monkeypatch):
    from pypdf._page import PageObject
    from pypdf.errors import LimitReachedError

    def unavailable_text(self):
        raise LimitReachedError("Dense vector figure exceeds parser limits")

    monkeypatch.setattr(PageObject, "extract_text", unavailable_text)
    pid = fixtures.project(client)
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    content = io.BytesIO()
    writer.write(content)
    response = client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("vector-figure.pdf", content.getvalue(), "application/pdf")},
    )
    assert response.status_code == 201 and response.json()["page_count"] == 1
    paper = client.get(f"/api/projects/{pid}/sources/{response.json()['id']}/pages").json()
    assert paper["pages"][0]["extraction_error"] == "LimitReachedError"
    assert paper["pages"][0]["text"] == ""
    assert (
        client.get(f"/api/assets/{paper['version']['asset_id']}?inline=true").content
        == content.getvalue()
    )


def test_conversation_rename_delete_restore_preserves_history(client, monkeypatch):
    pid = fixtures.project(client)
    monkeypatch.setattr(client.app.state.manager, "_submit", lambda _: None)
    run = client.post(f"/api/projects/{pid}/runs", json={"prompt": "Original question"}).json()
    with client.app.state.db.session() as session:
        session.get(AgentRun, run["id"]).status = "completed"
    base = f"/api/projects/{pid}/conversations/{run['conversation_id']}"
    assert client.put(base, json={"title": "A named research discussion"}).status_code == 200
    assert client.delete(base).status_code == 200
    assert client.get(f"/api/projects/{pid}/conversations").json() == []
    assert client.get(base).status_code == 404
    assert (
        client.post(
            f"/api/projects/{pid}/runs",
            json={"prompt": "Do not revive silently", "conversation_id": run["conversation_id"]},
        ).status_code
        == 404
    )
    item = client.get(f"/api/trash?project_id={pid}").json()[0]
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert (
        client.get(f"/api/projects/{pid}/conversations").json()[0]["title"]
        == "A named research discussion"
    )
