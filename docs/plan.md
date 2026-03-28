# 当前任务计划

更新时间：2026-03-28

## 当前目标

- 完成单一 `POST /analysis/research/snapshot` HTTP 入口改造，并验证统一模块调度、旧路由删除和文档一致性

## 最近完成项

- 已将公共研究分析入口统一为 `POST /analysis/research/snapshot`
- 已扩展 `ResearchSnapshotService` 为 FSP 客观能力快照调度器，支持：
  - 按市场加载默认模块
  - 显式 `modules`
  - `module_options`
  - `cn/us` 双市场 item 级调度
- 已删除旧 `/valuation/*`、`/model/*`、`/analysis/*` 专项公共路由，并从 OpenAPI 中移除
- 已将 `dcf`、`comps`、`earnings`、`competitive` 等模块统一纳入单入口输出，并在统一出口去除 `recommendation`、`confidence`、`price_target`、`moat_assessment`、`positioning`、`thesis`、`conviction`
- 已更新 CLI、HTTP 测试与 service 测试，覆盖默认模块、显式模块、`module_options`、旧路由删除与客观字段约束

## 当前状态

- 公共接口仍然只有 HTTP REST API；内部 `scripts/` 允许承载 skill / agent 调用脚本
- `scripts/poll_research_snapshot.py` 与 `ResearchSnapshotService` 已与 HTTP 入口保持同构
- 当前统一入口默认模块为：
  - `cn`: `research_report`、`report_rc`、`anns_d`、`news`、`major_news`、`earnings`
  - `us`: `earnings`、`earnings_preview`、`dcf`、`comps`、`three_statement`
- 当前扩展模块为：`lbo`、`three_statement_scenarios`、`competitive`、`catalysts`、`model_update`、`sector_overview`、`screen`
- 旧专项分析公共接口已移除；外部调用方必须迁移到统一 snapshot 入口

## 下一步计划

### P0

- 继续补强 `earnings_preview`、`catalysts`、`model_update`、`sector_overview`、`screen` 的字段深度与来源覆盖
- 视数据源能力补充 `cn/us` 模块的 `partial` / `permission_denied` 降级细节

### P1

- 继续扩展第二数据源或更多市场时，沿用统一 dispatcher，不再回到分散路由模式
- 持续收紧模块级 contract，避免客观接口重新引入主观或启发式字段

## 已知风险与阻塞

- `research_report`、`anns_d`、`news`、`major_news` 都可能受 Tushare 单独权限限制，必须在 block 顶层字段中清晰区分 `permission_denied` 与空结果
- `news` / `major_news` 的提及过滤依赖标题与正文文本命中，存在一定召回 / 精度折中，但本阶段不做主观合并或语义扩展
- 统一入口会把模型类、事件类和原始 block 类模块放到同一 payload 中，必须明确 item / module 两层状态语义，避免消费方误读
- `cn` 默认核心模块包含 `earnings`，但现有 A 股财务能力比美股更弱，需要通过 `partial` 或有限字段表达真实覆盖范围
