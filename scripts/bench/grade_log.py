"""Run the official pinned SWE-bench grader on captured tests, without changing Harbor rewards."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    from swebench.harness.test_spec.test_spec import make_test_spec
    from swebench.harness.grading import get_logs_eval, get_eval_tests_report, get_resolution_status
    from swebench.harness.constants import (
        ResolvedStatus,
        EvalType,
        PASS_TO_PASS,
        FAIL_TO_PASS,
        KEY_INSTANCE_ID,
        FAIL_ONLY_REPOS,
        START_TEST_OUTPUT,
        END_TEST_OUTPUT,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--job-id")
    args = parser.parse_args()
    root = Path(args.directory)
    datum = json.loads((root / "config.json").read_text())
    specification = make_test_spec(datum)
    raw = (root / "test.log").read_bytes()
    text = raw.decode(errors="replace")
    normalized = root / "normalized-test.log"
    normalized.write_text(f"{START_TEST_OUTPUT}\n{text}\n{END_TEST_OUTPUT}")
    status, found = get_logs_eval(specification, str(normalized))
    reference = {
        KEY_INSTANCE_ID: specification.instance_id,
        FAIL_TO_PASS: specification.FAIL_TO_PASS,
        PASS_TO_PASS: specification.PASS_TO_PASS,
    }
    kind = EvalType.FAIL_ONLY if specification.repo in FAIL_ONLY_REPOS else EvalType.PASS_AND_FAIL
    tests = get_eval_tests_report(status, reference, eval_type=kind) if found else {}
    resolved = found and get_resolution_status(tests) == ResolvedStatus.FULL.value
    output = {
        "instance_id": specification.instance_id,
        "benchmark": "SWE-bench Verified",
        "resolved": bool(resolved),
        "graded": bool(found),
        "reward": int(bool(resolved)),
        "grader": "swebench==4.0.3 official grading functions",
        "mode": "official grading of saved tests; original Harbor reward files untouched",
        "tests_status": tests,
        "test_log_sha256": hashlib.sha256(raw).hexdigest(),
        "config_sha256": hashlib.sha256((root / "config.json").read_bytes()).hexdigest(),
        "patch_sha256": hashlib.sha256((root / "model.patch").read_bytes()).hexdigest(),
        "model": "qwen3.8-27b",
        "harness": "mini-harness",
        "n_tasks": 1,
        "harbor_job": args.job_id,
    }
    (root / "official-report.json").write_text(json.dumps(output, indent=2))
    print(json.dumps({k: v for k, v in output.items() if k != "tests_status"}, indent=2))
    raise SystemExit(0 if resolved else 1)


if __name__ == "__main__":
    main()
