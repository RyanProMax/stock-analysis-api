# CLI Reference

本文件是 `stock-analysis-skill` 的唯一 CLI 使用说明。

当前标准化能力统一直接调用同一 `stock-analysis-api` 仓库中的内部 CLI，本 skill
不维护 quote / analyze wrapper。

## 默认选择规则

以下请求默认直接走 CLI，不先走 Futu 或 Tushare：

- 单票客观分析
- 单票研报摘要
- 单票“最近怎么样”
- A 股股票 / ETF 标准化实时行情轮询
- 日报 / 定时内容任务的一次性中美指数与美债收盘数据包
- 用户明确要求的模拟盘 dry-run 单轮执行、回放或链路验证
- 用户明确要求的模拟盘盘后总结、策略评审或自我迭代方向

示例：

- “查 300627 的研报” 默认走 `stock_analyze.py`
- 只有“查 300627 的原始 report_rc 记录”才走 Tushare 直连
- 港 / 美 / 多市场 watchlist、盘口、逐笔、分时、K 线、期权链、账户、持仓、订单、成交和流水只读查询见 `references/futu.md`
- 港股 IPO 暗盘 / OTC 单次或定时查询默认走 `/otc` -> `grey_market_watch.py`；Futu 为正式 provider，未接入正式 API 的券商返回 `unsupported`
- “跑一轮模拟盘 dry-run” 默认走 `trading_run_once.py`，不得改成真实交易
- “定时轮询模拟盘”默认走 `trading_scheduler_tick.py`，不得让 Agent 在实时链路里直接判断是否下单
- “总结今天模拟盘表现 / 生成策略迭代方向”默认走 `trading_daily_summary.py` 与 `trading_strategy_review.py`，proposal 不自动应用
- “连接 Futu 模拟盘执行”必须显式传 `--broker futu-simulate`，默认不启用
- “回测当前策略 / 历史 K 线验证”默认走 `trading_strategy_backtest.py`，不读写 ledger，不触发 broker
- “生成日报行情数据包”默认走 `market_data_query.py daily-pack`，无需启动
  FastAPI，固定 `persistence=none`

## 环境变量

```bash
STOCK_ANALYSIS_API_ROOT="/absolute/path/to/stock-analysis-api"
STOCK_ANALYSIS_UV="/absolute/path/to/uv"
TUSHARE_TOKEN="your_token_here"
TUSHARE_HTTP_URL=""
TRADING_LEDGER_DB_PATH="/optional/path/to/trading_ledger.sqlite"
```

字段说明：

- `STOCK_ANALYSIS_API_ROOT`: 可选 API 根目录覆盖；同仓安装时 executor 会从
  `.agents/skills/stock-analysis/` 自动识别仓库根目录
- `STOCK_ANALYSIS_UV`: 固定 `uv` 可执行文件路径；未设置时 `/research` 按 `UV_BIN` / `UV` / PATH / `$HOME/.local/bin/uv` / `$HOME/.cargo/bin/uv` 查找，并在 prompt 中输出绝对路径
- `TUSHARE_TOKEN`: A 股 realtime / Tushare 直连能力需要
- `TUSHARE_HTTP_URL`: 可选，覆盖默认 Tushare 接口地址
- `TRADING_LEDGER_DB_PATH`: 可选，覆盖 API 侧模拟盘 ledger 路径

## 标准命令

### 1. realtime quote

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/poll_realtime_quotes.py --symbols 600000,510300 --pretty
```

参数：

- `--symbols`: 逗号分隔的 A 股 / ETF 代码
- `--pretty`: 可选，格式化 JSON

### 2. objective analyze

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/stock_analyze.py --market cn --symbols 300827 --mode base --pretty
```

参数：

- `--market`
- `--symbols`
- `--start-date`
- `--end-date`
- `--mode`
- `--pretty`

### 3. daily market pack

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/market_data_query.py daily-pack --cutoff-at 2026-07-29T13:00:00Z --persistence none
```

参数：

- `--cutoff-at`: 必填，带时区的 ISO datetime
- `--persistence`: 当前只允许 `none`
- `--pretty`: 可选，格式化 JSON

约束：

- 单次执行，不要求 FastAPI / Uvicorn 常驻。
- 固定返回 SPX、IXIC、DJI、DGS10、SSE、CSI300 六项日报指标。
- provider、fallback、截点和来源追踪由 API service 确定；调用 Agent 不自行改写。
- 不读写 API SQLite、scheduler state、watchlist 或券商状态。
- `status != ok`、六项不完整或 contract 不匹配时，调用方不得补编缺失行情。

### 4. Futu/OpenD readonly query

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py order-book --code HK.00700 --num 10 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py ticker --code HK.00700 --num 500 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py rt-data --code HK.00700 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py option-chain --code US.AAPL --start 2026-05-15 --end 2026-06-19 --option-type CALL --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py positions --market HK --code HK.00700 --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/futu_market_data.py orders --market HK --code HK.00700 --start 2026-05-01 --end 2026-05-07 --history --json
```

边界：

- 只允许查询；不得调用下单、改单、撤单、交易解锁、订阅或任何 OpenD 写入能力。
- 账户、持仓、订单、成交和流水查询固定为 Futu `SIMULATE` 只读路径。
- 账户类结果按最小必要原则展示，除非用户明确要求调试原始 JSON。

### 5. HK grey-market watch

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/grey_market_watch.py --once --code HK.02618 --name 剂泰医药 --issue-price 10 --providers futu,tiger,fosun --json
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/grey_market_watch.py --code HK.02618 --name 剂泰医药 --issue-price 10 --providers futu,tiger,fosun --interval-seconds 300 --json
```

参数：

- `--code`: Futu 港股代码，例如 `HK.02618`
- `--name`: 可选展示名
- `--issue-price`: 可选发行价，用于计算相对发行价涨跌幅
- `--providers`: 默认 `futu,tiger,fosun`
- `--order-book-depth`: 默认 5
- `--once`: 单次查询模式；仍校验暗盘时间窗，但不读取或写入 scheduler tick 状态
- `--state-db`: 可选，覆盖 scheduler tick 状态库路径；默认 API 仓库 `.cache/grey_market_watch.sqlite`
- `--interval-seconds`: 默认 10
- `--timezone`: 默认 `Asia/Shanghai`
- `--active-window`: 默认 `16:15-18:30`
- `--state-key`: 可选，不传时按标的 / provider / 发行价生成
- `--force`: 忽略时间窗和执行间隔，仅用于显式验证
- `--pretty`

边界：

- 只读查询，不下单、不改单、不撤单、不解锁交易、不订阅推送。
- Futu provider 使用 API 侧 OpenD snapshot / order book。
- Tiger / Fosun 等未接入正式授权 API 时只返回 `unsupported`，不得用网页抓取伪造报价。
- `/otc 07666.HK` 由 executor 映射到 `--once`；`/otc 07666.HK --loop=300s` 映射到 `--interval-seconds 300`。
- `--once` 不写 scheduler tick 状态；轮询 tick 可写 API 侧 scheduler tick 节流状态，但不写券商状态、不保存订单或 watchlist。

### 6. simulated trading dry-run

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_run_once.py --codes HK.00700 --buy-above HK.00700=0 --quantity 1 --max-order-notional 1000000
```

参数：

- `--codes`: 逗号分隔 Futu 格式代码，例如 `HK.00700`
- `--strategy-version`: 默认 `threshold-v1`
- `--buy-above`: 逗号分隔阈值，例如 `HK.00700=100`
- `--quantity`
- `--max-order-notional`
- `--ledger-db`: 可选，覆盖 SQLite ledger 路径
- `--snapshots-json`: 可选，注入离线行情快照做回放或测试
- `--broker`: `dry-run` 或 `futu-simulate`，默认 `dry-run`
- `--lock-name`: 默认 `trading_run_once`
- `--lock-ttl-seconds`: 默认 900
- `--disable-lock`: 只允许本地调试或显式验证使用

Futu 模拟盘显式 opt-in 示例：

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_run_once.py --broker futu-simulate --codes HK.00700 --buy-above HK.00700=100 --quantity 10 --max-order-notional 2000
```

约束：

- `--broker futu-simulate` 固定使用 Futu `TrdEnv.SIMULATE`。
- 该路径不得调用 `unlock_trade`。
- 该路径不能和 `--snapshots-json` 混用，避免用离线 / 测试行情触发模拟盘订单。

### 7. simulated trading scheduler tick

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_scheduler_tick.py --codes HK.00700 --buy-above HK.00700=0 --quantity 1 --max-order-notional 1000000
```

参数：

- 透传 dry-run 参数：`--codes`、`--strategy-version`、`--buy-above`、`--quantity`、`--max-order-notional`、`--ledger-db`、`--snapshots-json`、`--broker`
- `--interval-seconds`: 默认 300
- `--timezone`: 默认 `Asia/Shanghai`
- `--active-window`: 默认 `09:30-12:00,13:00-16:00`
- `--state-key`: 可选，不传时按策略参数生成
- `--force`: 忽略时间窗和间隔，仅用于显式验证

### 8. simulated trading daily summary

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_daily_summary.py --date 2026-05-07 --pretty
```

参数：

- `--ledger-db`: 可选，覆盖 SQLite ledger 路径
- `--date`: `YYYY-MM-DD`，不传时按 `--timezone` 取当天
- `--timezone`: 默认 `Asia/Shanghai`
- `--pretty`

### 9. simulated trading strategy review

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_strategy_review.py --date 2026-05-07 --min-runs 3 --pretty
```

参数：

- `--ledger-db`: 可选，覆盖 SQLite ledger 路径
- `--date`: `YYYY-MM-DD`，不传时按 `--timezone` 取当天
- `--timezone`: 默认 `Asia/Shanghai`
- `--min-runs`: 默认 3
- `--max-rejection-rate`: 默认 0.5
- `--pretty`

### 10. simulated trading strategy backtest

```bash
cd "$STOCK_ANALYSIS_API_ROOT" && "$STOCK_ANALYSIS_UV" run python scripts/trading_strategy_backtest.py --codes HK.00700 --buy-above HK.00700=100 --start 2026-05-01 --end 2026-05-07 --pretty
```

参数：

- `--codes`: 逗号分隔 Futu 格式代码
- `--strategy-version`: 默认 `threshold-v1`
- `--buy-above`: 逗号分隔阈值，例如 `HK.00700=100`
- `--quantity`
- `--max-order-notional`
- `--kline-json`: 可选，注入 K 线 JSON 字符串或文件路径
- `--start` / `--end`: 未传 `--kline-json` 时用于 Futu 历史 K 线
- `--ktype`: 默认 `1d`
- `--rehab`: 默认 `none`
- `--pretty`

## 原始 JSON 结构

### realtime quote

顶层：

- `status`
- `computed_at`
- `source`
- `request`
- `summary`
- `items`

单个 `item`：

- `requested_symbol`
- `status`
- `error`
- `info`
- `quote_data`

`quote_data`：

- `price`
- `change_pct`
- `change_amount`
- `open`
- `high`
- `low`
- `pre_close`
- `volume`
- `amount`
- `volume_ratio`
- `turnover_rate`
- `amplitude`
- `as_of`
- `source`
- `mode`

约束：

- `change_pct / turnover_rate / amplitude` 使用 ratio
- `mode` 当前只允许：
  - `realtime`
  - `legacy_realtime`

### objective analyze

顶层固定为 `StandardResponse`：

- `status_code`
- `data`
- `err_msg`

`data`：

- `status`
- `computed_at`
- `source`
- `market`
- `strategy`
- `request`
- `items`

主消费对象默认取 `data.items[0]`。

### daily market pack

顶层：

- `schema_version=market-data-query.v1`
- `status=ok|partial|failed`
- `source=market_data_query`
- `computed_at`
- `request.operation=daily_market_pack`
- `request.cutoff_at`
- `request.persistence=none`
- `summary`
- `data.markets`
- `data.failures`

`data.markets[]`：

- `symbol`
- `name`
- `region`
- `kind`
- `unit`
- `latest_value`
- `previous_value`
- `change_value`
- `change_ratio`
- `display_value`
- `display_change`
- `direction`
- `as_of`
- `provider`
- `source`
- `source_label`
- `provider_attempts`

约束：

- 输出是机器消费 contract，可由定时任务直接解析 raw JSON。
- `provider_attempts` 只表达来源成功、失败或不支持，不代表投资判断。
- `DGS10` 的 `latest_value` 单位为百分比，`display_change` 使用 bp。
- 该入口无持久化副作用。

### simulated trading dry-run

顶层：

- `status`
- `run_id`
- `strategy_version`
- `started_at`
- `finished_at`
- `source`
- `request`
- `account`
- `positions`
- `snapshots`
- `signals`
- `risk_decisions`
- `orders`
- `broker_mode`

约束：

- 成功执行时 `broker_mode` 必须是 `dry_run`。
- 拿不到调度锁时返回 `status=skipped`、`reason=lock_unavailable`，不应继续解读为失败或重复下单。
- 输出必须是严格 JSON，非有限数值会归一化为 `null`。
- 该入口只用于模拟执行、回放和审计；不得作为真实交易指令或投资建议。
- `--broker futu-simulate` 只在用户明确要求连接 Futu 模拟盘时使用；不能和 `--snapshots-json` 混用，不调用 `unlock_trade`。

### simulated trading scheduler tick

顶层：

- `status`
- `source`
- `schedule`
- `run_once`

跳过语义：

- `reason=outside_active_window`: 当前不在 active window。
- `reason=not_due`: 距离上次执行未达到 `--interval-seconds`。
- `run_once.reason=lock_unavailable`: 单轮 dry-run 锁冲突。

约束：

- `trading_scheduler_tick.py` 只做调度判断，不实现策略、风控或 broker。
- 到点后仍复用 `trading_run_once.py`；不得绕过 dry-run broker 和 SQLite ledger。
- 该入口适合 cron / launchd / Agent 高频调用。

### simulated trading daily summary

顶层：

- `status`
- `source=trading_daily_summary`
- `date`
- `timezone`
- `summary`
- `risk_reason_counts`
- `market`

默认不输出 ledger 明细，遵循最小必要原则；只保留盘后总结需要的计数、标的、策略版本、风控原因分布和行情首末变化。需要排障时才显式加 `--include-details`，额外返回：

- `orders`
- `risk_decisions`
- `runs`

约束：

- 只读 API 侧 SQLite ledger。
- `market` 使用 ledger 中已记录的 snapshot 做首末价格与变化比例汇总；缺失时不补编。
- 面向用户展示时默认转为北京时间。
- 面向用户默认使用 summary-only 输出，不原样转贴 `orders`、`risk_decisions`、`runs` 明细。

### simulated trading strategy review

顶层：

- `status`
- `source=trading_strategy_review`
- `date`
- `timezone`
- `review`
- `strategy_proposal`

`review.ledger_backtest`：

- `method=ledger_snapshot_replay`
- `runs_total`
- `orders_total`
- `risk_decisions_total`
- `rejection_rate`
- `order_mark_to_market`
- `average_order_return_ratio`

`strategy_proposal`：

- `schema_version=trading_strategy_proposal.v1`
- `status=candidate|blocked`
- `strategy_version`
- `approval_required=true`
- `effective_status=candidate_only|not_applied`
- `proposed_changes`
- `evidence`
- `constraints`

约束：

- 当前 `ledger_snapshot_replay` 只是基于已记录 snapshot 和 dry-run order 的回放式评估，不等同完整历史 K 线回测。
- proposal 只作为候选，不写策略配置、不改调度 state、不触发 broker。
- Agent 可以解释 proposal 和总结迭代方向，但不能在盘中链路里直接改策略或决定下单。

### simulated trading strategy backtest

顶层：

- `status`
- `source=trading_strategy_backtest`
- `strategy_version`
- `request`
- `summary`
- `results`

`summary`：

- `codes_total`
- `bars_total`
- `orders_total`
- `accepted_orders`
- `rejected_orders`
- `average_return_ratio`
- `total_unrealized_pnl`

约束：

- 只读历史 K 线或注入样本，不读写 ledger，不触发 broker。
- 当前回测口径是固定 threshold 策略的首个触发点建仓、样本最后一根 K 线 mark-to-market。
- 不包含交易成本、滑点、成交量约束或分钟线 / tick 级执行模型。

## 固定模板

默认优先输出固定模板，不默认附完整 raw JSON。只有用户明确要求调试 / 原始输出时，才附完整 JSON。

### realtime quote 模板

#### 请求

- symbols
- computed_at

#### 结果摘要

- `summary.ok`
- `summary.failed`
- 顶层 `status`

#### 逐标的行情

逐条汇总：

- `requested_symbol`
- `info.name`
- `quote_data.price`
- `quote_data.change_pct`
- `quote_data.change_amount`
- `quote_data.volume`
- `quote_data.mode`

#### 降级与异常

进入本节的条件：

- `item.status != ok`
- 或 `quote_data.mode != realtime`

### objective analyze 模板

#### 请求

- market
- symbols
- mode
- start_date / end_date

#### 执行状态

- `status_code`
- `data.status`
- `data.strategy`
- `item.status`
- `data.computed_at`

#### 客观分析摘要

只取 `data.items[0].summary.research_strategy`，并按固定顺序输出：

1. `expectations_vs_reported`
2. `fundamental_quality`
3. `valuation_context`
4. `catalyst_path`
5. `price_action_confirmation`
6. `cross_signal_alignment`
7. `risk_flags`
8. `evidence_strength`

#### 模块摘要

优先使用：

- `summary.technical`
- `summary.earnings`
- `summary.catalysts`
- `summary.screen`
- `summary.models`

#### 降级与限制

只取：

- `item.error`
- `item.meta.modules`

必须显式暴露：

- `partial`
- `permission_denied`
- `not_supported`
- 任何非 `ok` 模块状态

### simulated trading daily summary 模板

#### 请求

- `date`
- `timezone`
- ledger 来源

#### 当日摘要

- `summary.runs_total`
- `summary.orders_total`
- `summary.risk_decisions_total`
- `summary.accepted_risk_decisions`
- `summary.rejected_risk_decisions`
- `summary.codes`
- `summary.strategy_versions`

#### 行情与操作

- `market[].code`
- `market[].first_price`
- `market[].latest_price`
- `market[].change_ratio`
- `orders[].code`
- `orders[].side`
- `orders[].quantity`
- `orders[].price`
- `risk_reason_counts`

### simulated trading strategy review 模板

#### 评审状态

- `status`
- `review.gate_status`
- `review.gate_reasons`
- `review.ledger_backtest.method`

#### 回放式指标

- `review.ledger_backtest.runs_total`
- `review.ledger_backtest.orders_total`
- `review.ledger_backtest.rejection_rate`
- `review.ledger_backtest.average_order_return_ratio`
- `review.ledger_backtest.order_mark_to_market`

#### 策略候选

- `strategy_proposal.status`
- `strategy_proposal.strategy_version`
- `strategy_proposal.approval_required`
- `strategy_proposal.effective_status`
- `strategy_proposal.proposed_changes`
- `strategy_proposal.constraints`

必须明确说明：

- `ledger_snapshot_replay` 不是完整历史回测。
- proposal 未自动应用，仍需人工批准。

### simulated trading strategy backtest 模板

#### 请求

- `request.codes`
- `request.buy_above`
- `request.quantity`
- `request.max_order_notional`
- `request.source`
- `request.start` / `request.end`

#### 回测摘要

- `summary.bars_total`
- `summary.orders_total`
- `summary.accepted_orders`
- `summary.rejected_orders`
- `summary.average_return_ratio`
- `summary.total_unrealized_pnl`

#### 逐标的结果

- `results[].code`
- `results[].entry_time`
- `results[].entry_price`
- `results[].exit_time`
- `results[].exit_price`
- `results[].return_ratio`
- `results[].decision`

## 禁止事项

固定模板不得把源端字段升级成主观建议，不输出：

- `recommendation`
- `confidence`
- `price_target`
- `thesis`
- `conviction`
