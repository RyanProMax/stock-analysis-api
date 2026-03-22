# 架构约束

更新时间：2026-03-22

## 系统边界

- 项目当前仅保留 HTTP REST API，对外协议不再包含 MCP
- 外部 Agent 的盯盘能力统一通过单一轮询接口提供，不提供额外的 cursor、rules、health 等公共盯盘接口
- 新增能力时只更新 HTTP 路由、schema、文档和测试
- 业务逻辑放在 `src/core/` 或 `src/analyzer/`
- 标准化 contract 放在 `src/model/contracts.py` 和 `src/analyzer/normalizers.py`

## 模块边界

```text
src/
├── analyzer/         # 因子计算、分析拼装、标准化适配
├── api/              # FastAPI 路由与 schema
├── core/             # 共享服务、工作流和管线
├── data_provider/    # 数据源接入、fallback 与字段采集
├── model/            # 领域模型与统一 contract
├── storage/          # 缓存
└── utils/            # 工具
```

- `api/` 只负责 HTTP 输入输出，不承载业务规则
- `core/` 和 `analyzer/` 负责工作流、推导逻辑和分析编排
- `data_provider/` 负责取数、source chain、fallback、字段原始语义维护
- `model/` 负责统一 contract，避免 route 或 provider 私自扩字段语义

## 输出 contract 约束

- 复杂接口统一返回 `entity`、`facts`、`analysis`、`meta`
- 盯盘接口默认返回 compact snapshot，不复用重型分析报告整包 payload
- `facts` 仅允许 `reported` / `consensus`
- `analysis` 仅允许 `derived` / `estimate` / `model_output`
- 比例型机器值统一存 `ratio`
- 缺少可靠原始数据时宁可降级，也不要伪造历史或共识

## 数据与来源约束

- `facts` 优先使用 statement/event 等具备明确期别和来源语义的数据
- `snapshot` 型字段不得混充季度事实或报表期事实
- 所有关键事实字段应逐步补齐 `source_chain`、`as_of`、`period_end_date`、`filing_or_release_date`
- fallback 需要区分：
  - 降级成功
  - 真实失败
  - `partial`
  - `not_supported`
- 不同 fallback 路径应支持分层 cache key，避免跨路径污染

## 工作流与质量约束

- 各复杂分析接口应逐步补齐 workflow contract，而不是只定义最终返回字段
- 盯盘接口优先服务 5-10 分钟轮询场景，服务端内部维护 symbol 级 baseline
- workflow 至少覆盖：
  - 输入检查
  - 证据要求
  - 输出结构
  - 质量检查
  - 限制说明
- 输出中的关键结论应可追溯到事实、证据或模型方法

## 演进方向

- 继续向共享 `fundamental_context` 收敛
- 在共享 context 之上补齐 compact/detail snapshot 层
- 让 route 层和 analysis 层默认消费稳定 extractor，而不是直接消费整包 context
- 持续增强 evidence、quality check、source-chain、fallback 和 provenance 测试
