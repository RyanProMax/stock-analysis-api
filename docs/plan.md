# 当前任务计划

更新时间：2026-03-29

## 当前目标

- 维持 `POST /analysis/research/snapshot` 的 `mode` 化单入口设计，并确保文档、测试和真实返回持续一致

## 最近完成项

- 已将 research snapshot 公共请求收敛为：
  - `market`
  - `symbols`
  - `start_date`
  - `end_date`
  - `mode`
- 已移除公共 `modules` / `module_options`，并在 schema 上启用 `extra=forbid`
- 已把 `mode` 固定为 `base` / `full`，并按市场内置模块集合
- 已将旧 `derived` 升级为跨市场统一 `summary`
- 已把重复状态、来源和限制说明统一上收至 `item.meta.modules`
- 已让 `empty` / `permission_denied` / `not_supported` 模块不再输出空壳 body，只在 `meta.modules` 中体现
- 已同步更新：
  - `docs/architecture.md`
  - `docs/api.md`
  - `docs/strategy.md`
  - `README.md`
  - CLI、HTTP 与 service 测试
- 已用 `300827 + mode=full` 的真实返回重写 `docs/strategy.md`
- 已完成全量回归：`93 passed`

## 当前状态

- 公共接口仍然只有 HTTP REST API；内部 `scripts/` 允许承载 skill / agent 调用脚本
- 旧专项分析公共接口已移除；外部调用方统一通过 snapshot 入口消费客观研究能力
- 当前 research snapshot 公共 contract 已稳定为：
  - 顶层：`status / computed_at / source / market / strategy / request / items`
  - 请求：`market / symbols / start_date / end_date / mode`
  - item：`requested_symbol / status / error / info / summary / 模块业务数据 / meta`
- 当前 `mode` 集合：
  - `cn.base`: `research_report / report_rc / earnings / catalysts / screen`
  - `cn.full`: `research_report / report_rc / anns_d / news / major_news / earnings / catalysts / screen / model_update`
  - `us.base`: `earnings / dcf / comps / three_statement / screen`
  - `us.full`: `earnings / earnings_preview / dcf / comps / three_statement / lbo / three_statement_scenarios / competitive / catalysts / screen / model_update / sector_overview`

## 下一步计划

- 继续观察 `summary` 是否已经覆盖外部 Agent 的决策需求，必要时只在 `summary` 内做增量，不重新暴露模块调度细节
- 若后续需要增强 `screen`、`catalysts` 或 `model_update`，优先沿用当前 `summary + meta.modules` 模式，不回退到模块内重复状态壳
- 继续保持 `docs/strategy.md` 与真实 `mode=full` 输出同步

## 已知风险与阻塞

- `research_report`、`anns_d`、`news`、`major_news` 都可能受 Tushare 单独权限限制，因此 `meta.modules` 的状态与说明必须真实、可追溯
- `news` / `major_news` 的提及过滤依赖标题与正文文本命中，存在一定召回 / 精度折中，因此 `filter_rule` 需要保留在 `notes`
- `base` 既要控制复杂度，又要保留 Agent 决策所需关键信息，后续扩字段时必须避免“看起来更短，但信息损失过大”
- `cn` 默认 `base` 依赖 `research_report` / `report_rc` / `earnings` / `catalysts` / `screen` 协同表达，但 A 股财务能力仍弱于美股，需要通过真实降级而不是补写结论来表达
