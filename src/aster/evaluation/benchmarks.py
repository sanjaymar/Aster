"""Read local Harbor evidence without treating environment exceptions as solved tasks."""

import json
from pathlib import Path


def read_benchmarks(root=None):
    root = Path(root or Path.cwd() / "jobs")
    rows = []
    for job in sorted(root.glob("*/20*/result.json"), reverse=True):
        if not job.parent.parent.name.startswith(("aster-qwen-swe", "qwen-swe")):
            continue
        try:
            result = json.loads(job.read_text())
            trials = []
            for path in sorted(job.parent.glob("*/result.json")):
                trial = json.loads(path.read_text())
                verifier = trial.get("verifier_result") or {}
                rewards = verifier.get("rewards") or {}
                reward = rewards.get("reward", next(iter(rewards.values()), None))
                error = trial.get("exception_info")
                diagnostic = None
                log_path = path.parent / "verifier/test-stdout.txt"
                if reward == 0 and log_path.exists():
                    log = log_path.read_text(errors="replace")
                    if "get_marker" in log and "AttributeError" in log:
                        diagnostic = "测试插件版本不兼容，测试未能执行。"
                    elif "242 passed" in log and "test_compose_roundtrip[unit0]" in log:
                        diagnostic = (
                            "测试日志通过，但严格评分未通过；此历史运行存在参数化测试 ID 差异。"
                        )
                trials.append(
                    {
                        "task": path.parent.name,
                        "reward": reward,
                        "exception": error.get("exception_type") if error else None,
                        "resolved": reward == 1,
                        "model": (trial.get("agent_info") or {}).get("model_name"),
                        "diagnostic": diagnostic,
                    }
                )
            graded = [
                trial for trial in trials if trial["reward"] is not None and not trial["exception"]
            ]
            finished = bool(result.get("finished_at"))
            rows.append(
                {
                    "id": str(job.parent.relative_to(root)),
                    "benchmark": "SWE-bench Verified",
                    "sample": "local task subset",
                    "model": "qwen3.8-27b",
                    "harness": "mini-harness",
                    "started_at": result.get("started_at"),
                    "status": "complete"
                    if finished and graded
                    else "failed"
                    if finished
                    else "running",
                    "resolved": sum(t["resolved"] for t in graded),
                    "graded": len(graded),
                    "exceptions": sum(bool(t["exception"]) for t in trials),
                    "score": sum(t["resolved"] for t in graded) / len(graded) if graded else None,
                    "total_tasks": result.get("n_total_trials"),
                    "trials": trials,
                }
            )
        except (ValueError, OSError):
            continue
    return sorted(rows, key=lambda row: row.get("started_at") or "", reverse=True)
