# Task Chain Worker

## 目标

提供一条可持久化、可回溯、可续跑的模拟盘 / Alpha 自迭代任务链。外部只需要周期性触发轻量 `tick`，真正的下一轮任务由上一轮任务结果写入下一颗 task 的 `due_at`，避免多个重任务固定 cron 同时堆积。

## 边界

- 只用于内部 Agent / skill / launchd 调用，不新增公共 HTTP API。
- 当前阶段全部模拟盘 / 只读研究，不触发真实下单、不调用 `unlock_trade`。
- task-chain 只做元调度、lease、run log 和 summary，不把具体策略、broker、数据源逻辑写入仓表层。
- 具体策略研究仍复用现有 `alpha_research_loop.py`、`strategy_judge.py`、`watch_worker_tick.py`、`trading_run_once.py` 等内部 CLI。

## CLI

入口：

```bash
uv run python scripts/task_chain.py --task-db .cache/task_chain.sqlite bootstrap --task-type market_observe --due-at 2026-05-15T01:30:00+00:00
uv run python scripts/task_chain.py --task-db .cache/task_chain.sqlite tick
```

launchd 示例配置：

- `ops/com.ryan.stock-analysis-task-chain.plist`
- `StartInterval=60`，只负责轻量调用 `tick`。
- `tick` 每次最多执行一颗 due task；重任务间隔仍由 task-chain 写入的下一颗 task `due_at` 控制。

### `bootstrap`

创建第一颗 pending task。

参数：

- `--task-type`: `market_observe | alpha_mine | judge_review | paper_trade | hourly_report | daily_report`
- `--due-at`: ISO datetime；不传则使用当前 UTC 时间。
- `--payload-json`: JSON object，保存 market、symbols、factor 等任务上下文。

### `tick`

只执行一个 due task。

流程：

1. 从 SQLite 中找 `due_at <= now` 的 pending task。
2. 对 task 写入 lease：`status=running`、`lease_owner`、`lease_expires_at`。
3. 追加一条 `task_chain_runs`。
4. 执行原子任务。
5. 完成 task，写 result。
6. 写入下一颗 pending task。

参数：

- `--now`: 测试用 ISO datetime；不传则当前 UTC 时间。
- `--owner-id`: worker identity；不传自动生成。
- `--lease-ttl-seconds`: 默认 900 秒。

## 仓表

### `task_chain_tasks`

保存任务状态和下一轮调度。

关键字段：

- `id`
- `task_type`
- `status`: `pending | running | completed | failed`
- `due_at`
- `payload_json`
- `parent_task_id`
- `lease_owner`
- `lease_expires_at`
- `result_json`
- `error`

### `task_chain_runs`

append-only 运行日志。

关键字段：

- `id`
- `task_id`
- `task_type`
- `owner_id`
- `started_at`
- `finished_at`
- `status`
- `input_json`
- `output_json`
- `error`

### `task_chain_summaries`

保存小时 / 日终总结。

关键字段：

- `summary_type`: `hourly | daily`
- `period_start`
- `period_end`
- `summary_json`

## 初始任务链

当前 MVP 的确定性链路：

```text
market_observe
-> alpha_mine
-> judge_review
-> paper_trade
-> hourly_report
-> market_observe
```

日终可单独 bootstrap：

```text
daily_report
-> market_observe
```

`daily_report` 必须包含纠偏 review 结构：

- `trade_auditor`
- `strategy_reviewer`
- `risk_reviewer`
- `contrarian_reviewer`

当前 MVP 先落结构化 reviewer verdict；后续由 Cli Claw / Agent 层接入真实 subagents，把各 reviewer 的只读审查结果写回同一 summary contract。

## 准出标准

在进入真实 Alpha 挖掘前，task-chain 至少满足：

- due task 能被 lease 获取。
- active lease 未过期时不会重入。
- lease 过期后可恢复。
- 每轮 task 和 run 都能落库回溯。
- 每小时能输出 `hourly_report`。
- 每天能输出 `daily_report`，并带纠偏 review 结构。
- 所有输出是严格 JSON。
