"""Browser regression with temporary data. Does not call Qwen or modify personal projects."""

import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


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
    output = root / ".local/workspace-validation"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aster-browser-") as temp:
        directory = Path(temp)
        paper = directory / "paper.pdf"
        make_paper(paper)
        csv = directory / "matrix.csv"
        csv.write_text("condition,area\nQC,1.2300e-8\nSample,5.6")
        image = directory / "plot.png"
        image.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6EN0AAAAASUVORK5CYII="
            )
        )
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
            ASTER_DATA_DIR=str(directory / "data"),
            ASTER_DATABASE_URL=f"sqlite:///{directory}/data/browser.db",
            ASTER_MODEL_URL="http://127.0.0.1:1/v1",
            ASTER_MODEL="offline-fixture",
            ASTER_RETRIEVAL_MODE="lexical",
        )
        log = (output / "server.log").open("w")
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
        client = httpx.Client(base_url=address, trust_env=False, timeout=15)
        try:
            for _ in range(100):
                try:
                    if client.get("/api/health").is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.getenv("CHROME_BIN", "/usr/bin/google-chrome"),
                    headless=True,
                    args=["--no-sandbox"],
                )
                context = browser.new_context(viewport={"width": 1512, "height": 1000})
                page = context.new_page()
                errors = []
                page.on(
                    "pageerror",
                    lambda error: (
                        errors.append(str(error)),
                        print("PAGEERROR", error.stack, flush=True),
                    ),
                )
                page.on(
                    "console",
                    lambda message: (
                        print("BROWSER", message.type, message.text[:600], flush=True)
                        if message.type in ("error", "warning")
                        else None
                    ),
                )
                page.goto(address)
                page.get_by_role("button", name="创建项目", exact=True).click()
                page.get_by_label("项目名称", exact=True).fill("Browser research")
                page.get_by_role("button", name="保存项目", exact=True).click()
                expect(
                    page.get_by_role("heading", name="Browser research", exact=True)
                ).to_be_visible()
                project = client.get("/api/projects").json()[0]["id"]
                sidebar = page.locator(".sidebar")
                for label in ["SWE-bench", "评测", "会话记忆", "任务记录", "资料检索"]:
                    assert sidebar.get_by_role("button", name=label, exact=True).count() == 0
                # Daily discussion uses a model even with an empty knowledge base.
                # This isolated fixture deliberately has no available model API.
                page.get_by_label("研究问题", exact=True).fill("现在有什么资料？")
                page.get_by_role("button", name="发送研究任务").click()
                expect(page.get_by_text("无法连接模型服务", exact=False).first).to_be_visible(
                    timeout=15000
                )
                sidebar.get_by_role("button", name="文献阅读", exact=False).click()
                page.get_by_role("button", name="导入文献", exact=True).click()
                page.locator("dialog input[type=file]").set_input_files(paper)
                page.get_by_label("标题", exact=True).fill("Reader fixture")
                page.get_by_role("button", name="导入资料", exact=True).click()
                expect(
                    page.locator(".library-title").filter(has_text="Reader fixture")
                ).to_be_visible()
                source = client.get(f"/api/projects/{project}/sources").json()[0]
                spans = client.get(f"/api/projects/{project}/sources/{source['id']}/pages").json()[
                    "pages"
                ]
                sidebar.get_by_role("button", name="项目概览", exact=True).click()
                page.locator(".dashboard-row").filter(has_text="Reader fixture").click()
                reader = page.get_by_role("dialog", name="论文阅读器", exact=True)
                expect(reader).to_be_visible()
                reader.get_by_role("button", name="问答", exact=True).click()
                prompt = reader.get_by_role("textbox", name="给Aster的任务", exact=True)
                expect(prompt).to_be_visible()
                try:
                    page.wait_for_function(
                        'document.querySelector(".textLayer")?.querySelectorAll("span").length > 0',
                        timeout=20000,
                    )
                except Exception:
                    page.screenshot(path=str(output / "failure.png"))
                    print(
                        "ERRORS",
                        errors,
                        "BODY",
                        page.locator("body").inner_text()[-2500:],
                        flush=True,
                    )
                    raise
                page.screenshot(path=str(output / "reader-pdf.png"))
                # Selectable text must line up with the painted PDF, not just exist in the DOM.
                assert page.evaluate("""() => {
                    const span=[...document.querySelectorAll('.textLayer span')].find(e=>e.textContent.includes('pooled'));
                    const text=span.getBoundingClientRect(), sheet=document.querySelector('.pdf-sheet canvas').getBoundingClientRect();
                    return text.width > 100 && text.height > 8 && text.left >= sheet.left && text.right <= sheet.right + 2;
                }"""), "PDF text layer is not aligned"
                # Select actual PDF text, anchor it to the immutable backend text, add a comment.
                select_excerpt = """() => {
                    const span = [...document.querySelectorAll('.textLayer span')]
                        .find(element => element.textContent.includes('pooled'));
                    const range = document.createRange();
                    range.selectNodeContents(span);
                    const selection = getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                    span.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                }"""
                page.evaluate(select_excerpt)
                selection = reader.get_by_role("region", name="选段操作")
                selection.get_by_role("button", name="询问选段", exact=True).click()
                expect(reader.get_by_role("button", name="发送任务", exact=True)).to_be_enabled()
                assert "pooled quality-control" in prompt.input_value()
                page.evaluate(select_excerpt)
                expect(selection).to_be_visible()
                page.get_by_label("标注评论", exact=True).fill("关注QC设计")
                page.get_by_role("region", name="选段操作").get_by_role(
                    "button", name="标注", exact=True
                ).click()
                expect(page.locator(".annotation-card")).to_have_count(1)
                page.get_by_role("button", name="加入笔记", exact=True).click()
                page.get_by_label("阅读笔记标题").fill("QC reading note")
                # Keep the cited quote and append an independent personal thought.
                editor = page.get_by_role("textbox", name="阅读笔记正文", exact=True)
                editor.click()
                editor.press("Control+End")
                editor.press("Enter")
                editor.press_sequentially("My hypothesis needs an independent validation.")
                page.get_by_role("button", name="保存笔记", exact=True).click()
                expect(page.locator(".reader-linked-note")).to_have_count(1)
                note = client.get(f"/api/projects/{project}/artifacts").json()[0]
                assert "[[S:" in note["version"]["content"], note["version"]["content"]
                assert page.locator("[data-reader-page]").count() == 2
                page.get_by_label("页码", exact=True).select_option("1")
                page.wait_for_function(
                    'document.querySelector(\'[data-reader-page="1"] .textLayer\')?.textContent.includes("synthetic")'
                )
                assert page.locator(".reading-scroll").evaluate(
                    "(element) => element.scrollTop > 100"
                ), "Reader did not scroll continuously"
                page.get_by_role("button", name="返回文献库", exact=True).click()
                expect(reader).not_to_be_visible()
                sidebar.get_by_role("button", name="文献阅读", exact=False).click()
                page.get_by_role("button", name="阅读", exact=True).click()
                expect(page.get_by_label("页码", exact=True)).to_have_value("1")
                page.wait_for_function("""() => {
                    const target = document.querySelector('[data-reader-page="1"]');
                    const container = document.querySelector('.reading-scroll');
                    if (!target || !container) return false;
                    const difference = target.getBoundingClientRect().top - container.getBoundingClientRect().top;
                    return difference >= -300 && difference <= 200;
                }""")
                page.get_by_role("button", name="返回文献库", exact=True).click()
                sidebar.get_by_role("button", name="笔记", exact=True).click()
                page.get_by_role("button", name="QC reading note", exact=False).click()
                page.get_by_role("button", name="Markdown 源文", exact=True).click(timeout=5000)
                page.get_by_role("textbox", name="正文源文", exact=True).fill(
                    f"## QC idea\n\n| condition | area |\n| --- | --- |\n| QC | 1.2300e-8 |\n\n[[S:{spans[0]['id']}]]"
                )
                page.get_by_role("button", name="Markdown 源文", exact=True).click(timeout=5000)
                expect(page.locator(".tiptap table")).to_be_visible()
                page.get_by_label("上传文档附件", exact=True).set_input_files([csv, image])
                expect(page.locator(".attachment")).to_have_count(2)
                page.get_by_role("button", name="保存", exact=True).click()
                expect(page.locator(".document-save-state")).to_contain_text(
                    "已保存", timeout=15000
                )
                note = client.get(f"/api/projects/{project}/artifacts").json()[0]
                assert (
                    "1.2300e-8" in note["version"]["content"]
                    and "[[S:" in note["version"]["content"]
                )
                page.get_by_role("button", name="查看数据", exact=True).click()
                expect(page.get_by_role("dialog", name="matrix.csv", exact=True)).to_be_visible()
                page.get_by_role("button", name="关闭", exact=True).click()
                page.screenshot(path=str(output / "document.png"))
                page.get_by_role("button", name="历史版本", exact=True).click()
                expect(page.get_by_role("dialog", name="历史版本", exact=True)).to_be_visible()
                page.get_by_role("button", name="关闭", exact=True).click()
                page.get_by_role("button", name="返回", exact=True).click()
                sidebar.get_by_role("button", name="实验记录", exact=True).click()
                page.get_by_role("button", name="新建实验记录", exact=True).click()
                page.get_by_label("标题", exact=True).fill("QC experiment log")
                page.get_by_role("textbox", name="正文", exact=True).fill(
                    "Personal experimental design, not an executed experiment."
                )
                page.get_by_role("button", name="保存", exact=True).click()
                expect(page.locator(".document-save-state")).to_contain_text(
                    "已保存", timeout=15000
                )
                page.get_by_role("button", name="返回", exact=True).click()
                expect(
                    page.get_by_role("button", name="QC experiment log", exact=False)
                ).to_be_visible()
                page.get_by_role("button", name="方案与结果", exact=True).click()
                page.get_by_role("button", name="新建方案", exact=True).click()
                page.get_by_label("方案名称", exact=True).fill("QC protocol")
                page.get_by_role("textbox", name="实验方案正文", exact=True).fill(
                    "Compare pooled QC across fixed batch conditions."
                )
                page.get_by_role("button", name="保存方案", exact=True).click()
                expect(page.get_by_role("heading", name="QC protocol", exact=True)).to_be_visible()
                page.get_by_role("button", name="记录结果", exact=True).click()
                page.get_by_role("textbox", name="实验结果正文", exact=True).fill(
                    "Synthetic browser fixture: no scientific experiment was performed."
                )
                page.get_by_role("button", name="保存结果", exact=True).click()
                expect(
                    page.get_by_role("dialog", name="记录实验结果", exact=True)
                ).not_to_be_visible()
                expect(page.get_by_text("1 次执行记录", exact=True)).to_be_visible()
                experiments = client.get(f"/api/projects/{project}/experiments").json()
                assert (
                    len(experiments[0]["runs"]) == 1
                    and experiments[0]["runs"][0]["plan_version"] == 1
                )
                sidebar.get_by_role("button", name="论文写作", exact=True).click()
                page.get_by_role("button", name="新建文档", exact=True).click()
                page.get_by_label("标题", exact=True).fill("Discussion outline")
                page.get_by_role("textbox", name="正文", exact=True).fill(
                    "## Hypothesis\nA personal outline requiring evidence."
                )
                page.get_by_role("button", name="保存", exact=True).click()
                expect(page.locator(".document-save-state")).to_contain_text(
                    "已保存", timeout=15000
                )
                # Spreadsheet paste must keep string values without floating-point conversion.
                page.get_by_role("textbox", name="正文", exact=True).click()
                page.get_by_role("textbox", name="正文", exact=True).press("Control+End")
                page.evaluate(
                    """() => { const data=new DataTransfer(); data.setData('text/plain','condition\\tarea\\nQC\\t1.2300e-8'); document.querySelector('.tiptap').dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true})); }"""
                )
                expect(page.locator(".tiptap table")).to_be_visible()
                page.get_by_role("button", name="保存", exact=True).click()
                expect(page.locator(".document-save-state")).to_contain_text(
                    "已保存", timeout=15000
                )
                rows = client.get(f"/api/projects/{project}/artifacts").json()
                assert any(
                    row["kind"] == "draft" and "1.2300e-8" in row["version"]["content"]
                    for row in rows
                )
                # Backup includes reading state, annotation anchors, documents and attachments.
                archive = client.get(f"/api/projects/{project}/export")
                assert archive.is_success
                restored = client.post(
                    "/api/restore",
                    files={"file": ("backup.zip", archive.content, "application/zip")},
                )
                assert restored.status_code == 201, restored.text
                pid = restored.json()["id"]
                new_source = client.get(f"/api/projects/{pid}/sources").json()[0]
                assert (
                    len(
                        client.get(
                            f"/api/projects/{pid}/sources/{new_source['id']}/annotations"
                        ).json()
                    )
                    == 1
                )
                for width in [1512, 1000, 760, 390, 320]:
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_timeout(150)
                    close_assistant = page.get_by_role("button", name="关闭助手", exact=True)
                    if close_assistant.is_visible():
                        close_assistant.click()
                    if width <= 760:
                        assert page.locator(".sidebar").evaluate(
                            "(element) => element.clientWidth >= innerWidth - 2"
                        ), "PDF styles leaked into navigation"
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth + 1"
                    ), f"document overflow at {width}"
                page.screenshot(path=str(output / "document-mobile.png"), full_page=True)
                page.get_by_role("button", name="返回", exact=True).click()
                sidebar.get_by_role("button", name="文献阅读", exact=False).click()
                page.get_by_role("button", name="阅读", exact=True).click()
                expect(page.get_by_role("dialog", name="论文阅读器")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                page.screenshot(path=str(output / "reader-mobile.png"))
                page.set_viewport_size({"width": 1512, "height": 1000})
                page.get_by_role("button", name="返回文献库", exact=True).click()
                page.get_by_role("button", name="编辑资料 Reader fixture", exact=True).click()
                page.get_by_label("标题", exact=True).fill("Renamed paper")
                page.get_by_role("button", name="保存资料", exact=True).click()
                expect(
                    page.locator(".library-title").filter(has_text="Renamed paper")
                ).to_be_visible()
                page.get_by_role("button", name="编辑资料 Renamed paper", exact=True).click()
                page.get_by_role("button", name="删除资料", exact=True).click()
                page.get_by_role("button", name="确认删除", exact=True).click()
                expect(page.get_by_role("button", name="阅读", exact=True)).to_have_count(0)
                sidebar.get_by_role("button", name="回收站", exact=True).click()
                trash = page.get_by_role("dialog", name="回收站", exact=True)
                trash.get_by_role("button", name="恢复", exact=True).click()
                expect(trash.locator(".trash-row")).to_have_count(0)
                trash.get_by_role("button", name="关闭", exact=True).click()
                expect(page.get_by_role("button", name="阅读", exact=True)).to_have_count(1)
                sidebar.get_by_role("button", name="论文写作", exact=True).click()
                page.get_by_role("button", name="Discussion outline", exact=False).click()
                page.get_by_role("button", name="删除文档", exact=True).click()
                page.get_by_role("button", name="确认删除", exact=True).click()
                expect(
                    page.get_by_role("button", name="Discussion outline", exact=False)
                ).to_have_count(0)
                sidebar.get_by_role("button", name="回收站", exact=True).click()
                trash.get_by_role("button", name="恢复", exact=True).click()
                expect(trash.locator(".trash-row")).to_have_count(0)
                trash.get_by_role("button", name="关闭", exact=True).click()
                expect(
                    page.get_by_role("button", name="Discussion outline", exact=False)
                ).to_be_visible()
                sidebar.get_by_role("button", name="实验记录", exact=True).click()
                page.get_by_role("button", name="方案与结果", exact=True).click()
                page.get_by_role("button", name="编辑结果", exact=False).click()
                page.get_by_label("实际条件与偏离", exact=True).fill(
                    "Corrected browser fixture conditions"
                )
                page.get_by_role("button", name="保存结果", exact=True).click()
                expect(
                    page.get_by_role("dialog", name="编辑实验结果", exact=True)
                ).not_to_be_visible()
                assert (
                    client.get(f"/api/projects/{project}/experiments").json()[0]["runs"][0][
                        "conditions"
                    ]
                    == "Corrected browser fixture conditions"
                )
                sidebar.get_by_role("button", name="项目概览", exact=True).click()
                page.get_by_role("button", name="编辑项目", exact=True).click()
                page.get_by_role("button", name="删除项目", exact=True).click()
                page.get_by_role("button", name="确认删除", exact=True).click()
                expect(page.get_by_role("dialog", name="编辑项目", exact=True)).not_to_be_visible()
                assert all(row["id"] != project for row in client.get("/api/projects").json())
                sidebar.get_by_role("button", name="回收站", exact=True).click()
                trash.locator(".trash-row").filter(has_text="Browser research").get_by_role(
                    "button", name="恢复", exact=True
                ).click()
                expect(trash.locator(".trash-row")).to_have_count(0)
                assert any(row["id"] == project for row in client.get("/api/projects").json())
                assert not errors, errors
                browser.close()
                print(
                    json.dumps(
                        {
                            "browser": "passed",
                            "screenshots": str(output),
                            "widths": [1512, 1000, 760, 390, 320],
                        }
                    )
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
            client.close()
            log.close()


if __name__ == "__main__":
    main()
