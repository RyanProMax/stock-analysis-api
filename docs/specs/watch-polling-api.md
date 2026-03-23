# 盯盘轮询 API 规格

更新时间：2026-03-23

## 目标

- 为外部 Agent 提供单接口、多股票、5-10 分钟级别的盯盘轮询能力
- 默认输出 compact snapshot，降低 token 成本
- 由服务端内部维护 symbol 级 baseline，自动生成 delta 与 alerts

## 对外接口

### `POST /watch/poll`

请求体：

- `symbols: string[]`

处理规则：

- 统一清洗、去重、保序
- 支持 A 股和美股同时轮询
- 服务端按 `symbol` 在进程内内存中维护最近一次 snapshot 作为 baseline
- 首次无 baseline 时返回 `delta.status = initial`
- baseline 不落 SQLite，服务重启后重新进入 `initial`

返回结构：

- 顶层使用 `StandardResponse[List[StructuredInterfaceResponse]]`
- 每个 item 包含：
  - `entity.symbol`
  - `entity.name`
  - `entity.market`
  - `facts.quote`
  - `facts.fundamentals`
  - `analysis.delta`
  - `analysis.alerts`
  - `analysis.technical`
  - `analysis.earnings_watch`
  - `meta.computed_at`
  - `meta.source_chain`
  - `meta.baseline_at`
  - `meta.poll_interval_hint`
  - `meta.status`
  - `meta.partial`
  - `meta.degradation`

补充语义：

- `quote.mode` 仅允许：
  - `realtime`
  - `daily_fallback`
  - `unavailable`
- 当任一市场仅拿到 latest available daily snapshot 时，必须：
  - 返回 `quote.mode = daily_fallback`
  - 返回 `meta.partial = true`
  - 不得将整体状态标记为等同 realtime 的完整 `ok`
- 对 A 股“盘中最新数据”的验收必须同时满足：
  - `quote.mode = realtime`
  - `meta.degradation.quote_is_realtime = true`
  - `quote.as_of` 为当前请求时间，而不是最新日线日期
- `meta.degradation` 至少包含：
  - `quote_mode`
  - `quote_is_realtime`
  - `quote_fallback_used`
  - `fundamentals_partial`
  - `earnings_partial`
- `analysis.earnings_watch.next_earnings_date` 的提取顺序应尽量覆盖：
  - `raw_data.info`
  - `raw_data.calendar`
  - `raw_data.earnings_dates`
- 多个候选财报日期同时存在时，应优先返回未来最近的日期

## 服务端规则

- `price_jump_up`
- `price_jump_down`
- `volume_spike`
- `turnover_spike`
- `near_day_high`
- `near_day_low`
- `breakout_up`
- `breakout_down`
- `earnings_soon`

每条 alert 统一包含：

- `code`
- `severity`
- `summary`
- `evidence`
- `symbol`
- `as_of`

## 实现约束

- 只保留一个公共盯盘接口，不新增 cursor / monitor_id / health / rules 公共接口
- 盯盘 route 层不复用 `/stock/analyze`、`/earnings`、`/competitive` 的整包输出
- baseline cache 以 `symbol` 为 key，TTL 为 24 小时
- A 股历史日线优先使用本地 SQLite canonical 日线仓，缺失时通过 `daily_data_read_service -> daily_data_write_service` 自动补数并回写
- A 股实时行情链路固定优先级为：
  - `Tushare`
  - `Efinance`
  - `Pytdx`
- 美股实时行情链路固定为：
  - `Yfinance`
- A 股 `facts.fundamentals` 固定走轻量基本面模式：
  - 优先使用 realtime quote 已带出的 `pe / pb / total_mv / circ_mv`
  - 必要时只允许读取本地 canonical daily / daily_basic 已落库事实
  - 不再为 `/watch/poll` 触发重型多源 `get_financial_data()` fallback
- A 股 ETF / 基金 / 非普通股票若不适用股票财务口径，应直接返回轻量 `partial`，不能反复触发 `CN财务 数据获取全失败`
- 美股股票应优先尝试 realtime quote；当 realtime 不可用时才允许返回 `daily_fallback`
- 若 A 股 realtime source 全部失败，允许降级为 `daily_fallback`，但必须显式标记为非盘中实时
- 美股允许降级为 latest available daily snapshot
- 缺失字段显式返回 `null`，不得伪造实时性

## 验收标准

- 单次请求支持多股票
- 重复 symbol 只处理一次
- 无 baseline 时返回 `initial`
- 有 baseline 时返回 `delta` 和 `alerts`
- 单只股票失败不影响整个批次
- 输出保持 compact，不泄露旧重型分析 payload
