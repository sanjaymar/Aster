"""Optional offline vector builder; writes the same content-addressed cache as Retriever.

Export with the application environment, encode with an existing CUDA Python if desired.
No packages are installed into the supplied worker environment.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid
import os
import inspect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--export", default=".local/metabolomics/embeddings.jsonl")
    parser.add_argument("--input")
    parser.add_argument("--model")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=2)
    args = parser.parse_args()
    if args.project:
        from aster.app.settings import Settings
        from aster.storage.database import Database
        from aster.domain.service import Service
        from aster.retrieval.engine import Retriever

        settings = Settings.from_env()
        database = Database(settings.database_url, settings.data_dir)
        retriever = Retriever(Service(database), settings)
        snapshot = retriever.corpus.snapshot(args.project, scope="project")
        items = retriever.corpus.items(args.project, snapshot)
        modelkey = json.dumps(retriever.models.fingerprint()["embedding"], sort_keys=True)
        cache = retriever.root / "vectors"
        cache.mkdir(exist_ok=True)
        output = Path(args.export)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w") as file:
            for item in items:
                key = hashlib.sha256((modelkey + "\n" + item.text).encode()).hexdigest()
                file.write(
                    json.dumps(
                        {"text": item.text, "path": str((cache / (key + ".npy")).resolve())},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        print(json.dumps({"items": len(items), "export": str(output)}), flush=True)
        return
    if not args.input or not args.model:
        parser.error("provide --project to export, or --input and --model to encode")
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    started = time.monotonic()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    supported = inspect.signature(SentenceTransformer).parameters
    options = {"device": args.device}
    if "local_files_only" in supported:
        options["local_files_only"] = True
    if "trust_remote_code" in supported:
        options["trust_remote_code"] = False
    model = SentenceTransformer(args.model, **options)
    model.max_seq_length = 1536
    if args.device.startswith("cuda"):
        model.half()
    rows = [json.loads(line) for line in Path(args.input).read_text().splitlines()]
    missing = [row for row in rows if not Path(row["path"]).exists()]
    done = 0
    for start in range(0, len(missing), 32):
        batch = missing[start : start + 32]
        vectors = model.encode(
            [row["text"] for row in batch],
            batch_size=args.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        for row, vector in zip(batch, vectors):
            destination = Path(row["path"])
            temporary = destination.with_name(destination.stem + "." + uuid.uuid4().hex + ".tmp")
            with temporary.open("wb") as file:
                np.save(file, np.asarray(vector, dtype=np.float32), allow_pickle=False)
            temporary.replace(destination)
        done += len(batch)
        print(f"ENCODE {done}/{len(missing)} elapsed={time.monotonic() - started:.1f}s", flush=True)
    report = {
        "items": len(rows),
        "new_vectors": len(missing),
        "model": args.model,
        "max_length": 1536,
        "device": args.device,
        "dtype": "float16" if args.device.startswith("cuda") else "float32",
        "normalized": True,
        "torch": torch.__version__,
        "duration_seconds": time.monotonic() - started,
        "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
    }
    Path(args.input + ".report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
