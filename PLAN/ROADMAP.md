# 自动盯盘、Alpha 挖掘与自我迭代路线图

更新时间：2026-05-09

## 目标

在现有 `stock-analysis-api` 基础上，建设一套可审计、可回测、可人工批准生效的自动盯盘和 Alpha 研究闭环：

1. 定时盯盘：按固定调度读取行情、账户和模拟盘 ledger，输出异动、风险和执行状态。
2. 自动挖掘 Alpha：从股票池、因子、行情和基本面数据中生成候选信号，并做样本内 / 样本外评估。
3. 模拟盘执行：只允许 dry-run 或显式 opt-in 的 Futu `SIMULATE`，禁止真实交易、交易解锁和订阅写入。
4. 自我迭代：Agent 只在盘后或离线阶段生成结构化 `strategy_proposal`，必须经过回测门槛和人工批准后才能进入候选或生效策略版本。

## 当前基线

已经可用：

- `POST /stock/analyze`：A 股 / 美股结构化分析。
- `POST /watch/poll`：多标的盯盘轮询。
- `scripts/poll_realtime_quotes.py`：A 股 / ETF 轻量实时行情轮询。
- `scripts/futu_market_data.py`：Futu/OpenD 只读数据入口，已覆盖 `global-state`、`ipo-list`、`snapshot`、`kline`、`order-book`、`ticker`、`rt-data`、`option-expirations`、`option-chain`、`account`、`positions`、`orders`、`deals`、`cash-flow`。
- `scripts/trading_run_once.py`：单轮 dry-run / Futu `SIMULATE` 模拟执行。
- `scripts/trading_scheduler_tick.py`：定时 tick、时间窗、间隔、锁和单轮执行编排。
- `scripts/trading_daily_summary.py`：只读 ledger 的 summary-only 盘后总结。
- `scripts/trading_strategy_review.py`：只读 ledger，生成需要人工批准的 `strategy_proposal`。
- `scripts/trading_strategy_backtest.py`：固定 threshold 策略历史 K 线 / 注入样本回测。
- `scripts/alpha_scan.py`：只读本地行情仓，输出 Alpha 候选池。
- `scripts/alpha_evaluate.py`：只读本地行情仓，输出 forward returns、IC / RankIC、分组收益、换手和样本切分。
- `scripts/strategy_registry.py`：保存候选 strategy proposal、人工 approval、单 active strategy 指针和 append-only 状态事件。

当前缺口：

- Alpha 扫描和因子评估已有 MVP，但尚未持久化到 strategy registry，也没有接入盘后日报。
- 因子评估已有 IC / RankIC / 分组收益 / 换手和样本切分，尚未覆盖 group neutral、holding decay 细分和更严格的样本外门槛。
- 策略版本 registry 与审批记录已有 MVP，但自动盯盘 worker 尚未读取 active strategy。
- 回测仍是固定 threshold 策略，尚未覆盖组合构建、交易成本、滑点、成交约束和多因子组合。
- 调度入口已有 CLI，但还缺统一 worker、运行状态面、失败重试、日报推送和异常告警。

## 开源库选型

### 采用优先级

1. `Qlib`：作为 Alpha 研究和因子 / 模型评估的主要参考与可选集成对象。Qlib 是 AI-oriented quantitative investment platform，覆盖 data、model、backtest、analysis，且官方 README 明确覆盖 alpha seeking、risk modeling、portfolio optimization、order execution。
2. `vectorbt`：作为第一阶段参数扫描和信号回测引擎。它基于 pandas / NumPy / Numba 做向量化回测，适合快速跑大量参数组合。
3. `Alphalens` 方法论：作为因子评估指标参考。优先在本仓库实现核心指标，避免直接引入老旧依赖导致兼容性风险；指标包括 forward returns、IC、quantile returns、turnover、grouped analysis。
4. `NautilusTrader` / `LEAN`：作为中长期事件驱动回测和 research-to-live parity 参考，不在 MVP 阶段直接接入。两者更适合复杂多资产、多 venue、组合级执行。
5. `Backtrader` / `zipline-reloaded`：作为低频事件驱动回测备选，不作为第一选择；当前 API 的高 ROI 路线应优先复用已有 SQLite 仓、Futu provider 和 CLI contract。
6. `OpenBB`：作为数据源整合和 provider extension 参考，不替代当前 Tushare / Futu 主链路。
7. `vn.py / VeighNa`：作为国内量化交易框架参考。当前不接入其交易网关，避免绕开已有 Futu `SIMULATE` 和只读护栏。

### 选型原则

- 先引入方法和数据 contract，再引入重型运行时。
- 第一阶段不得把自动交易主路径交给 Agent 或外部框架。
- 任何库都必须通过本仓库 `src/model/` contract、`src/services/` service 和 `scripts/` CLI 适配，不直接污染公共 HTTP API。
- 新增依赖前必须先有最小实验脚本和可重复测试；不能为了“成熟库”直接重构现有闭环。

## 总体架构

```text
Data Providers
  ├─ Tushare / local SQLite warehouse
  ├─ Futu/OpenD readonly provider
  └─ optional OpenBB-style provider adapters

Research Layer
  ├─ universe builder
  ├─ feature / factor builder
  ├─ alpha scanner
  ├─ factor evaluator
  └─ backtest engine adapter: native first, vectorbt optional, Qlib optional

Strategy Governance
  ├─ alpha candidate store
  ├─ evaluation result store
  ├─ strategy version registry
  ├─ approval record
  └─ active strategy reader

Execution Layer
  ├─ trading_scheduler_tick.py
  ├─ trading_run_once.py
  ├─ dry-run broker
  └─ explicit Futu SIMULATE broker

Agent Loop
  ├─ daily_summary
  ├─ strategy_review
  ├─ alpha_research_report
  └─ strategy_proposal, human approval required
```

## 里程碑

### P0：先锁安全边界和数据契约

状态：done，2026-05-09

目标：

- 确认所有新增能力默认只读或 dry-run。
- 明确 Alpha、策略、回测、审批和生效配置的 schema。
- 不新增真实交易、订阅、交易解锁或任何 OpenD 写入能力。

新增 / 修改文件：

- `docs/specs/alpha-research-loop.md`
- `docs/plan.md`
- `src/model/serialization.py`
- `src/model/alpha.py`
- `src/model/strategy.py`
- `tests/test_alpha_contracts.py`

交付：

- `AlphaCandidate`
  - `candidate_id`
  - `universe_id`
  - `as_of`
  - `symbol`
  - `factor_values`
  - `score`
  - `rank`
  - `reasons`
  - `data_quality`
- `AlphaEvaluation`
  - `candidate_id`
  - `method`
  - `forward_windows`
  - `ic`
  - `rank_ic`
  - `quantile_returns`
  - `turnover`
  - `hit_rate`
  - `max_drawdown`
  - `cost_model`
  - `sample_split`
- `StrategyVersion`
  - `strategy_version`
  - `status=draft|candidate|approved|active|retired|rejected`
  - `source_proposal_id`
  - `parameters`
  - `risk_limits`
  - `created_at`
  - `approved_by`

验收：

- `pytest tests/test_alpha_contracts.py`
- JSON contract 不允许 `NaN` / `Infinity`。
- proposal 默认 `approval_required=true`。

### P1：Alpha 扫描 MVP

状态：done，2026-05-09

目标：

- 从本地行情仓和现有因子计算中生成每日 Alpha 候选池。
- 先支持 A 股和 ETF，后续扩展港 / 美。
- 不做下单，只输出候选与原因。

新增 / 修改文件：

- `src/services/alpha_universe_service.py`
- `src/services/alpha_feature_service.py`
- `src/services/alpha_scan_service.py`
- `src/services/alpha_scan_cli.py`
- `scripts/alpha_scan.py`
- `tests/test_alpha_scan_cli.py`

功能：

- `alpha_universe_service`
  - 读取 `cn_symbols`。
  - 支持 `--market cn`、`--universe watchlist|all|etf|stock`。
  - 支持 `--symbols` 显式覆盖。
- `alpha_feature_service`
  - 复用现有技术因子、基本面字段和 daily 数据。
  - 输出标准化 factor frame。
- `alpha_scan_service`
  - 计算初版 score：趋势确认、动量、波动、成交量、估值、增长、风险扣分。
  - 输出 top N 候选。

CLI：

```bash
uv run python scripts/alpha_scan.py --market cn --universe watchlist --top 20 --pretty
```

验收：

- stdout 严格 JSON。
- 空 universe 返回 `status=empty`，不报 500。
- 数据不足标记 `data_quality=partial`，不伪造分数。
- 不写交易 ledger，不触发 broker。
- 已通过 `uv run pytest tests/test_alpha_scan_cli.py -q`。

### P2：因子评估与 Alpha 验证

状态：done，2026-05-09

目标：

- 把候选 Alpha 变成可验证结果，而不是只看扫描分。
- 优先实现 Alphalens 方法论中的核心指标，后续再评估是否直接接入 Alphalens。

新增 / 修改文件：

- `src/services/alpha_evaluation_service.py`
- `src/services/alpha_evaluate_cli.py`
- `scripts/alpha_evaluate.py`
- `tests/test_alpha_evaluate_cli.py`

功能：

- forward returns：1D / 3D / 5D / 10D / 20D。
- IC / RankIC。
- quantile return spread。
- turnover / holding decay。
- group neutral 可选。
- train / validation / out-of-sample split。
- cost-aware return，至少支持固定 bps 成本。

CLI：

```bash
uv run python scripts/alpha_evaluate.py --market cn --factor momentum_20d --start 2026-01-01 --end 2026-05-08 --forward-windows 1,5,20 --pretty
```

验收：

- 样本内和样本外分开展示。
- `rank_ic_mean`、`rank_ic_tstat`、`quantile_spread`、`turnover` 必须存在。
- 数据缺口必须进入 `data_gaps`。
- 已通过 `uv run pytest tests/test_alpha_evaluate_cli.py -q`。

### P3：快速回测引擎升级

目标：

- 在现有 `trading_strategy_backtest.py` 之外，增加组合级和参数网格回测能力。
- 第一阶段优先自研轻量 + 可选 `vectorbt` adapter，不直接引入 LEAN / Nautilus。

新增 / 修改文件：

- `src/services/backtest_engine.py`
- `src/services/vectorbt_backtest_adapter.py`
- `src/services/strategy_backtest_cli.py`
- `scripts/strategy_backtest.py`
- `tests/test_strategy_backtest_cli.py`

功能：

- 支持 signal matrix 输入。
- 支持 long-only top N / equal weight / volatility capped。
- 支持 rebalance frequency。
- 支持交易成本、滑点、最大单标的权重、最大持仓数。
- 支持参数网格扫描。

CLI：

```bash
uv run python scripts/strategy_backtest.py --market cn --strategy alpha_topn_v1 --start 2026-01-01 --end 2026-05-08 --top-n 10 --rebalance 1d --cost-bps 10 --pretty
```

验收：

- 输出 `total_return`、`annualized_return`、`max_drawdown`、`sharpe`、`turnover`、`win_rate`、`orders_total`。
- 任何回测结果都不能直接变成 active 策略。

### P4：策略版本 Registry 和人工审批链

状态：done，2026-05-09

目标：

- 让 Agent 的自我迭代建议进入结构化治理链，而不是直接改代码或改运行策略。

新增 / 修改文件：

- `src/repositories/strategy_registry_repository.py`
- `src/services/strategy_registry_service.py`
- `src/services/strategy_registry_cli.py`
- `scripts/strategy_registry.py`
- `tests/test_strategy_registry_cli.py`

SQLite 表：

- `strategy_versions`
- `strategy_approvals`
- `strategy_activation_history`
- `alpha_candidates`
- `alpha_evaluations`

CLI：

```bash
uv run python scripts/strategy_registry.py propose --proposal-json proposal.json --pretty
uv run python scripts/strategy_registry.py approve --strategy-version alpha_topn_v1.20260509 --approved-by ryan --pretty
uv run python scripts/strategy_registry.py activate --strategy-version alpha_topn_v1.20260509 --pretty
uv run python scripts/strategy_registry.py current --pretty
```

验收：

- 没有 approval record 的策略不能 active。
- active 策略只能有一个。
- 所有状态变化 append-only。
- Agent 只能生成 proposal，不能自动 approve / activate。
- 已通过 `uv run pytest tests/test_strategy_registry_cli.py -q`。

### P5：自动盯盘 Worker

目标：

- 把现有 tick CLI 组合成稳定运行的自动盯盘流程。
- 默认只读 + dry-run；Futu `SIMULATE` 必须显式配置。

新增 / 修改文件：

- `src/services/watch_worker_service.py`
- `src/services/watch_worker_cli.py`
- `scripts/watch_worker_tick.py`
- `ops/com.ryan.stock-analysis-watch.plist`
- `tests/test_watch_worker_tick_cli.py`

流程：

1. 读取 active strategy。
2. 拉取 watchlist / alpha candidate pool。
3. 读取行情 snapshot。
4. 生成 watch alerts。
5. 如启用模拟执行，调用 `trading_scheduler_tick.py`。
6. 写入 worker run 状态。
7. 输出 summary-only JSON。

验收：

- outside window 返回 `skipped`。
- not due 返回 `skipped`。
- provider 不可用返回 degraded，不吞异常。
- 不会真实下单。

### P6：盘后自我迭代报告

目标：

- 每天收盘后自动汇总行情、盯盘、模拟执行、Alpha 评估和候选策略变化。
- Agent 只生成候选 proposal 和解释，不自动应用。

新增 / 修改文件：

- `src/services/alpha_daily_report_service.py`
- `src/services/alpha_daily_report_cli.py`
- `scripts/alpha_daily_report.py`
- `tests/test_alpha_daily_report_cli.py`

输出：

- 当日行情概览。
- watch alerts 统计。
- simulated orders / risk decisions。
- alpha candidates top/bottom。
- factor evaluation drift。
- strategy proposal diff。
- human action required。

CLI：

```bash
uv run python scripts/alpha_daily_report.py --date 2026-05-09 --pretty
```

验收：

- 默认 summary-only。
- 明细必须 `--include-details`。
- 报告必须明确 `proposal_not_applied`。

### P7：Qlib 集成实验

目标：

- 将 Qlib 作为独立实验 adapter，不影响主路径。
- 先验证数据转换和 Alpha158 / 模型评估能否复用，再决定是否纳入主流程。

新增 / 修改文件：

- `docs/specs/qlib-adapter-experiment.md`
- `src/services/qlib_data_export_service.py`
- `src/services/qlib_experiment_cli.py`
- `scripts/qlib_experiment.py`
- `tests/test_qlib_data_export.py`

实验范围：

- SQLite daily -> Qlib compatible dataset。
- Alpha158 或自定义 feature set。
- 单模型训练 / 预测 / 回测。
- 输出与本仓库 `AlphaEvaluation` 对齐。

不做：

- 不把 Qlib trainer 放入盘中执行链路。
- 不让 Qlib 直接下单。
- 不要求所有策略迁移到 Qlib。

验收：

- 实验失败不影响 `watch_worker_tick.py`。
- 输出可映射到 `AlphaEvaluation`。

### P8：事件驱动回测评估

目标：

- 当策略复杂到需要订单簿、撮合、分钟线或多资产组合时，再评估 NautilusTrader / LEAN / Backtrader。

决策标准：

- 如果目标是 production-grade research-to-live parity，优先评估 NautilusTrader。
- 如果目标是多资产、券商模型、组合和云/本地混合生态，评估 LEAN。
- 如果目标是低频 Python 策略和学习成本低，评估 Backtrader。
- 如果目标是 Zipline / Alphalens 风格 pipeline，评估 zipline-reloaded，但不作为第一选择。

验收：

- 先完成 PoC，不直接替换主 backtest CLI。
- PoC 必须证明比当前 native/vectorbt 路线更适合目标策略。

## 自动化运行建议

### 日内

```bash
uv run python scripts/watch_worker_tick.py --market cn --state-key cn-alpha-watch --interval-seconds 300 --active-window 09:30-11:30,13:00-15:00 --pretty
```

### 盘后

```bash
uv run python scripts/alpha_scan.py --market cn --universe all --top 50 --pretty
uv run python scripts/alpha_evaluate.py --market cn --start 2026-01-01 --end 2026-05-09 --forward-windows 1,5,20 --pretty
uv run python scripts/alpha_daily_report.py --date 2026-05-09 --pretty
uv run python scripts/trading_strategy_review.py --date 2026-05-09 --min-runs 3 --pretty
```

## 风险与硬约束

- 禁止真实交易。
- 禁止 `unlock_trade`。
- 禁止订阅推送、提醒、自选股和 OpenD 配置写入。
- Agent 不能在日内链路直接决定下单。
- Agent 不能自动 approve / activate 策略。
- 任何 alpha 都必须经过样本外验证和成本 / 滑点评估。
- 回测报告必须标注数据来源、样本窗口、幸存者偏差、停牌 / 涨跌停 / 复权口径。
- 任何策略生效必须可回滚。

## 推荐实施顺序

1. P0 contract 与 spec。
2. P1 alpha scan MVP。
3. P2 factor evaluation。
4. P4 strategy registry 和审批链。
5. P3 vectorbt/native backtest upgrade。
6. P5 watch worker。
7. P6 daily self-iteration report。
8. P7 Qlib experiment。
9. P8 event-driven engine PoC。

## 第一轮最小可交付

第一轮不追求复杂 ML，只交付可用闭环：

1. `alpha_scan.py` 生成候选池。
2. `alpha_evaluate.py` 输出 IC / RankIC / quantile spread。
3. `strategy_registry.py` 保存 candidate proposal，但不自动生效。
4. `alpha_daily_report.py` 汇总并输出人工操作项。
5. 所有输出严格 JSON，Feishu 只展示 summary-only。

## 调研来源

- Qlib documentation: https://qlib.readthedocs.io/en/stable/
- Qlib GitHub: https://github.com/microsoft/qlib
- vectorbt documentation: https://vectorbt.dev/
- Alphalens documentation: https://quantopian.github.io/alphalens/
- NautilusTrader documentation: https://nautilustrader.io/docs/latest/concepts/overview
- LEAN documentation: https://www.quantconnect.com/docs/v2/lean-engine/getting-started
- LEAN GitHub: https://github.com/QuantConnect/Lean
- Backtrader documentation: https://www.backtrader.com/
- zipline-reloaded PyPI: https://pypi.org/project/zipline-reloaded/
- OpenBB Open Data Platform: https://openbb.co/products/odp
- vn.py PyPI: https://pypi.org/project/vnpy/
