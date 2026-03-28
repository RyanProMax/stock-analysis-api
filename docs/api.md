# HTTP API 设计说明

更新时间：2026-03-28

本文档是当前对外 HTTP REST API 的唯一接口设计说明，统一描述：

- 接口用途
- 调用方式
- 入参
- 出参
- 关键字段含义

`README.md` 只保留运行和使用入口，不承载完整 API contract。

说明：

- 仓库中的内部 `scripts/` 仅供 Agent / skill 调用，不属于本文档维护范围

## 通用约定

### Base URL

- 本地开发默认：`http://127.0.0.1:8080`

### 通用响应封装

除 Excel 导出接口外，所有接口统一返回：

```json
{
  "status_code": 200,
  "data": {},
  "err_msg": null
}
```

字段含义：

- `status_code`: 业务状态码，通常与 HTTP 状态一致
- `data`: 业务数据
- `err_msg`: 错误信息；成功时为 `null`

### 复杂分析接口统一结构

`/stock/analyze`、`/watch/poll`、`/analysis/research/snapshot` 的复杂 `data` 通常使用统一分层：

```json
{
  "entity": {},
  "facts": {},
  "analysis": {},
  "meta": {}
}
```

字段含义：

- `entity`: 标的身份信息，如代码、名称、市场、行业
- `facts`: 原始事实或标准化后的事实数据，只放 `reported` / `consensus`
- `analysis`: 派生分析、模型输出或估算结果
- `meta`: 时间、来源、完整性、限制、source chain 等元信息

### 标准字段对象

复杂接口里的很多数值字段不是裸值，而是标准字段对象：

```json
{
  "field": "price",
  "value": 1418.68,
  "display_value": 1418.68,
  "unit": "currency",
  "period_type": "spot",
  "data_type": "reported",
  "source": "Tushare",
  "as_of": "2026-03-23T02:31:23.869916+00:00",
  "status": "available",
  "confidence": "medium",
  "notes": []
}
```

关键含义：

- `value`: 机器值
- `display_value`: 展示值
- `unit`: 单位，如 `currency`、`ratio`、`multiple`
- `period_type`: 时间语义，如 `spot`、`ttm`
- `data_type`: 数据类型，如 `reported`、`derived`、`estimate`
- `source`: 数据来源
- `as_of`: 该字段的观测时间
- `status`: `available` / `unavailable`

## 根路径与健康检查

### `GET /`

用途：

- 返回简单欢迎信息

响应：

- `data.message`: 欢迎文案

### `GET /health`

用途：

- 唯一健康检查接口
- 同时属于“任意 HTTP 请求”范围，会触发后台 symbols preflight 检查

响应：

- `data.message`: 固定为 `ok`
- `data.status`: 固定为 `healthy`

附加行为：

- 当前请求不会等待 symbols 刷新完成
- `cn/us` 会各自按当日是否开市独立判断是否触发后台刷新
- `/docs`、`/redoc`、`/openapi.json` 不触发该后台检查

## 股票基础接口

### `POST /stock/analyze`

用途：

- 批量分析股票，返回统一结构化分析结果

请求体：

```json
{
  "symbols": ["NVDA", "AAPL", "600519"],
  "include_qlib_factors": false
}
```

字段含义：

- `symbols`: 股票代码数组，必填
- `include_qlib_factors`: 是否包含额外 Qlib 因子，默认 `false`

成功响应：

- `data` 为数组，每个元素是一个 `StructuredInterfaceResponse`

返回重点：

- `entity`: 标的基本信息
- `facts`: 标准化后的价格、财务、共识等事实数据
- `analysis`: 技术面、基本面、模型结论
- `meta`: 数据来源、时间、限制说明

错误语义：

- `400`: `symbols` 为空或无有效代码
- `404`: 无法获取任何股票数据

### `GET /stock/list`

用途：

- 返回股票列表，默认来自本地 SQLite symbol 仓
- 当 `market=A股` 时，返回的是 `cn_symbols` 结果，可能同时包含 A 股股票与 `market=ETF` 的记录

Query 参数：

- `market`: 可选，市场筛选；常见值为 `A股`、`美股`
- `limit`: 可选，返回数量上限；`>= 0`

附加行为：

- 当前请求会触发后台 symbols preflight 检查，但不会阻塞接口返回

成功响应结构：

```json
{
  "stocks": [
    {
      "ts_code": "600519.SH",
      "symbol": "600519",
      "name": "贵州茅台",
      "area": null,
      "industry": null,
      "market": "A股",
      "list_date": null,
      "meta": {}
    }
  ],
  "total": 1,
  "meta": {
    "source": "stock_list_sqlite",
    "status": "available",
    "as_of": null
  }
}
```

字段含义：

- `stocks`: 股票记录数组
- `total`: 当前返回条数
- `meta.source`: 当前列表来源

单条股票记录字段含义：

- `ts_code`: 带交易所后缀的代码
- `symbol`: 纯代码
- `name`: 股票名称
- `area`: 地域
- `industry`: 行业
- `market`: 市场标签
- `list_date`: 上市日期
- `meta`: 扩展元信息

补充说明：

- 不新增 ETF-only 过滤参数
- 若请求 `market=A股`，`market` 字段可能为 `主板 / 创业板 / 科创板 / 北交所 / CDR / ETF`

### `POST /stock/search`

用途：

- 在本地 SQLite symbol 仓中按关键词搜索股票
- 当 `market=A股` 时，搜索范围是 `cn_symbols`，结果可能包含 `market=ETF`

请求体：

```json
{
  "keyword": "NVDA",
  "market": null
}
```

字段含义：

- `keyword`: 搜索关键词，必填
- `market`: 可选市场筛选

附加行为：

- 当前请求会触发后台 symbols preflight 检查，但不会阻塞接口返回

响应结构：

- 与 `/stock/list` 相同，返回 `stocks`、`total`、`meta`

错误语义：

- `400`: `keyword` 为空

## 盯盘轮询接口

### `POST /watch/poll`

用途：

- 面向外部 Agent 的多股票轮询接口
- 返回盘中快照、相对上次轮询的变化和预警

请求体：

```json
{
  "symbols": ["600519", "000001", "NVDA"]
}
```

字段含义：

- `symbols`: 股票代码数组，必填；服务端会去重、保序

响应：

- `data` 为数组，每个元素对应一只股票的轮询结果

返回重点字段：

- `entity.symbol`
- `entity.name`
- `entity.market`
- `facts.quote`
- `facts.fundamentals`
- `analysis.delta`
- `analysis.alerts`
- `analysis.technical`
- `analysis.earnings_watch`
- `meta.degradation`
- `meta.source_chain`

A 股轮询补充约束：

- A 股 `facts.fundamentals` 走轻量基本面模式，不再触发重型多源财务 fallback
- A 股普通股票优先使用 realtime quote 已带出的 `pe / pb / total_mv / circ_mv` 等轻量字段
- A 股 ETF / 基金 / 非普通股票若缺少适用基本面字段，可返回 `partial` 或 `null`，但不会再触发整条股票财务抓取链路

美股轮询补充约束：

- 美股股票正式支持 realtime quote
- 美股 realtime 主源为 `yfinance`
- 当 `yfinance` 无法提供实时 quote 时，仍允许降级为 `daily_fallback` 或 `unavailable`

`facts.quote` 常见字段：

- `price`: 当前价格
- `change_pct`: 涨跌幅
- `change_amount`: 涨跌额
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `pre_close`: 昨收
- `volume`: 成交量
- `amount`: 成交额
- `turnover_rate`: 换手率
- `amplitude`: 振幅

`analysis.delta` 字段：

- `status`: `initial` 或 `updated`
- `changed_fields`: 本次相对 baseline 变化的字段列表
- `price_move_pct_since_last_poll`: 距上次轮询的价格变化幅度
- `trend_changed`: 趋势是否变化

`analysis.alerts` 字段：

- `code`: 预警代码
- `severity`: 严重级别
- `summary`: 简短说明
- `evidence`: 触发证据
- `symbol`: 股票代码
- `as_of`: 触发时间

常见 `alert.code`：

- `price_jump_up`
- `price_jump_down`
- `volume_spike`
- `turnover_spike`
- `near_day_high`
- `near_day_low`
- `breakout_up`
- `breakout_down`
- `earnings_soon`

`meta.degradation` 字段：

- `quote_mode`: `realtime` / `daily_fallback` / `unavailable`
- `quote_is_realtime`: 是否为盘中实时 quote
- `quote_fallback_used`: 是否用了日线降级
- `fundamentals_partial`: 基本面是否部分缺失
- `earnings_partial`: 财报观察是否部分缺失

实时性判断规则：

- `quote_mode = realtime` 且 `quote_is_realtime = true`：盘中实时数据
- `quote_mode = daily_fallback`：仅拿到最新日线快照，不是盘中实时

`facts.fundamentals` 补充说明：

- A 股轮询场景下，`source` 可能直接来自 realtime quote 源，例如 `CN_Tushare`
- 当 A 股标的不适用股票财务口径，或轻量字段不足时，`fundamentals_partial = true`
- 美股轮询场景下，`quote.source` 与 realtime 命中源应明确为 `yfinance`

## 统一研究接口

### `POST /analysis/research/snapshot`

用途：

- 提供统一的客观研究快照入口
- 替代原有分散的 `/valuation/*`、`/model/*`、`/analysis/*` 专项分析接口
- 单次请求可按市场、symbol 和模块集合返回结构化研究结果

请求体：

- `market`: 必填，`cn` / `us`
- `symbols`: 必填，字符串数组，去重保序
- `start_date`: 可选，`YYYYMMDD`
- `end_date`: 可选，`YYYYMMDD`
- `modules`: 可选，字符串数组；不传则按市场走默认核心模块
- `module_options`: 可选，对象；承载模块级参数

默认核心模块：

- `cn`
  - `research_report`
  - `report_rc`
  - `anns_d`
  - `news`
  - `major_news`
  - `earnings`
- `us`
  - `earnings`
  - `earnings_preview`
  - `dcf`
  - `comps`
  - `three_statement`

可扩展模块：

- `lbo`
- `three_statement_scenarios`
- `competitive`
- `catalysts`
- `model_update`
- `sector_overview`
- `screen`

`module_options` 约定：

- `dcf`
  - `risk_free_rate`
  - `equity_risk_premium`
  - `terminal_growth_rate`
- `comps`
  - `sector`
- `lbo`
  - `holding_period`
  - `entry_multiple`
  - `exit_multiple`
  - `leverage`
- `three_statement`
  - `scenario`
  - `projection_years`
- `earnings`
  - `quarter`
  - `fiscal_year`
- `catalysts`
  - `horizon_days`
- `screen`
  - `filters`

顶层响应：

- `status`
- `computed_at`
- `source`
- `market`
- `strategy`
- `request`
- `items`

`items[]` 固定字段：

- `requested_symbol`
- `status`
- `error`
- `info`
- 各模块结果

模块返回规则：

- 原始 / 事件型模块：
  - `records`
  - `source`
  - `source_status`
  - `source_error`
  - `attempted_sources`
- 结构化分析型模块：
  - 直接展开 `entity`
  - `facts`
  - `analysis`
  - `meta`
  - `module_status`
  - `module_error`
  - `attempted_sources`

客观边界：

- 接口只返回客观、结构化、可追溯输出
- 不返回 thesis、moat、positioning、recommendation、confidence、price target、morning note、idea pitch 等主观字段

状态语义：

- item `status`
  - `ok`
  - `partial`
  - `failed`
  - `not_supported`
  - `not_implemented`
- 顶层 `status`
  - `ok`
  - `partial`
  - `not_implemented`

说明：

- `cn` 仍复用当前 research snapshot 的 block contract 与确定性 `derived`
- `us` 与结构化分析模块统一通过同一入口调度，不再单独暴露 HTTP 路由
- CLI `scripts/poll_research_snapshot.py` 与该 HTTP 接口保持同构请求 / 响应语义

## 错误语义

常见返回：

- `400`: 参数非法、缺关键参数或分析器返回业务错误
- `404`: 仅个别接口使用，如 `/stock/analyze` 在没有任何有效结果时返回
- `500`: 服务端内部异常

错误体统一仍使用：

```json
{
  "status_code": 500,
  "data": null,
  "err_msg": "错误说明"
}
```
