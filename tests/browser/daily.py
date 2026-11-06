"""Daily workflows with synthetic documents, isolated database and no model calls."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    root = Path(__file__).resolve().parents[2]
    output = root / ".local/daily-assistant-2026-11-06/browser"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aster-daily-browser-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        address = f"http://127.0.0.1:{port}"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ASTER_", "ZHIXU_"))}
        env.update(
            ASTER_DATA_DIR=directory,
            ASTER_DATABASE_URL=f"sqlite:///{directory}/test.db",
            ASTER_RETRIEVAL_MODE="lexical",
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
                with httpx.Client(base_url=address + "/api", trust_env=False, timeout=20) as client:
                    for _ in range(100):
                        try:
                            if client.get("/health").is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    pid = client.post(
                        "/projects", json={"title": "Daily research fixtures"}
                    ).json()["id"]
                    base = f"/projects/{pid}"
                    source = client.post(
                        base + "/sources",
                        data={"title": "Synthetic methods"},
                        files={
                            "file": (
                                "method.txt",
                                b"Synthetic document. Pooled QC for browser testing only.",
                                "text/plain",
                            )
                        },
                    ).json()
                    linked = client.post(
                        base + "/artifacts",
                        json={"title": "Earlier idea", "content": "Synthetic research idea."},
                    ).json()
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
                        sidebar = page.locator(".sidebar")
                        sidebar.get_by_role("button", name="设置", exact=False).click()
                        page.get_by_role("button", name="添加模型", exact=True).click()
                        page.get_by_label("配置名称", exact=True).fill("Reading fixture API")
                        page.get_by_label("模型名称", exact=True).fill("synthetic-reader")
                        page.get_by_label("API 地址", exact=True).fill("http://127.0.0.1:1/v1")
                        page.get_by_label("API Key", exact=True).fill("synthetic-key")
                        page.get_by_role("button", name="保存配置", exact=True).click()
                        expect(page.get_by_text("模型配置已保存", exact=True)).to_be_visible()
                        profile = client.get("/models/profiles").json()["profiles"][-1]
                        page.get_by_label("PDF 问答默认模型").select_option(profile["id"])
                        page.get_by_role("tab", name="Skills", exact=True).click()
                        expect(page.locator(".skill-card")).to_have_count(7)
                        page.get_by_role("button", name="新建", exact=True).click()
                        dialog = page.get_by_role("dialog")
                        dialog.get_by_label("名称", exact=True).fill("Personal review")
                        dialog.get_by_label("用途", exact=True).fill("Synthetic test workflow")
                        dialog.get_by_label("技能指令", exact=True).fill(
                            "Read the selected evidence and list open questions."
                        )
                        dialog.get_by_role("button", name="保存 Skill", exact=True).click()
                        expect(page.locator(".skill-card")).to_have_count(8)
                        page.screenshot(path=str(output / "skills.png"))
                        sidebar.get_by_role("button", name="项目概览", exact=False).click()
                        page.get_by_role("button", name="编辑项目", exact=True).click()
                        page.get_by_label("知识库主题", exact=True).fill("Custom mass spectrometry")
                        page.get_by_text("术语与助手偏好", exact=True).click()
                        page.get_by_label("知识库术语", exact=True).fill("QC = quality control")
                        page.get_by_role("button", name="保存项目", exact=True).click()
                        expect(page.get_by_role("dialog")).to_have_count(0)
                        assert (
                            client.get("/projects").json()[0]["knowledge"]["subject"]
                            == "Custom mass spectrometry"
                        )
                        sidebar.get_by_role("button", name="笔记", exact=True).click()
                        page.get_by_role("button", name="组会记录", exact=False).click()
                        page.get_by_label("标题", exact=True).fill("Group meeting")
                        expect(
                            page.get_by_role("textbox", name="正文", exact=True).locator("table")
                        ).to_have_count(1)
                        page.get_by_role("button", name="文档属性", exact=True).click()
                        page.get_by_label("文档标签", exact=True).fill("QC, meeting")
                        page.get_by_label("置顶", exact=True).check()
                        page.get_by_label("关联文献", exact=True).select_option(source["id"])
                        page.get_by_label("添加关联文档", exact=True).select_option(linked["id"])
                        page.locator(".related-document").get_by_role(
                            "button", name="引用", exact=True
                        ).click()
                        editor = page.get_by_role("textbox", name="正文", exact=True)
                        editor.click()
                        editor.press("Control+End")
                        editor.press("Enter")
                        page.get_by_role("button", name="任务清单", exact=True).click()
                        page.keyboard.type("Review QC design")
                        page.get_by_role("button", name="Markdown 源文", exact=True).click()
                        source_text = page.get_by_label("正文源文", exact=True)
                        source_text.fill(source_text.input_value() + "\n\n$$x^2 + y^2$$\n")
                        page.get_by_role("button", name="保存", exact=True).click()
                        expect(page.get_by_text("未保存", exact=True)).to_have_count(0)
                        page.get_by_role("button", name="预览", exact=True).click()
                        expect(page.locator(".document-sheet .katex")).to_have_count(1)
                        expect(page.locator(".document-sheet .citation")).to_have_count(1)
                        page.screenshot(path=str(output / "document.png"))
                        page.get_by_role("button", name="返回", exact=True).click()
                        note = next(
                            r
                            for r in client.get(base + "/artifacts").json()
                            if r["title"] == "Group meeting"
                        )
                        assert note["version"]["fields"]["note_type"] == "meeting"
                        assert note["version"]["fields"]["tags"] == ["QC", "meeting"]
                        assert note["version"]["fields"]["pinned"]
                        assert note["version"]["fields"]["related_record_ids"] == [linked["id"]]
                        (output / "note.json").write_text(
                            __import__("json").dumps(note, ensure_ascii=False, indent=2)
                        )
                        assert "- [ ] Review QC design" in note["version"]["content"], note[
                            "version"
                        ]["content"]
                        page.get_by_label("笔记类型", exact=True).select_option("meeting")
                        page.get_by_label("笔记标签", exact=True).select_option("QC")
                        page.get_by_role("button", name="列表视图", exact=True).click()
                        expect(page.locator(".note-card")).to_have_count(1)
                        for width in [1512, 1024, 390, 320]:
                            page.set_viewport_size({"width": width, "height": 1000})
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= innerWidth + 1"
                            ), width
                            page.screenshot(path=str(output / f"notes-{width}.png"))
                        page.set_viewport_size({"width": 1512, "height": 1000})
                        sidebar.get_by_role("button", name="文献阅读", exact=False).click()
                        page.get_by_role("button", name="阅读", exact=True).click()
                        page.get_by_role("button", name="问答", exact=True).click()
                        expect(page.get_by_label("PDF 问答模型", exact=True)).to_contain_text(
                            "Reading fixture API"
                        )
                        expect(
                            page.get_by_role("dialog", name="论文阅读器").get_by_label(
                                "助手 Skill", exact=True
                            )
                        ).to_contain_text("Personal review")
                        assert not errors, errors
                        browser.close()
                        print("Daily browser workflows passed:", output)
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
