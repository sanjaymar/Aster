# Web 使用指南

启动：`uv run aster`，访问 `http://127.0.0.1:8765`。[代码学习](../README.md#技术方案与代码学习) · [实验指南](EXPERIMENTS.md)

## 阅读、笔记与汇报

1. **导入论文：** 选择或新建知识库，导入 PDF／TXT／Markdown；可修改标题、作者、年份、DOI、标签、星标与阅读状态。
2. **阅读提问：** 打开 PDF 连续滚动，选中文字后点击“询问选段”。选择模型与工作方法，点击回答中的引用核对原文。
3. **记录笔记：** 手动新建，或选择论文自动生成精读／方法／对照笔记。生成后可继续编辑，支持表格、公式、图片、附件和引用；通过打印导出 PDF。
4. **制作汇报：** 选择论文与笔记，填写主题、听众和页数。逐页编辑标题、流程、表格、原图及讲稿，调整顺序后导出 PPTX；文字、流程框和表格可编辑。
5. **浏览地图：** 按主题、关键词与阅读状态筛选，查看摘要、相关论文和笔记，可直接进入阅读、笔记生成或汇报。资料变化后重新进入地图即可更新。

模型生成的事实和图表解释需要核对。地图表示文本相似关系；原文图版来自固定版本 PDF，自动提取不表示模型理解了图中曲线。

## 问答与工作方法

| 设置 | 用途 |
|---|---|
| 按需检索 | 根据问题选择搜索资料、使用选段或通用讨论 |
| 依据资料 | 要求原文证据；不足时补检索、澄清或拒答 |
| 不检索 | 使用已提供选段、对话和模型常识 |
| 模型 | 本地 Qwen、兼容 API 或已安装并登录的 Codex CLI |

在“设置与模型”配置阅读和普通问答的默认模型。长内容生成默认超时 600 秒，可调整；生成期间可以继续阅读。任务结束可能返回答案、澄清或拒答，只有产出成功才会新增笔记／汇报。

内置工作方法可查看、复制和修改，也可导入自定义 `SKILL.md`；作为指令使用，不自动执行附带脚本。整页生图 PPT 可下载 Codex 材料包，在配置了 `codex-ppt-skill` 与生图能力的环境中打开 `TASK.md`。

## 数据在哪里

默认使用启动目录下的 `data/`，可通过 `.env` 的 `ASTER_HOME` 修改。该目录不上传 Git。

```text
data/
  library/aster.db  论文文本、批注、笔记、汇报、会话与引用
  library/files/   原始 PDF、图片与附件
  library/imports/ 采集清单与来源材料
  models/          embedding 与 reranker
  cache/           索引、地图、预览；可重建
  exports/         PDF、PPTX、材料包与学习稿
  config/          模型密钥与检索服务配置
  logs/            应用日志
  experiments/     问答与 SWE-bench 实验
  archive/         历史材料与迁移快照
```

已配置的 API Key 保存在 `config/keys.json`，项目导出不包含密钥。文献数量与实验快照口径见 [README](../README.md#数据与评测)。

## 管理与备份

- 论文、笔记、汇报和会话可删除并从回收站恢复；重传论文产生新版本，旧引用保持不变。
- 文档保存检查版本，防止旧页面覆盖新内容。论文可能同时有结构化检索文本和原始 PDF；引用页码以实际取材版本为准。
- 项目概览“导出”下载 ZIP，“恢复项目备份”创建新项目并重映射引用。备份整个数据目录时，先停止应用或使用 SQLite backup API。
- 迁移旧目录：停止应用，运行 `uv run python scripts/data/migrate_storage.py --source 旧目录 --target ./data`；目标不能已有数据库，校验后设置 `ASTER_HOME=./data`。
- Docker 将项目 `data/` 挂载到容器 `/data`；使用 PostgreSQL 时配置 `ASTER_CONTAINER_DATABASE_URL`。

## 学习文档导出

README 是学习稿内容源。安装 Pandoc 与 Google Chrome／Playwright Chromium 后运行：

```sh
uv run --with playwright python scripts/docs/export.py
```

生成 `data/exports/guide.pdf`、`guide.docx`、`guide.html`。可用 `CHROME_BIN` 指定浏览器。`data/archive/guide/` 中的旧稿仅用于留档。
