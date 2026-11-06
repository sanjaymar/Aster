"""Browser smoke: real PDF rendering, reader chat, notes, live map and editable slides.

Uses an isolated database, no real model calls and no personal data changes.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from aster.app.settings import Settings


def make_paper(path):
    writer = PdfWriter()
    for title, body in [
        ("Methods", "This study uses pooled quality-control samples."),
        ("Limitations", "These are synthetic browser test pages, not research findings."),
    ]:
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 18 Tf 50 780 Td ({title}) Tj 0 -40 Td /F1 12 Tf ({body}) Tj ET".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)


def main():
    root = Path(__file__).resolve().parents[2]
    output = Settings.from_env().data_dir / "cache/checks/product"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aster-browser-") as temporary:
        directory = Path(temporary)
        paper = directory / "paper.pdf"
        make_paper(paper)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ASTER_", "ZHIXU_"))}
        env.update(
            ASTER_HOME=str(directory),
            ASTER_DATABASE_URL="sqlite:///" + str(directory / "library/aster.db"),
            ASTER_RETRIEVAL_MODE="lexical",
            ASTER_RETRIEVAL_URL="",
            ASTER_ACCESS_TOKEN="",
            ASTER_MODEL="fixture",
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
                address = f"http://127.0.0.1:{port}"
                with httpx.Client(base_url=address + "/api", timeout=20, trust_env=False) as client:
                    for _ in range(100):
                        try:
                            if client.get("/health").is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    pid = client.post("/projects", json={"title": "Reading fixtures"}).json()["id"]
                    base = f"/projects/{pid}"
                    imported = client.post(
                        base + "/sources",
                        data={"title": "Synthetic QC paper"},
                        files={"file": ("paper.pdf", paper.read_bytes(), "application/pdf")},
                    )
                    assert imported.status_code == 201, imported.text
                    source = imported.json()
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(
                            executable_path=os.getenv("CHROME_BIN", "/opt/google/chrome/chrome"),
                            headless=True,
                            args=["--no-sandbox"],
                        )
                        page = browser.new_page(viewport={"width": 1440, "height": 1000})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(address)
                        sidebar = page.locator(".sidebar")
                        sidebar.get_by_role("button", name="文献阅读", exact=False).click()
                        page.screenshot(path=str(output / "library.png"))
                        page.locator(".library-title").first.click()
                        expect(page.locator(".reader-workspace")).to_be_visible()
                        expect(page.locator("canvas").first).to_be_visible(timeout=20000)
                        page.locator(".reader-workspace").get_by_role(
                            "button", name="问答", exact=True
                        ).click()
                        expect(page.get_by_placeholder("输入问题…")).to_be_visible()
                        page.get_by_placeholder("输入问题…").fill("解释质量控制")
                        expect(
                            page.locator('select[aria-label="PDF 问答模型"]:visible')
                        ).to_be_visible()
                        page.screenshot(path=str(output / "reader.png"))
                        page.locator(".reader-workspace").get_by_role(
                            "button", name="笔记", exact=True
                        ).click()
                        expect(
                            page.get_by_role("button", name="生成阅读笔记", exact=True)
                        ).to_be_visible()
                        page.get_by_role("button", name="新建", exact=True).click()
                        page.get_by_label("阅读笔记标题").fill("QC 阅读笔记")
                        page.get_by_role("textbox", name="阅读笔记正文").fill(
                            "Synthetic note with a table to add later."
                        )
                        page.get_by_role("button", name="保存笔记", exact=True).click()
                        expect(page.get_by_text("QC 阅读笔记", exact=True)).to_be_visible()
                        # Return to project without reaching into React state.
                        page.reload()
                        sidebar = page.locator(".sidebar")
                        sidebar.get_by_role("button", name="文献地图", exact=True).click()
                        expect(page.get_by_label("交互式文献主题图")).to_be_visible(timeout=20000)
                        expect(page.locator(".topic-canvas canvas").first).to_be_visible()
                        page.screenshot(path=str(output / "map.png"))
                        sidebar.get_by_role("button", name="汇报", exact=True).click()
                        page.get_by_role("button", name="空白汇报", exact=True).click()
                        page.get_by_label("汇报标题", exact=True).fill("QC 汇报")
                        page.locator(".slide-properties").get_by_label("标题", exact=True).fill(
                            "Quality control"
                        )
                        page.get_by_label("要点 · 每行一条").fill("Pooled samples\nCheck drift")
                        page.get_by_label("幻灯片版式").select_option("flow")
                        page.get_by_label("方法流程", exact=True).fill(
                            "Collect | Synthetic samples\nPrepare | Synthetic preparation\nMeasure | Synthetic measurement\nCheck | Synthetic check\nReport | Synthetic summary"
                        )
                        page.get_by_label("本页结论", exact=True).fill("Synthetic workflow only")
                        page.get_by_role("button", name="保存", exact=True).click()
                        expect(page.get_by_role("button", name="保存", exact=True)).to_be_disabled()
                        flow = page.locator(".deck-main .sp-flow li").last.bounding_box()
                        takeaway = page.locator(".deck-main .sp-takeaway").bounding_box()
                        assert flow["y"] + flow["height"] <= takeaway["y"], "Flow overlaps takeaway"
                        page.get_by_role("button", name="添加一页", exact=False).click()
                        page.locator(".slide-properties").get_by_label("标题", exact=True).fill(
                            "Limitations"
                        )
                        page.get_by_role("button", name="保存", exact=True).click()
                        expect(page.get_by_role("button", name="保存", exact=True)).to_be_disabled()
                        with page.expect_download() as download:
                            page.get_by_role("link", name="PPTX", exact=True).click()
                        download.value.save_as(output / "slides.pptx")
                        page.screenshot(path=str(output / "slides.png"))
                        assert not errors, errors
                        assert len(client.get(base + "/artifacts").json()) == 2
                        browser.close()
                        print(
                            "PASS PDF, reader chat, note save, map, editable slides and PPTX export",
                            flush=True,
                        )
            finally:
                process.terminate()
                process.wait(timeout=20)


if __name__ == "__main__":
    main()
