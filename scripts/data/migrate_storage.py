"""Copy an existing Aster library into its structured home, preserving all IDs.

Stop Aster before running. The original is retained until the copy is verified.
Usage: uv run python scripts/data/migrate_storage.py --source .local/zhixu --target ./data
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from aster.storage.paths import filename, prepare


def migrate(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents:
        raise ValueError("Use a separate destination")
    prepare(target)
    destination = target / "library/aster.db"
    if destination.exists():
        raise FileExistsError("Destination already contains a database; no changes made")
    original = source / ("aster.db" if (source / "aster.db").exists() else "zhixu.db")
    with sqlite3.connect(original) as old, sqlite3.connect(destination) as new:
        if old.execute(
            "select count(*) from agent_runs where status in ('queued','running')"
        ).fetchone()[0]:
            raise RuntimeError("Finish or cancel active tasks first")
        old.backup(new)
    assets = target / "library/files"
    assets.mkdir(exist_ok=True)
    copied = {}
    with sqlite3.connect(destination) as database:
        for asset_id, name, key, digest in database.execute(
            "select id,name,storage_key,sha256 from assets"
        ).fetchall():
            if key not in copied:
                original_file = source / "files" / key
                if hashlib.sha256(original_file.read_bytes()).hexdigest() != digest:
                    raise RuntimeError("Asset integrity check failed: " + name)
                key_name = filename(name)
                path = assets / key_name
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    key_name = f"{path.stem}-{asset_id[:6]}{path.suffix}"
                    path = assets / key_name
                if not path.exists():
                    try:
                        os.link(original_file, path)
                    except OSError:
                        shutil.copy2(original_file, path)
                copied[key] = key_name
            database.execute("update assets set storage_key=? where id=?", (copied[key], asset_id))
        if database.execute("pragma quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database check failed")
        if database.execute("pragma foreign_key_check").fetchall():
            raise RuntimeError("Database references invalid")
    for folder, dest in [("models", "models"), ("indexes", "cache/indexes")]:
        if (source / folder).is_dir():
            shutil.copytree(
                source / folder,
                target / dest,
                dirs_exist_ok=True,
                copy_function=lambda a, b: os.link(a, b),
            )
    manifest = {"source": str(source), "home": str(target), "assets": len(copied), "verified": True}
    (target / "archive/storage.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.target), indent=2))
