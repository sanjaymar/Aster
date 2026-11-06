"""Retrieve original article PDFs from the documented, anonymous PMC cloud service."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

from pypdf import PdfReader
from sqlalchemy import select

from aster.data.sources import PublicClient, save_json, sha, utc_now

BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
MAX_BYTES = 200 * 1024 * 1024


def download_pdf(client, url, path):
    response = client.client.head(url)
    response.raise_for_status()
    length = int(response.headers["content-length"])
    if not 0 < length <= MAX_BYTES:
        raise ValueError("Original PDF exceeds the 200 MB import limit")
    # Small verified ranges avoid restarting large transfers after proxy disconnects.
    with path.open("wb") as output:
        for start in range(0, length, 8 * 1024 * 1024):
            end = min(length - 1, start + 8 * 1024 * 1024 - 1)
            for attempt in range(3):
                try:
                    part = client.client.get(url, headers={"Range": f"bytes={start}-{end}"})
                    part.raise_for_status()
                    if (
                        part.status_code != 206
                        or not part.headers.get("content-range", "").startswith(
                            f"bytes {start}-{end}/"
                        )
                        or len(part.content) != end - start + 1
                    ):
                        raise ValueError("Invalid partial PDF response")
                    output.write(part.content)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)


def pdf_location(metadata):
    value = urlparse(metadata.get("pdf_url") or "")
    if value.scheme != "s3" or value.netloc != "pmc-oa-opendata":
        raise ValueError("No original PDF in the official article dataset")
    return BUCKET + value.path, parse_qs(value.query).get("md5", [None])[0]


def collect(directory, workers=3, limit=None):
    directory = Path(directory)
    papers = json.loads((directory / "papers/manifest.json").read_text())["papers"]
    target = directory / "pdfs"
    target.mkdir(exist_ok=True)
    path = target / "manifest.json"
    manifest = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "provider": "NIH NLM NCBI PMC Article Datasets on AWS",
            "documentation": "https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/",
            "papers": {},
        }
    )
    client = PublicClient()

    def download(paper):
        accession = paper["accession"]
        previous = manifest["papers"].get(accession, {})
        pdf = target / f"{accession}.pdf"
        if (
            previous.get("status") == "downloaded"
            and pdf.exists()
            and sha(pdf.read_bytes()) == previous["sha256"]
        ):
            return accession, previous
        try:
            listing = ET.fromstring(
                client.get(
                    BUCKET + "/",
                    **{
                        "list-type": "2",
                        "prefix": accession + ".",
                        "delimiter": "/",
                        "max-keys": 1000,
                    },
                ).content
            )
            prefixes = [p.text for p in listing.findall("s:CommonPrefixes/s:Prefix", NS)]
            choices = []
            for prefix in prefixes:
                metadata_url = f"{BUCKET}/{prefix}{prefix.rstrip('/')}.json"
                metadata = client.get(metadata_url).json()
                if metadata.get("pmcid") != accession:
                    raise ValueError("Official metadata PMCID mismatch")
                if paper.get("doi") and metadata.get("doi", "").lower() != paper["doi"].lower():
                    continue
                if metadata.get("pdf_url"):
                    choices.append((metadata, metadata_url))
            if not choices:
                return accession, {
                    "status": "unavailable",
                    "checked_at": utc_now(),
                    "reason": "No matching licensed PDF in PMC cloud dataset",
                }
            choices.sort(
                key=lambda choice: (
                    choice[0].get("is_manuscript", True),
                    -int(choice[0]["version"]),
                )
            )
            metadata, metadata_url = choices[0]
            url, expected_md5 = pdf_location(metadata)
            temporary = pdf.with_suffix(".part")
            try:
                download_pdf(client, url, temporary)
                data = temporary.read_bytes()
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Response is not a PDF")
                if expected_md5 and hashlib.md5(data).hexdigest() != expected_md5.zfill(32):
                    raise ValueError("Official PDF checksum mismatch")
                pages = len(PdfReader(io.BytesIO(data)).pages)
                temporary.replace(pdf)
            finally:
                temporary.unlink(missing_ok=True)
            save_json(target / f"{accession}.json", metadata)
            return accession, {
                "status": "downloaded",
                "file": pdf.name,
                "sha256": sha(data),
                "bytes": len(data),
                "pages": pages,
                "url": url,
                "metadata_url": metadata_url,
                "license": metadata.get("license_code"),
                "publisher_version": metadata["version"],
                "is_manuscript": metadata.get("is_manuscript"),
                "is_retracted": metadata.get("is_retracted"),
                "verified_pmcid": metadata["pmcid"],
                "verified_doi": metadata.get("doi"),
                "verified_title": metadata.get("title"),
                "fetched_at": utc_now(),
            }
        except Exception as error:
            return accession, {
                "status": "failed",
                "reason": str(error)[:250],
                "checked_at": utc_now(),
            }

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for accession, result in pool.map(download, papers[:limit]):
                manifest["papers"][accession] = result
                manifest["updated_at"] = utc_now()
                save_json(path, manifest)
                print(accession, result["status"], flush=True)
    finally:
        client.client.close()
    return manifest


def ingest(service, directory):
    from aster.domain.models import Asset, Source, SourceVersion, ReadingState
    from aster.domain.management import is_deleted

    directory = Path(directory)
    mapping = json.loads((directory / "imported.json").read_text())["papers"]
    manifest = json.loads((directory / "pdfs/manifest.json").read_text())
    imported = 0
    for accession, row in manifest["papers"].items():
        if row["status"] != "downloaded" or accession not in mapping["sources"]:
            continue
        source_id = mapping["sources"][accession]["source_id"]
        with service.db.session() as session:
            if is_deleted(session, mapping["project_id"], "source", source_id):
                continue
            source = service.source(session, mapping["project_id"], source_id)
            existing = session.scalar(
                select(SourceVersion)
                .join(Asset, Asset.id == SourceVersion.asset_id)
                .where(
                    SourceVersion.source_id == source_id,
                    Asset.sha256 == row["sha256"],
                )
            )
            title, authors, year, doi = source.title, source.authors, source.year, source.doi
        if existing:
            result = {"version_id": existing.id}
        else:
            data = (directory / "pdfs" / row["file"]).read_bytes()
            if sha(data) != row["sha256"]:
                raise ValueError("Cached PDF changed: " + accession)
            result = service.import_source(
                mapping["project_id"],
                row["file"],
                data,
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                source_id=source_id,
            )
        with service.db.session() as session:
            source = session.get(Source, source_id)
            source.provenance = {
                **source.provenance,
                "retrieval_version_id": mapping["sources"][accession]["version_id"],
                "original_pdf": {
                    "url": row["url"],
                    "sha256": row["sha256"],
                    "license": row["license"],
                    "metadata_url": row["metadata_url"],
                    "source_version_id": result["version_id"],
                    "retrieved_at": row["fetched_at"],
                    "is_retracted": row["is_retracted"],
                },
            }
            reading = session.get(ReadingState, (mapping["project_id"], source_id))
            if (
                not existing
                and reading
                and reading.last_version_id == mapping["sources"][accession]["version_id"]
            ):
                reading.last_version_id = result["version_id"]
                reading.last_page, reading.last_scroll = 1, 0
        row["imported_version_id"] = result["version_id"]
        save_json(directory / "pdfs/manifest.json", manifest)
        imported += not bool(existing)
        print("IMPORTED PDF", accession, result["version_id"], flush=True)
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".local/metabolomics")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--ingest-only", action="store_true")
    args = parser.parse_args()
    if not args.ingest_only:
        collect(args.directory, args.workers, args.limit)
    if args.ingest or args.ingest_only:
        from aster.app.settings import Settings
        from aster.domain.service import Service
        from aster.storage.database import Database

        settings = Settings.from_env()
        database = Database(settings.database_url, settings.data_dir)
        database.migrate()
        print("Imported", ingest(Service(database), args.directory))


if __name__ == "__main__":
    main()
