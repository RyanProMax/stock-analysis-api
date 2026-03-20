# HTTP-Only 服务线上准确性全接口审计

审计时间：2026-03-20  
审计对象：本地 HTTP 服务 `http://127.0.0.1:8080`  
审计方法：本地 live 调用 + 外部公开来源核验  
审计范围：全部 HTTP 接口，不涉及 MCP

## 审计结论总览

| 接口 | 方法 | interface_type | 当前结论 |
|------|------|----------------|----------|
| `/stock/list` | GET | fact | `usable-with-caveats` |
| `/stock/search` | POST | fact | `usable-with-caveats` |
| `/stock/analyze` | POST | mixed | `usable-with-caveats` |
| `/analysis/earnings/earnings` | GET | mixed | `usable-with-caveats` |
| `/analysis/competitive/competitive` | GET | mixed | `usable-with-caveats` |
| `/valuation/comps` | GET | mixed | `inaccurate` |
| `/valuation/dcf` | GET | model | `model-only` |
| `/model/lbo` | GET | model | `model-only` |
| `/model/three-statement` | GET | model | `model-only` |
| `/model/three-statement/scenarios` | GET | model | `model-only` |

## 样本与外部来源

本地样本：

- `NVDA`
- `AAPL`
- `600519`
- `INVALID_SYMBOL_12345`

主要外部来源：

- NVIDIA IR: https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Fourth-Quarter-and-Fiscal-2026/default.aspx
- NVIDIA IR FY2025 对照: https://investor.nvidia.com/news/press-release-details/2025/NVIDIA-Announces-Financial-Results-for-Fourth-Quarter-and-Fiscal-2025/default.aspx
- Apple IR dividend history: https://investor.apple.com/dividend-history/default.aspx?source=content_type%3Areact%7Cfirst_level_url%3Aarticle%7Csection%3Amain_content%7Cbutton%3Abody_link
- Apple Investor Relations 主页: https://investor.apple.com/
- 上交所贵州茅台公告样本: https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-03-05/600519_20250305_3PI5.pdf
- NASDAQ Agilent 新闻稿样本: https://www.nasdaq.com/press-release/agilent-announces-cash-dividend-255-cents-share-2026-02-11

## 分接口审计

### `/stock/list` `GET`

- 主要 facts：证券主数据列表
- 主要 analysis：无
- 本地样本：
  - `market=美股&limit=2` 返回 `A`, `AA`
  - 记录级 `meta.source/status/as_of` 已存在
- 线上核验：
  - `A = Agilent Technologies Inc. Common Stock`
  - `AA = Alcoa Corporation Common Stock`
  - 命名与公开市场命名方向一致
- 当前结论：`usable-with-caveats`
- 已确认问题：
  - `meta.as_of` 为空，无法判断主数据快照日期
  - A 股与美股 `market` 字段口径不一致，美股返回“美股”，A 股样本返回“主板”
- 修复建议：
  - 为列表数据补充 `as_of`
  - 统一 `market` 枚举值与展示值

### `/stock/search` `POST`

- 主要 facts：匹配到的证券主数据
- 主要 analysis：无
- 本地样本：
  - `NVDA` 返回 `NVDA.US / NVIDIA Corporation Common Stock`
  - `600519` 返回 `600519.SH / 贵州茅台`
- 线上核验：
  - `NVDA` 名称与公开市场命名一致
  - `600519` 与上交所贵州茅台样本公告代码一致
- 当前结论：`usable-with-caveats`
- 已确认问题：
  - A 股样本 `industry/area/list_date` 为空，元数据完整性不足
- 修复建议：
  - 对 A 股主数据增加字段完整性标识
  - 将缺失字段来源写入 `meta`

### `/stock/analyze` `POST`

- 主要 facts：
  - `facts.market_snapshot.price`
  - `facts.fundamentals.*`
- 主要 analysis：
  - `technical_signals`
  - `fear_greed`
  - `trend`
  - `qlib`
- 本地样本：
  - `NVDA` 返回 `price=178.56`
  - `dividendYield.value=0.0002`, `display_value=0.02%`
  - `heldPercentInsiders=4.21%`
  - `heldPercentInstitutions=69.77%`
  - `sharesPercentSharesOut=1.02%`
- 线上核验：
  - NVDA 官方股息现金额极低，公开市场口径约 `0.02%`，与当前返回方向一致
  - 市值、营收、利润率等与公开市场口径大体一致
- 当前结论：`usable-with-caveats`
- 已确认问题：
  - `bookValue` 仍以字符串事实字段公开，未标准化为 `book_value_per_share`
  - `market_snapshot.price.source=market_data` 过于泛化，未细化到具体源
  - `technical_signals` 仍缺少字段级 `data_type`，只是被整体归类到 `analysis`
- 修复建议：
  - 细化 `bookValue` 为标准字段名和单位
  - 细化事实层 source
  - 为 analysis 内关键字段增加字段级 metadata

### `/analysis/earnings/earnings` `GET`

- 主要 facts：
  - `facts.quarterly.revenue`
  - `facts.quarterly.net_income`
  - `facts.quarterly.ebitda`
  - `facts.quarterly.eps`
  - `facts.consensus_comparison`
- 主要 analysis：
  - `estimated_segments`
  - `guidance_interpretation`
  - `key_metrics`
  - `trends`
- 本地样本：
  - `NVDA`: `Q4 FY2026`, `report_date=2026-01-31`, `revenue=$68.13B`, `eps=$1.76`
  - `AAPL`: `Q1 FY2026`, `report_date=2025-12-31`, `revenue=$143.76B`, `eps=$2.84`
- 线上核验：
  - NVIDIA 官方 FY2026 Q4 财报披露季度收入 `$68.1B`、GAAP diluted EPS `$1.76`，与当前返回对齐
  - `consensus_comparison.status=unavailable` 属于正确降级，不视为错误
  - Apple dividend history 显示单季股息金额极小，但当前 `AAPL` earnings 返回 `dividend_yield=42.00%`
- 当前结论：`usable-with-caveats`
- 已确认问题：
  - `AAPL` 样本中 `analysis.key_metrics.dividends.dividend_yield=42.00%`，明显错误
  - `estimated_segments` 仍是聚合/行业级替代，不是公司真实分部披露
  - `report_date` 目前是报表期末日，不一定等于财报发布日期；字段命名容易误导
- 修复建议：
  - 将股息率归一化逻辑从 NVDA 单点修正升级为跨标的统一规则
  - `report_date` 拆分为 `period_end_date` 与 `filing_or_release_date`
  - 如果无真实 segment source，字段名改为更明确的 `estimated_segments`

### `/analysis/competitive/competitive` `GET`

- 主要 facts：
  - `facts.company_profile`
  - `facts.peer_set`
- 主要 analysis：
  - `market_context`
  - `positioning`
  - `comparative`
  - `moat_assessment`
  - `industry_metrics`
  - `scenario_analysis`
- 本地样本：
  - `NVDA` peer 集包括 `AMD/INTC/AVGO/QCOM`
  - `AAPL` peer 集包括 `GOOGL/MSFT/AMZN/META`
  - peer 事实值不再全 0
- 线上核验：
  - NVDA、AAPL 及 peer 的市值/营收/增长大体符合公开市场口径
- 当前结论：`usable-with-caveats`
- 已确认问题：
  - `analysis.market_context.estimated_market_context` 仍为 `market_cap * 5 heuristic`
  - `moat_assessment` 与 `scenario_analysis` 纯属启发式分析，不能解释为事实
  - `facts.company_profile` 里仍混入 `analyst_consensus` 这类并非硬事实字段
- 修复建议：
  - 将 `analyst_consensus` 从 `facts` 移到 `analysis`
  - 为启发式字段补充更明确的 `data_type=estimate/derived`
  - 将 `estimated_market_context` 的方法说明进一步结构化

### `/valuation/comps` `GET`

- 主要 facts：
  - `facts.target`
  - `facts.peer_set`
- 主要 analysis：
  - `operating_metrics`
  - `valuation_multiples`
  - `percentiles`
  - `implied_valuation`
  - `recommendation`
- 本地样本：
  - `NVDA` 返回多个 peer，包括 `TSM/AVGO/AMD/INTC/...`
- 线上核验：
  - 部分 peer 的原始量级明显异常
  - `TSM revenue=3,809,054.29`（百万）对应约 `3.8T`，与正常量级不符
  - `AVGO market_cap=1,516,448.91` 但 `enterprise_value=160,833.24`，量级关系异常
- 当前结论：`inaccurate`
- 已确认问题：
  - peer 层存在明显单位或币种/口径混乱
  - 事实层 `peer_set` 中至少部分字段不可信，会污染后续 `percentiles` 与 `implied_valuation`
  - recommendation 虽已放入 `analysis`，但依赖的输入事实已受污染
- 修复建议：
  - 对 peer 逐个增加货币、单位和源字段
  - 对异常量级加校验阈值，异常时直接剔除而不是进入统计
  - 对跨市场/ADR/非 USD 口径做显式换算或禁用

### `/valuation/dcf` `GET`

- 主要 facts：
  - `current_price`
  - `wacc`
  - `fcf_history.status`
  - `fcf_source`
- 主要 analysis：
  - 估值输出、敏感性矩阵、recommendation
- 本地样本：
  - `NVDA` 返回 `current_price=178.56`
  - `fcf_source=cashflow_statement`
  - `data_completeness=complete`
- 线上核验：
  - 输入事实层结构清晰
  - 输出显然属于模型估值，不适合按事实准确性审计
- 当前结论：`model-only`
- 已确认问题：
  - `facts.inputs.wacc` 被标成输入，但其本身是 derived 值
  - `current_price.as_of=2026-01-31` 与现价语义不完全一致，更像估值基准日期而非实时报价日期
- 修复建议：
  - 将 `wacc` 移到 `analysis` 或明确标记为 derived input
  - 区分 `pricing_date` 与 `financial_as_of`

### `/model/lbo` `GET`

- 主要 facts：
  - `facts.baseline.current_price`
- 主要 analysis：
  - 全部交易、债务、收益输出
- 本地样本：
  - `purchase_price` 在 `facts.baseline` 为 `null`
  - 输出 IRR、exit multiple 等均为典型情景结果
- 线上核验：
  - 不适合作为事实接口审计
- 当前结论：`model-only`
- 已确认问题：
  - `facts.baseline.purchase_price` 为 `null`，事实层字段设计不完整
  - 事实层与模型层分界仍略显粗糙
- 修复建议：
  - 若 purchase price 是模型推导值，则从 `facts` 移除
  - 将 baseline 严格限制为真实历史输入

### `/model/three-statement` `GET`

- 主要 facts：
  - `facts.baseline.historical_source`
  - `facts.baseline.as_of`
- 主要 analysis：
  - 全部预测三表与关键指标
- 本地样本：
  - `historical_source=yfinance financial statements`
  - `balance_check=0.0`
  - 不再出现负债和现金符号错误
- 线上核验：
  - 只能验证基线来源真实与分类正确，不能按“预测准确”审计
- 当前结论：`model-only`
- 已确认问题：
  - `facts.baseline` 仅暴露来源和日期，未暴露真实历史基线摘要
  - 使用者仍不容易区分哪些值来自历史、哪些来自预测
- 修复建议：
  - 将历史基线摘要放进 `facts.baseline`
  - 对输出数组增加更强的 `model_output` 标记

### `/model/three-statement/scenarios` `GET`

- 主要 facts：
  - `facts.baseline.historical_source=scenario_comparison`
- 主要 analysis：
  - bull/base/bear 对比
- 本地样本：
  - 返回结构正确，`interface_type=model`
- 线上核验：
  - 纯模型情景比较，不按事实准确性审计
- 当前结论：`model-only`
- 已确认问题：
  - `facts.baseline.historical_source=scenario_comparison` 不是事实来源名，字段语义偏弱
- 修复建议：
  - 使用真实历史基线来源，情景比较只放在 `analysis`

## 重点发现

### 已确认准确或基本准确

- `NVDA earnings` 的季度核心事实值已与 NVIDIA 官方 FY2026 Q4 财报对齐
- `NVDA stock/analyze` 的股息率与持股比例口径已从之前的错误状态修正
- `competitive peer_set` 的事实值不再全 0，基础可用性恢复

### 已确认异常

- `AAPL earnings` 的 `analysis.key_metrics.dividends.dividend_yield=42.00%`
  - 这是明显错误，属于单位/口径归一化缺陷
- `NVDA comps` 中至少部分 peer 的量级异常
  - 典型表现是 `TSM revenue` 与 `AVGO enterprise_value` 明显不合理
  - 已影响事实层和后续统计结果

### 结构性风险

- 一些非硬事实字段仍留在 `facts`
  - 例如 `competitive.company_profile.analyst_consensus`
- `as_of` 在部分接口里混用“财务报表基准日”和“市场价格观测日”
- `analysis` 层虽然已与 `facts` 分开，但字段级 `data_type` 仍不统一

## 修复优先级

### P0

- 修复 `earnings` 的跨标的股息率归一化
- 修复 `comps` peer 数据的单位/币种/量级校验

### P1

- 统一 `as_of`、`pricing_date`、`period_end_date`、`filing_date`
- 将 `competitive` 中 `analyst_consensus` 从 `facts` 移到 `analysis`

### P2

- 为 `analysis` 内部字段补充字段级 metadata
- 补充 `facts.baseline` 的历史摘要，提高模型接口可解释性

## 备注

- 本轮未修改代码，只做 live 审计与文档固化
- 模型接口的结论是“分类正确/基线真实/限制充分”，不是“预测正确”
