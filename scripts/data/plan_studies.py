"""Collect three small official processed matrices and draft reproducible study plans."""

import csv
import io
import json
from pathlib import Path

from sqlalchemy import select
from aster.data.sources import PublicClient, save_json, sha, MW
from aster.storage.database import Database
from aster.domain.models import AppSetting, SourceSpan
from aster.domain.service import Service
from aster.app.settings import Settings


def main():
    directory = Path(".local/metabolomics")
    imported = json.loads((directory / "imported.json").read_text())
    origin = imported["studies"]
    project = origin["project_id"]
    settings = Settings.from_env()
    db = Database(settings.database_url, settings.data_dir)
    db.migrate()
    service = Service(db)
    key = "aster:study-plans:v1"
    with db.session() as session:
        if session.get(AppSetting, key):
            print("Existing plans preserved")
            return
    studies = json.loads((directory / "studies/manifest.json").read_text())["studies"]
    # Repair canonical URLs: the prefix summary API can echo its prefix in study_url.
    changed = False
    for entry in studies:
        if entry["repository"] != "Metabolomics Workbench":
            continue
        correct = f"https://www.metabolomicsworkbench.org/data/DRCCMetadata.php?StudyID={entry['accession']}"
        old = entry["url"]
        entry["url"] = correct
        origin["sources"][entry["accession"]]["url"] = correct
        if old != correct:
            source = origin["sources"][entry["accession"]]
            pages = service.source_pages(project, source["source_id"])
            content = "".join(page["text"] for page in pages["pages"]).replace(old, correct)
            new = service.import_source(
                project, entry["accession"] + ".md", content.encode(), source_id=source["source_id"]
            )
            source["version_id"] = new["version_id"]
            changed = True
        copy = {k: v for k, v in entry.items() if k not in {"metadata_file", "sha256"}}
        save_json(directory / "studies" / entry["metadata_file"], copy)
        entry["sha256"] = sha((directory / "studies" / entry["metadata_file"]).read_bytes())
    if changed:
        with db.session() as session:
            session.merge(AppSetting(key="aster:collection:studies:v1", value=origin))
        imported["studies"] = origin
        save_json(directory / "imported.json", imported)
        manifest = json.loads((directory / "studies/manifest.json").read_text())
        manifest["studies"] = studies
        save_json(directory / "studies/manifest.json", manifest)
    selected = [
        row
        for row in studies
        if row["repository"] == "Metabolomics Workbench"
        and row["accession"] in {"ST000001", "ST000002", "ST000003"}
    ]
    client = PublicClient()
    matrices = []
    try:
        for study in selected:
            accession = study["accession"]
            raw = client.get(f"{MW}/study/study_id/{accession}/data").content
            rows = json.loads(raw)
            rows = list(rows.values()) if isinstance(rows, dict) else rows
            measurements = [
                row for row in rows if isinstance(row, dict) and isinstance(row.get("DATA"), dict)
            ]
            if not measurements:
                continue
            samples = list(dict.fromkeys(sample for row in measurements for sample in row["DATA"]))
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["analysis_id", "metabolite_id", "metabolite_name", "units", *samples])
            for row in measurements:
                writer.writerow(
                    [
                        row.get(k, "")
                        for k in ["analysis_id", "metabolite_id", "metabolite_name", "units"]
                    ]
                    + [row["DATA"].get(sample, "") for sample in samples]
                )
            matrix = out.getvalue().encode("utf-8-sig")
            data_dir = directory / "processed"
            data_dir.mkdir(exist_ok=True)
            (data_dir / f"{accession}.json").write_bytes(raw)
            (data_dir / f"{accession}.csv").write_bytes(matrix)
            original = service.add_asset(project, f"{accession}.json", raw, "application/json")
            csv_asset = service.add_asset(project, f"{accession}.csv", matrix, "text/csv")
            with db.session() as session:
                span = session.scalar(
                    select(SourceSpan)
                    .where(
                        SourceSpan.source_version_id == origin["sources"][accession]["version_id"]
                    )
                    .order_by(SourceSpan.page)
                )
                citation = f"[[S:{span.id}]]"
            content = f"# {accession}: official processed matrix\n\n{study['title']}\n\nSource: {MW}/study/study_id/{accession}/data\nLicense: {study['license']}\n\n矩阵含 {len(measurements)} 行代谢物/分析记录、{len(samples)} 个样本列；行不一定代表独立鉴定化合物。来自官方处理数据，不是本项目新做的实验结果。未重新处理原始质谱。{citation}\n\n原始 JSON SHA256: {sha(raw)}\nCSV SHA256: {sha(matrix)}"
            record = service.save_record(
                project,
                title=f"{accession} · processed matrix",
                kind="report",
                content=content,
                asset_ids=[original["id"], csv_asset["id"]],
                author="assistant",
            )
            matrices.append(
                {
                    "accession": accession,
                    "features": len(measurements),
                    "samples": len(samples),
                    "sha256": sha(raw),
                    "record_id": record["id"],
                    "record_version_id": record["version"]["id"],
                    "url": study["url"],
                    "license": study["license"],
                }
            )
            print("MATRIX", accession, len(measurements), len(samples), flush=True)
    finally:
        client.client.close()
    plans = [
        (
            "归一化方法敏感性",
            "比较同一公开矩阵在不归一化、TIC、中位数和PQN处理下的变化。",
            "不同归一化假设会改变分布和部分效应估计，需同时保留生物分组信息与方法限制。",
            "固定原始矩阵、样本顺序、缺失值规则及随机种子；只改变归一化方法。",
            "不归一化作为基线；不得把生物学对照样本自动认定为技术QC。",
            "核对数据与分组→保留原始数值副本→固定预处理→并行四种归一化→检查分布、组内离散及效应方向→导出逐样本结果与参数。若无技术QC，不计算或宣称QC-RSD。",
            "样本保留率、缺失率、稳健离散指标、效应方向稳定性；技术QC指标仅在标签明确时计算。",
        ),
        (
            "缺失值填补稳健性",
            "在真实已观测条目上人工遮蔽，比较填补方法的重建误差。",
            "不同缺失机制和遮蔽比例下，填补方法的稳定性可能不同；随机遮蔽结果不代表真实删失机制。",
            "固定矩阵和种子，设置5%、10%、20%观测值遮蔽；比较训练集内中位数、半最小值及KNN。",
            "未遮蔽观测值作为重建参考；原始缺失条目不能作为已知真值；按样本划分后拟合填补器。",
            "识别原始缺失定义→划分样本→在有效观测单元遮蔽→仅用训练部分拟合→重复多次→按分组和丰度层报告误差与失败例。",
            "RMSE、MAE、丰度分层误差、下游效应方向变化、失败比例；报告均值与不确定性。",
        ),
        (
            "MetaboLights 原始数据复现",
            "选一项具有公开协议和可用开放格式谱图的研究，复现峰检测与质量控制。",
            "元数据完整性与参数选择会影响可恢复的峰和最终特征表，应在相同数据和条件下比较。",
            "固定研究编号、文件哈希、样本清单、软件版本和参数；单因素改变峰检测或分割设置。",
            "保留未分割基线与参数对照；人工区域标注需要另行建立，不能用作者检出表代替原始处理。",
            "核对MetaboLights协议/样本/assay表→盘点原始文件格式与体积→先选少量明确标注样本下载→转换开放格式（如需）→执行固定版本处理→核对EIC及失败区间→保留日志和参数。未下载或未执行的步骤保持待开始。",
            "可读文件比例、有效扫描数、特征数、保留时间漂移；仅在提供独立标注时计算标记区域恢复率。",
        ),
    ]
    created = []
    references = "\n".join(
        f"- {row['accession']}: {row['url']} (matrix {row['features']} rows × {row['samples']} samples) [[V:{row['record_version_id']}]]"
        for row in matrices
    )
    mtbls = [
        row
        for row in studies
        if row["repository"] == "MetaboLights"
        and (
            "spectrom" in json.dumps(row["detail"]).lower()
            or "mass" in json.dumps(row["detail"]).lower()
        )
    ][:5]
    references += "\n" + "\n".join(
        f"- {row['accession']}: {row['url']} (metadata only; raw files pending)" for row in mtbls
    )
    for title, question, hypothesis, variables, controls, procedure, metrics in plans:
        fields = {
            "question": question,
            "hypothesis": hypothesis,
            "variables": variables,
            "controls": controls,
            "procedure": procedure,
            "metrics": metrics,
            "provenance": "assistant proposal based on public study metadata; no experiment executed",
        }
        content = (
            "\n\n".join([f"## {key}\n{value}" for key, value in fields.items()])
            + "\n\n## Sources\n"
            + references
        )
        result = service.save_experiment(project, title, content, fields, author="assistant")
        created.append(result["id"])
    output = {
        "matrices": matrices,
        "experiment_ids": created,
        "status": "draft_plans_only; no reanalysis performed",
    }
    save_json(directory / "experiment-plan.json", output)
    with db.session() as session:
        session.merge(AppSetting(key=key, value=output))
    Path("docs/EXPERIMENT_PLAN.md").write_text(
        "# Public study experiments\n\n三个方案已保存至 Public Studies 项目的实验记录，均为待执行草稿。原始官方处理矩阵保存在 `.local/metabolomics/processed`，可从该项目的报告附件下载。\n\n"
        + "\n\n".join(f"## {row[0]}\n\n" + "\n\n".join(row[1:]) for row in plans)
        + "\n\n## Sources\n\n"
        + references
        + "\n"
    )
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
