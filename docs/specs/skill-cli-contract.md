# Skill / Agent CLI Contract

更新时间：2026-05-07

本文件是 `stock-analysis-api` 内部 skill / agent CLI contract 的唯一规格说明，不属于公共 HTTP API 文档。

## 目标

- 让外部 `stock-analysis-skill` 与其他 agent 直接消费本仓库 CLI
- 统一内部脚本的输入、输出、状态语义和降级规则
- 保证 CLI stdout 始终为机器可读 JSON

## CLI 列表

### 1. `scripts/stock_analyze.py`

用途：

- 当前唯一客观分析 CLI
- 能力与 `POST /stock/analyze` 保持同构

参数：

- `--market`
- `--symbols`: 逗号分隔；支持标准代码，也支持中文股票名 / 公司名输入
- `--start-date`
- `--end-date`
- `--mode`
- `--pretty`

输出：

- 顶层固定为 `StandardResponse`
- `data` 内部 payload 固定为：
  - `status`
  - `computed_at`
  - `source`
  - `market`
  - `strategy`
  - `request`
  - `items`

说明：

- 本 CLI 继续作为 skill / agent 的唯一客观分析入口
- `--symbols` 若为明确代码，直接进入分析服务；若为中文股票名 / 公司名，CLI 先查询 `symbol_catalog_service.search_symbols`。
- 股票名解析语义：唯一精确匹配或唯一候选时，传递标准 `symbol` 给分析服务；无匹配返回 `identity_not_found`；多候选返回 `identity_conflict` 并附候选 `symbol / ts_code / name / market / exchange`。
- 解析失败仍输出 `StandardResponse` JSON，`data.items[0].status = failed`，不输出裸异常。
- 不输出自由文本总结、主观 thesis、confidence 或 target price

### 2. `scripts/poll_realtime_quotes.py`

用途：

- 批量查询 A 股 / ETF 最新日内行情
- 为 skill / agent 提供低 token 的 quote polling 结果

参数：

- `--symbols`
- `--pretty`

输出：

- 顶层固定返回：
  - `status`
  - `computed_at`
  - `source`
  - `request`
  - `summary`
  - `items`
- 单个 item 固定返回：
  - `requested_symbol`
  - `status`
  - `error`
  - `info`
  - `quote_data`

`quote_data` 固定字段：

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

语义约束：

- `change_pct / turnover_rate / amplitude` 一律使用 ratio 机器值
- `mode` 当前仅允许：
  - `realtime`
  - `legacy_realtime`
- `status` 当前仅允许：
  - `ok`
  - `partial`
  - `failed`

### 3. `scripts/futu_market_data.py`

用途：

- Futu/OpenD 内部只读查询 CLI
- 供 `/hkipo`、`/research`、多市场 watchlist 和账户只读查询消费
- 不属于公共 HTTP API，不承载任何写入、订阅或交易解锁能力

子命令：

- `global-state`: OpenD 行情登录和市场状态预检
- `ipo-list --market HK`: IPO 当前池查询
- `snapshot --codes HK.00700,US.AAPL`: 多市场行情快照
- `symbol-rules --codes HK.00700,US.AAPL`: 逐标的 lot size / tick 规则，只读来自 Futu snapshot，缺失时回退到 `MarketSpec`
- `kline --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD`: 历史 K 线
- `order-book --code HK.00700 --num 10`: 盘口
- `ticker --code HK.00700 --num 500`: 逐笔成交
- `rt-data --code HK.00700`: 分时数据
- `option-expirations --code US.AAPL`: 期权到期日
- `option-chain --code US.AAPL --start YYYY-MM-DD --end YYYY-MM-DD --option-type CALL|PUT|ALL`: 期权链
- `account --market HK --currency HKD`: Futu `SIMULATE` 账户资金只读查询
- `positions --market HK --code HK.00700`: Futu `SIMULATE` 持仓只读查询
- `orders --market HK --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD --history`: Futu `SIMULATE` 订单只读查询
- `deals --market HK --code HK.00700 --start YYYY-MM-DD --end YYYY-MM-DD --history`: Futu `SIMULATE` 成交只读查询
- `cash-flow --market HK --clearing-date YYYY-MM-DD`: Futu `SIMULATE` 流水只读查询

输出语义：

- 顶层固定包含：
  - `status`
  - `source=futu_opend`
  - `request` 或命令对应的请求摘要
  - `data`
- 账户相关只读命令额外包含：
  - `environment=SIMULATE`
  - `market`
- stdout 必须是标准 JSON；Futu SDK stdout / warning 必须被屏蔽。
- 不暴露 `place-order`、`modify-order`、`cancel-order`、`unlock-trade`、`subscribe` 等写入类子命令。

### 4. `scripts/trading_run_once.py`

用途：

- 模拟盘自动交易一期的内部单次执行 CLI
- 供 agent / worker / cron / launchd 调用确定性 `run_once` 流程
- 默认只使用 dry-run broker，不连接真实交易环境

参数：

- `--codes`: 逗号分隔，使用 Futu 格式，例如 `HK.00700`
- `--strategy-version`
- `--buy-above`: 逗号分隔阈值，例如 `HK.00700=100`
- `--quantity`
- `--max-order-notional`
- `--ledger-db`: 覆盖 SQLite ledger 路径；未传时读取 `TRADING_LEDGER_DB_PATH` 或 `.cache/trading_ledger.sqlite`
- `--lock-name`: SQLite 调度锁名称，默认 `trading_run_once`
- `--lock-ttl-seconds`: 调度锁 TTL，默认 900 秒
- `--disable-lock`: 关闭调度锁，仅用于本地调试或显式验证
- `--snapshots-json`: 行情快照 JSON 字符串或文件路径；用于测试、回放和离线验证
- `--account-cash`
- `--currency`
- `--broker`: `dry-run` 或 `futu-simulate`，默认 `dry-run`
- `--pretty`

输出：

- 顶层固定返回：
  - `status`
  - `run_id`
  - `strategy_version`
  - `started_at`
  - `request`
  - `source`
  - `broker_mode`
  - `account`
  - `positions`
  - `snapshots`
  - `signals`
  - `risk_decisions`
  - `orders`
  - `finished_at`

语义约束：

- CLI stdout 必须是纯 JSON。
- `--snapshots-json` 存在时只使用注入行情，不连接 Futu/OpenD。
- 未传 `--snapshots-json` 时允许读取 Futu/OpenD snapshot，但 broker 仍固定为 dry-run。
- 只有显式传 `--broker futu-simulate` 时，broker 才连接 Futu `SIMULATE` 环境。
- `--broker futu-simulate` 固定 `TrdEnv.SIMULATE`，禁止调用 `unlock_trade`，并且不允许和 `--snapshots-json` 混用。
- 已通过风控并提交过的订单必须写入 SQLite ledger，`idempotency_key` 跨进程生效。
- 重复执行同一策略版本、代码、方向、数量和触发价时，不得重复提交 dry-run broker 订单。
- 默认必须先拿 SQLite `trading_run_once` 调度锁；拿不到锁时返回 `status=skipped`、`reason=lock_unavailable`，不得继续读取行情或提交 dry-run broker。

## 数据源与降级规则

### `stock_analyze.py`

- 按既有 `stock_analyze_service` 流程执行
- 来源、partial、permission 等状态语义沿用现有 `meta.modules`

### `poll_realtime_quotes.py`

- 当前固定为 Tushare-only
- 身份信息：
  - `stock_basic`
  - `etf_basic`
- 行情优先级：
  1. `quotation`
  2. 旧版 `get_realtime_quotes`

降级规则：

- 只要 `quotation` 未成功但 legacy realtime 成功：
  - item `status = ok`
  - `quote_data.mode = legacy_realtime`
- 若两条链路都失败：
  - item `status = failed`
  - `quote_data = null`

### `trading_run_once.py`

- 行情来源：
  - `--snapshots-json` 注入的静态行情
  - 或 Futu/OpenD snapshot
- broker 当前固定为 dry-run broker
- 审计与幂等固定写入 SQLite trading ledger
- 不新增公共 HTTP API，不调用外部 `futuapi` skill 脚本

### 5. `scripts/trading_scheduler_tick.py`

用途：

- cron / launchd / Agent 的模拟盘调度 tick 入口
- 到点后复用 `trading_run_once.py` 的单轮执行能力
- 只做时间窗、执行间隔和 state key 判断，不实现策略或 broker 逻辑

关键参数：

- 透传 `trading_run_once.py` 参数：`--codes`、`--strategy-version`、`--buy-above`、`--quantity`、`--max-order-notional`、`--ledger-db`、`--snapshots-json`、`--broker`
- 调度参数：
  - `--interval-seconds`: 默认 300
  - `--timezone`: 默认 `Asia/Shanghai`
  - `--active-window`: 默认 `09:30-12:00,13:00-16:00`
  - `--state-key`: 可选，不传时按策略参数生成
  - `--force`: 忽略时间窗和执行间隔

输出语义：

- 到点执行：顶层 `status=ok`，`run_once` 保存单轮执行结果。
- 未到时间窗：`status=skipped`、`reason=outside_active_window`。
- 未到执行间隔：`status=skipped`、`reason=not_due`。
- 单轮执行锁冲突：`status=skipped`，`run_once.reason=lock_unavailable`。

### 6. `scripts/grey_market_watch.py`

用途：

- 港股 IPO 暗盘 / grey market / OTC 只读监听入口。
- 支持单次查询，也供 cron / launchd / Agent 在暗盘时段定时查询。
- 聚合 provider capability 状态；当前 Futu 为正式 provider，Tiger / Fosun 等未接入正式授权 API 时返回 `unsupported`。

关键参数：

- `--code`: Futu 港股代码，例如 `HK.02618`
- `--name`: 可选展示名
- `--issue-price`: 可选发行价，用于计算相对发行价涨跌幅
- `--providers`: 默认 `futu,tiger,fosun`
- `--order-book-depth`: 默认 5
- `--once`: 单次查询模式；仍校验 `--active-window`，但不读取或写入 scheduler tick 状态
- `--state-db`: SQLite scheduler tick 状态库路径，默认 `.cache/grey_market_watch.sqlite`
- `--interval-seconds`: 默认 10
- `--timezone`: 默认 `Asia/Shanghai`
- `--active-window`: 默认 `16:15-18:30`
- `--state-key`: 可选，不传时按标的、provider 和发行价生成
- `--force`: 忽略时间窗和执行间隔
- `--pretty`

输出语义：

- 单次查询：顶层 `status=ok`、`source=grey_market_watch_once`，`watch` 保存本次暗盘快照，不受 scheduler tick 节流影响。
- 到点执行：顶层 `status=ok`、`source=grey_market_watch_tick`，`watch` 保存本次暗盘快照。
- 未到时间窗：`status=skipped`、`reason=outside_active_window`。
- 未到执行间隔：`status=skipped`、`reason=not_due`。
- provider 未接入正式 API：provider item `status=unsupported`，不补编报价。

安全边界：

- 只读查询，不下单、不改单、不撤单、不解锁交易、不订阅推送。
- 不把单一券商暗盘报价解释为全市场价格。

### 7. `scripts/trading_daily_summary.py`

用途：

- 模拟盘盘后总结入口
- 只读 SQLite trading ledger，汇总当日 run、snapshot、risk decision 和 dry-run order
- 供 Agent 盘后总结消费，不进入盘中执行链路

关键参数：

- `--ledger-db`: 覆盖 SQLite ledger 路径
- `--date`: `YYYY-MM-DD`，不传时按 `--timezone` 取当天
- `--timezone`: 默认 `Asia/Shanghai`
- `--include-details`: 显式输出 `orders` / `risk_decisions` / `runs` 明细；默认不输出
- `--pretty`

输出语义：

- 顶层默认返回 summary-only：
  - `status`
  - `source=trading_daily_summary`
  - `date`
  - `timezone`
  - `summary`
  - `risk_reason_counts`
  - `market`
- 显式传 `--include-details` 时才额外返回：
  - `orders`
  - `risk_decisions`
  - `runs`
- `summary` 至少包含：
  - `runs_total`
  - `orders_total`
  - `risk_decisions_total`
  - `accepted_risk_decisions`
  - `rejected_risk_decisions`
  - `codes`
  - `strategy_versions`
- 默认输出遵循最小必要原则：只给用户盘后总结需要的计数、标的、策略版本、风控原因分布和行情首末变化；明细仅供调试或策略评审内部使用。

### 8. `scripts/trading_strategy_review.py`

用途：

- 模拟盘盘后策略评审入口
- 基于 `trading_daily_summary.py` 同一套 ledger summary 生成 ledger replay 指标和结构化 `strategy_proposal`
- Agent 可消费 proposal 做解释和迭代方向讨论，但本 CLI 不应用策略、不写配置、不触发下单

关键参数：

- `--ledger-db`: 覆盖 SQLite ledger 路径
- `--date`: `YYYY-MM-DD`，不传时按 `--timezone` 取当天
- `--timezone`: 默认 `Asia/Shanghai`
- `--min-runs`: 最小 run 数，默认 3
- `--max-rejection-rate`: 最大风控拒绝率，默认 0.5
- `--pretty`

输出语义：

- 顶层固定返回：
  - `status=ok|blocked|failed`
  - `source=trading_strategy_review`
  - `date`
  - `timezone`
  - `review`
  - `strategy_proposal`
- `review.ledger_backtest.method` 当前固定为 `ledger_snapshot_replay`，表示只用 ledger 内已有 snapshot 与 dry-run order 做回放式评估，不等同完整历史 K 线回测。
- `strategy_proposal` 固定包含：
  - `schema_version=trading_strategy_proposal.v1`
  - `status=candidate|blocked`
  - `strategy_version`
  - `approval_required=true`
  - `effective_status=candidate_only|not_applied`
  - `proposed_changes`
  - `evidence`
  - `constraints`

### 9. `scripts/trading_strategy_backtest.py`

用途：

- 模拟盘策略历史 K 线回测入口
- 基于注入 K 线 JSON 或 Futu/OpenD 历史 K 线，离线回测固定 threshold 策略
- 不读写 ledger、不触发 broker、不生成实时交易指令

关键参数：

- `--codes`: 逗号分隔 Futu 格式代码
- `--strategy-version`
- `--buy-above`: 逗号分隔阈值，例如 `HK.00700=100`
- `--quantity`
- `--max-order-notional`
- `--kline-json`: 可选，K 线 JSON 字符串或文件路径
- `--start` / `--end`: 未传 `--kline-json` 时用于 Futu 历史 K 线
- `--ktype`: 默认 `1d`
- `--rehab`: 默认 `none`
- `--pretty`

输出语义：

- 顶层固定返回：
  - `status=ok|failed`
  - `source=trading_strategy_backtest`
  - `strategy_version`
  - `request`
  - `summary`
  - `results`
- `summary` 至少包含：
  - `codes_total`
  - `bars_total`
  - `orders_total`
  - `accepted_orders`
  - `rejected_orders`
  - `average_return_ratio`
  - `total_unrealized_pnl`
- 单个 `results[]` 至少包含：
  - `code`
  - `bars_total`
  - `entry_time`
  - `entry_price`
  - `exit_time`
  - `exit_price`
  - `return_ratio`
  - `unrealized_pnl`
  - `decision`

## 输出质量要求

- CLI stdout 必须是纯 JSON，不得混入初始化日志或调试 print
- CLI 成功路径不得向 stderr 输出 SDK warning / log 噪声
- JSON 输出必须是标准 JSON，`NaN` / `Infinity` 等非有限数值统一归一化为 `null`
- 失败也应尽量输出结构化 JSON，而不是裸异常堆栈
- 该 contract 仅供内部 skill / agent 消费，不写入 `docs/api.md`
