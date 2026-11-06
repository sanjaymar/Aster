"""Verify local provenance and optionally compare samples with official live services."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from aster.data.sources import PublicClient, sha, utc_now, save_json, MW, MTBLS


def audit(directory, online=False):
    directory = Path(directory)
    papers = json.loads((directory / "papers/manifest.json").read_text())["papers"]
    studies = json.loads((directory / "studies/manifest.json").read_text())["studies"]
    failures = []
    for row in papers:
        xml = (directory / "papers" / row["xml_file"]).read_bytes()
        text = (directory / "papers" / row["text_file"]).read_bytes()
        ids = {
            node.get("pub-id-type"): node.text
            for node in ET.fromstring(xml).findall(".//article-meta/article-id")
        }
        if (
            sha(xml) != row["xml_sha256"]
            or sha(text) != row["text_sha256"]
            or ids.get("pmcid") != row["accession"]
            or ids.get("doi", "") != row.get("doi", "")
        ):
            failures.append(row["accession"])
    for row in studies:
        if sha((directory / "studies" / row["metadata_file"]).read_bytes()) != row["sha256"]:
            failures.append(row["accession"])
    matrices = []
    for row in json.loads((directory / "experiment-plan.json").read_text())["matrices"]:
        raw = (directory / "processed" / (row["accession"] + ".json")).read_bytes()
        records = json.loads(raw)
        values = [
            r for r in records.values() if isinstance(r, dict) and isinstance(r.get("DATA"), dict)
        ]
        samples = list(dict.fromkeys(sample for r in values for sample in r["DATA"]))
        with (directory / "processed" / (row["accession"] + ".csv")).open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            table = list(csv.reader(stream))
        unchanged = (
            table[0][4:] == samples
            and len(table) - 1 == len(values)
            and all(
                table[i + 1][4:]
                == [
                    "" if value["DATA"].get(sample) is None else str(value["DATA"].get(sample, ""))
                    for sample in samples
                ]
                for i, value in enumerate(values)
            )
        )
        if sha(raw) != row["sha256"] or not unchanged:
            failures.append(row["accession"] + ":matrix")
        matrices.append(
            {
                "accession": row["accession"],
                "records": len(values),
                "samples": len(samples),
                "csv_values_unchanged": unchanged,
            }
        )
    originals_path = directory / "pdfs/manifest.json"
    originals = json.loads(originals_path.read_text())["papers"] if originals_path.exists() else {}
    for key, row in originals.items():
        if (
            row["status"] == "downloaded"
            and sha((directory / "pdfs" / row["file"]).read_bytes()) != row["sha256"]
        ):
            failures.append(key + ":pdf")
    report = {
        "checked_at": utc_now(),
        "papers": len(papers),
        "study_metadata": dict(Counter(r["repository"] for r in studies)),
        "local_hash_and_article_identity_failures": failures,
        "original_pdf_status": dict(Counter(r["status"] for r in originals.values())),
        "processed_matrices": matrices,
        "scope": "Real archived articles, public study metadata and official processed matrices. No raw spectra reanalysis or expert validation of article findings.",
        "online_samples": [],
    }
    if online:
        client = PublicClient()
        try:
            for index in [
                0,
                len(papers) // 4,
                len(papers) // 2,
                3 * len(papers) // 4,
                len(papers) - 1,
            ]:
                row = papers[index]
                try:
                    metadata = client.get(
                        f"https://pmc-oa-opendata.s3.amazonaws.com/metadata/{row['accession']}.1.json"
                    ).json()
                    report["online_samples"].append(
                        {
                            "accession": row["accession"],
                            "provider": "NCBI PMC Cloud",
                            "identity_matches": metadata["pmcid"] == row["accession"]
                            and metadata.get("doi", "").lower() == row["doi"].lower(),
                            "title": metadata["title"],
                        }
                    )
                except Exception as error:
                    report["online_samples"].append(
                        {"accession": row["accession"], "error": str(error)[:180]}
                    )
            study = next(row for row in studies if row["repository"] == "MetaboLights")
            try:
                metadata = client.get(f"{MTBLS}/studies/{study['accession']}").json()
                rows = metadata.get("isaInvestigation", {}).get("studies", [])
                record = next((r for r in rows if r.get("identifier") == study["accession"]), {})
                report["online_samples"].append(
                    {
                        "accession": study["accession"],
                        "provider": "MetaboLights",
                        "title_matches": record.get("title") == study["title"],
                        "public": metadata.get("mtblsStudy", {}).get("studyStatus", "").lower()
                        == "public",
                    }
                )
            except Exception as error:
                report["online_samples"].append(
                    {"accession": study["accession"], "error": str(error)[:180]}
                )
            for row in matrices:
                try:
                    remote = client.get(f"{MW}/study/study_id/{row['accession']}/data").json()
                    cached = json.loads(
                        (directory / "processed" / (row["accession"] + ".json")).read_text()
                    )
                    report["online_samples"].append(
                        {
                            "accession": row["accession"],
                            "provider": "Metabolomics Workbench",
                            "official_matrix_matches": remote == cached,
                        }
                    )
                except Exception as error:
                    report["online_samples"].append(
                        {"accession": row["accession"], "error": str(error)[:180]}
                    )
        finally:
            client.client.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".local/metabolomics")
    parser.add_argument("--output", default=".local/metabolomics/provenance-audit.json")
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    result = audit(args.directory, args.online)
    save_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert not result["local_hash_and_article_identity_failures"], "See audit for failed checks"
