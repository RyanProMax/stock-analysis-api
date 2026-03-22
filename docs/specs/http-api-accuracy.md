# HTTP API 准确性与整改规格

更新时间：2026-03-22

## 审计结论总览

| 端点 | 结论 |
|------|------|
| `/stock/list` | `usable-with-caveats` |
| `/stock/search` | `usable-with-caveats` |
| `/stock/analyze` | `usable-with-caveats` |
| `/analysis/earnings/earnings` | `usable-with-caveats` |
| `/analysis/competitive/competitive` | `usable-with-caveats` |
| `/valuation/comps` | `inaccurate` |
| `/valuation/dcf` | `model-only` |
| `/model/lbo` | `model-only` |
| `/model/three-statement` | `model-only` |
| `/model/three-statement/scenarios` | `model-only` |

## 已确认问题

### `/stock/list`

- `meta.as_of` 为空
- A 股与美股 `market` 枚举口径不一致

### `/stock/search`

- A 股样本 `industry/area/list_date` 缺失较多
- 元数据完整性不足

### `/stock/analyze`

- `bookValue` 仍未标准化为 `book_value_per_share`
- `market_snapshot.price.source` 过于泛化
- `technical_signals` 缺少字段级 metadata

### `/analysis/earnings/earnings`

- `AAPL` 样本出现 `dividend_yield=42.00%` 的明显错误
- `report_date` 混用了报表期末日与财报发布日期语义
- `estimated_segments` 仍是估算替代而非真实分部披露

### `/analysis/competitive/competitive`

- `estimated_market_context` 仍是启发式估算
- `moat_assessment` 和 `scenario_analysis` 需要更明确的非事实标识
- `facts.company_profile` 仍混入 `analyst_consensus`

### `/valuation/comps`

- peer 层存在单位、币种和量级混乱
- 已污染 `percentiles` 与 `implied_valuation`
- 当前是最优先修复接口

### 模型类接口

- `wacc`、`purchase_price`、`historical_source` 等字段的事实层边界仍不够清晰
- 使用者仍不易区分真实历史输入与模型输出

## 整改要求

### P0

- 修复 `earnings` 的跨标的股息率归一化
- 修复 `comps` peer 数据的单位、币种和量级校验

### P1

- 统一 `as_of`、`pricing_date`、`period_end_date`、`filing_date`
- 将 `competitive` 中 `analyst_consensus` 从 `facts` 移到 `analysis`
- 为事实层细化 source 和 provenance

### P2

- 为 `analysis` 内关键字段补充字段级 metadata
- 为模型接口补充更清晰的 baseline 摘要与 `model_output` 标识

## 已确认保留项

- `NVDA earnings` 的季度核心事实值已与官方披露对齐
- `NVDA stock/analyze` 的股息率与持股比例口径已较此前修正
- `competitive peer_set` 基础可用性已恢复，但仍需继续清洗
