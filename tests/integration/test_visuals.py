import io
import zipfile
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from pptx import Presentation
import test_platform as fixtures
from test_platform import client as client


def paper(caption="Figure 1. Synthetic vector result, not scientific data."):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        f"0.2 0.4 0.8 rg 60 400 400 220 re f BT /F1 12 Tf 50 360 Td ({caption}) Tj ET".encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def upload(
    client, pid, source_id=None, caption="Figure 1. Synthetic vector result, not scientific data."
):
    data = {"title": "Synthetic figure paper"}
    if source_id:
        data["source_id"] = source_id
    response = client.post(
        f"/api/projects/{pid}/sources",
        data=data,
        files={"file": ("figure.pdf", paper(caption), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_vector_page_extraction_is_original_version_pinned_and_authorized(client):
    pid = fixtures.project(client)
    source = upload(client, pid)
    base = f"/api/projects/{pid}/sources/{source['id']}"
    first = client.get(base + "/figures")
    assert first.status_code == 200, first.text
    result = first.json()
    fig = result["figures"][0]
    assert fig["kind"] == "page" and fig["page"] == 1 and "Synthetic vector" in fig["caption"]
    assert client.get(fig["url"]).content.startswith(b"\x89PNG")
    assert client.get(base + "/figures").json() == result
    upload(client, pid, source["id"], "Figure 2. A changed synthetic caption.")
    second = client.get(base + "/figures").json()
    assert second["version_id"] != result["version_id"]
    assert (
        client.get(base + "/figures", params={"version_id": result["version_id"]}).json() == result
    )
    foreign = fixtures.project(client)
    assert client.get(base.replace(pid, foreign) + "/figures").status_code == 404
    assert client.get(base + "/preview?page=0").status_code == 404
    client.delete(base)
    assert client.get(base + "/figures").status_code == 404


def test_scientific_deck_exports_editable_flow_table_original_image_and_skill_pack(client):
    pid = fixtures.project(client)
    source = upload(client, pid)
    base = f"/api/projects/{pid}"
    fig = client.get(base + f"/sources/{source['id']}/figures").json()["figures"][0]
    body = {
        "title": "Synthetic scientific briefing",
        "theme": "academic",
        "slides": [
            {
                "title": "Method workflow",
                "layout": "flow",
                "steps": [
                    {"label": "Stage A", "detail": "Input"},
                    {"label": "Stage B", "detail": "Check"},
                ],
                "citations": [fig["citation"]],
            },
            {
                "title": "Comparison",
                "layout": "table",
                "table": {"headers": ["Group", "Observed"], "rows": [["A", "Synthetic value"]]},
                "citations": [fig["citation"]],
            },
            {
                "title": "Original page",
                "layout": "figure",
                "image_asset_id": fig["asset_id"],
                "image_caption": "Original PDF page",
                "citations": [fig["citation"]],
            },
        ],
    }
    r = client.post(base + "/decks", json=body)
    assert r.status_code == 201, r.text
    key = r.json()["id"]
    exported = client.get(base + f"/decks/{key}/export")
    ppt = Presentation(io.BytesIO(exported.content))
    assert any(shape.has_text_frame and "Stage A" in shape.text for shape in ppt.slides[0].shapes)
    # The table is composed of editable cells/shapes, not a flattened image.
    assert any(
        shape.has_text_frame and "Synthetic value" in shape.text for shape in ppt.slides[1].shapes
    )
    assert any(shape.shape_type == 13 for shape in ppt.slides[2].shapes)
    assert fig["citation"] in ppt.slides[2].notes_slide.notes_text_frame.text
    pack = client.get(base + f"/decks/{key}/pack")
    with zipfile.ZipFile(io.BytesIO(pack.content)) as archive:
        assert "figures/slide-3.png" in archive.namelist()
    restored = client.post(
        "/api/restore",
        files={"file": ("backup.zip", client.get(base + "/export").content, "application/zip")},
    ).json()
    record = next(
        r
        for r in client.get(f"/api/projects/{restored['id']}/artifacts").json()
        if r["kind"] == "deck"
    )
    assert (
        client.get(f"/api/projects/{restored['id']}/decks/{record['id']}/export").status_code == 200
    )


def test_map_exposes_linked_notes_and_invalidates_after_edit(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid)
    base = f"/api/projects/{pid}"
    first = client.get(base + "/map").json()
    note = fixtures.note(client, pid, "My observation", fields={"source_id": source["id"]})
    updated = client.get(base + "/map").json()
    assert updated["revision"] != first["revision"]
    assert updated["nodes"][0]["notes"][0]["id"] == note["id"]
    assert sum(t["count"] for t in updated["topics"]) == len(updated["nodes"])
    client.delete(base + "/artifacts/" + note["id"])
    assert not client.get(base + "/map").json()["nodes"][0]["notes"]


def test_retrieval_text_uses_its_paired_original_pdf_after_a_later_upload(client):
    from aster.library.figures import pin, selected

    pid = fixtures.project(client)
    text = fixtures.source(client, pid, "Structured text for retrieval")
    base = f"/api/projects/{pid}/sources/{text['id']}"
    text_version = client.get(base + "/pages").json()["version"]["id"]
    upload(client, pid, text["id"])
    pdf_version = client.get(base + "/pages").json()["version"]["id"]
    service = client.app.state.service
    with service.db.session() as session:
        source = service.source(session, pid, text["id"])
        source.provenance = {
            "retrieval_version_id": text_version,
            "original_pdf": {"source_version_id": pdf_version},
        }
    pinned = pin(service, pid, [text_version])
    assert pinned == [(text["id"], pdf_version)]
    upload(client, pid, text["id"], "Figure 2. A later revision.")
    figures = selected(service, pid, pinned)
    assert len(figures) == 1 and figures[0]["version_id"] == pdf_version
    assert "Synthetic vector" in figures[0]["caption"]


def test_deck_review_removes_invented_comparison_without_discarding_supported_text():
    from types import SimpleNamespace
    from aster.slides.schema import Deck
    from aster.slides.review import Review, Issue, check

    deck = Deck(
        title="Study",
        slides=[
            {
                "title": "Reported observation",
                "layout": "table",
                "bullets": ["Measured result"],
                "table": {
                    "headers": ["Platform", "Claim"],
                    "rows": [["GC-MS", "Invented coverage"]],
                },
            }
        ],
    )
    gateway = SimpleNamespace(
        structured=lambda *args: (
            Review(issues=[Issue(page=1, part="table", reason="No evidence for coverage")]),
            {},
        )
    )
    report, _ = check(deck, "Measured result", [], gateway)
    assert report["issues"] and not deck.slides[0].table.rows
    assert deck.slides[0].layout == "bullets" and deck.slides[0].bullets == ["Measured result"]
