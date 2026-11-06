# Aster

科研资料与个人研究记录平台，基于 mini-harness。默认使用本地 Qwen，也可配置模型 API 或 Codex CLI。

[快速上手与本机数据位置](docs/WEB_GUIDE.md#快速上手) · [实验指南](docs/EXPERIMENTS.md)

## 简历描述

**Aster：科研知识管理与多轮检索问答平台｜主要完成人**

**技术栈：** Python、mini-harness、Qwen、FastAPI、Pydantic、BGE-M3、FAISS、BM25、RRF、Cross-Encoder、SQLAlchemy / Alembic、SQLite / PostgreSQL、React / TypeScript、Tiptap、PDF.js。

面向代谢组学文献阅读、研究思路记录与证据问答，构建集论文库、原文标注、个人文档、实验记录及多轮问答于一体的平台。

- **知识库与检索：** 采集300篇开放论文的原始PDF与XML全文，以XML形成19,250个保留来源、章节与版本的分块；采用BGE-M3 / FAISS与BM25双路召回、RRF融合、Cross-Encoder重排，封装`search_papers`、`read_chunk`。另整理202项公开研究元数据和3份官方处理矩阵。
- **Agent：** 基于mini-harness构建日常助手，将混合检索、原文读取、文献目录与技能加载封装为受限工具，按问题需要调用；支持独立配置科研问答与PDF问答模型。另保留七阶段RAG实验流程，通过Pydantic校验意图、改写、证据充分性及主张引用，用于组件评测与消融。
- **科研记录：** 实现PDF / 文本连续阅读、版本化摘录标注、多类型笔记、标签/分类/置顶、文档关联与反向关联、富文本表格/清单、公式预览及实验记录；补齐资料增删改查、回收站、历史版本与备份。知识库主题、术语和回答偏好可自定义；内置7个科研技能，支持导入指令型SKILL.md。
- **追踪与记忆：** 引入AgentState与Turn / Stage追踪，保存输入输出、工具调用、状态、耗时和用量；维护研究对象、逐字约束、问题与引用的会话快照，支持规则压缩及`/trace`、`/corpus`、`/memory`诊断命令。
- **评测：** 构建100意图、40改写、100检索、55边界、30组四轮对话及70-turn端到端子集，完成四组检索对照和去改写、去Reflect、去重排、去记忆消融。草案题集上，混合重排Recall@5为80.75%，较混合召回提高22.75个百分点；70-turn工程流程成功率为77.14%。

指标来自作者/模型辅助草案，尚待独立人工复核；工程成功率不等同科研答案准确率。生成模型未微调；FAISS使用精确IndexFlatIP，BGE-M3只使用dense输出。完整口径与SWE-bench单题结果见实验指南。

## 代码分层

```text
src/
  mini_harness/          底层模型与工具循环、重试、上下文压缩
  aster/
    app/                CLI、配置、任务队列、API启动
      routes/           项目、文献、文档、会话、诊断接口
    domain/             数据模型、输入契约、记录与阅读业务
    agent/              日常助手、技能；独立七阶段实验、记忆与追踪
    models/             多模型配置、密钥隔离、API与Codex适配
    retrieval/          分块、证据快照、混合检索与重排
    data/               公开资料采集与导入
    storage/            数据库、迁移、项目备份恢复
    evaluation/         问答评测、消融与基准结果读取
web/src/
  features/             library、documents、experiments、assistant等功能
  layout/               导航与布局
  shared/               API类型、通用界面、引用与附件
  styles/               基础与功能样式
scripts/                 data、evaluation、bench、server
tests/                  unit、integration、browser、live
```

Web提供日常工具；记忆、追踪、评测与SWE-bench保留在后端和CLI。`mini-harness`是底座，模型可切换；`openai`包连接兼容API，`models/codex.py`调用已登录的本机Codex CLI，业务工具仍由Aster执行。

七阶段编排是本项目的`ResearchPipeline`实现；`Generate`阶段调用mini-harness的模型与工具循环。SWE-bench直接调用mini-harness编码循环。

## 代码学习路线

| 顺序 | 入口 | 要看懂什么 |
| --- | --- | --- |
| 1 | `app/routes/conversations.py` → `app/runtime.py:create` | 请求如何排队、固定资料版本并创建对话 |
| 2 | `agent/assistant.py:DailyAssistant.run` → `mini_harness/agent.py:_run_turn` | 日常助手如何自主调用检索、读取与技能工具 |
| 3 | `agent/llm.py`、`retrieval/corpus.py` | 查询结构、允许证据、分块与引用ID |
| 4 | `retrieval/engine.py:Retriever.search` | BM25、dense、RRF与重排各负责什么 |
| 5 | `models/profiles.py`、`clients.py`、`codex.py` | 默认模型、读PDF独立模型、凭据与接入方式 |
| 6 | `agent/state.py`、`memory.py`、`trace.py` | 单轮状态、跨轮记忆和执行记录的区别 |
| 7 | `domain/reading.py`、`management.py`、`service.py`、`storage/archive.py` | 标注锚点、版本、回收站与备份关联 |
| 8 | `web/src/features/library/`、`documents/` | 阅读器、文档编辑、自动保存与表格 |
| 9 | `agent/pipeline.py`、`generation.py`、`evaluation/suite.py` | 实验流程的结构化输出、主张审核和消融；旧成绩只属于此流程 |

练习：空库先讨论一个想法；导入论文后询问具体方法，再追问局限。运行`aster trace RUN_ID`，沿`question → snapshot → tool_calls → evidence → answer → memory`对应代码。研究实验另看`plan → hits → decision → claims`。

三条业务链：

- **导入与阅读：** `routes/library.py → Service.import_source`保存文件、原文版本与页/段；`Corpus.ensure_chunks`按需创建分块，`ReadingLibrary`保存阅读位置和标注。
- **记录：** `DocumentEditor → routes/documents.py → Service.save_record`新增不可变版本；引用绑定原文或记录版本，后续编辑不会覆盖旧依据。
- **问答：** `Assistant → routes/conversations.py → RunManager → DailyAssistant → MiniHarnessAgent → 模型`，模型按需调用`search_knowledge → Retriever`。`engine=pipeline`才进入独立的ResearchPipeline；评测入口显式固定此值。

参考：底座[mini-harness](https://github.com/mini-harness/mini-harness)；阅读交互[NeoRead](https://github.com/cynicalight/NeoRead)、[Readest](https://github.com/readest/readest)；技能方法对照[K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)。内置技能为Aster编写的适配工作流，不包含上游的分析脚本或外部数据库客户端。
