# 参考仓库对照与可借鉴优化点

更新时间：2026-03-20  
对照仓库：

- `~/projects/daily_stock_analysis`
- `~/projects/financial-services-plugins`

本文只记录除“数据源标准化”和“研报分析策略”之外，当前项目仍值得借鉴的工程与产品设计点。

## 结论摘要

当前项目已经在两条主线上明显向参考仓库收敛：

- 数据事实层已基本对齐 `daily_stock_analysis` 的共享 `fundamental_context` 思路
- `earnings` 分析块已开始借鉴 `financial-services-plugins` 的研究流程结构

但除这两块之外，仍有 6 类高价值优化点值得继续吸收：

1. 紧凑上下文与稳定提取层
2. 分层 fallback 与预算控制
3. 更完整的可观测性与证据元数据
4. 更高密度的语义回归测试
5. 工作流模板化与 schema 化
6. 输出质量控制与证据纪律

## 一、来自 `daily_stock_analysis` 的可借鉴点

### 1. 紧凑上下文设计

`daily_stock_analysis` 不只是维护 `fundamental_context`，还会为下游消费方额外生成 compact context，降低 token、耦合和字段漂移风险。

可借鉴点：

- 在共享 `fundamental_context` 之上，再维护一层稳定的 compact/detail snapshot
- 给 `earnings`、`competitive`、`comps`、`dcf` 提供统一 extractor，而不是让接口直接消费整包 context
- 明确“聚合层”和“消费层”的边界

当前项目建议：

- 新增 `compact_fundamental_snapshot` 或等价结构
- route 层和 analysis 层默认只消费 compact 视图

参考：

- `~/projects/daily_stock_analysis/src/agent/tools/data_tools.py`

### 2. 分层 fallback 与预算控制

`daily_stock_analysis` 的一个优势是：不是简单“拿不到就报错”，而是有明确的 fallback 顺序、预算约束、缓存键隔离和 `partial/not_supported` 语义。

可借鉴点：

- 为高成本或不稳定源引入 budget bucket
- 不同 fallback 路径使用不同 cache key
- block 级别保留 `ok/partial/not_supported/failed`
- 明确“降级成功”和“真实失败”的区别

当前项目建议：

- 给 `competitive`、`comps` 的 peer 数据抓取增加降级预算
- 给 statement/event/snapshot 不同路径增加分层 cache key
- 避免在 fallback 失败时静默写入 0 或空结构

参考：

- `~/projects/daily_stock_analysis/tests/test_fundamental_context.py`

### 3. 更完整的可观测性元数据

`daily_stock_analysis` 会把 `source_chain`、`coverage`、`errors` 当成一等公民，而不是调试附属物。

可借鉴点：

- block 级 source chain 更细
- 能区分实际命中源与 fallback 尝试源
- 对失败原因有结构化记录
- `as_of`、`computed_at`、cache 语义更清晰

当前项目建议：

- 在 `meta` 和 block `source_chain` 中补充 `attempted/selected` 语义
- 为关键接口增加 `pricing_date`、`financial_as_of`、`computed_at`
- 对 peer 剔除、异常量级过滤保留 evidence

参考：

- `~/projects/daily_stock_analysis/tests/test_fundamental_context.py`
- `~/projects/daily_stock_analysis/tests/test_analysis_metadata.py`

### 4. 更强的语义测试体系

`daily_stock_analysis` 的测试价值不在数量本身，而在它大量覆盖“语义正确性”和“降级行为”，而不是只测接口能否返回。

可借鉴点：

- 对 context 聚合规则建专门测试
- 对 fallback 顺序和 cache key 建测试
- 对 report schema 和 metadata 建测试
- 对 compact context 输出建测试

当前项目建议：

- 新增 `tests/test_fundamental_context_contract.py`
- 新增 `tests/test_source_chain_semantics.py`
- 新增 `tests/test_peer_validation.py`
- 新增 `tests/test_model_input_provenance.py`

参考：

- `~/projects/daily_stock_analysis/tests/test_fundamental_context.py`
- `~/projects/daily_stock_analysis/tests/test_report_schema.py`
- `~/projects/daily_stock_analysis/tests/test_analysis_metadata.py`

## 二、来自 `financial-services-plugins` 的可借鉴点

### 5. 工作流模板化与 schema 化

`financial-services-plugins` 最值得借鉴的不是“文案像卖方研报”，而是它把复杂分析拆成可重复的 workflow、references、output schema 和 checklist。

可借鉴点：

- 每个分析能力都应有显式 workflow
- workflow 包含输入检查、证据要求、输出结构、质检规则
- 不是只定义最终文案，而是定义“如何完成工作”

当前项目建议：

- 给 `competitive`、`dcf`、`three-statement`、`lbo` 分别补 workflow docs
- 给每个 analysis 接口增加 `methodology`、`evidence`、`quality_checks`
- 在 `docs/` 保留接口级 workflow，而不是只保留 API 描述

参考：

- `~/projects/financial-services-plugins/equity-research/skills/earnings-analysis/references/workflow.md`
- `~/projects/financial-services-plugins/financial-analysis/skills/competitive-analysis/references/schemas.md`
- `~/projects/financial-services-plugins/financial-analysis/skills/3-statement-model/references/formulas.md`

### 6. 输出质量控制与证据纪律

`financial-services-plugins` 的另一项长处，是会把方法、假设、检查项、模板、引用纪律前置，不让输出停留在“像分析”。

可借鉴点：

- 输出必须可追溯到 workflow
- 关键结论要有 evidence 或明确方法来源
- 模型更新要有 assumption delta
- 报告模板要有 quality checklist

当前项目建议：

- `analysis` 增加 `evidence_refs`
- `model` 接口增加 `assumption_changes`
- `competitive` 增加 `heuristic_disclosure`
- `earnings` 增加 `release_evidence` 和 `thesis_delta`

参考：

- `~/projects/financial-services-plugins/equity-research/skills/initiating-coverage/assets/quality-checklist.md`
- `~/projects/financial-services-plugins/equity-research/skills/earnings-analysis/references/report-structure.md`
- `~/projects/financial-services-plugins/financial-analysis/skills/competitive-analysis/references/frameworks.md`

## 三、优先级建议

### P0

- 为共享 `fundamental_context` 增加 compact/detail snapshot 层
- 给复杂接口补 `methodology / evidence / limitations`
- 补 source chain / fallback / provenance 的语义测试

### P1

- 为 `competitive`、`dcf`、`three-statement`、`lbo` 补 workflow 文档与 schema
- 增强 cache key、budget bucket、降级策略
- 引入 evidence refs 和 quality checks

### P2

- 再考虑模板化输出、通知链路、前端/报表展示层面的能力迁移

## 四、最终判断

如果只看“底层架构”，当前项目最应该继续借鉴的是 `daily_stock_analysis` 的工程化数据上下文体系。  
如果看“分析产出质量”，当前项目最应该继续借鉴的是 `financial-services-plugins` 的 workflow productization。

换句话说：

- `daily_stock_analysis` 更适合指导“系统怎么稳定取数、降级、缓存、聚合和消费”
- `financial-services-plugins` 更适合指导“分析结果怎么变成专业、可复核、可复用的工作流产物”

当前项目下一阶段最合理的方向，不是继续堆接口，而是把这两者结合成：

- 统一 context
- 统一 extractor
- 统一 workflow contract
- 统一 evidence / quality check
