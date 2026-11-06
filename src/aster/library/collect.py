"""Resumable journal-paper collection with provenance, dates and original PDFs."""

import html
import json
import re
from datetime import date
from sqlalchemy import select
from aster.data.sources import PublicClient, save_json, article_text, EPMC
from aster.data.originals import collect as collect_originals
from aster.domain.models import Source, ReadingState

JOURNALS = [
    "Nature",
    "Nature Methods",
    "Nature Biotechnology",
    "Nature Machine Intelligence",
    "Nature Communications",
    "Nature Genetics",
    "Nature Medicine",
    "Cell",
    "Cell Systems",
    "Cell Metabolism",
    "Science",
    "Science Advances",
    "PNAS",
    "Genome Biology",
    "Nucleic Acids Research",
    "Bioinformatics",
    "Analytical Chemistry",
]
TOPICS = {
    "metabolomics": "(TITLE_ABS:metabolomics OR TITLE_ABS:metabolomic OR TITLE_ABS:lipidomics)",
    "ai4bio": '((TITLE_ABS:"foundation model" OR TITLE_ABS:"deep learning" OR TITLE_ABS:"machine learning" OR TITLE_ABS:"artificial intelligence" OR TITLE_ABS:"language model" OR TITLE_ABS:"generative model") AND (TITLE_ABS:protein OR TITLE_ABS:genomic OR TITLE_ABS:genomics OR TITLE_ABS:"single cell" OR TITLE_ABS:"single-cell" OR TITLE_ABS:drug OR TITLE_ABS:biological OR TITLE_ABS:metabolomics))',
}


def collect(service, topic, limit=30, since="2024-01-01", project_id=None):
    if topic not in TOPICS or not 1 <= limit <= 300:
        raise ValueError("Choose metabolomics or ai4bio and 1–300 papers")
    date.fromisoformat(since)
    directory = service.db.data_dir / "library/imports" / topic
    papers_dir = directory / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    title = "Metabolomics" if topic == "metabolomics" else "AI4Bio"
    if not project_id:
        existing = next((p for p in service.projects() if p["title"] == title), None)
        project_id = (
            existing or service.save_project(title, knowledge={"subject": title, "language": "zh"})
        )["id"]
    manifest_path = papers_dir / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {"papers": [], "errors": []}
    )
    with service.db.session() as session:
        existing = list(session.scalars(select(Source)))
        known_doi = {s.doi.lower() for s in existing if s.doi}
        known_accession = {s.provenance.get("accession") for s in existing}
    journal_query = " OR ".join('JOURNAL:"' + j + '"' for j in JOURNALS)
    query = f'{TOPICS[topic]} AND FIRST_PDATE:[{since} TO {date.today().isoformat()}] AND OPEN_ACCESS:Y AND IN_PMC:Y AND ({journal_query}) NOT PUB_TYPE:"Preprint" NOT PUB_TYPE:"Retracted Publication"'
    manifest.update(
        query=query,
        selection="Recent first; journal whitelist; open access; original PDF required; not a systematic review",
        journals=JOURNALS,
        project_id=project_id,
    )
    client = PublicClient()
    try:
        response = client.get(
            EPMC + "/search",
            query=query,
            format="json",
            resultType="core",
            pageSize=min(1000, limit * 4),
            sort="FIRST_PDATE_D desc",
        ).json()
        picked = {p["accession"]: p for p in manifest["papers"]}
        for row in response.get("resultList", {}).get("result", []):
            key, doi = row.get("pmcid"), row.get("doi", "")
            if len(picked) >= limit:
                break
            if not key or key in picked or key in known_accession or doi.lower() in known_doi:
                continue
            try:
                title = re.sub("<[^>]+>", "", html.unescape(row["title"]))
                entry = {
                    "accession": key,
                    "title": title,
                    "authors": row.get("authorString", ""),
                    "doi": doi,
                    "year": row.get("pubYear", ""),
                    "published": row.get("firstPublicationDate", ""),
                    "journal": row.get("journalInfo", {}).get("journal", {}).get("title", ""),
                    "abstract": re.sub("<[^>]+>", " ", html.unescape(row.get("abstractText", ""))),
                    "url": "https://europepmc.org/articles/" + key,
                    "topic": topic,
                    "api_url": EPMC + "/" + key + "/fullTextXML",
                }
                raw = client.get(entry["api_url"]).content
                text, license_text = article_text(raw, entry)
                (papers_dir / (key + ".xml")).write_bytes(raw)
                (papers_dir / (key + ".md")).write_text(text)
                entry.update(license=license_text, content_level="full_text")
                picked[key] = entry
                manifest["papers"] = list(picked.values())
                save_json(manifest_path, manifest)
                print(topic, len(picked), key, title[:100], flush=True)
            except Exception as error:
                manifest["errors"].append({"accession": key, "reason": str(error)[:250]})
        save_json(manifest_path, manifest)
    finally:
        client.client.close()
    pdfs = collect_originals(directory, workers=3)
    report = {
        "project_id": project_id,
        "topic": topic,
        "imported": [],
        "existing": [],
        "unavailable": [],
    }
    for entry in manifest["papers"]:
        key = entry["accession"]
        if key in known_accession or entry["doi"].lower() in known_doi:
            report["existing"].append(key)
            continue
        original = pdfs["papers"].get(key, {})
        if original.get("status") != "downloaded" or original.get("is_retracted"):
            report["unavailable"].append(
                {"accession": key, "reason": original.get("reason", "No licensed PDF")}
            )
            continue
        imported = service.import_source(
            project_id,
            key + ".pdf",
            (directory / "pdfs" / original["file"]).read_bytes(),
            title=entry["title"],
            authors=entry["authors"],
            year=entry["year"],
            doi=entry["doi"],
        )
        with service.db.session() as session:
            source = session.get(Source, imported["id"])
            source.provenance = {k: v for k, v in entry.items() if k != "api_url"}
            source.provenance = {
                **source.provenance,
                "repository": "Europe PMC",
                "original_pdf": {
                    "url": original["url"],
                    "license": original.get("license"),
                    "source_version_id": imported["version_id"],
                    "metadata_url": original["metadata_url"],
                    "is_retracted": False,
                },
            }
            session.add(
                ReadingState(
                    project_id=project_id,
                    source_id=imported["id"],
                    tags=[topic, entry["journal"][:30]],
                )
            )
        report["imported"].append(
            {
                "accession": key,
                "source_id": imported["id"],
                "title": entry["title"],
                "journal": entry["journal"],
                "published": entry["published"],
            }
        )
        known_accession.add(key)
        if entry["doi"]:
            known_doi.add(entry["doi"].lower())
        save_json(directory / "report.json", report)
    save_json(directory / "report.json", report)
    return report
