# Aster

Aster 是一个本地运行的科研工作台。你可以导入论文、在 PDF 上标注与提问、核对回答的原文依据，再把阅读笔记、实验记录和写作草稿整理到同一个项目。

[使用指南](docs/WEB_GUIDE.md#文献阅读) · [实验与评测](docs/EXPERIMENTS.md) · [代码导览](#代码导览)

## 能做什么

| 功能 | 用法 |
| --- | --- |
| 文献阅读 | 导入 PDF、Markdown、TXT 或 CSV。阅读器提供目录、搜索、选段标注和阅读位置恢复。 |
| 有引用的问答 | 对当前论文选段提问，或在项目内跨论文和笔记检索。点击引用可查看对应的原文页、文本段或记录版本。 |
| 笔记与写作 | 用精读、组会、方法卡片和论文提纲等模板起草文档。支持 Markdown、表格、公式预览、附件和历史版本。 |
| 实验记录 | 记录方案、过程和结果，附上数据表与图。结果可关联实际使用的方案版本。 |
| 模型与技能 | 支持 OpenAI 兼容 API、OpenAI API 和本机 Codex CLI。项目问答和阅读器可分别选模型，内置科研技能可按需启用，也可导入 `SKILL.md`。 |

项目可自定义领域、术语和回答偏好。代谢组学是本仓库的示例研究领域。

## 快速开始

需要 Python 3.12+、uv 和 Node.js 22.13+。

```bash
git clone https://github.com/sanjaymar/Aster.git
cd Aster
uv sync --locked
npm ci --prefix web
npm run build --prefix web
uv run --locked aster
```

打开 [127.0.0.1:8765](http://127.0.0.1:8765)。首次启动时创建一个项目，然后导入一篇 PDF。仓库提供采集与导入脚本，论文由使用者导入或按实验指南获取。[数据准备](docs/EXPERIMENTS.md#数据与题集)

在「设置 → 模型」中配置生成服务。本地兼容接口默认是 `http://127.0.0.1:8000/v1`，例如已运行的 Qwen 服务。也可以填写远程 API，或选择已在本机登录的 Codex CLI。阅读、标注和编辑笔记可以独立使用。

### 第一次读论文

1. 打开一篇已导入的 PDF，选中一段方法文字，点击「询问选段」。
2. 问一个能核对的问题，例如「这段里的实验组和对照组分别有多少样本？」。
3. 点击回答中的引用，对照论文的页码和实验条件。
4. 点击「记笔记」，保存摘录、引用和核对后的理解。

### 启用混合检索

基础安装可用 BM25 关键词检索。要加入 BGE-M3 向量召回、FAISS 和 Cross-Encoder 重排，安装检索依赖并下载模型。

```bash
uv sync --locked --extra retrieval
uv run --locked --extra retrieval aster models --download
uv run --locked --extra retrieval aster
```

## 数据与运行方式

新安装默认将 SQLite 数据库、导入文件和索引放在 `.local/aster/`。可用 `ASTER_DATA_DIR` 指定目录，用 `ASTER_DATABASE_URL` 连接 PostgreSQL。项目概览提供 ZIP 导出和恢复，便于迁移论文、笔记、标注与附件。[数据与备份](docs/WEB_GUIDE.md#备份)

选择本地生成服务时，问答使用本机服务。选择远程 API 或 Codex 时，所选资料与会话上下文会交给对应的模型服务。扫描版 PDF 可以阅读原图，问答使用已提取的文字。

## 代码导览

前端使用 React、TypeScript、PDF.js 和 Tiptap。FastAPI 提供资料、记录和问答接口，SQLAlchemy 与 Alembic 管理存储和迁移。日常问答由 mini-harness 调用模型，并按需使用文献目录、检索、原文读取与技能工具。

| 想看什么 | 从哪里开始 |
| --- | --- |
| 选段如何成为一条问题 | [阅读器 `ask`](web/src/features/library/PaperReader.tsx#L360) → [问答 `submit`](web/src/features/assistant/Assistant.tsx#L242) |
| 模型能查哪些资料 | [创建任务与固定资料版本](src/aster/app/runtime.py#L119) → [日常助手与工具](src/aster/agent/assistant.py) |
| 检索如何找到证据 | [语料与分块](src/aster/retrieval/corpus.py) → [BM25、向量召回、RRF 和重排](src/aster/retrieval/engine.py) |
| 引用和笔记如何保存 | [引用按钮](web/src/shared/MarkdownView.tsx) → [记录与证据服务](src/aster/domain/service.py) |
| 模型调用与评测怎么跑 | [mini-harness 工具循环](src/mini_harness/agent.py) · [七阶段评测流程](src/aster/agent/pipeline.py) · [实验指南](docs/EXPERIMENTS.md) |

评测指南记录了代谢组学七阶段基线的题集、指标、消融和复跑命令。日常助手另有行为测试，SWE-bench 部分记录单题验证。[评测结果与口径](docs/EXPERIMENTS.md)

Aster 的工具循环基于 mini-harness。阅读交互参考 NeoRead 与 Readest，科研流程参考 K-Dense Scientific Agent Skills。[mini-harness](https://github.com/mini-harness/mini-harness) · [NeoRead](https://github.com/cynicalight/NeoRead) · [Readest](https://github.com/readest/readest) · [K-Dense](https://github.com/K-Dense-AI/scientific-agent-skills)
