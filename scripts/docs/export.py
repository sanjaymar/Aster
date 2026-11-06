"""Export README as the illustrated learning guide. Requires pandoc and Playwright.

Run: uv run --with playwright python scripts/docs/export.py
Only generated files under data/cache/guide and data/exports are written.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
ET.register_namespace("w", W)


def element(parent, name, **attrs):
    node = parent.find(f"w:{name}", NS)
    if node is None:
        node = ET.SubElement(parent, f"{{{W}}}{name}")
    for key, value in attrs.items():
        node.set(f"{{{W}}}{key}", str(value))
    return node


def style_word(path):
    """Use explicit CJK fonts, A4 margins and compact, non-splitting table rows."""
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    styles = ET.fromstring(files["word/styles.xml"])
    sizes = {"Title": 44, "Subtitle": 24, "Heading1": 32, "Heading2": 26,
             "Heading3": 23, "SourceCode": 17, "VerbatimChar": 18}
    for style in styles.findall("w:style", NS):
        name = style.get(f"{{{W}}}styleId", "")
        run = element(style, "rPr")
        font = "DejaVu Sans Mono" if name in {"SourceCode", "VerbatimChar"} else "Noto Sans CJK SC"
        element(run, "rFonts", ascii=font, hAnsi=font, eastAsia="Noto Sans CJK SC")
        element(run, "sz", val=sizes.get(name, 21))
        element(run, "szCs", val=sizes.get(name, 21))
        element(run, "lang", val="zh-CN", eastAsia="zh-CN")
        para = element(style, "pPr")
        element(para, "spacing", after=120, line=285, lineRule="auto")
        element(para, "keepLines")
        if name.startswith("Heading") or name == "Title":
            element(run, "color", val="183E77")
            element(para, "keepNext")
            element(para, "spacing", before=240, after=120)
    files["word/styles.xml"] = ET.tostring(styles, encoding="utf-8", xml_declaration=True)

    doc = ET.fromstring(files["word/document.xml"])
    section = doc.find(".//w:sectPr", NS)
    element(section, "pgSz", w=11906, h=16838)
    element(section, "pgMar", top=1050, right=1100, bottom=1050, left=1100)
    for table in doc.findall(".//w:tbl", NS):
        props = element(table, "tblPr")
        element(props, "tblW", type="dxa", w=9706)
        element(props, "tblLayout", type="fixed")
        margins = element(props, "tblCellMar")
        for side in ("top", "bottom", "left", "right"):
            element(margins, side, type="dxa", w=85)
        rows = table.findall("w:tr", NS)
        cols = len(rows[0].findall("w:tc", NS))
        weights = {2: [0.45, 0.55], 3: [0.22, 0.41, 0.37]}.get(cols, [1 / cols] * cols)
        widths = [round(9706 * weight) for weight in weights]
        widths[-1] += 9706 - sum(widths)
        grid = element(table, "tblGrid")
        grid.clear()
        for width in widths:
            ET.SubElement(grid, f"{{{W}}}gridCol", {f"{{{W}}}w": str(width)})
        for index, row in enumerate(rows):
            element(element(row, "trPr"), "cantSplit")
            if index == 0:
                element(element(row, "trPr"), "tblHeader")
            for col, cell in enumerate(row.findall("w:tc", NS)):
                element(element(cell, "tcPr"), "tcW", type="dxa", w=widths[col])
                if index == 0:
                    element(element(cell, "tcPr"), "shd", fill="EDF3FA")
                for run in cell.findall(".//w:r", NS):
                    element(element(run, "rPr"), "sz", val=18)
                    element(element(run, "rPr"), "szCs", val=18)
    files["word/document.xml"] = ET.tostring(doc, encoding="utf-8", xml_declaration=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def prepare_source(cache):
    content = (ROOT / "README.md").read_text(encoding="utf-8").removeprefix("# Aster\n")
    ast = json.loads(subprocess.check_output(
        ["pandoc", "--from=gfm", "--to=json"], input=content.encode()))
    checked = 0

    def walk(item):
        nonlocal checked
        if isinstance(item, list):
            for value in item:
                walk(value)
        elif isinstance(item, dict):
            if item.get("t") in {"Link", "Image"}:
                target = item["c"][-1][0]
                parsed = urlsplit(target)
                if not parsed.scheme and parsed.path:
                    path = ROOT / unquote(parsed.path)
                    if not path.is_file():
                        raise FileNotFoundError(f"README link: {target}")
                    checked += 1
                    item["c"][-1][0] = path.resolve().as_uri() + (
                        f"#{parsed.fragment}" if parsed.fragment else "")
            for value in item.values():
                walk(value)

    walk(ast)
    source = cache / "guide.json"
    source.write_text(json.dumps(ast, ensure_ascii=False), encoding="utf-8")
    return source, checked


async def print_pdf(html, destination):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=os.getenv("CHROME_BIN") or shutil.which("google-chrome")
        )
        try:
            page = await browser.new_page()
            await page.goto(html.as_uri(), wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
            invalid = await page.locator("img").evaluate_all(
                "images => images.filter(i => !i.complete || !i.naturalWidth).length")
            if invalid:
                raise RuntimeError("Export contains unloaded illustrations")
            await page.pdf(
                path=str(destination), format="A4", print_background=True,
                margin={"top": "16mm", "right": "18mm", "bottom": "19mm", "left": "18mm"},
                display_header_footer=True, header_template="<span></span>",
                footer_template='<div style="width:100%;text-align:center;font-size:9px;color:#777">'
                                'Aster · <span class="pageNumber"></span> / '
                                '<span class="totalPages"></span></div>',
            )
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/exports")
    args = parser.parse_args()
    if not shutil.which("pandoc"):
        raise SystemExit("Install pandoc before exporting the guide.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = ROOT / "data/cache/guide"
    cache.mkdir(parents=True, exist_ok=True)
    source, checked = prepare_source(cache)
    base = ["pandoc", str(source), "--from=json", "--standalone",
            "--metadata=title:Aster：技术方案与代码学习", "--metadata=lang:zh-CN"]
    docx, html, pdf = (output / f"guide.{extension}" for extension in ("docx", "html", "pdf"))
    subprocess.run([*base, "--to=docx", "-o", str(docx)], check=True, cwd=ROOT)
    style_word(docx)
    subprocess.run([*base, "--to=html5", "--self-contained", "--toc", "--toc-depth=2",
                    "--metadata=toc-title:阅读导航", "--css", str(Path(__file__).with_name("guide.css")),
                    "-o", str(html)], check=True, cwd=ROOT)
    asyncio.run(print_pdf(html, pdf))
    with ZipFile(docx) as archive:
        images = [name for name in archive.namelist() if name.startswith("word/media/")]
    if not images:
        raise RuntimeError("The Word guide has no embedded illustration")
    report = {"source": "README.md", "local_links_checked": checked,
              "embedded_images": len(images), "outputs": [str(p) for p in (pdf, docx, html)]}
    (cache / "check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
