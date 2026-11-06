"""Prepare a Linux offline coding-agent runtime without the research app dependencies."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / ".local/bench-runtime"
REQUIREMENTS = ["openai==2.45.0", "httpx==0.28.1", "pydantic==2.13.4", "python-dotenv==1.2.2"]


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    wheels = DEST / "wheels"
    wheels.mkdir(exist_ok=True)
    name = "mini_harness_coding_agent-0.1.0"
    info = name + ".dist-info"
    files = {
        str(p.relative_to(ROOT / "src")): p.read_bytes()
        for p in (ROOT / "src/mini_harness").rglob("*.py")
    }
    files[info + "/METADATA"] = (
        "Metadata-Version: 2.1\nName: mini-harness-coding-agent\nVersion: 0.1.0\nRequires-Python: >=3.12\n"
        + "".join(f"Requires-Dist: {r}\n" for r in REQUIREMENTS)
        + "\n"
    ).encode()
    files[info + "/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: mini-harness\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files[info + "/entry_points.txt"] = (
        b"[console_scripts]\nmini-harness = mini_harness.main:main\n"
    )
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for path, data in files.items():
        writer.writerow(
            [
                path,
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("="),
                len(data),
            ]
        )
    writer.writerow([info + "/RECORD", "", ""])
    files[info + "/RECORD"] = record.getvalue().encode()
    wheel = wheels / (name + "-py3-none-any.whl")
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            "pip",
            "python",
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--python-version",
            "3.12",
            "--dest",
            str(wheels),
            *REQUIREMENTS,
        ],
        check=True,
    )
    executable = Path(
        subprocess.check_output(["uv", "python", "find", "3.12"], text=True).strip()
    ).resolve()
    prefix = executable.parent.parent
    if not (prefix / "lib/python3.12/os.py").exists():
        raise RuntimeError("Requires a portable uv-managed Python 3.12 installation")
    if not (DEST / "python").exists():
        shutil.copytree(prefix, DEST / "python", symlinks=True)
    manifest = {
        "platform": sys.platform,
        "python": str(executable),
        "agent_dependencies": REQUIREMENTS,
        "core_sha256": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in files.items()
            if name.startswith("mini_harness/")
        },
        "wheels": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels.glob("*.whl")
        },
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(DEST)


if __name__ == "__main__":
    main()
