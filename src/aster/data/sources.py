"""Public HTTP, JATS parsing and collection provenance helpers."""

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from aster.domain.models import AppSetting

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


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
