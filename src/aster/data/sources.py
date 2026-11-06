"""Resumable public metabolomics collection. Full texts and study metadata stay distinct."""

import csv
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from aster.domain.models import AppSetting, Source

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
MTBLS = "https://www.ebi.ac.uk/metabolights/ws"
MW = "https://www.metabolomicsworkbench.org/rest"


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class PublicClient:
    def __init__(self):
        self.client = httpx.Client(
            timeout=45,
            follow_redirects=True,
            headers={"User-Agent": "Aster-Research/0.1 (public research corpus collector)"},
        )

    def get(self, url, **params):
        for attempt in range(4):
            try:
                result = self.client.get(url, params=params)
                result.raise_for_status()
                return result
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {
                    400,
                    401,
                    403,
                    404,
                }:
                    raise
                if attempt == 3:
                    raise
                time.sleep(min(2**attempt, 8))


def article_text(xml, metadata):
    """JATS body/abstract to readable text; XML is retained as the original source."""
    root = ET.fromstring(xml)
    body = root.find("body")
    if body is None:
        body = root.find(".//body")
    if body is None:
        raise ValueError("full text has no article body")
    license_node = root.find(".//permissions/license")
    license_text = (
        " ".join(license_node.itertext()) if license_node is not None else "See source article"
    )
    license_text = re.sub(r"\s+", " ", license_text).strip()
    blocks = [
        f"# {metadata['title']}",
        f"Source: {metadata['url']}",
        f"DOI: {metadata.get('doi', '')}",
        f"License: {license_text}",
        "Format: full-text JATS XML converted to text; text pages are not PDF page numbers.",
    ]
    abstract = root.find(".//article-meta/abstract")
    if abstract is not None:
        blocks.extend(["## Abstract", " ".join(abstract.itertext())])
    for node in body.iter():
        if node.tag in {"title", "p", "table-wrap"}:
            # Tables have their own text; paragraphs in table cells are skipped below.
            text = re.sub(r"\s+", " ", "".join(node.itertext())).strip()
            if text:
                blocks.append(("## " if node.tag == "title" else "") + text)
    if sum(len(b) for b in blocks) < 2500:
        raise ValueError("article body too short for this corpus")
    return "\n\n".join(blocks), license_text


def collect_papers(client, directory, target=300, workers=3):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {
            "version": 1,
            "provider": "Europe PMC",
            "created_at": utc_now(),
            "papers": [],
            "errors": [],
        }
    )
    existing = {p["accession"]: p for p in manifest["papers"]}
    # NCBI supplies a bounded accession list; Europe PMC supplies original JATS.
    # The Europe PMC search endpoint intermittently returns 503, so acquisition
    # does not depend on it. Full text still has to pass XML/body validation.
    query = "metabolomics[Title/Abstract] AND open access[filter]"
    print("SEARCH NCBI PMC", flush=True)
    search = client.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        db="pmc",
        term=query,
        retmax=max(target * 2, 500),
        retmode="json",
    ).json()
    manifest["query"] = query
    manifest["search_api"] = "NCBI ESearch PMC"
    manifest["selection"] = (
        "NCBI default order, open-access filter, deduplicated PMCID; topic labels are lexical tags"
    )
    ordered = [
        {
            "accession": "PMC" + key,
            "title": "PMC" + key,
            "url": "https://europepmc.org/articles/PMC" + key,
            "api_url": EPMC + "/PMC" + key + "/fullTextXML",
        }
        for key in search["esearchresult"]["idlist"]
    ]
    ordered = [p for p in ordered if p["accession"] not in existing]

    def download(paper):
        key = paper["accession"]
        try:
            raw_path, text_path = directory / f"{key}.xml", directory / f"{key}.md"
            raw = (
                raw_path.read_bytes() if raw_path.exists() else client.get(paper["api_url"]).content
            )
            root = ET.fromstring(raw)
            title = root.find(".//article-title")
            authors = [
                " ".join(n.itertext()).strip()
                for n in root.findall(".//article-meta/contrib-group/contrib/name")
            ]
            doi = next(
                (
                    node.text
                    for node in root.findall(".//article-meta/article-id")
                    if node.get("pub-id-type") == "doi"
                ),
                "",
            )
            year = root.find(".//article-meta/pub-date/year")
            paper.update(
                title="".join(title.itertext()) if title is not None else key,
                doi=doi or "",
                authors=", ".join(authors),
                year=year.text if year is not None else "",
            )
            words = " ".join(root.itertext()).lower()
            paper["topic"] = next(
                (
                    t
                    for t in [
                        "quality control",
                        "normalization",
                        "data processing",
                        "lipidomics",
                        "mass spectrometry",
                    ]
                    if t in words
                ),
                "metabolomics",
            )
            text, license_text = article_text(raw, paper)
            raw_path.write_bytes(raw)
            text_path.write_text(text, encoding="utf-8")
            return {
                **paper,
                "xml_file": raw_path.name,
                "text_file": text_path.name,
                "xml_sha256": sha(raw),
                "text_sha256": sha(text.encode()),
                "characters": len(text),
                "license": license_text,
                "content_level": "full_text",
                "fetched_at": utc_now(),
            }, None
        except Exception as error:
            return None, {"accession": key, "error": str(error)[:240], "at": utc_now()}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Small batches avoid requesting hundreds of unnecessary extra articles.
        for start in range(0, len(ordered), workers):
            if len(existing) >= target:
                break
            batch = ordered[start : start + min(workers, target - len(existing))]
            for paper, error in pool.map(download, batch):
                if error:
                    manifest["errors"].append(error)
                else:
                    existing[paper["accession"]] = paper
                    print(f"PAPERS {len(existing)}/{target} {paper['accession']}", flush=True)
            manifest.update(papers=list(existing.values()), updated_at=utc_now(), target=target)
            save_json(manifest_path, manifest)
    return manifest


def collect_studies(client, directory, per_repository=100, workers=3):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    manifest = (
        json.loads(path.read_text())
        if path.exists()
        else {"version": 1, "studies": [], "errors": []}
    )
    existing = {p["accession"]: p for p in manifest["studies"]}
    mtbls_ids = client.get(MTBLS + "/studies").json()["content"]
    # Spread across accession history; selection is deterministic and disclosed.
    mtbls_ids = sorted(mtbls_ids, key=lambda s: int(s.replace("MTBLS", "")))
    stride = max(1, len(mtbls_ids) // (per_repository + 20))
    selected = mtbls_ids[::stride][: per_repository + 20]

    def mtbls(key):
        data = client.get(f"{MTBLS}/studies/{key}").json()
        public = data.get("mtblsStudy", {})
        if public.get("studyStatus", "").lower() != "public":
            raise ValueError("study is not public")
        inv = data.get("isaInvestigation", {})
        studies = inv.get("studies", [])
        study = next(
            (s for s in studies if s.get("identifier") == key), studies[0] if studies else {}
        )
        # Whitelist research metadata; never store API reviewer tokens/contact details.
        detail = {
            k: study.get(k)
            for k in [
                "title",
                "description",
                "studyDesignDescriptors",
                "factors",
                "protocols",
                "publications",
            ]
        }
        detail["assays"] = [
            {
                k: a.get(k)
                for k in ["filename", "measurementType", "technologyType", "technologyPlatform"]
            }
            for a in study.get("assays", [])
        ]
        return {
            "accession": key,
            "repository": "MetaboLights",
            "title": study.get("title") or inv.get("title") or key,
            "description": study.get("description") or inv.get("description", ""),
            "url": f"https://www.ebi.ac.uk/metabolights/{key}",
            "api_url": f"{MTBLS}/studies/{key}",
            "license": public.get("datasetLicense", "See repository"),
            "raw_data_url": public.get("studyHttpUrl", "").replace("http://", "https://"),
            "release_date": public.get("firstPublicDate", ""),
            "detail": detail,
        }

    def capture(function, key):
        try:
            record = function(key)
            record.update(
                content_level="study_metadata", raw_data_downloaded=False, fetched_at=utc_now()
            )
            filename = key + ".json"
            save_json(directory / filename, record)
            record["metadata_file"] = filename
            record["sha256"] = sha((directory / filename).read_bytes())
            return record, None
        except Exception as error:
            return None, {"accession": key, "error": str(error)[:240], "at": utc_now()}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        todo = [k for k in selected if k not in existing]
        for start in range(0, len(todo), workers):
            if sum(r["repository"] == "MetaboLights" for r in existing.values()) >= per_repository:
                break
            for row, error in pool.map(
                lambda key: capture(mtbls, key), todo[start : start + workers]
            ):
                if row:
                    existing[row["accession"]] = row
                if error:
                    manifest["errors"].append(error)
            manifest.update(studies=list(existing.values()), updated_at=utc_now())
            save_json(path, manifest)
            print(f"STUDIES {len(existing)}", flush=True)
    # Substring prefix retrieves a bounded public batch (first 100+ accessions).
    summaries = client.get(MW + "/study/study_id/ST000/summary").json()
    if isinstance(summaries, dict):
        summaries = list(summaries.values()) if "study_id" not in summaries else [summaries]
    summaries = sorted(summaries, key=lambda r: r["study_id"])
    for index, summary in enumerate(summaries[:per_repository]):
        key = summary["study_id"]
        if key in existing:
            continue
        record = {
            "accession": key,
            "repository": "Metabolomics Workbench",
            "title": summary["study_title"],
            "url": f"https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?StudyID={key}",
            "api_url": f"{MW}/study/study_id/{key}/summary",
            "license": summary.get("license", "See repository"),
            "raw_data_url": f"https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?StudyID={key}",
            "detail": {
                k: summary.get(k)
                for k in ["species", "analysis_type", "number_of_samples", "release_date"]
            },
            "content_level": "study_metadata",
            "raw_data_downloaded": False,
            "fetched_at": utc_now(),
        }
        if index < 20:
            try:
                detail = client.get(f"{MW}/study/study_id/{key}/mwtab").json()
                detail = detail if isinstance(detail, list) else [detail]
                # Preserve scientific fields, exclude investigator contact information.
                record["detail"]["analyses"] = [
                    {
                        k: value[k]
                        for k in [
                            "SUBJECT",
                            "SUBJECT_SAMPLE_FACTORS",
                            "COLLECTION",
                            "TREATMENT",
                            "SAMPLEPREP",
                            "CHROMATOGRAPHY",
                            "MS",
                            "NMR",
                            "ANALYSIS",
                        ]
                        if k in value
                    }
                    for value in detail
                ]
                study = detail[0].get("STUDY", {})
                record["description"] = study.get("STUDY_SUMMARY", "")
            except Exception as error:
                record["detail_error"] = str(error)[:200]
        filename = key + ".json"
        save_json(directory / filename, record)
        record.update(metadata_file=filename, sha256=sha((directory / filename).read_bytes()))
        existing[key] = record
        manifest.update(studies=list(existing.values()), updated_at=utc_now())
        save_json(path, manifest)
        print(f"STUDIES {len(existing)} {key}", flush=True)
    return manifest


def ingest_collection(service, directory):
    """Idempotently import usable content into visible application projects."""
    directory = Path(directory)
    mapping = {}
    for kind, title in [("papers", "Metabolomics"), ("studies", "Public Studies")]:
        manifest = json.loads((directory / kind / "manifest.json").read_text())
        entries = manifest[kind]
        key = f"aster:collection:{kind}:v1"
        with service.db.session() as session:
            previous = session.get(AppSetting, key)
            state = previous.value if previous else {}
        if not state:
            project = service.save_project(
                title, "代谢组学论文" if kind == "papers" else "公开研究元数据；未执行实验"
            )
            state = {"project_id": project["id"], "sources": {}}
        for entry in entries:
            accession = entry["accession"]
            existing = state["sources"].get(accession)
            with service.db.session() as session:
                if existing and session.get(Source, existing["source_id"]):
                    continue
            if kind == "papers":
                filename = entry["text_file"]
                data = (directory / kind / filename).read_bytes()
                if sha(data) != entry["text_sha256"]:
                    raise ValueError(f"hash mismatch: {filename}")
            else:
                filename = accession + ".md"
                data = (
                    f"# {entry['title']}\n\nAccession: {accession}\nRepository: {entry['repository']}\nSource: {entry['url']}\nLicense: {entry['license']}\nContent: public study metadata; raw data not downloaded; no reanalysis performed.\n\n{entry.get('description', '')}\n\n## Metadata\n\n"
                    + json.dumps(entry["detail"], ensure_ascii=False, indent=2)
                ).encode()
            source = service.import_source(
                state["project_id"],
                filename,
                data,
                title=entry["title"],
                authors=entry.get("authors", entry.get("repository", "")),
                year=str(entry.get("year", "")),
                doi=entry.get("doi", ""),
            )
            state["sources"][accession] = {
                "source_id": source["id"],
                "version_id": source["version_id"],
                "content_level": entry["content_level"],
                "url": entry["url"],
                "license": entry.get("license", ""),
                "topic": entry.get("topic", ""),
                "repository": entry.get("repository", "Europe PMC"),
            }
            with service.db.session() as session:
                entry_origin = {
                    key: value
                    for key, value in state["sources"][accession].items()
                    if key not in {"source_id", "version_id"}
                }
                session.get(Source, source["id"]).provenance = {
                    "accession": accession,
                    **entry_origin,
                }
            with service.db.session() as session:
                session.merge(AppSetting(key=key, value=state.copy()))
            print(f"IMPORTED {kind} {len(state['sources'])} {accession}", flush=True)
        mapping[kind] = state
    save_json(directory / "imported.json", mapping)
    # Small shareable catalog has provenance, not the article bodies.
    with (directory / "catalog.csv").open("w", newline="", encoding="utf-8-sig") as file:
        fields = ["accession", "title", "content_level", "url", "doi", "repository"]
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for kind in ["papers", "studies"]:
            writer.writerows(json.loads((directory / kind / "manifest.json").read_text())[kind])
    return mapping


def collection_status(service, project_id=None):
    with service.db.session() as session:
        if project_id:
            service.project(session, project_id)
        rows = session.scalars(select(AppSetting).where(AppSetting.key.like("aster:collection:%")))
        return [
            {"kind": row.key.split(":")[2], **row.value}
            for row in rows
            if not project_id or row.value["project_id"] == project_id
        ]


def main():
    import argparse
    from aster.storage.database import Database
    from aster.domain.service import Service
    from aster.app.settings import Settings

    parser = argparse.ArgumentParser(
        description="Collect public metabolomics literature and study metadata"
    )
    parser.add_argument("--directory", default=".local/metabolomics")
    parser.add_argument("--papers", type=int, default=300)
    parser.add_argument("--studies", type=int, default=100, help="per repository")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--ingest-only", action="store_true")
    args = parser.parse_args()
    directory = Path(args.directory)
    if not args.ingest_only:
        client = PublicClient()
        try:
            collect_papers(client, directory / "papers", args.papers)
            collect_studies(client, directory / "studies", args.studies)
        finally:
            client.client.close()
    if args.ingest or args.ingest_only:
        settings = Settings.from_env()
        database = Database(settings.database_url, settings.data_dir)
        database.migrate()
        ingest_collection(Service(database), directory)


if __name__ == "__main__":
    main()
