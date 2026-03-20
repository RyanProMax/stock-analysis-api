# 数据源字段规范审计

审计时间：2026-03-20  
审计对象：当前 HTTP-only 服务所依赖的数据源字段实现  
审计目标：明确不同数据源的字段语义、单位、周期、置信度与归一化约束，作为后续修复的前置依据  

## 结论摘要

当前项目的字段问题，根因不是单个接口格式化错误，而是缺少“数据源字段规范层”。

已确认结论：

- 美股链路大量直接消费 `yfinance.Ticker.info`，但 `info` 在 yfinance 官方文档里只有“返回 dict”这一层公开接口说明，没有稳定的字段级契约。
- `yfinance.info` 里的若干字段在不同标的上存在口径不透明或不一致风险，尤其是 `dividendYield`、`revenueGrowth`、`earningsGrowth` 这类需要周期解释的字段。
- A 股链路的 `tushare` 字段契约整体优于 `yfinance.info`，因为其 endpoint 与列名有明确文档；但当前项目仍存在“把报表值直接转成增长率”或“没有显式 period_type”的问题。
- A 股备用链路 `akshare.stock_financial_abstract` 本质上是网页摘要表抓取，不是稳定 schema API；当前实现按表格位置取值，字段置信度明显低于 `tushare`。
- 后续修复不能继续做“按返回值阈值猜单位”的逻辑，必须先定义 source-field registry，再做归一化。

## 审计方法

- 核对当前代码中各字段的实际使用位置。
- 核对数据源公开文档或库文档。
- 结合本地 HTTP live 样本验证高风险字段表现。
- 对缺少稳定公开字段契约的源，明确标注为低置信度，不把经验判断写成规范。

## 当前数据源拓扑

### 美股

- 行情日线：`yfinance.history`
- 基本面快照：`yfinance.info`
- 季报/三表：`yfinance.quarterly_income_stmt`、`quarterly_balance_sheet`、`quarterly_cashflow`、`income_stmt`、`cashflow`、`balance_sheet`
- 分红/事件：`yfinance.dividends`、`actions`、`earnings_dates`

### A 股

- 主财务源：`tushare.daily_basic`、`tushare.fina_indicator`、`tushare.income`
- 备用财务源：`akshare.stock_financial_abstract`、`akshare.stock_individual_info_em`

## 字段规范审计

### 1. yfinance

官方公开接口能确认的是：

- `Ticker.info` 仅承诺返回 `dict`，没有字段级 schema 文档。
- `Ticker.quarterly_income_stmt`、`Ticker.quarterly_cashflow`、`Ticker.quarterly_balance_sheet`、`Ticker.earnings_dates`、`Ticker.dividends` 等表格/序列接口是更适合承载“事实值”的公开 API。

参考：

- yfinance 文档首页：https://ranaroussi.github.io/yfinance/index.html
- `Ticker` API：https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html
- `Ticker.info`：https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.info.html
- `Ticker.quarterly_income_stmt`：https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.quarterly_income_stmt.html

#### 1.1 `yfinance.info` 高风险字段

| 原始字段 | 当前使用位置 | 代码中当前理解 | 审计结论 | 标准化要求 |
|------|------|------|------|------|
| `dividendYield` | `stock/analyze`、`earnings` | 被当成统一 ratio/percent 字段 | `P0`。不能通过数值大小猜单位。现网样本中 `NVDA=0.02` 被解释为 `0.02%`，`AAPL=0.42` 被解释为 `42.00%`，说明当前逻辑不具备跨标的稳定性。由于 `info` 没有字段级公开契约，不能继续直接作为 canonical yield。 | 不能直接对外暴露为 reported fact。应改为用 `dividends/actions` 与价格自行计算 trailing dividend yield，或在无可靠计算链路时降级为 `unavailable`。 |
| `payoutRatio` | `stock/analyze`、`earnings` | 被当成 ratio | `P1`。样本值表现更像标准 ratio，如 `0.0082 -> 0.82%`，但仍属于 `info` snapshot，缺少字段级公开契约。 | 可作为 `reported_snapshot` 候选字段保留，但必须在 registry 里写明 `unit=ratio`、`period_type=ttm_or_snapshot`、`confidence=medium`。 |
| `bookValue` | `stock/analyze`、历史上曾误入三表基线 | 被展示为“每股账面价值” | `P0`。这是每股字段，不是总权益。历史问题已经说明该字段极易被误用。 | 统一字段名必须改为 `book_value_per_share`，`unit=currency_per_share`，禁止参与 `total_equity`、`book_equity`、`balance_sheet_equity` 计算。 |
| `marketCap` | `stock/analyze`、`competitive`、`comps` | 被当成绝对金额 | `P1`。可视为 spot 市值快照，语义相对清晰，但仍是 snapshot，不应混同报表期字段。 | `unit=currency`、`period_type=spot`、`data_type=reported_snapshot`。 |
| `enterpriseValue` | `stock/analyze`、`comps` | 被当成绝对金额 | `P1`。样本显示 peer 里可能存在量级异常，说明仅靠 `info` 直接透传不可靠。 | 必须带 `currency` 与异常值校验；跨市场 peer 未做货币统一前不得直接并表统计。 |
| `totalRevenue` | `stock/analyze`、`competitive`、`dcf` | 被当成总营收 | `P0/P1`。可用于 TTM/annual snapshot，但不能当季度收入。历史 bug 已证实该字段被误拿去做季报摘要。 | 统一字段名为 `revenue_ttm` 或 `revenue_snapshot`；默认 `period_type=ttm`，禁止填入季度 facts。 |
| `revenueGrowth` | `stock/analyze`、`competitive`、`dcf`、`earnings` | 被当成通用营收增长率 | `P1`。该字段在 yfinance 文档中没有字段级周期说明，不能断言一定是季度同比或 TTM 增长。 | 只能作为 `analysis` 或 `reported_snapshot` 候选字段，必须在 meta 标明“exact base period undocumented”。 |
| `earningsGrowth` | `stock/analyze`、`earnings` | 被当成通用盈利增长率 | `P1`。与 `revenueGrowth` 同类问题，缺乏公开周期契约。 | 仅用于 `analysis` 或 `snapshot`，不得写入严格事实层季度字段。 |
| `heldPercentInsiders` | `stock/analyze` | 被当成 ratio | `P1`。样本表现与 ratio 一致，字段名也清楚，但仍属于 snapshot。 | `unit=ratio`、`period_type=spot`、`data_type=reported_snapshot`。 |
| `heldPercentInstitutions` | `stock/analyze` | 被当成 ratio | `P1`。同上。 | 同上。 |
| `sharesPercentSharesOut` | `stock/analyze` | 被当成 ratio | `P1`。同上。 | 同上。 |

#### 1.2 yfinance 更适合作为事实层的接口

| 接口 | 适合承载的标准字段 | 审计结论 | 标准化要求 |
|------|------|------|------|
| `quarterly_income_stmt` | 季度收入、营业利润、净利润等 | `P0` 推荐。比 `info.totalRevenue` 更适合季度 facts。 | `period_type=quarterly`，以报表列日期为 `period_end_date`。 |
| `quarterly_cashflow` | 季度经营现金流、资本开支、FCF 原料 | `P0` 推荐。 | 历史 FCF 应优先从现金流表构造，不得倒推。 |
| `quarterly_balance_sheet` | 现金、债务、总资产、总负债、股东权益等 | `P0` 推荐。 | 三表/LBO 基线必须优先读这里，不得再读 `bookValue` 替代。 |
| `earnings_dates` | 财报发布日期、事件日期 | `P0` 推荐。 | `period_end_date` 与 `filing_or_release_date` 必须分开。 |
| `dividends` / `actions` | 分红现金序列 | `P0` 推荐。 | trailing dividend yield 应由分红序列 + 价格计算，不应信任 `info.dividendYield` 作为唯一事实源。 |

#### 1.3 yfinance 审计结论

- `info` 只能作为 snapshot 补充源，不应继续承担字段规范真值源角色。
- 凡是涉及“季度”“期间”“同比”“收益率”的字段，优先级都应低于 statement/event API。
- 后续 registry 里应把 `yfinance.info` 字段默认标为 `confidence=low/medium`，除非已有外部一手源或稳定交叉校验。

### 2. Tushare

当前代码主用：

- `daily_basic(ts_code, fields="ts_code,trade_date,pe,pe_ttm,pb")`
- `fina_indicator(ts_code, fields="ts_code,ann_date,end_date,roe,debt_to_assets")`
- `income(ts_code, fields="ts_code,ann_date,end_date,revenue")`

公开文档与站内索引可确认：

- `daily_basic` / `income` / `fina_indicator` 都属于 Tushare Pro 的正式 endpoint。
- `income`、`fina_indicator` 与 `ann_date/end_date` 绑定，具有明确报表期语义。

参考：

- Tushare 财务数据索引：https://www.tushare.pro/document/2?doc_id=108
- Tushare 财务快报样例页（包含 `revenue`、`ann_date`、`end_date` 字段展示）：https://tushare.pro/document/2?doc_id=46

#### 2.1 `daily_basic`

| 原始字段 | 当前使用位置 | 审计结论 | 标准化要求 |
|------|------|------|------|
| `pe_ttm` | A 股 fundamentals | `P1`。字段语义清楚，适合作为 `pe_ratio_ttm`。 | 统一字段名为 `pe_ratio_ttm`，`unit=multiple`，`period_type=ttm`。 |
| `pe` | A 股 fundamentals 兜底 | `P1`。字段语义清楚，但不等于 TTM。 | 统一字段名为 `pe_ratio`，与 `pe_ttm` 分开，不得混为同一标准字段。 |
| `pb` | A 股 fundamentals | `P1`。字段语义清楚。 | `field=price_to_book`，`unit=multiple`，`period_type=spot`。 |

#### 2.2 `fina_indicator`

| 原始字段 | 当前使用位置 | 审计结论 | 标准化要求 |
|------|------|------|------|
| `roe` | A 股 fundamentals | `P1`。属于财务指标字段，和 `ann_date/end_date` 绑定，不是实时 snapshot。 | 默认作为 `unit=percent` 原始字段接入，再统一归一化成 `ratio` 机器值；`period_type` 必须跟随 `end_date`，不能标 spot。 |
| `debt_to_assets` | A 股 fundamentals | `P1`。语义清楚。 | 统一字段名为 `debt_to_assets_ratio`，机器值存 `ratio`，展示值存 percent。 |

#### 2.3 `income`

| 原始字段 | 当前使用位置 | 审计结论 | 标准化要求 |
|------|------|------|------|
| `revenue` | A 股 fundamentals | `P0`。这是报表金额，不是增长率。当前代码直接比较最近两行算增长，未确保是同口径同比，存在季度/年度混比风险。 | 若要产出 `revenue_growth`，必须按同一报表粒度、同一期间同比计算；拿不到可比基准时返回 `unavailable`。 |
| `ann_date` | 当前仅存 raw | `P1`。可用于披露日期。 | 应进入标准 meta。 |
| `end_date` | 当前仅存 raw | `P1`。可用于报表期末。 | 应进入标准 meta。 |

#### 2.4 Tushare 审计结论

- Tushare 是 A 股事实层的主标准源。
- 但当前项目对 period_type 建模不足，尤其是 `income.revenue -> revenue_growth` 的推导方式需要重写。
- 与 yfinance 相比，Tushare 更适合进入 `facts`，前提是把 `ann_date/end_date` 一并标准化。

### 3. AkShare

当前代码主用：

- `stock_individual_info_em(symbol)`
- `stock_financial_abstract(symbol)`

本地库 docstring 可确认：

- `stock_financial_abstract` 对应新浪财经“财务报表-关键指标”页面。
- `stock_individual_info_em` 对应东方财富个股信息页面。

这两个接口都更接近“页面摘要采集”，不是像 Tushare 那样的强 schema 财务 API。

#### 3.1 `stock_financial_abstract`

| 原始来源 | 当前使用位置 | 审计结论 | 标准化要求 |
|------|------|------|------|
| “常用指标”表中的 `净资产收益率(ROE)` | A 股备用财务源 | `P1/P2`。可作为备用值，但这是表格展示字段，列顺序和格式更脆弱。 | 只能作为 fallback；必须连同列标题一起解析，不能继续用 `iloc[0,2]` 这种位置读取。 |
| “常用指标”表中的 `资产负债率` | A 股备用财务源 | `P1/P2`。同上。 | 同上。 |
| “成长能力”表中包含“营业收入”的行 | A 股备用财务源 | `P0/P1`。当前实现以行名包含“营业收入”即视为营收增长，语义过宽。 | 必须把具体行名白名单化，并记录 period header；拿不到明确增长字段时返回 `unavailable`。 |

#### 3.2 `stock_individual_info_em`

| 原始来源 | 当前使用位置 | 审计结论 | 标准化要求 |
|------|------|------|------|
| 东方财富个股信息页摘要 | A 股备用 metadata | `P2`。更适合主数据或展示 metadata，不适合作为财务事实主源。 | 不参与核心财务字段归一化。 |

#### 3.3 AkShare 审计结论

- AkShare 财务摘要更适合作为 fallback 或展示性补充，不应作为高置信度事实层真值源。
- 当前位置索引取值方式过于脆弱，后续必须改成“按列头 + 指标名”的解析方式。

## 当前代码与字段规范的主要偏差

### P0

- `src/data_provider/sources/yfinance.py` 直接把 `info` 整包下放，没有 source-schema 层。
- `src/analyzer/fundamental_factors.py` 仍对 `dividendYield` 使用阈值式格式化。
- `src/analyzer/earnings_analyzer.py` 仍从 `info.dividendYield` 直接构造股息率展示。
- `src/data_provider/sources/tushare.py` 直接比较 `income` 最近两行推导 `revenue_growth`，没有保证同比口径。
- `src/data_provider/sources/akshare.py` 用表格位置 `iloc[0,2]` 读摘要字段，缺少列头和单位校验。

### P1

- `src/analyzer/normalizers.py` 把多类 `info` 字段都按统一规则写入 `facts`，没有字段级 source confidence。
- `competitive`、`comps`、`dcf` 仍直接消费 `info.totalRevenue`、`enterpriseValue`、`revenueGrowth` 等 snapshot 字段。
- `bookValue` 已不再误入三表，但仍未完成 canonical rename。

## 建议的字段标准层

后续修复前必须先建立 source-field registry。每个字段至少需要这组元数据：

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

建议先覆盖这批高风险字段：

- `dividend_yield`
- `payout_ratio`
- `book_value_per_share`
- `total_equity`
- `market_cap`
- `enterprise_value`
- `revenue_ttm`
- `quarterly_revenue`
- `revenue_growth`
- `earnings_growth`
- `held_percent_insiders`
- `held_percent_institutions`
- `shares_percent_shares_out`

## 建议的归一化规则

### 1. 对 `dividend_yield`

- 禁止继续直接消费 `yfinance.info.dividendYield` 作为 reported fact。
- 优先链路：
  - `yfinance.dividends` 聚合 trailing 12m 分红
  - 配合价格源计算 trailing dividend yield
- 如果无法稳定计算：
  - 返回 `status=unavailable`
  - 不再做阈值猜测

### 2. 对 `book_value_per_share`

- 只允许映射自 `info.bookValue`
- 统一字段名 `book_value_per_share`
- 任何总权益字段必须来自资产负债表，不允许 fallback 到这个字段

### 3. 对 `revenue`

- `info.totalRevenue` 只允许映射为 `revenue_ttm` 或 `revenue_snapshot`
- 季度收入必须来自 `quarterly_income_stmt` 或正式报表源
- A 股 `income.revenue` 必须附带 `end_date`

### 4. 对 growth 字段

- `revenueGrowth`、`earningsGrowth` 在 yfinance 中默认不进入硬事实层
- A 股 growth 若由 `income` 自算，必须保证同口径同比
- 拿不到可比较基准时返回 `unavailable`

### 5. 对 peer 可比口径

- `market_cap`、`enterprise_value`、`revenue` 进入 `comps` 前必须先统一币种与单位
- 对 ADR、非 USD 标的、跨市场标的必须显式转换；无法转换时剔除

## 审计后的修复优先级

### Phase 1

- 建立 `source-field registry`
- 下线 `info.dividendYield` 直出链路
- 修正 A 股 `income -> revenue_growth` 的比较逻辑
- 修正 AkShare 摘要表位置取值

### Phase 2

- 为 `stock/analyze`、`earnings`、`competitive`、`comps` 接入字段级 `confidence/source_field`
- 将 `bookValue` 全量重命名为 `book_value_per_share`
- 将 `totalRevenue` 全量重命名为 `revenue_ttm` 或显式 `snapshot_revenue`

### Phase 3

- 为 `comps` 引入货币统一与异常值剔除
- 为所有事实字段补全 `period_end_date` / `filing_or_release_date`

## 相关代码位置

- [src/data_provider/sources/yfinance.py](/home/ryan/projects/stock-analysis-api/src/data_provider/sources/yfinance.py)
- [src/data_provider/sources/tushare.py](/home/ryan/projects/stock-analysis-api/src/data_provider/sources/tushare.py)
- [src/data_provider/sources/akshare.py](/home/ryan/projects/stock-analysis-api/src/data_provider/sources/akshare.py)
- [src/analyzer/fundamental_factors.py](/home/ryan/projects/stock-analysis-api/src/analyzer/fundamental_factors.py)
- [src/analyzer/earnings_analyzer.py](/home/ryan/projects/stock-analysis-api/src/analyzer/earnings_analyzer.py)
- [src/analyzer/normalizers.py](/home/ryan/projects/stock-analysis-api/src/analyzer/normalizers.py)
- [docs/http-api-online-audit.md](/home/ryan/projects/stock-analysis-api/docs/http-api-online-audit.md)

## 备注

- 本文是字段规范审计，不直接修改代码。
- 对 `yfinance.info` 的字段语义，本文只在“文档明确可证”与“现网样本已观测”范围内下结论；凡无法从公开文档稳定确认的部分，均按低置信度处理。
