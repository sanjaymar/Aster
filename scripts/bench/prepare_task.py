"""Copy a task and repair runtime dependencies, preserving assertions and reference labels."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", default=".local/swebench-http1/astropy__astropy-7606")
    p.add_argument("--output", default=".local/swebench-runtime/astropy__astropy-7606")
    args = p.parse_args()
    source = Path(args.source).resolve()
    target = Path(args.output).resolve()
    if target.exists():
        raise SystemExit(
            "Output exists; preserve the previous task snapshot and choose another output."
        )
    shutil.copytree(source, target)
    script = target / "tests/test.sh"
    text = script.read_text()
    original = "        python -m pip install -e .[test] --verbose"
    assert original in text
    text = text.replace(
        original,
        "        python -m pip install --no-index --find-links /opt/mini-harness-runtime/test-wheels pytest==4.6.11 pytest-remotedata==0.3.2\n"
        + original,
        1,
    )
    assert "uv run parser.py | tee" in text
    text = text.replace(
        "uv run parser.py | tee",
        "PYTHONPATH=/opt/mini-harness-runtime/verifier /opt/mini-harness-runtime/python/bin/python3.12 parser.py | tee",
        1,
    )
    script.write_text(text)
    assert digest(source / "tests/config.json") == digest(target / "tests/config.json")
    report = {
        "source": str(source),
        "changes": [
            "pytest 4.6.11 plus pytest-remotedata 0.3.2 preserve reference parameter IDs and compatible marker hooks",
            "offline swebench 4.0.3 parser dependencies, including pyarrow 20 compatible with datasets 2.16.1",
        ],
        "reference_config_sha256": digest(target / "tests/config.json"),
        "original_test_script_sha256": digest(source / "tests/test.sh"),
        "test_script_sha256": digest(script),
        "test_assertions_changed": False,
        "reference_labels_changed": False,
        "inherited_environment_repair": json.loads(
            (source / "infrastructure-fix.json").read_text()
        ),
    }
    (target / "runtime-fix.json").write_text(json.dumps(report, indent=2))
    print(target)


if __name__ == "__main__":
    main()
