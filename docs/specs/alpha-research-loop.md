# Alpha Research Loop

更新时间：2026-05-11

## 目标

建设自动盯盘、Alpha 挖掘、因子评估、策略 proposal 和人工批准的闭环。系统可以自动发现候选信号和生成迭代建议，但不能在未经人工批准时改变运行中策略，更不能触发真实交易。

## 边界

- 公共接口仍只通过 HTTP REST 暴露；新增 research 能力先走内部 CLI。
- Agent 不进入日内下单路径，只能在盘后或离线阶段生成结构化建议。
- Alpha 自迭代在达到评估门槛前可以自动循环研究；进入候选策略审核前必须由独立 evaluator / judge 角色复核，不能由同一个 Agent 同时完成开发、回测和最终评估。
- 默认只读或 dry-run；Futu broker 仅允许显式 opt-in 的 `SIMULATE`。
- 禁止真实交易、交易解锁、订阅推送、OpenD 写入配置和任何绕过 broker adapter 的交易调用。
- 所有 JSON contract 必须可被 `json.dumps(..., allow_nan=False)` 序列化。

## Legacy Qlib / Alpha158 移除要求

- 当前 Alpha 研究与回测只使用本地 native factor / backtest 实现，不保留
  Qlib / Alpha158 运行时兼容入口。
- 从根依赖中删除 `pyqlib`，并从 `requirements.txt` 移除仅由它引入的传递依赖。
- 删除 `src/analyzer/qlib_158_factors.py` 及 package export。
- `MultiFactorAnalyzer`、`StockService.analyze_symbol` / `batch_analyze` 不再接受
  `include_qlib_factors`，也不初始化 Qlib analyzer。
- `AnalysisReport.to_dict()` 与 `stock_analysis_contract()` 不再输出空 `qlib`
  字段；技术面和基本面仍保持现有 contract。
- 删除未引用的 `src/model/storage.py` ORM 占位；正式 SQLite 持久化继续只通过
  `src/repositories/`。
- 验收必须覆盖：仓库内无运行时代码引用 Qlib / Alpha158、全量测试通过、
  `requirements.txt` 可由 `pyproject.toml` 重建、全局 Black 检查通过。

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
- `summary.effective_end` / `evaluation.as_of`：真实可验证的成熟样本截止日；当请求 `end` 落到最新交易日时，系统会按最大 forward window 自动剔除尾部未成熟样本。
- `metrics`：IC、RankIC、分组收益、换手、命中率、回撤等指标。
- `sample_split`：必须包含 `train`、`validation`、`out_of_sample`。
- `cost_model`：交易成本假设。显式传 `--cost-bps` 时使用固定 bps；未传时使用 `MarketSpec` 的市场默认估算成本。
- `status` / `data_gaps`：评估状态和数据缺口。

### MarketSpec

用于表达策略评估和后续回测所需的最小市场规则，不参与下单。

- `market` / `exchange` / `currency` / `timezone`：市场基础身份。
- `regular_sessions`：常规交易时段，仅用于调度和报告语义，不代表完整交易日历。
- `lot_size` / `price_tick`：默认交易单位和价格最小变动；港股真实 lot size / tick 可能逐标的不同，当前可先通过 `futu_market_data.py symbol-rules` 读取 Futu snapshot 暴露值，缺失时回退到 `MarketSpec` 默认假设。
- `entry_fee_bps` / `exit_fee_bps` / `entry_slippage_bps` / `exit_slippage_bps`：用于因子评估的 round-trip 成本估算。
- `constraints`：标记估算成本、逐标的规则未完全覆盖等限制。

`MarketSpec` 的设计原则是先把市场差异收敛到独立 contract，Alpha / backtest 消费 contract，不在评估逻辑里散落市场判断。

### AlphaBacktest

用于表达候选策略的只读组合回测结果。

- 输入只来自本地 SQLite 日线仓、显式 universe / symbols、factor、top N、holding period 和成本假设。
- 输出 `summary` 固定包含 `periods`、`orders_total`、`gross_return_mean`、`net_return_mean`、`total_return`、`annualized_return`、`max_drawdown`、`sharpe`、`turnover`、`win_rate`、`data_gaps`。
- `summary.effective_end` 表示本次回测最后一个可验证调仓日；请求 `end` 晚于持有期成熟日时自动向前截断。
- 默认 summary-only，不输出逐期 `periods`；只有显式 `--include-details` 才输出回测明细。
- 固定约束包含 `backtest_not_applied_to_runtime`、`read_only_market_data`、`no_broker_or_order_side_effects`。
- 当前实现是轻量 native backtest，不接 Qlib / Alpha158 / 外部因子库。

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
- `src/model/market.py`：CN / HK / US 最小 `MarketSpec`，包含交易时段、币种、lot / tick 和默认评估成本模型。
- `src/model/serialization.py`：跨 contract 复用的 JSON 安全序列化。
- `src/services/alpha_universe_service.py`：只读构建 Alpha 扫描股票池，支持 `all` / `stock` / `etf` / 显式 `symbols`，`watchlist` 在未提供 symbols 时返回空集合；非显式股票池只返回本地已有日线覆盖摘要的标的，显式 `symbols` 不隐藏缺口。
- `src/services/alpha_feature_service.py`：从本地 SQLite 日线仓提取首批因子，不访问 broker，不拉外部实时行情。
- `src/services/alpha_scan_service.py`：将 universe 与 feature 转换为 `AlphaCandidate`，数据不足时只标记 `partial`，不伪造分数。
- `src/services/alpha_scan_cli.py`：内部 CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_evaluation_service.py`：只读本地日线仓，计算因子前瞻收益、IC / RankIC、分组收益、换手和样本切分。
- `src/services/alpha_evaluate_cli.py`：内部因子评估 CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_backtest_service.py`：只读本地日线仓，做 long-only top-N equal-weight 组合回测，使用 `MarketSpec` 成本假设，不调用 broker。
- `src/services/alpha_backtest_cli.py`：内部组合回测 CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_universe_seed_status_service.py`：只读 tracked seed 和本地日线仓，检查 seed 内标的是否缺失、历史不足或 stale。
- `src/services/alpha_universe_seed_status_cli.py`：内部 seed 覆盖状态 CLI 参数解析与纯 JSON 输出。
- `src/repositories/strategy_registry_repository.py`：SQLite strategy registry，保存 proposal、strategy version、approval、activation history、version event 以及 alpha candidate / evaluation 记录。
- `src/services/strategy_registry_service.py`：策略版本治理业务逻辑，保证未审批不能 active、active 同时只能有一个、状态变更进入事件表。
- `src/services/strategy_registry_cli.py`：内部策略 registry CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_daily_report_service.py`：盘后 summary-only Alpha 自迭代报告，串联 scan / evaluate 并生成候选 proposal。
- `src/services/alpha_daily_report_cli.py`：内部 Alpha 日报 CLI 参数解析与纯 JSON 输出。
- `src/services/watch_worker_service.py`：自动盯盘 tick，读取已审批 active strategy，生成 Alpha watch summary；当前 MVP 默认不触发模拟交易。
- `src/services/watch_worker_cli.py`：内部盯盘 worker CLI 参数解析与纯 JSON 输出。
- `src/services/strategy_judge_service.py`：独立 evaluator / judge gate，根据固定门槛输出 `passed` / `blocked` verdict。
- `src/services/strategy_judge_cli.py`：内部评委 CLI 参数解析与纯 JSON 输出。
- `src/services/alpha_research_loop_service.py`：离线 agent teams 编排，将 researcher / backtester / evaluator 三类职责串成自迭代尝试；默认不写 registry、不 approve、不 activate。
- `src/services/alpha_research_loop_cli.py`：内部自迭代 research loop CLI 参数解析与纯 JSON 输出。
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
- `--universe all|stock|etf` 等非显式股票池必须按本地 `daily_start_date` / `daily_end_date` 覆盖摘要过滤，只扫描已有日线的标的；显式 `--symbols` 不过滤，缺日线时返回 `data_quality=missing` 与 `missing_daily_history`。
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
- `summary.effective_end` 固定存在，用于说明本次 metrics 实际覆盖到哪一天；`evaluation_id` 和 `evaluation.as_of` 使用该日期，避免把未成熟尾部当作有效样本。
- `metrics` 固定包含 `rank_ic_mean`、`rank_ic_tstat`、`rank_ic_by_window`、`ic_by_window`、`quantile_returns_by_window`、`quantile_spread`、`quantile_spread_by_window`、`cost_adjusted_quantile_spread`、`turnover`。
- `sample_split` 必须包含 `train`、`validation`、`out_of_sample` 三段，即使样本为空也要显式输出。
- `status=empty`：股票池为空，`summary.data_gaps=["empty_universe"]`。
- `status=partial`：存在缺失因子、缺失 forward return 或样本不足，缺口必须进入 `data_gaps`，不得用 0 或伪造值补齐指标。
- 当前 MVP 支持 `momentum_5d`、`momentum_20d`、`volatility_5d`、`volume_change_5d`、`turnover_rate`、`pe_ttm`、`pb`、`pct_chg`。
- 未显式传 `--cost-bps` 时，`cost_model.type=market_spec_bps`，按市场默认 `MarketSpec.round_trip_bps` 计算 `cost_adjusted_quantile_spread`。
- 显式传 `--cost-bps` 时，保持 `cost_model.type=fixed_bps`，用于回归、敏感性分析或人工指定成本假设。
- 该 CLI 只读本地行情仓，不写 trading ledger，不触发 broker，不调用 Futu `SIMULATE`，也不改变运行时策略。

## P3 Alpha Backtest CLI

内部入口：

```bash
uv run python scripts/alpha_backtest.py --market cn --symbols 300827,300274 --factor momentum_5d --start 2026-01-01 --end 2026-05-08 --top-n 5 --holding-period 1 --pretty
uv run python scripts/alpha_backtest.py --market hk --symbols HK.00700,HK.09988 --factor momentum_5d --top-n 2 --include-details --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_backtest`、`computed_at`、`request`、`cost_model`、`summary`、`constraints`。
- `summary` 固定包含组合级收益、回撤、夏普、换手、胜率和数据缺口。
- `summary.effective_end` 固定存在，用于说明回测实际覆盖到的最后可验证调仓日。
- `status=empty`：股票池为空或无可回测期，`summary.periods=0`。
- `status=partial`：存在缺失因子、缺失 forward return 或样本不足，缺口必须进入 `data_gaps`。
- 默认 summary-only；逐期持仓和收益必须显式 `--include-details` 才输出。
- 该 CLI 只读本地行情仓，不写 registry、不写 trading ledger、不触发 broker、不调用 Futu `SIMULATE`。

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
- `approve` 必须已有同 strategy version 的 passed judge verdict；否则拒绝审批。
- `activate` 必须先存在 approval record；否则返回 `status=failed`，不会产生 active strategy。
- `activate` 只允许 `approved -> active`，不得重复激活 active 或重新激活 retired。
- `activate` 成功时只允许一个 `active`，已有 active 会被标记为 `retired`。
- 状态变化必须写入 append-only `strategy_version_events`；激活历史必须写入 `strategy_activation_history`。
- `alpha_candidates` 和 `alpha_evaluations` 表作为 append-only research 记录入口，供后续日报和 registry 汇总使用。
- `record-verdict` 只追加独立 judge verdict，不创建 approval，不 activate。
- `research-history` 汇总已记录的 alpha research loop runs、阻断原因和 factor 指标漂移，不改变策略状态。
- 该 CLI 不触发 broker、不下单、不调用 Futu `SIMULATE`、不交易解锁，也不让 Agent 自动 approve / activate。

## Judge Gate CLI

内部入口：

```bash
uv run python scripts/strategy_judge.py --proposal-json proposal.json --evaluation-json evaluation.json --evaluator-id judge-agent --researcher-id researcher-agent --pretty
uv run python scripts/strategy_judge.py --proposal-json proposal.json --evaluation-json evaluation.json --champion-json active-verdict.json --min-challenger-rank-ic-delta 0.01 --min-challenger-quantile-spread-delta 0.005 --evaluator-id judge-agent --researcher-id researcher-agent --pretty
uv run python scripts/strategy_registry.py record-verdict --verdict-json verdict.json --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=strategy_judge`、`verdict`、`strategy_proposal`。
- `status=passed` 时 `verdict.human_review_ready=true`，并回传原始 `strategy_proposal` 给人工审核或 registry propose。
- `status=blocked` 时 `strategy_proposal=null`，`verdict.reasons` 必须说明阻断原因。
- `verdict.proposal_not_applied=true` 必须固定存在，表示评委结论不会修改运行时策略。
- `evaluator_id` 与 `researcher_id` 相同会阻断，原因固定为 `evaluator_must_be_independent`。
- 当前固定门槛包括 `min_rank_ic_mean`、`min_quantile_spread`、`max_turnover`、`min_observations`、`allow_data_gaps`。
- 回测证据门槛默认包括 `min_backtest_periods=1`、`min_backtest_total_return=0`、`max_backtest_drawdown=-1`；缺失回测、样本不足、收益不达标或回撤超阈值都会 blocked。
- 可选 `champion-json` 用于 champion/challenger 对比；提供后 challenger 必须满足 `min_challenger_rank_ic_delta` 和 `min_challenger_quantile_spread_delta`，否则阻断原因分别为 `challenger_rank_ic_not_improved` / `challenger_quantile_spread_not_improved`。
- `champion-json` 可传 registry 中 active strategy 对应的 passed judge verdict；没有 active champion 时只执行绝对阈值。
- registry 只能 append 记录 judge verdict；不能因为 verdict passed 自动 approve / activate。

## Agent Teams Research Loop CLI

内部入口：

```bash
uv run python scripts/alpha_research_loop.py --market cn --factors momentum_5d,momentum_20d --researcher-id researcher-agent --backtester-id backtester-agent --evaluator-id judge-agent --pretty
uv run python scripts/alpha_research_loop.py --market cn --factors momentum_5d,momentum_20d --researcher-id researcher-agent --backtester-id backtester-agent --evaluator-id judge-agent --record-to-registry --registry-db .cache/strategy_registry.sqlite --pretty
uv run python scripts/strategy_registry.py --registry-db .cache/strategy_registry.sqlite research-history --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_research_loop`、`computed_at`、`team`、`request`、`summary`、`attempts`、`selected`、`next_research_actions`。
- `team` 必须明确 `researcher`、`backtester`、`evaluator` 三个角色和 ID。
- 三个角色 ID 必须互不相同；否则返回失败，不继续生成 proposal。
- 每个 attempt 只处理一个 factor，并串联：
  - researcher：通过 `alpha_daily_report` 生成候选 `strategy_proposal`。
  - backtester：复用 `alpha_evaluation` 和 `alpha_backtest` 指标作为独立评估材料。
  - evaluator：调用 `strategy_judge` 输出 verdict。
- `status=human_review_ready` 表示至少一个 attempt 通过 judge gate，`selected.strategy_proposal` 可交给人工审核。
- `status=needs_iteration` 表示所有 attempt 均 blocked，必须输出 `next_research_actions`，不得伪装为通过。
- 默认 summary-only；attempt 明细必须显式 `--include-attempt-details` 才输出。
- 默认不写 registry、不 approve、不 activate、不触发 broker。
- 只有显式 `--record-to-registry` 时才追加记录 research loop run 和 judge verdict；该记录动作仍不得 propose / approve / activate。
- 当 service 持有 strategy registry 且存在 active strategy 时，research loop 会读取 active strategy 对应的 passed judge verdict 作为 champion，交给 judge 做相对增量评估；CLI 显式传 `--registry-db` 即可读取 champion，不要求同时 `--record-to-registry`。
- 已记录的 research loop run 必须保留 `run_id`、attempts、judge verdict、proposal_not_applied 和 approval_required。

## P6 Alpha Daily Report CLI

内部入口：

```bash
uv run python scripts/alpha_daily_report.py --market cn --date 2026-05-09 --factor momentum_20d --pretty
uv run python scripts/alpha_daily_report.py --market cn --symbols 300827,300274 --factor momentum_5d --forward-windows 1,3 --include-details --pretty
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_daily_report`、`date`、`summary`、`watch`、`simulated_trading`、`factor_evaluation_drift`、`alpha_scan`、`alpha_evaluation`、`alpha_backtest`、`strategy_proposal`。
- 默认 summary-only：`alpha_scan` 不含完整 `items`，`alpha_evaluation` 不含完整 `evaluation`，`alpha_backtest` 不含逐期 `periods`；明细必须显式 `--include-details`。
- `summary.proposal_not_applied=true` 必须固定存在，表示报告不会修改运行时策略。
- 有候选且有评估样本时生成 `StrategyProposal`，默认 `approval_required=true`、`effective_status=candidate_only`，并把 `alpha_backtest_summary` 写入 proposal evidence。
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
- `uv run pytest tests/test_alpha_backtest_cli.py -q`
- `uv run pytest tests/test_strategy_registry_cli.py -q`
- `uv run pytest tests/test_alpha_daily_report_cli.py -q`
- `uv run pytest tests/test_watch_worker_tick_cli.py -q`
- `uv run pytest tests/test_strategy_judge_cli.py -q`
- `uv run pytest tests/test_alpha_research_loop_cli.py -q`
- contract 输出不包含 `NaN` / `Infinity`。
- proposal 默认需要人工批准。
- `approve` 前必须存在 passed judge verdict。
- P1 开始前不得新增交易写入能力。
