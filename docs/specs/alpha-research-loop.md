# Alpha Research Loop

更新时间：2026-05-09

## 目标

建设自动盯盘、Alpha 挖掘、因子评估、策略 proposal 和人工批准的闭环。系统可以自动发现候选信号和生成迭代建议，但不能在未经人工批准时改变运行中策略，更不能触发真实交易。

## 边界

- 公共接口仍只通过 HTTP REST 暴露；新增 research 能力先走内部 CLI。
- Agent 不进入日内下单路径，只能在盘后或离线阶段生成结构化建议。
- Alpha 自迭代在达到评估门槛前可以自动循环研究；进入候选策略审核前必须由独立 evaluator / judge 角色复核，不能由同一个 Agent 同时完成开发、回测和最终评估。
- 默认只读或 dry-run；Futu broker 仅允许显式 opt-in 的 `SIMULATE`。
- 禁止真实交易、交易解锁、订阅推送、OpenD 写入配置和任何绕过 broker adapter 的交易调用。
- 所有 JSON contract 必须可被 `json.dumps(..., allow_nan=False)` 序列化。

## 数据契约

### AlphaCandidate

用于表达一次扫描产出的候选信号。

- `candidate_id`：候选唯一 ID。
- `universe_id`：股票池 ID。
- `as_of`：信号日期或时间。
- `market` / `symbol`：市场与标的。
- `factor_values`：原始因子值。
- `score` / `rank`：综合分与排名，数据不足时允许为空。
- `reasons`：入选原因。
- `data_quality` / `data_gaps`：数据质量和缺口。

### AlphaEvaluation

用于表达候选或因子的评估结果。

- `evaluation_id` / `candidate_id` / `method`：评估标识。
- `forward_windows`：前瞻窗口，例如 1D / 5D / 20D。
- `metrics`：IC、RankIC、分组收益、换手、命中率、回撤等指标。
- `sample_split`：必须包含 `train`、`validation`、`out_of_sample`。
- `cost_model`：交易成本假设。
- `status` / `data_gaps`：评估状态和数据缺口。

### StrategyProposal

用于表达 Agent 或 research service 生成的策略调整建议。

- 默认 `approval_required=true`。
- 默认 `effective_status=candidate_only`。
- 默认约束包含：
  - `proposal_not_applied_to_runtime`
  - `requires_human_approval`
  - `agent_not_in_intraday_order_path`

### StrategyVersion

用于表达策略版本治理状态。

- 合法状态：`draft`、`candidate`、`approved`、`active`、`retired`、`rejected`。
- `approved` 或 `active` 必须有 `approved_by`。
- 不允许出现 `auto_applied` 这类绕过审批的状态。

## 模块分工

- `src/model/alpha.py`：Alpha 候选与评估 contract。
- `src/model/strategy.py`：策略 proposal 与版本治理 contract。
- `src/model/serialization.py`：跨 contract 复用的 JSON 安全序列化。
- `src/services/alpha_universe_service.py`：只读构建 Alpha 扫描股票池，支持 `all` / `stock` / `etf` / 显式 `symbols`，`watchlist` 在未提供 symbols 时返回空集合。
- `src/services/alpha_feature_service.py`：从本地 SQLite 日线仓提取首批因子，不访问 broker，不拉外部实时行情。
- `src/services/alpha_scan_service.py`：将 universe 与 feature 转换为 `AlphaCandidate`，数据不足时只标记 `partial`，不伪造分数。
- `src/services/alpha_scan_cli.py`：内部 CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_evaluation_service.py`：只读本地日线仓，计算因子前瞻收益、IC / RankIC、分组收益、换手和样本切分。
- `src/services/alpha_evaluate_cli.py`：内部因子评估 CLI 参数解析与纯 JSON 输出。
- `src/repositories/strategy_registry_repository.py`：SQLite strategy registry，保存 proposal、strategy version、approval、activation history、version event 以及 alpha candidate / evaluation 记录。
- `src/services/strategy_registry_service.py`：策略版本治理业务逻辑，保证未审批不能 active、active 同时只能有一个、状态变更进入事件表。
- `src/services/strategy_registry_cli.py`：内部策略 registry CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_daily_report_service.py`：盘后 summary-only Alpha 自迭代报告，串联 scan / evaluate 并生成候选 proposal。
- `src/services/alpha_daily_report_cli.py`：内部 Alpha 日报 CLI 参数解析与纯 JSON 输出。
- `src/services/watch_worker_service.py`：自动盯盘 tick，读取已审批 active strategy，生成 Alpha watch summary；当前 MVP 默认不触发模拟交易。
- `src/services/watch_worker_cli.py`：内部盯盘 worker CLI 参数解析与纯 JSON 输出。
- `src/services/*`：后续继续承载 evaluate、registry 等业务逻辑。
- `scripts/*`：只做 CLI 参数解析和 service 调用，不沉淀正式业务逻辑。

## P1 Alpha Scan CLI

内部入口：

```bash
uv run python scripts/alpha_scan.py --market cn --universe all --top 20 --pretty
uv run python scripts/alpha_scan.py --market cn --symbols 300827,300274 --top 10
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_scan`、`computed_at`、`request`、`summary`、`items`。
- `status=empty`：股票池为空，`items=[]`。
- `status=partial`：至少一个候选缺少足够日线；该候选 `score=null`、`data_quality=partial`、`data_gaps` 说明缺口。
- `items` 中每项必须符合 `AlphaCandidate.to_dict()` contract。
- 该 CLI 只读本地行情仓，不写 trading ledger，不触发 broker，不调用 Futu `SIMULATE`。

## P2 Alpha Evaluate CLI

内部入口：

```bash
uv run python scripts/alpha_evaluate.py --market cn --factor momentum_20d --start 2026-01-01 --end 2026-05-08 --forward-windows 1,5,20 --pretty
uv run python scripts/alpha_evaluate.py --market cn --symbols 300827,300274 --factor momentum_5d --forward-windows 1,3
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_evaluate`、`computed_at`、`request`、`summary`、`evaluation`。
- `evaluation` 必须符合 `AlphaEvaluation.to_dict()` contract。
- `metrics` 固定包含 `rank_ic_mean`、`rank_ic_tstat`、`rank_ic_by_window`、`ic_by_window`、`quantile_returns_by_window`、`quantile_spread`、`quantile_spread_by_window`、`cost_adjusted_quantile_spread`、`turnover`。
- `sample_split` 必须包含 `train`、`validation`、`out_of_sample` 三段，即使样本为空也要显式输出。
- `status=empty`：股票池为空，`summary.data_gaps=["empty_universe"]`。
- `status=partial`：存在缺失因子、缺失 forward return 或样本不足，缺口必须进入 `data_gaps`，不得用 0 或伪造值补齐指标。
- 当前 MVP 支持 `momentum_5d`、`momentum_20d`、`volatility_5d`、`volume_change_5d`、`turnover_rate`、`pe_ttm`、`pb`、`pct_chg`。
- 该 CLI 只读本地行情仓，不写 trading ledger，不触发 broker，不调用 Futu `SIMULATE`，也不改变运行时策略。

## P4 Strategy Registry CLI

内部入口：

```bash
uv run python scripts/strategy_registry.py propose --proposal-json proposal.json --pretty
uv run python scripts/strategy_registry.py approve --strategy-version alpha_topn_v1.20260509 --approved-by ryan --pretty
uv run python scripts/strategy_registry.py activate --strategy-version alpha_topn_v1.20260509 --pretty
uv run python scripts/strategy_registry.py current --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=strategy_registry`、`action`，并按命令返回 `proposal`、`strategy_version`、`current_strategy`、`events`、`activation` 等结构化字段。
- `propose` 只接受 `approval_required=true` 且 `effective_status=candidate_only` 的 `StrategyProposal`；保存后 strategy status 为 `candidate`，不会 active，也不会写运行时策略配置。
- `approve` 必须显式传 `--approved-by`；审批记录写入 `strategy_approvals`。
- `activate` 必须先存在 approval record；否则返回 `status=failed`，不会产生 active strategy。
- `activate` 成功时只允许一个 `active`，已有 active 会被标记为 `retired`。
- 状态变化必须写入 append-only `strategy_version_events`；激活历史必须写入 `strategy_activation_history`。
- `alpha_candidates` 和 `alpha_evaluations` 表作为 append-only research 记录入口，供后续日报和 registry 汇总使用。
- 该 CLI 不触发 broker、不下单、不调用 Futu `SIMULATE`、不交易解锁，也不让 Agent 自动 approve / activate。

## P6 Alpha Daily Report CLI

内部入口：

```bash
uv run python scripts/alpha_daily_report.py --market cn --date 2026-05-09 --factor momentum_20d --pretty
uv run python scripts/alpha_daily_report.py --market cn --symbols 300827,300274 --factor momentum_5d --forward-windows 1,3 --include-details --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_daily_report`、`date`、`summary`、`watch`、`simulated_trading`、`factor_evaluation_drift`、`alpha_scan`、`alpha_evaluation`、`strategy_proposal`。
- 默认 summary-only：`alpha_scan` 不含完整 `items`，`alpha_evaluation` 不含完整 `evaluation`；明细必须显式 `--include-details`。
- `summary.proposal_not_applied=true` 必须固定存在，表示报告不会修改运行时策略。
- 有候选且有评估样本时生成 `StrategyProposal`，默认 `approval_required=true`、`effective_status=candidate_only`。
- 空股票池或无评估样本时 `strategy_proposal=null`，`human_action_required=false`。
- 报告中的 `watch` 和 `simulated_trading` 在当前 MVP 中只输出状态占位，不读取或写入 trading ledger，不触发 broker。
- `factor_evaluation_drift` 在当前单日报告 MVP 中固定为 `not_available`，后续接入历史 evaluation 后再计算跨日报漂移。
- 该 CLI 不调用 Futu `SIMULATE`、不下单、不 approve、不 activate，只为下一步人工治理链生成候选材料。

## P5 Watch Worker CLI

内部入口：

```bash
uv run python scripts/watch_worker_tick.py --state-key cn-alpha-watch --interval-seconds 300 --active-window 09:30-11:30,13:00-15:00 --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=watch_worker_tick`、`schedule`，运行时包含 `active_strategy`、`summary`、`watch_alerts`、`simulated_execution`。
- `outside_active_window` 和 `not_due` 返回 `status=skipped`，不读取行情，不执行报告。
- 没有 active strategy 返回 `status=skipped / reason=no_active_strategy`。
- active strategy 必须来自 `strategy_registry.py activate` 后的 registry current strategy。
- 当前 MVP 只做只读 Alpha watch summary，`simulated_execution.status=disabled`，不调用 broker，不写 trading ledger order。
- Alpha report 失败时返回 `status=degraded / reason=report_failed`，不吞异常。
- launchd 示例配置在 `ops/com.ryan.stock-analysis-watch.plist`，默认 300 秒 tick。

## 验收

- `uv run pytest tests/test_alpha_contracts.py -q`
- `uv run pytest tests/test_alpha_scan_cli.py -q`
- `uv run pytest tests/test_alpha_evaluate_cli.py -q`
- `uv run pytest tests/test_strategy_registry_cli.py -q`
- `uv run pytest tests/test_alpha_daily_report_cli.py -q`
- `uv run pytest tests/test_watch_worker_tick_cli.py -q`
- contract 输出不包含 `NaN` / `Infinity`。
- proposal 默认需要人工批准。
- P1 开始前不得新增交易写入能力。
