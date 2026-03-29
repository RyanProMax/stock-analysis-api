# HTTP API 设计说明

更新时间：2026-03-29

本文档是当前对外 HTTP REST API 的唯一接口设计说明。

## 通用约定

### Base URL

- 本地开发默认：`http://127.0.0.1:8080`

### 通用响应封装

所有公共接口统一返回：

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

## 根路径与健康检查

### `GET /`

用途：

- 返回简单欢迎信息

### `GET /health`

用途：

- 唯一健康检查接口
- 同时属于“任意 HTTP 请求”范围，会触发后台 symbols preflight 检查

响应重点：

- `data.message`: 固定为 `ok`
- `data.status`: 固定为 `healthy`

附加行为：

- 当前请求不会等待 symbols 刷新完成
- `cn/us` 会各自按当日是否开市独立判断是否触发后台刷新
- `/docs`、`/redoc`、`/openapi.json` 不触发该后台检查

## 股票分析接口

### `POST /stock/analyze`

用途：

- 当前唯一公共分析入口
- 批量分析单市场股票列表
- 返回统一的 stock-analyze snapshot payload

请求体：

```json
{
  "market": "cn",
  "symbols": ["300827"],
  "start_date": "20260227",
  "end_date": "20260329",
  "mode": "base"
}
```

字段含义：

- `market`: 必填，`cn` 或 `us`
- `symbols`: 必填，股票代码数组
- `start_date`: 可选，`YYYYMMDD`
- `end_date`: 可选，`YYYYMMDD`
- `mode`: 可选，`base` / `full`，默认 `base`

请求约束：

- 仅支持单市场批次请求
- 请求体启用 `extra=forbid`
- 不再公开 `include_qlib_factors`
- 不再公开 `modules` / `module_options`

响应结构：

- `data.status`: 顶层聚合状态
- `data.computed_at`: 本次生成时间
- `data.source`: 当前固定为 `stock_analyze_dispatcher`
- `data.market`: 生效市场
- `data.strategy`: 当前固定为 `fsp_objective_stock_analyze_v2`
- `data.request`: 生效后的请求参数回显
- `data.items`: 每个 symbol 的分析结果

单个 `item` 固定包含：

- `requested_symbol`
- `status`
- `error`
- `info`
- `summary`
- 成功产出业务数据的模块 body
- `meta`

`info` 说明：

- `common`: 跨市场统一身份字段
- `cn_specific`: A 股专属身份字段
- `us_specific`: 美股专属身份字段

`summary` 说明：

- 跨市场统一汇总层
- 只承载 Agent 决策所需的关键确定性摘要
- 首位固定为 `research_strategy`，按 FSP 风格组织：
  - `expectations_vs_reported`
  - `fundamental_quality`
  - `valuation_context`
  - `catalyst_path`
  - `price_action_confirmation`
  - `cross_signal_alignment`
  - `risk_flags`
  - `evidence_strength`
- 按模块情况输出：
  - `research`
  - `earnings`
  - `catalysts`
  - `screen`
  - `models`
  - `change_flags`
  - `technical`

`meta.provenance` 说明：

- 统一承载字段级出处说明
- 当前至少覆盖 `summary.research_strategy.*`
- 每个子块至少包含：
  - `source_modules`
  - `field_paths`
  - `fallback_used`
  - `heuristic`
  - `evidence_class`

`meta.modules` 说明：

- 统一承载每个模块的：
  - `status`
  - `source`
  - `error`
  - `notes`
- `permission_denied`、`not_supported`、`empty` 等状态只在这里表达，不再为对应模块输出空壳 body

模块 body 约束：

- 原始块：
  - `research_report`
  - `report_rc`
  - `anns_d`
  - `news`
  - `major_news`
  - 只保留 `records`
- 结构化块：
  - `technical`
  - `earnings`
  - `earnings_preview`
  - `dcf`
  - `comps`
  - `three_statement`
  - `lbo`
  - `three_statement_scenarios`
  - `competitive`
  - `catalysts`
  - `model_update`
  - `sector_overview`
  - `screen`
- 结构化块不再公开：
  - `entity`
  - `meta`
  - `module_status`
  - `module_error`
  - `attempted_sources`
- `technical` 是研究辅助确认层：
  - 不单独承担买卖建议语义
  - 公共层使用 `stance / score / risk_context / invalidation_levels`
  - `fear_greed.label` 统一为标准 band
- `screen` 无 filters 时：
  - `evaluated=false`
  - `passed=null`
- `earnings_preview` 不再公开 placeholder scenarios，只保留可验证字段

`mode` 对应模块集合：

- `cn.base`
  - `technical`
  - `research_report`
  - `report_rc`
  - `earnings`
  - `catalysts`
  - `screen`
- `cn.full`
  - `technical`
  - `research_report`
  - `report_rc`
  - `anns_d`
  - `news`
  - `major_news`
  - `earnings`
  - `catalysts`
  - `screen`
  - `model_update`
- `us.base`
  - `technical`
  - `earnings`
  - `dcf`
  - `comps`
  - `three_statement`
  - `screen`
- `us.full`
  - `technical`
  - `earnings`
  - `earnings_preview`
  - `dcf`
  - `comps`
  - `three_statement`
  - `lbo`
  - `three_statement_scenarios`
  - `competitive`
  - `catalysts`
  - `screen`
  - `model_update`
  - `sector_overview`

返回约束：

- 只输出客观、结构化、可追溯结果
- `evidence_strength` 为规则生成，不是主观 confidence
- 不输出：
  - `recommendation`
  - `confidence`
  - `price_target`
  - `moat_assessment`
  - thesis / conviction / positioning / idea pitch / morning note

错误语义：

- `400`: 请求参数非法，如缺少 symbol、非法 mode、额外字段
- `200 + item.status=failed`: 单个 symbol 无法分析或核心模块不可用
- `200 + item.status=not_supported`: 非普通股、ETF 或当前市场不支持的标的

## 盯盘轮询接口

### `POST /watch/poll`

用途：

- 多股票盯盘轮询
- 返回 compact snapshot、delta 和 alerts

请求体：

```json
{
  "symbols": ["NVDA", "AAPL", "600519"]
}
```

字段含义：

- `symbols`: 股票代码数组，必填

返回重点：

- `data` 是数组
- 每个元素保持 `entity / facts / analysis / meta` 结构
- `facts.quote`: 实时或降级行情快照
- `facts.fundamentals`: 轻量基本面事实
- `analysis.delta`: 与进程内 baseline 的变化
- `analysis.alerts`: 当前触发的盯盘告警
- `meta.degradation`: realtime / fallback / partial 说明

错误语义：

- `400`: `symbols` 为空或无有效代码
