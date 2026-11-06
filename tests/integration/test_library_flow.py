import io
import json
import zipfile
from types import SimpleNamespace
from PIL import Image
from pptx import Presentation
from aster.retrieval.corpus import Evidence
from aster.slides.schema import Deck
from aster.slides.service import Slides
import test_platform as fixtures
from test_platform import client as client


def test_map_updates_after_import_edit_delete_restore(client):
    pid = fixtures.project(client)
    base = f"/api/projects/{pid}"
    before = client.get(base + "/map").json()
    assert not before["nodes"]
    source = fixtures.source(
        client, pid, "Metabolomics quality control pooled plasma lipid chromatography"
    )
    after = client.get(base + "/map").json()
    assert after["revision"] != before["revision"] and len(after["nodes"]) == 1
    assert after == client.get(base + "/map").json()
    client.put(
        base + "/sources/" + source["id"],
        json={"title": "Changed paper", "authors": "", "year": "2026", "doi": ""},
    )
    edited = client.get(base + "/map").json()
    assert (
        edited["nodes"][0]["title"] == "Changed paper" and edited["revision"] != after["revision"]
    )
    client.delete(base + "/sources/" + source["id"]).json()
    assert not client.get(base + "/map").json()["nodes"]
    trash = client.get("/api/trash", params={"project_id": pid}).json()
    client.post("/api/trash/" + trash[0]["id"] + "/restore")
    assert len(client.get(base + "/map").json()["nodes"]) == 1


def test_deck_edit_export_citations_backup_and_recycle(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid, "Original measured result for presentation.")
    span = client.get(f"/api/projects/{pid}/sources/{source['id']}/pages").json()["pages"][0]
    ref = f"[[S:{span['id']}]]"
    body = {
        "title": "论文汇报",
        "theme": "paper",
        "slides": [
            {
                "title": "Research question",
                "bullets": ["Measured result"],
                "notes": "Check original conditions",
                "citations": [ref],
            }
        ],
    }
    base = f"/api/projects/{pid}"
    response = client.post(base + "/decks", json=body)
    assert response.status_code == 201, response.text
    record = response.json()
    key = record["id"]
    assert record["kind"] == "deck" and ref in record["version"]["content"]
    changed = {**body, "title": "Updated", "expected_revision": 1}
    assert client.put(base + "/decks/" + key, json=changed).status_code == 200
    assert client.put(base + "/decks/" + key, json=changed).status_code == 409
    exported = client.get(base + "/decks/" + key + "/export")
    assert exported.status_code == 200, exported.text[:200] if exported.status_code != 200 else ""
    ppt = Presentation(io.BytesIO(exported.content))
    assert len(ppt.slides) == 1 and ref in ppt.slides[0].notes_slide.notes_text_frame.text
    assert any(s.has_text_frame and "Measured result" in s.text for s in ppt.slides[0].shapes)
    pack = client.get(base + "/decks/" + key + "/pack")
    with zipfile.ZipFile(io.BytesIO(pack.content)) as z:
        assert set(z.namelist()) == {"outline.json", "sources.json", "TASK.md"}
        assert ref in json.loads(z.read("sources.json"))
    archive = client.get(base + "/export").content
    restored = client.post(
        "/api/restore", files={"file": ("backup.zip", archive, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    pid2 = restored.json()["id"]
    deck = client.get(f"/api/projects/{pid2}/artifacts").json()[0]
    assert ref not in deck["version"]["content"]
    assert client.get(f"/api/projects/{pid2}/decks/{deck['id']}/export").status_code == 200
    client.delete(base + "/artifacts/" + key)
    assert client.get(base + "/decks/" + key + "/export").status_code == 404


def test_decks_reject_foreign_references_and_invalid_images(client):
    pid = fixtures.project(client)
    other = fixtures.project(client)
    source = fixtures.source(client, other)
    span = client.get(f"/api/projects/{other}/sources/{source['id']}/pages").json()["pages"][0]
    slide = {"title": "Page", "bullets": [], "notes": "", "citations": [f"[[S:{span['id']}]]"]}
    body = {"title": "Deck", "theme": "paper", "slides": [slide]}
    assert client.post(f"/api/projects/{pid}/decks", json=body).status_code == 404
    slide["citations"] = []
    slide["image_asset_id"] = "missing"
    assert client.post(f"/api/projects/{pid}/decks", json=body).status_code == 404
    assert not client.get(f"/api/projects/{pid}/artifacts").json()


def test_generated_deck_resolves_short_aliases_and_keeps_provenance_when_edited(client):
    pid = fixtures.project(client)
    source = fixtures.source(client, pid, "Measured result from the selected paper.")
    page = client.get(f"/api/projects/{pid}/sources/{source['id']}/pages").json()
    span = page["pages"][0]
    evidence = Evidence(
        span["id"], "S", source["title"], span["text"], source["id"], page["version"]["id"], 1
    )

    def structured(schema, instructions, payload, budget):
        from aster.slides.review import Review

        if schema is Review:
            return Review(), {}
        assert payload["allowed_references"] == ["R1"]
        assert evidence.id not in payload["checked_answer"]
        return Deck(
            title="Group meeting",
            slides=[{"title": "Result", "bullets": ["Measured result"], "citations": ["R1"]}],
        ), {}

    slides = Slides(client.app.state.service)
    record, _ = slides.generate(
        pid,
        "Make slides",
        "Measured result " + evidence.citation,
        {evidence.id: evidence},
        SimpleNamespace(structured=structured),
        {"run_id": "source-run", "source_ids": [source["id"]]},
    )
    body = record["version"]["fields"]["deck"]
    assert body["slides"][0]["citations"] == [evidence.citation]
    body.update(title="Edited meeting", expected_revision=1)
    edited = client.put(f"/api/projects/{pid}/decks/{record['id']}", json=body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"]["fields"]["run_id"] == "source-run"


def test_webp_slide_image_exports_as_supported_png(client):
    pid = fixtures.project(client)
    picture = io.BytesIO()
    Image.new("RGB", (64, 32), "white").save(picture, format="WEBP")
    asset = client.post(
        f"/api/projects/{pid}/assets",
        files={"file": ("figure.webp", picture.getvalue(), "image/webp")},
    )
    assert asset.status_code == 201, asset.text
    body = {
        "title": "Figure",
        "slides": [{"title": "Result", "image_asset_id": asset.json()["id"]}],
    }
    deck = client.post(f"/api/projects/{pid}/decks", json=body)
    assert deck.status_code == 201, deck.text
    exported = client.get(f"/api/projects/{pid}/decks/{deck.json()['id']}/export")
    assert exported.status_code == 200
    ppt = Presentation(io.BytesIO(exported.content))
    assert any(shape.shape_type == 13 for shape in ppt.slides[0].shapes)
