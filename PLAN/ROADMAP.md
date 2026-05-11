# 自动盯盘、Alpha 挖掘与自我迭代路线图

更新时间：2026-05-11

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
- `scripts/alpha_backtest.py`：只读本地行情仓，输出 native long-only top-N equal-weight 组合回测 summary。
- `scripts/strategy_registry.py`：保存候选 strategy proposal、人工 approval、单 active strategy 指针和 append-only 状态事件。
- `scripts/alpha_daily_report.py`：盘后串联 Alpha scan / evaluate，输出 summary-only 报告和候选 proposal。
- `scripts/watch_worker_tick.py`：读取已审批 active strategy，按时间窗和间隔生成只读 watch summary。
- `scripts/strategy_judge.py`：由独立 evaluator 根据固定门槛输出 passed / blocked verdict；passed 只代表可进入人工审核，不自动审批或生效。
- `scripts/alpha_research_loop.py`：离线串联 researcher / backtester / evaluator 三类角色，按 factor 多轮尝试，输出 `human_review_ready` 或 `needs_iteration`。
- HK / US 的非显式 Alpha universe 当前只扫描本地已有日线覆盖的标的；显式 `--symbols` 会保留缺口并输出结构化 `missing_daily_history`，便于补库排障。

当前缺口：

- Alpha 扫描、因子评估、native 组合回测、成熟窗口自动截断、盘后日报、research loop run 记录、verdict 记录和 research-history 查询已有 MVP；后续仍需更完整的 HK / US 日线覆盖、参数搜索、模拟盘对照和失败归因策略生成。
- 因子评估已有 IC / RankIC / 分组收益 / 换手和样本切分，尚未覆盖 group neutral、holding decay 细分和更严格的样本外门槛。
- 策略版本 registry、审批记录、Alpha 日报、自动盯盘 worker、evaluator / judge gate 和离线 agent teams 编排已有 MVP；真实多 Agent 运行时和调度状态面尚未实现。
- 回测已有固定 threshold 策略与 native top-N 组合 MVP，尚未覆盖滑点、成交量容量、停牌 / 涨跌停、公司行动、复权口径和多因子组合参数搜索。
- 调度入口已有 CLI，但还缺统一 worker、运行状态面、失败重试、日报推送和异常告警。

## 开源库选型

### 采用优先级

1. Native services：第一阶段优先复用本仓库 SQLite 日线仓、`MarketSpec`、Alpha contract、judge gate 和 registry，避免引入重型运行时或旧因子库。
2. `vectorbt`：作为后续参数扫描和信号回测引擎备选。它基于 pandas / NumPy / Numba 做向量化回测，适合快速跑大量参数组合；接入前必须先有 adapter contract 和测试。
3. `Alphalens` 方法论：作为因子评估指标参考。优先在本仓库实现核心指标，避免直接引入老旧依赖导致兼容性风险；指标包括 forward returns、IC、quantile returns、turnover、grouped analysis。
4. `NautilusTrader` / `LEAN`：作为中长期事件驱动回测和 research-to-live parity 参考，不在 MVP 阶段直接接入。两者更适合复杂多资产、多 venue、组合级执行。
5. `Backtrader` / `zipline-reloaded`：作为低频事件驱动回测备选，不作为第一选择；当前 API 的高 ROI 路线应优先复用已有 SQLite 仓、Futu provider 和 CLI contract。
6. `OpenBB`：作为数据源整合和 provider extension 参考，不替代当前 Tushare / Futu 主链路。
7. `vn.py / VeighNa`：作为国内量化交易框架参考。当前不接入其交易网关，避免绕开已有 Futu `SIMULATE` 和只读护栏。
8. `Qlib`：只参考其 data / model / backtest / analysis 分层和实验组织思路，不接入 Qlib runtime、trainer、Alpha158 或旧因子定义；最终有效性只能由本仓库回测、模拟盘 ledger 和 judge gate 验证。

### 选型原则

- 先引入方法和数据 contract，再引入重型运行时。
- 第一阶段不得把自动交易主路径交给 Agent 或外部框架。
- 不引入 Qlib / Alpha158 作为 Alpha 自迭代主链路的因子来源。
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
  └─ backtest engine adapter: native first, vectorbt optional

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

状态：done，2026-05-10

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
  - 读取本地 `cn_symbols` / `hk_symbols` / `us_symbols`。
  - 支持 `--market cn/hk/us`、`--universe watchlist|all|etf|stock`。
  - 支持 `--symbols` 显式覆盖。
  - 非显式 universe 只返回本地已有 `daily_start_date` / `daily_end_date` 覆盖摘要的标的；显式 symbols 不过滤，缺日线时让下游输出缺口。
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
- 非显式 universe 不把无日线覆盖的目录标的扫入候选池；显式 symbols 仍能返回 `missing_daily_history`。
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
- `src/model/market.py`
- `scripts/alpha_evaluate.py`
- `tests/test_alpha_evaluate_cli.py`
- `tests/test_market_spec.py`

功能：

- forward returns：1D / 3D / 5D / 10D / 20D。
- 请求 end 自动按最大 forward window 截到最后一个成熟样本日，并输出 `summary.effective_end`。
- IC / RankIC。
- quantile return spread。
- turnover / holding decay。
- group neutral 可选。
- train / validation / out-of-sample split。
- cost-aware return：显式 `--cost-bps` 使用固定 bps；未显式传参时使用 `MarketSpec` 的 CN / HK / US 默认 round-trip 成本。
- `MarketSpec` 独立维护市场币种、时区、常规交易时段、默认 lot / tick 和估算成本，避免在 Alpha 评估逻辑里散落市场判断。

CLI：

```bash
uv run python scripts/alpha_evaluate.py --market cn --factor momentum_20d --start 2026-01-01 --end 2026-05-08 --forward-windows 1,5,20 --pretty
```

验收：

- 样本内和样本外分开展示。
- `rank_ic_mean`、`rank_ic_tstat`、`quantile_spread`、`turnover` 必须存在。
- 数据缺口必须进入 `data_gaps`。
- HK / US 未传 `--cost-bps` 时输出 `cost_model.type=market_spec_bps`。
- 已通过 `uv run pytest tests/test_alpha_evaluate_cli.py -q`。

### P3：快速回测引擎升级

状态：partial，2026-05-11

目标：

- 在现有 `trading_strategy_backtest.py` 之外，增加组合级和参数网格回测能力。
- 第一阶段优先自研轻量 + 可选 `vectorbt` adapter，不直接引入 Qlib / LEAN / Nautilus。

新增 / 修改文件：

- `src/services/alpha_backtest_service.py`
- `src/services/alpha_backtest_cli.py`
- `scripts/alpha_backtest.py`
- `tests/test_alpha_backtest_cli.py`
- 后续再评估是否新增 `src/services/vectorbt_backtest_adapter.py`

功能：

- 已支持 long-only top N / equal weight native 回测。
- 已支持 holding period、成熟窗口自动截断、MarketSpec 成本和 fixed bps override。
- 后续支持 signal matrix、volatility capped、rebalance frequency、滑点、最大单标的权重、最大持仓数。
- 支持参数网格扫描。

CLI：

```bash
uv run python scripts/alpha_backtest.py --market cn --factor momentum_5d --start 2026-01-01 --end 2026-05-08 --top-n 10 --holding-period 1 --pretty
uv run python scripts/alpha_backtest.py --market hk --symbols HK.00700,HK.09988 --factor momentum_5d --top-n 2 --include-details --pretty
```

验收：

- 输出 `total_return`、`annualized_return`、`max_drawdown`、`sharpe`、`turnover`、`win_rate`、`orders_total`。
- 任何回测结果都不能直接变成 active 策略。
- 已通过 `uv run pytest tests/test_alpha_backtest_cli.py -q`。

### P4：策略版本 Registry 和人工审批链

状态：done，2026-05-10

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

状态：done，2026-05-09

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
- 已通过 `uv run pytest tests/test_watch_worker_tick_cli.py -q`。

### P5.1：独立 Evaluator / Judge Gate

状态：done，2026-05-09

目标：

- 把“模型自研迭代”和“最终评估放行”拆成不同角色，避免同一个 Agent 既开发、回测又最终评估。
- 在候选策略进入人工审核前，由独立 evaluator 按固定门槛输出结构化 verdict。
- 可选读取 active champion verdict 做 champion/challenger 相对增量评估，避免只过绝对阈值就进入人工审核。
- verdict 不得自动 approve / activate，passed 只代表 `human_review_ready=true`。

新增 / 修改文件：

- `src/services/strategy_judge_service.py`
- `src/services/strategy_judge_cli.py`
- `scripts/strategy_judge.py`
- `src/model/strategy.py`
- `src/repositories/strategy_registry_repository.py`
- `src/services/strategy_registry_service.py`
- `src/services/strategy_registry_cli.py`
- `tests/test_strategy_judge_cli.py`

CLI：

```bash
uv run python scripts/strategy_judge.py --proposal-json proposal.json --evaluation-json evaluation.json --evaluator-id judge-agent --researcher-id researcher-agent --pretty
uv run python scripts/strategy_judge.py --proposal-json proposal.json --evaluation-json evaluation.json --champion-json active-verdict.json --min-challenger-rank-ic-delta 0.01 --min-challenger-quantile-spread-delta 0.005 --evaluator-id judge-agent --researcher-id researcher-agent --pretty
uv run python scripts/strategy_registry.py record-verdict --verdict-json verdict.json --pretty
```

验收：

- `evaluator_id == researcher_id` 必须 blocked。
- 指标未达 `rank_ic_mean`、`quantile_spread`、`turnover`、`observations` 或存在 data gaps 时必须 blocked。
- passed verdict 返回原 `strategy_proposal` 和 `human_review_ready=true`。
- blocked verdict 不返回 `strategy_proposal`。
- 提供 champion verdict 时，challenger 未达到配置的 RankIC / spread 增量必须 blocked。
- registry 只 append verdict，不创建 approval、不 activate。
- 已通过 `uv run pytest tests/test_strategy_judge_cli.py -q`。

### P5.2：离线 Agent Teams Research Loop

状态：done，2026-05-10

目标：

- 把 researcher / backtester / evaluator 的职责分开，形成可被 Agent 调度的离线自迭代 contract。
- 在未达到 judge 门槛前自动尝试下一组 factor；达到门槛后只输出给人工审核。
- 持有 registry 且存在 active strategy 时，自动把 active strategy 对应的 passed judge verdict 作为 champion 交给 evaluator；CLI 传 `--registry-db` 即可只读使用 champion，不要求写 registry。
- 默认不写 registry、不 approve、不 activate、不触发 broker。

新增 / 修改文件：

- `src/services/alpha_research_loop_service.py`
- `src/services/alpha_research_loop_cli.py`
- `scripts/alpha_research_loop.py`
- `tests/test_alpha_research_loop_cli.py`

CLI：

```bash
uv run python scripts/alpha_research_loop.py --market cn --factors momentum_5d,momentum_20d --researcher-id researcher-agent --backtester-id backtester-agent --evaluator-id judge-agent --pretty
```

验收：

- researcher / backtester / evaluator 三类 role id 必须互不相同。
- 通过 judge gate 时返回 `status=human_review_ready`、候选 proposal 和 verdict。
- 全部 attempt blocked 时返回 `status=needs_iteration` 与 `next_research_actions`。
- 有 active champion 时，challenger 未相对改善会进入 `needs_iteration`，不会替代当前 active strategy。
- 默认 summary-only，不输出完整 report 明细；明细必须显式 `--include-attempt-details`。
- 默认不写 registry；显式 `--record-to-registry` 时只追加 research loop run 和 judge verdict，不创建 approval、不 activate。
- `strategy_registry.py research-history` 可汇总历史 run、阻断原因和同 factor 指标漂移。
- `approve` 必须已有同 strategy version 的 passed judge verdict；`activate` 只允许 approved strategy。
- 已通过 `uv run pytest tests/test_alpha_research_loop_cli.py -q`。

### P6：盘后自我迭代报告

状态：done，2026-05-09

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
- 已通过 `uv run pytest tests/test_alpha_daily_report_cli.py -q`。

### P7：模拟盘验证闭环强化

目标：

- 将 native backtest 的候选策略与 dry-run / Futu `SIMULATE` ledger 做对照，验证回测收益是否能在模拟盘执行中复现。
- 建立 champion / challenger 的多轮持久化对比，避免只看单次回测结果。

新增 / 修改文件：

- `docs/specs/simulated-alpha-validation.md`
- `src/services/alpha_simulation_validation_service.py`
- `src/services/alpha_simulation_validation_cli.py`
- `scripts/alpha_simulation_validate.py`
- `tests/test_alpha_simulation_validation_cli.py`

范围：

- 将 strategy proposal、alpha backtest summary、research-history 和 trading ledger 按 strategy version 关联。
- 对比回测指标、模拟盘执行收益、成交约束、风控拒绝、滑点假设偏差。
- 多轮次输出 champion / challenger 变化和失败归因。

不做：

- 不自动 approve / activate。
- 不真实下单，不交易解锁，不订阅推送。
- 不把模拟盘短期结果包装成真实策略有效性结论。

验收：

- validation 输出严格 JSON，可进入 judge evidence。
- 不影响 `watch_worker_tick.py`。
- 人工审核只接收 evaluator 通过后的候选。

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
uv run python scripts/alpha_backtest.py --market cn --factor momentum_5d --start 2026-01-01 --end 2026-05-09 --top-n 10 --pretty
uv run python scripts/alpha_daily_report.py --date 2026-05-09 --pretty
uv run python scripts/strategy_judge.py --proposal-json proposal.json --evaluation-json evaluation.json --evaluator-id judge-agent --researcher-id researcher-agent --pretty
uv run python scripts/alpha_research_loop.py --market cn --factors momentum_5d,momentum_20d --researcher-id researcher-agent --backtester-id backtester-agent --evaluator-id judge-agent --record-to-registry --pretty
uv run python scripts/strategy_registry.py research-history --pretty
uv run python scripts/trading_strategy_review.py --date 2026-05-09 --min-runs 3 --pretty
```

## 风险与硬约束

- 禁止真实交易。
- 禁止 `unlock_trade`。
- 禁止订阅推送、提醒、自选股和 OpenD 配置写入。
- Agent 不能在日内链路直接决定下单。
- Agent 不能自动 approve / activate 策略。
- 任何 alpha 都必须经过样本外验证和成本 / 滑点评估。
- 回测报告必须标注数据来源、样本窗口、本地日线覆盖范围、幸存者偏差、停牌 / 涨跌停 / 复权口径。
- 任何策略生效必须可回滚。

## 推荐实施顺序

1. P0 contract 与 spec。
2. P1 alpha scan MVP。
3. P2 factor evaluation。
4. P4 strategy registry 和审批链。
5. P3 vectorbt/native backtest upgrade。
6. P5 watch worker。
7. P6 daily self-iteration report。
8. P7 simulation validation loop。
9. P8 event-driven engine PoC。

## Agent Teams 治理原则

- Researcher Agent：负责提出因子、候选池和策略调整方向，可以在未达标前自动迭代研究。
- Backtester Agent：负责独立回测、成本 / 滑点 / 样本外验证和失败归因，不改策略状态。
- Evaluator / Judge Agent：负责基于固定门槛输出结构化 verdict，不能参与策略开发和参数选择。
- Human Reviewer：只审核 evaluator 通过后的候选 strategy proposal，不参与每一轮草稿研究。
- 系统不允许同一个 Agent 同时完成开发、回测和最终评估，避免结果偏宽松和反馈回路失真。
- 自动 approve / activate 默认关闭；如未来只在 `SIMULATE` 环境开放，也必须有显式配置、judge gate、冷却期、回滚和最大变更幅度限制。

## 第一轮最小可交付

第一轮不追求复杂 ML，只交付可用闭环：

1. `alpha_scan.py` 生成候选池。
2. `alpha_evaluate.py` 输出 IC / RankIC / quantile spread。
3. `alpha_backtest.py` 输出组合级收益、回撤、夏普、换手和胜率。
4. `strategy_registry.py` 保存 candidate proposal，但不自动生效。
5. `alpha_daily_report.py` 汇总并输出人工操作项。
6. `strategy_judge.py` 由独立 evaluator 基于 evaluation + backtest evidence 输出可审核 verdict。
7. `alpha_research_loop.py` 串联多 factor 尝试，输出 `human_review_ready` 或 `needs_iteration`。
8. `strategy_registry.py research-history` 汇总 run history、阻断原因和 factor drift。
9. 所有输出严格 JSON，Feishu 只展示 summary-only。

## 调研来源

- vectorbt documentation: https://vectorbt.dev/
- Alphalens documentation: https://quantopian.github.io/alphalens/
- NautilusTrader documentation: https://nautilustrader.io/docs/latest/concepts/overview
- LEAN documentation: https://www.quantconnect.com/docs/v2/lean-engine/getting-started
- LEAN GitHub: https://github.com/QuantConnect/Lean
- Backtrader documentation: https://www.backtrader.com/
- zipline-reloaded PyPI: https://pypi.org/project/zipline-reloaded/
- OpenBB Open Data Platform: https://openbb.co/products/odp
- vn.py PyPI: https://pypi.org/project/vnpy/
