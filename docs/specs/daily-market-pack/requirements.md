# Daily Market Pack Requirements

更新时间：2026-07-30

## 问题与范围

Stock Daily 当前在 Node.js 采集器内直接请求腾讯证券、东方财富、FRED 和
Yahoo Finance。相同的底层行情能力无法被常驻 HTTP 服务、内部 Agent CLI 和
一次性 Skill 调用复用，且调用方各自承担截点、fallback 和来源追踪。

本阶段新增一个只读、无持久化的日报行情数据包能力，并让 Stock Daily 通过
`stock-analysis-skill` 约定的一次性 CLI 调用它。新闻采集、行业热度计算和页面
展示仍由 Stock Daily 负责。

## 用户故事

1. 作为日报调度器，我希望在 FastAPI 未启动时一次取得中美主要指数和美国
   10 年期国债收益率，以便每日任务无需常驻本地服务。
2. 作为 Skill / Agent 调用方，我希望得到稳定的严格 JSON、统一截点和来源信息，
   以便可靠消费和审计降级路径。
3. 作为 API 维护者，我希望底层 provider 与上层 CLI 解耦，以便未来由 HTTP、
   其他 CLI 或分析服务复用同一取数逻辑。

## 验收条件

1. 当调用 `scripts/market_data_query.py daily-pack --cutoff-at <ISO>` 时，系统应在
   不启动 FastAPI 的情况下返回严格 JSON。
2. 当请求日报数据包时，系统应返回 SPX、IXIC、DJI、DGS10、SSE、SZSE、
   CSI300、CSI500、CHINEXT 和 STAR50 十项指标，并为每项提供 `as_of`、
   provider、来源 URL、最新值、前值和变化。
3. 当数据源返回晚于 `cutoff_at` 的数据时，系统应排除该数据，不把盘中或未来
   数据伪装成已完成收盘。
4. 当同一美股或美债指标有 FRED 与 Yahoo 两个完整候选时，系统应选择最新
   `as_of` 的候选，并保留尝试过的 provider 状态。
5. 当中国指数主源失败时，系统应按腾讯证券、东方财富、Yahoo Finance 的顺序
   降级；当某项仍失败时，系统应返回结构化失败，不补编数值。
6. 当未显式要求持久化时，系统应固定使用 `persistence=none`，且不得读取或写入
   SQLite 行情仓、scheduler state、watchlist 或券商状态。
7. 当 Stock Daily 采集行情时，采集器应调用上述一次性 CLI，而不再直接请求十项
   指数/收益率的外部数据源。
8. 当 CLI 返回非 `ok`、指标缺失或 contract 不匹配时，Stock Daily 应让采集失败，
   不静默回退到旧的 Node.js 直连实现。

## 非目标

- 本阶段不新增公共 HTTP 路由。
- 本阶段不迁移 Stock Daily 的新闻采集。
- 本阶段不迁移 Stock Daily 的行业热度采集与 0–100 热度算法。
- 本阶段不写入 canonical SQLite 日线仓。
- 本阶段不新增投资建议、目标价或主观评级。
