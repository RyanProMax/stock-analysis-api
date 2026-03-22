# 数据源字段治理规格

更新时间：2026-03-22

## 目标

- 建立数据源字段规范层，避免字段语义、单位和期别继续漂移
- 为 `facts / analysis` 分层提供可执行的字段接入约束
- 为后续修复提供优先级和整改路径

## 总体要求

- 修复不能继续依赖“按返回值阈值猜单位”的逻辑
- 在继续扩字段前，先建立 source-field registry
- 对缺少稳定公开契约的字段，按低置信度处理
- 没有可验证基础时，返回 `unavailable`，不要伪造事实值

## 数据源约束

### yfinance

- `Ticker.info` 只作为 snapshot 补充源，不作为字段真值源
- 涉及“季度”“期间”“同比”“收益率”的字段，优先级低于 statement/event API
- 更适合作为事实层的数据接口：
  - `quarterly_income_stmt`
  - `quarterly_cashflow`
  - `quarterly_balance_sheet`
  - `earnings_dates`
  - `dividends`
  - `actions`

### Tushare

- 是 A 股事实层主标准源
- `ann_date` 和 `end_date` 必须随标准化字段一起保留
- 由报表值推导增长率时，必须保证同口径、同期比较

### AkShare

- 财务摘要更适合作为 fallback 或展示补充
- 不得继续以表格固定位置读核心财务字段
- 必须改为“列头 + 指标名”解析

## 高风险字段要求

- `dividend_yield`
  - 禁止继续直接暴露 `yfinance.info.dividendYield` 为 reported fact
  - 优先使用 `dividends/actions + price` 计算 trailing yield
  - 无法稳定计算时返回 `unavailable`
- `book_value_per_share`
  - 只允许映射自 `info.bookValue`
  - 禁止参与 `total_equity` 等总量字段计算
- `revenue`
  - `info.totalRevenue` 仅允许映射为 `revenue_ttm` 或 `revenue_snapshot`
  - 季度收入必须来自正式报表源
- `revenue_growth` / `earnings_growth`
  - yfinance 默认不进入硬事实层
  - A 股自算增长率时必须保证同口径同比
- peer 可比字段
  - `market_cap`、`enterprise_value`、`revenue` 进入 `comps` 前必须先统一币种和单位
  - 无法转换或量级异常时直接剔除

## Source-Field Registry 最低字段

- `canonical_field`
- `source`
- `source_field`
- `unit_raw`
- `unit_normalized`
- `period_type`
- `data_type`
- `confidence`
- `allowed_interfaces`
- `fallback_order`
- `unavailable_rule`
- `notes`

## 当前优先级

### P0

- 建立 source-field registry
- 下线 `info.dividendYield` 直出链路
- 修正 A 股 `income -> revenue_growth` 的比较逻辑
- 修正 AkShare 摘要表位置取值

### P1

- 为 `stock/analyze`、`earnings`、`competitive`、`comps` 接入字段级 `confidence/source_field`
- 将 `bookValue` 全量重命名为 `book_value_per_share`
- 将 `totalRevenue` 全量重命名为 `revenue_ttm` 或 `revenue_snapshot`

### P2

- 为 `comps` 引入货币统一与异常值剔除
- 为所有事实字段补全 `period_end_date` / `filing_or_release_date`
