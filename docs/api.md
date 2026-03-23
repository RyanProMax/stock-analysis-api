# HTTP API 设计说明

更新时间：2026-03-23

本文档是当前对外 HTTP REST API 的唯一接口设计说明，统一描述：

- 接口用途
- 调用方式
- 入参
- 出参
- 关键字段含义

`README.md` 只保留运行和使用入口，不承载完整 API contract。

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

`/stock/analyze`、`/watch/poll`、`/valuation/*`、`/model/*`、`/analysis/*` 的 `data` 通常使用统一分层：

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

响应：

- `data.message`: 固定为 `ok`
- `data.status`: 固定为 `healthy`

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

Query 参数：

- `market`: 可选，市场筛选；常见值为 `A股`、`美股`
- `limit`: 可选，返回数量上限；`>= 0`

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

### `POST /stock/search`

用途：

- 在本地 SQLite symbol 仓中按关键词搜索股票

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

## 估值接口

### `GET /valuation/dcf`

用途：

- 对美股执行 DCF 估值分析

Query 参数：

- `symbol`: 必填，美股代码
- `risk_free_rate`: 可选，无风险利率，`0 ~ 0.2`
- `equity_risk_premium`: 可选，股权风险溢价，`0 ~ 0.2`
- `terminal_growth_rate`: 可选，永续增长率，`0 ~ 0.05`

响应重点：

- `entity`: 股票与公司标识
- `facts`: 历史经营事实与输入前提
- `analysis`: WACC、FCF 预测、终值、敏感性分析、估值结论
- `meta`: 来源、假设和限制

注意：

- 仅支持美股
- 返回属于模型估值，不是市场事实价格

### `GET /valuation/dcf/excel`

用途：

- 导出 DCF Excel 报告

参数：

- 与 `/valuation/dcf` 相同

响应：

- 成功时返回 `.xlsx` 文件流
- `Content-Disposition` 文件名格式：`dcf_<SYMBOL>.xlsx`

### `GET /valuation/comps`

用途：

- 对美股执行可比公司估值分析

Query 参数：

- `symbol`: 必填，美股代码
- `sector`: 可选，行业分类字符串

响应重点：

- `entity`: 目标公司标识
- `facts`: 可比公司原始经营与估值事实
- `analysis`: 倍数分位数、隐含估值、推荐方向
- `meta`: 数据来源与限制

### `GET /valuation/comps/excel`

用途：

- 导出 Comps Excel 报告

参数：

- 与 `/valuation/comps` 相同

响应：

- 成功时返回 `.xlsx` 文件流
- 文件名格式：`comps_<SYMBOL>.xlsx`

## 模型接口

### `GET /model/lbo`

用途：

- 对美股执行 LBO 情景模型测算

Query 参数：

- `symbol`: 必填，美股代码
- `holding_period`: 可选，持有年限，默认 `5`，范围 `3 ~ 10`
- `entry_multiple`: 可选，入场 EV/EBITDA 倍数，默认 `10.0`
- `exit_multiple`: 可选，退出 EV/EBITDA 倍数，默认 `10.0`
- `leverage`: 可选，债务占比，默认 `0.65`，范围 `0.3 ~ 0.9`

响应重点：

- `analysis`: Sources & Uses、债务时间表、现金流、IRR、MOIC

注意：

- 返回是参数化情景测算，不是外部市场事实

### `GET /model/three-statement`

用途：

- 对美股执行三表预测模型

Query 参数：

- `symbol`: 必填，美股代码
- `scenario`: 可选，`bull` / `base` / `bear`，默认 `base`
- `projection_years`: 可选，预测年限，默认 `5`，范围 `3 ~ 10`

响应重点：

- `analysis`: 损益表、资产负债表、现金流预测和关键指标

注意：

- 返回是预测模型，不是公司已披露报表

### `GET /model/three-statement/scenarios`

用途：

- 对比 `bull` / `base` / `bear` 三种三表情景结果

Query 参数：

- `symbol`: 必填，美股代码
- `projection_years`: 可选，预测年限，默认 `5`

响应重点：

- `analysis.scenarios`: 每个情景下的增长、关键指标和假设

## 专题分析接口

### `GET /analysis/competitive/competitive`

用途：

- 执行竞争格局分析

Query 参数：

- `symbol`: 必填，目标公司代码
- `competitors`: 可选，逗号分隔的竞争对手代码，如 `AMD,INTC,AVGO`
- `industry`: 可选，行业类型；默认 `technology`

响应重点：

- `entity`: 目标公司
- `facts`: 目标公司与竞争对手的原始指标
- `analysis`: 市场背景、定位矩阵、对比表、护城河分析

注意：

- 市场背景、护城河和部分场景字段包含启发式估算

### `GET /analysis/earnings/earnings`

用途：

- 执行季报分析

Query 参数：

- `symbol`: 必填，股票代码
- `quarter`: 可选，`Q1` / `Q2` / `Q3` / `Q4`
- `fiscal_year`: 可选，财年，范围 `2020 ~ 2030`

响应重点：

- `facts`: 季度收入、利润、EPS、预期对比等事实
- `analysis`: beat/miss、趋势分析、业务线解读
- `meta`: 引用来源和限制说明

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
