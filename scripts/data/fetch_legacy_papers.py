"""Download public example papers with a provenance manifest; never seed personal data."""

import argparse
import hashlib
import json
import time
from pathlib import Path
import httpx


def fetch(destination):
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "eval/corpus.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    completed = []
    with httpx.Client(
        follow_redirects=True,
        timeout=90,
        headers={"User-Agent": "Zhixu-local-research-example/0.1"},
    ) as client:
        for paper in manifest["papers"]:
            path = destination / (paper["key"] + ".pdf")
            url = "https://arxiv.org/pdf/" + paper["arxiv"]
            if not path.is_file():
                for attempt in range(3):
                    try:
                        response = client.get(url)
                        response.raise_for_status()
                        if not response.content.startswith(b"%PDF-"):
                            raise ValueError("not a PDF")
                        path.write_bytes(response.content)
                        break
                    except (httpx.HTTPError, ValueError):
                        if attempt == 2:
                            raise
                        time.sleep(2 * (attempt + 1))
                time.sleep(1)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if paper.get("expected_sha256") and digest != paper["expected_sha256"]:
                raise ValueError(
                    f"PDF hash differs for {paper['key']}; check the pinned version before changing evaluation labels"
                )
            completed.append(
                {
                    **paper,
                    "url": url,
                    "filename": path.name,
                    "sha256": digest,
                }
            )
            print("PAPER_READY", paper["key"], path.stat().st_size, flush=True)
    (destination / "manifest.json").write_text(
        json.dumps({**manifest, "papers": completed}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".local/evaluation/papers"))
    fetch(parser.parse_args().output)
