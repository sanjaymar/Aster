# 实验指南

以下结果为2026-11-05七阶段资料问答基线（`engine=pipeline`）。题集由作者/模型辅助构造，尚待独立人工复核。Web现用按需检索的日常助手（`engine=assistant`），旧成绩不代表新助手效果。

命令均在项目根目录运行，先执行`source .venv/bin/activate`；首次安装见Web指南。

## 问答助手

### 数据与题集

300篇代谢组学开放全文，19,250块。基线使用Europe PMC XML文字版；现已补齐300份PMC官方PDF供阅读，默认检索仍固定XML版本，阅读器问答可固定PDF版本。默认检索顺序偏近期，未逐篇完成人工质量筛选。另有MetaboLights 102项、Workbench 100项研究元数据及3份官方处理矩阵，原始谱图未批量下载。

```sh
python -m aster.data.sources --papers 300 --studies 100 --ingest
python scripts/evaluation/build_dataset.py
python -m aster.data.originals --ingest
python scripts/data/audit_collection.py --online
```

缓存：`.local/metabolomics`；题集：其下`eval/`；导入映射：`imported.json`。采集按accession续跑，原文与导出文本有SHA256。全新克隆不自带论文。

| 题集 | 数量 | 参考标签 |
| --- | ---: | --- |
| 意图 | 100 | 六分类作者草案 |
| 改写 | 40 | 期望实体保留 |
| 检索 | 100 | 真实原文锚点弱标注 |
| 边界 | 55 | 越界、证据不足、歧义、要求编造引用 |
| 多轮 | 30×4=120 turn | 真实论文对的模板问题 |
| 端到端 | 70 turn | 上述120轮的子集，非额外样本 |
| 记忆 | 20对 | 合成长历史与压缩快照的NLU比较 |

### 执行

```sh
aster evaluate-suite --output .local/metabolomics/evaluation/new-run \
  --variants full,no-rewrite,no-reflect,no-rerank,no-memory
```

`--suites intent,rewrite`等可单独选择。相同输出目录会跳过已有结果，失败保留在分母；数据或模型变化时使用新目录。SQLite评测使用独立`evaluation.db`，不向个人对话写入评测问题。

多轮消融默认各12轮，Reflect边界消融20题；差异按相同case ID配对，不能直接减去120轮总平均。

本机可选GPU检索：

```sh
# 在已有CUDA Python环境启动；不要重启Qwen。
/data_hdd/msj/conda_envs/msj/bin/python scripts/server/retrieval.py --device cuda:1
export ASTER_RETRIEVAL_URL=http://127.0.0.1:8767
```

### 已完成结果

| 指标 | 结果 | 口径 |
| --- | ---: | --- |
| 意图分类 | 99/100 | 草案总体准确率 |
| 改写实体保留 | 40/40 | 非完整语义改写准确率 |
| 边界响应类型 | 52/55 | answer/refuse/clarify |
| 拒答 | 42/45 | 仅应拒答题 |
| 多轮工程成功 | 88/120 | 73.33% |
| 70-turn工程成功 | 54/70 | 77.14% |
| 压缩后实体一致 | 20/20 | NLU合成长历史 |
| 输入token降幅 | 73.75% | 仅NLU组件，非整个Agent |

| 检索策略 | Recall@5 | MRR@10 |
| --- | ---: | ---: |
| BM25 | 4.00% | 0.0372 |
| Dense | 64.50% | 0.5087 |
| Hybrid | 58.00% | 0.3844 |
| Hybrid + Rerank | 80.75% | 0.7871 |

中文问题配英文正文，相关块由所选来源的原文锚点定义，并未穷尽其他有效证据。混合召回低于dense；不能宣称所有指标都提高。

20条证据不足题：Reflect拒答率85%，去Reflect为25%。12轮多轮子集上，完整流程相对去改写/去重排/去记忆分别高33.33/25.00/8.33个百分点，相对去Reflect低16.67个百分点；小样本结果不能推广为普遍收益。

工程成功=完成任务+参考响应类型正确；应回答题还需有效引用及参考论文覆盖。引用有效与来源一致不等于人工语义引用准确率，后者暂为空。

结果：`.local/metabolomics/evaluation/{run-20261105,gpu-20261105}`；分享摘要：`eval/results/metabolomics-2026-11-05.json`。

```sh
python scripts/evaluation/citation_review.py \
  --report .local/metabolomics/evaluation/gpu-20261105/dialogues.json \
  --export .local/metabolomics/citation-review.csv
# 独立审阅claim/evidence，填写supported=yes/no/uncertain、reviewer、reason后：
python scripts/evaluation/citation_review.py --score .local/metabolomics/citation-review.csv
aster console --project PROJECT_ID
# /corpus、/memory [CONVERSATION_ID]、/trace RUN_ID
```

## SWE-bench Verified

入口`bench/adapter.py`，直接评测mini-harness编码工具循环，不经过科研七阶段，不在Web展示。

本机Qwen服务标识`qwen3.8-27b`，Q8_0，32768上下文，单推理槽。已完成环境修复后的新运行：`astropy__astropy-7606` reward=1，242项测试通过；**单题样例，非500题成绩**。此前下载失败、安装超时及两次环境评分问题均保留。

```sh
export MINI_HARNESS_PROVIDER=local
export MINI_HARNESS_MODEL=qwen3.8-27b
export MINI_HARNESS_BASE_URL=http://127.0.0.1:8000/v1
export MINI_HARNESS_API_KEY=local
export MINI_HARNESS_MAX_TOKENS_MAIN=4096
export MINI_HARNESS_MAX_TOKENS_SUB=2048
export MINI_HARNESS_COMPACT_LIMIT=12000
export MINI_HARNESS_CLIP_LIMIT=12000
PYTHONPATH=. uv run --no-project --with 'harbor==0.20.0' harbor run \
  -d swebench-verified@1.0 --agent bench.adapter:MiniHarnessAgent \
  --model local/qwen3.8-27b --env docker \
  --extra-docker-compose bench/docker-host-network.yaml \
  --n-tasks 1 --n-attempts 1 -n 1 --jobs-dir jobs/qwen-swe-smoke
```

改`--n-tasks 20`先测20题；移除该参数跑500题，并使用新输出目录。当前单题4分46秒，不能据此推断全量耗时或准确率。

本机离线包`.local/bench-runtime`通过`MINI_HARNESS_OFFLINE_RUNTIME`启用；核心代码变化后运行`python scripts/bench/prepare_runtime.py`重建。已修复题目位于`.local/swebench-final/astropy__astropy-7606`，把`-d ...`换成`-p 该路径`即可复跑。

该题修复了uv下载与pytest 4.6.11 / pytest-remotedata 0.3.2的运行依赖，并离线安装官方parser；断言与参考标签未改，哈希保存在`runtime-fix.json`。它只覆盖这一题的环境，其他仓库可能仍需独立修复。

本机单题校验记录在 `.local/metabolomics/benchmarks/astropy-7606/`，包括校验报告、测试日志和补丁。Harbor 原始运行目录为 `jobs/aster-qwen-swe-final/2026-11-05__13-46-39/`，当前工作区保存了[运行摘要](../eval/results/metabolomics-2026-11-05.json)，其中包括成功及失败试次。复跑时以新运行的 verifier 结果为准。

## 程序检查

```sh
pytest -q
npm run build --prefix web
uv run --locked --extra retrieval --with playwright python tests/browser/smoke.py
uv run --locked --extra retrieval --with playwright python tests/browser/daily.py
uv run --locked --extra retrieval --with playwright python tests/browser/library.py
ASTER_RETRIEVAL_URL=http://127.0.0.1:8767 python tests/live/assistant.py \
  --paper .local/metabolomics/papers/PMC13691365.md \
  --output .local/evaluation/daily-check.json
python tests/live/codex.py
ASTER_RETRIEVAL_URL=http://127.0.0.1:8767 python tests/live/discussion.py \
  --paper .local/metabolomics/papers/PMC13691365.md \
  --output .local/evaluation/discussion-check.json
PYTHONPATH=. uv run --no-project --with 'harbor==0.20.0' --with pytest \
  pytest -q tests/integration/test_bench_adapter.py
```

`ZHIXU_TEST_POSTGRES_URL`仅用于独立测试库，测试会清空该库。浏览器回归使用临时资料，不调用Qwen。

2026-11-06日常助手已通过本地Qwen三项行为检查：空库讨论、实际知识库检索与引用、多轮建议；另以合成输入验证了Codex CLI回答及工具调用桥接。报告位于`.local/daily-assistant-2026-11-06/`。这些验证不计入旧基线成绩，也不代表独立人工答案准确率；新助手尚未重跑完整研究题集。
