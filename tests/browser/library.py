"""Long library rows must fit, expose their actions, and scroll with the page."""

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    root = Path(__file__).resolve().parents[2]
    from aster.app.settings import Settings

    output = Settings.from_env().data_dir / "cache/checks/library"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aster-library-") as temp:
        directory = Path(temp)
        database = directory / "library.db"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        address = f"http://127.0.0.1:{port}"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("ASTER_", "ZHIXU_"))
        }
        env.update(
            ASTER_HOME=str(directory),
            ASTER_DATABASE_URL=f"sqlite:///{database}",
            ASTER_RETRIEVAL_MODE="lexical",
            ASTER_MODEL_URL="http://127.0.0.1:1/v1",
        )
        with (output / "server.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "aster.app.api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                with httpx.Client(base_url=address, timeout=15, trust_env=False) as client:
                    for _ in range(100):
                        try:
                            if client.get("/api/health").is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    project = client.post(
                        "/api/projects", json={"title": "Library layout fixtures"}
                    ).json()["id"]
                    for index in range(28):
                        response = client.post(
                            f"/api/projects/{project}/sources",
                            data={
                                "title": f"Fixture {index:02d} — Multi-cohort metabolomics analysis of "
                                + "long scientific research titles and methods " * 5,
                                "authors": ", ".join(
                                    f"Researcher {number:02d} Longname" for number in range(28)
                                ),
                                "year": "2026",
                                "doi": "10.fixture/" + "very-long-identifier-" * 8,
                            },
                            files={
                                "file": (
                                    "layout.txt",
                                    b"Synthetic layout fixture, not scientific evidence.",
                                    "text/plain",
                                )
                            },
                        )
                        assert response.status_code == 201, response.text
                    with sqlite3.connect(database) as connection:
                        connection.execute(
                            "UPDATE sources SET provenance = ?",
                            (json.dumps({"url": "https://example.org/layout-fixture"}),),
                        )
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        executable_path=os.getenv("CHROME_BIN", "/usr/bin/google-chrome"),
                        headless=True,
                        args=["--no-sandbox"],
                    )
                    page = browser.new_page(viewport={"width": 1512, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(address)
                    page.locator(".sidebar").get_by_role(
                        "button", name="文献阅读", exact=False
                    ).click()
                    rows = page.locator(".library-table tbody tr")
                    expect(rows).to_have_count(25)
                    first = set(rows.evaluate_all("rows => rows.map(row => row.dataset.sourceId)"))
                    assert len(first) == 25
                    for width in [1512, 1280, 1024, 760, 390, 320]:
                        page.set_viewport_size({"width": width, "height": 1000})
                        page.locator(".main-content").evaluate("element => element.scrollTop = 0")
                        page.wait_for_timeout(100)
                        geometry = page.evaluate("""() => {
                            const list=document.querySelector('.library-list'), bounds=list.getBoundingClientRect();
                            const rows=[...list.querySelectorAll('tbody tr')];
                            return {
                                pageFits: document.documentElement.scrollWidth <= innerWidth + 1,
                                listFits: list.scrollWidth <= list.clientWidth + 1,
                                noInnerScroll: list.scrollHeight <= list.clientHeight + 1,
                                titleAtLeft: rows.every(row => row.querySelector('.library-title').getBoundingClientRect().left - bounds.left < 120),
                                actionsFit: rows.every(row => [...row.querySelectorAll('.library-actions button, .library-actions a')].every(button => {
                                    const rect=button.getBoundingClientRect(); return rect.width > 0 && rect.left >= bounds.left && rect.right <= bounds.right + 1;
                                }))
                            };
                        }""")
                        assert all(geometry.values()), (width, geometry)
                        page.screenshot(path=str(output / f"library-{width}.png"))
                    page.set_viewport_size({"width": 1512, "height": 1000})
                    page.locator(".main-content").evaluate("element => element.scrollTop = 1000")
                    assert page.locator(".main-content").evaluate(
                        "element => element.scrollTop > 500"
                    )
                    assert page.locator(".library-list").evaluate(
                        "element => element.scrollTop === 0"
                    )
                    page.get_by_role("button", name="下一页", exact=True).click()
                    expect(rows).to_have_count(3)
                    second = set(rows.evaluate_all("rows => rows.map(row => row.dataset.sourceId)"))
                    assert not first.intersection(second)
                    page.get_by_label("搜索文献", exact=True).fill("Fixture 07")
                    expect(rows).to_have_count(1)
                    rows.first.get_by_role("button", name="阅读", exact=True).click()
                    expect(page.get_by_role("dialog", name="论文阅读器")).to_be_visible()
                    page.get_by_role("button", name="返回文献库", exact=True).click()
                    expect(page.get_by_role("dialog", name="论文阅读器")).not_to_be_visible()
                    rows.first.get_by_role("button", name="编辑资料", exact=False).click()
                    expect(page.get_by_role("dialog", name="编辑资料", exact=True)).to_be_visible()
                    page.get_by_role("dialog", name="编辑资料", exact=True).get_by_role(
                        "button", name="关闭", exact=True
                    ).click()
                    assert not errors, errors
                    browser.close()
                print(
                    json.dumps(
                        {
                            "library_layout": "passed",
                            "widths": [1512, 1280, 1024, 760, 390, 320],
                            "unique_rows": 28,
                        }
                    )
                )
            finally:
                process.terminate()
                process.wait(timeout=20)


if __name__ == "__main__":
    main()
