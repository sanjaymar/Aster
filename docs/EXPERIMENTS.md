# 实验指南

[架构与代码入口](../README.md#技术方案与代码学习) · [Web 使用](WEB_GUIDE.md)

科研问答、笔记与汇报共用 `ResearchPipeline`；SWE-bench 使用通用 mini-harness 工具循环。两类实验分别衡量领域问答与编码能力。

## 问答评测

本机实验位于 `data/experiments/qa/`：`dataset/` 保存题集，`evaluation.db` 固定评测数据库，`reports/` 保存历史结果。基线为 **300 篇、19,250 块**；日常库新增论文不自动纳入该快照。

题集：意图 100、改写 40、检索 100、边界 55、30 组四轮对话（120 turns），另有 70-turn 端到端子集与 20 条记忆测试。标签包含作者／模型辅助草案，尚待独立人工复核。

```sh
export ASTER_HOME="$PWD/data"
uv run aster corpus --project PROJECT_ID
uv run aster console --project PROJECT_ID
# /corpus、/memory [CONVERSATION_ID]、/trace RUN_ID
uv run aster evaluate-suite --suites intent,rewrite,retrieval \
  --output "$ASTER_HOME/experiments/qa/current"
uv run aster evaluate-suite --suites boundary,dialogues,memory \
  --variants full,no-rewrite,no-reflect,no-rerank,no-memory \
  --output "$ASTER_HOME/experiments/qa/current"
```

仓库不附带私人题集和数据库；新用户需先建立语料、题集与来源映射。模型、代码、题集或语料变化时使用新的实验目录和相应数据库快照；相同配置可续跑。

| 指标 | 口径 |
|---|---|
| Intent accuracy | 正确意图 / 全部意图题；当前定义六类 |
| Recall@5 | 每题前五候选覆盖标注证据的比例，再取平均 |
| 拒答准确率 | 应拒答题中正确拒答的比例 |
| 引用有效性 | 引用存在且属于授权范围；语义支持另做人工审阅 |
| Pipeline success | 完成任务、响应类型正确；应答题还要求有效引用与参考来源覆盖 |
| Memory 一致性 | 压缩前后约束／实体是否保留 |

历史结果见 [baseline.json](../eval/results/baseline.json)：

| 检索配置 | Recall@5 |
|---|---:|
| BM25 | 4.00% |
| Dense | 64.50% |
| Hybrid | 58.00% |
| Hybrid + Rerank | 80.75% |

意图 99/100；边界响应 52/55；多轮工程成功 88/120；70-turn 子集 54/70（77.14%）。四项多轮消融各 12 turns，去 Reflect 另测 20 条证据不足题，属于小规模探索。

以上为**历史草案评测，当前重构版本尚待完整复测**。工程成功率不等于科研答案正确率；混合召回也未超过纯稠密基线。人工引用审阅：

```sh
uv run python scripts/evaluation/citation_review.py \
  --report PATH_TO_DIALOGUES_JSON --export citation-review.csv
# 填写 supported、reviewer、reason 后：
uv run python scripts/evaluation/citation_review.py --score citation-review.csv
```

## SWE-bench

共享改动包括执行状态、请求前上下文估算和摘要中的用户原话保留。`baseline` 沿用上一轮 token 用量触发压缩，`adaptive` 增加请求前估算和原话保留；领域七阶段与论文工具不注入编码任务。

先准备 Docker、本地模型服务和离线运行包：

```sh
export ASTER_HOME="$PWD/data"
export MINI_HARNESS_PROVIDER=local
export MINI_HARNESS_MODEL=qwen3.8-27b
export MINI_HARNESS_BASE_URL=http://127.0.0.1:8000/v1
export MINI_HARNESS_API_KEY=local
export MINI_HARNESS_MAX_TOKENS_MAIN=4096
export MINI_HARNESS_MAX_TOKENS_SUB=2048
export MINI_HARNESS_COMPACT_LIMIT=12000
export MINI_HARNESS_CLIP_LIMIT=12000
export MINI_HARNESS_OFFLINE_RUNTIME="$ASTER_HOME/experiments/swe/runtime"
uv run python scripts/bench/prepare_runtime.py

export MINI_HARNESS_CONTEXT_POLICY=adaptive
PYTHONPATH=. uv run --no-project --with 'harbor==0.20.0' harbor run \
  -d swebench-verified@1.0 --n-tasks 1 \
  --agent bench.adapter:MiniHarnessAgent --model local/qwen3.8-27b \
  --env docker --extra-docker-compose bench/docker-host-network.yaml \
  --n-attempts 1 -n 1 --job-name adaptive \
  --jobs-dir "$ASTER_HOME/experiments/swe/jobs"
```

模型名以服务实际返回的 ID 为准。将策略与 `--job-name` 一起改为 `baseline`，保持模型、题目、预算和环境相同。全量运行移除 `--n-tasks 1`，固定相同任务集；修改核心代码后重建离线包。

本机已修复的单题可将 `-d ... --n-tasks 1` 换成 `-p "$ASTER_HOME/experiments/swe/tasks/astropy__astropy-7606"`。该任务快照不随源码上传；历史结果 reward=1、242 项测试通过，尚无 500 题全量成绩或 adaptive 优于 baseline 的结论。

记录 resolved、基础设施异常、模型失败、耗时、token 与压缩次数。`baseline` 开关仅比较上下文策略，不是回滚到上游完整版本。

## 工程回归

```sh
uv run --locked ruff check src scripts tests tui.py
uv run --locked pytest tests/unit tests/integration -q
npm run build --prefix web
uv run --with playwright python tests/browser/smoke.py
uv run --with playwright python tests/browser/library.py
uv run --with playwright python tests/browser/daily.py
```

浏览器测试使用独立数据库与模拟模型。PostgreSQL 测试需要 `ZHIXU_TEST_POSTGRES_URL`；缺失时跳过。真实模型检查记录在本机 `data/experiments/reading/`，用于确认链路，不替代人工评测。
