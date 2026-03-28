# 当前任务计划

更新时间：2026-03-28

## 当前目标

- 新增 `scripts/poll_research_snapshot.py`，交付 Tushare-first 的 CN 股票研报快照脚本，供内部 Agent / skill 调用
- 建立 research snapshot 的单源运行、可多源扩展 provider 骨架，并固定输出结构化 JSON contract
- 清理现有 HTTP `/analysis/earnings/earnings` 输出中的旧 `analysis.research_strategy` 叙事结构，只保留确定性字段

## 最近完成项

- 已确认新能力是内部脚本入口，不改变“HTTP 是公共接口”的系统边界
- 已核实 Tushare `research_report`、`report_rc`、`anns_d` 的官方参数与字段形状，确定 schema 直接以 Tushare 字段为准
- 已确认 `news` / `major_news` 不能按股票直接过滤，v1 固定采用“按来源拉取 + 按股票名/代码提及过滤”的确定性策略
- 已确认仓库当前不存在 `poll_realtime_quotes.py`，本轮不追不存在的对齐脚本，只新增共享 identity helper 供 research snapshot 使用
- 已锁定 HTTP 清理范围：删除 `src/analyzer/research_strategy.py` 及其在 earnings contract 中的引用，并同步调整测试与文档
- 已新增 `scripts/poll_research_snapshot.py`、research snapshot service / CLI、Tushare research fetchers 与 shared identity contract
- 已完成 `/analysis/earnings/earnings` 的旧 `analysis.research_strategy` 清理，并同步调整文档与测试
- 已完成定向测试与全量测试，当前 `97 passed`
- 已修复 `report_rc` 请求窗口仅命中 `非个股` 时的回退策略，改为回退到最近个股研报日期
- 已补充 `docs/strategy.md`，明确当前项目的分析边界是“确定性 workflow / derived”，不包含主观研判
- 已将 `docs/strategy.md` 改为结合 `300827` 真实返回的带注释 JSON 示例，直接在示例中解释关键字段
- 已将 research snapshot 的 block contract 扁平化：删除 `capabilities`，并把各 block 改为 `records + source_status...` 单层结构

## 当前状态

- 公共接口仍然只有 HTTP REST API；内部 `scripts/` 允许承载 skill / agent 调用脚本
- `scripts/poll_research_snapshot.py` 已落地，当前支持 `CN` 股票与 `US not_implemented` 占位
- research snapshot 当前固定走 `tushare` provider registry，并保留多源 fallback 骨架与 `attempted_sources`
- `news` / `major_news` 当前采用固定来源 + 标题/正文提及过滤，不做主观聚合
- 当请求窗口内只有 `非个股` 的 `report_rc` 时，当前会回退到最近个股 `report_rc` 日期，避免误判为无个股研究覆盖
- `/analysis/earnings/earnings` 已移除旧 `analysis.research_strategy`，仅保留确定性字段
- `docs/specs/tushare-first-research-snapshot.md` 已补充本轮 contract、状态语义和 derived 规则
- `docs/strategy.md` 已明确说明：research snapshot 不是原始透传，但也不包含 LLM 或主观研究结论层
- research snapshot 各原始数据块当前统一直接返回 `records`、`source`、`source_status`、`source_error`、`attempted_sources`

## 下一步计划

### P0

- 用真实 Tushare 凭证验证 `research_report`、`report_rc`、`anns_d`、`news`、`major_news` 的权限语义与线上字段稳定性
- 观察 `news` / `major_news` 提及过滤的噪音情况，决定后续是否需要更严格的标题优先规则

### P1

- 若后续接入 US 或第二数据源，再在当前 dispatcher 上扩展 provider registry
- 若后续重新引入主观研究层，需要先定义与当前确定性输出分层隔离的 contract

## 已知风险与阻塞

- `research_report`、`anns_d`、`news`、`major_news` 都可能受 Tushare 单独权限限制，必须在 block 顶层字段中清晰区分 `permission_denied` 与空结果
- `news` / `major_news` 的提及过滤依赖标题与正文文本命中，存在一定召回 / 精度折中，但本阶段不做主观合并或语义扩展
- `US` 本轮只做 schema 预留，不交付实际研报策略
