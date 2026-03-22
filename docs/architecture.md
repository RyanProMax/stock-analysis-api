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
├── storage/          # 本地 SQLite 行情仓
└── utils/            # 工具
```

- `api/` 只负责 HTTP 输入输出，不承载业务规则
- `core/` 和 `analyzer/` 负责工作流、推导逻辑和分析编排
- `data_provider/` 负责取数、source chain、fallback、字段原始语义维护
- `storage/` 负责单机 SQLite 行情仓，不承载分析规则
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
- A 股与美股的 canonical 日线历史优先沉淀到本地 SQLite 行情仓，作为 watch 与分析接口的首选历史数据来源
- SQLite 只保存数据源返回的必要持久信息与事实型扩展字段，不保存分析报告缓存，不保存 5-10 分钟级 watch baseline
- SQLite 行情仓只承载单机、单写多读的 EOD/日线场景，不承载分钟线、tick 或多实例共享写入
- SQLite 日线仓主表固定为：
  - `a_share_symbols`
  - `a_share_daily`
  - `us_symbols`
  - `us_daily`
  - `sync_runs`
- 主列按 tushare 核心口径建模；低频、跨市场差异大的事实字段放入 `extra` JSON 文本列
- 所有关键事实字段应逐步补齐 `source_chain`、`as_of`、`period_end_date`、`filing_or_release_date`
- fallback 需要区分：
  - 降级成功
  - 真实失败
  - `partial`
  - `not_supported`
- 不同 fallback 路径应支持分层 cache key，避免跨路径污染

## 工作流与质量约束

- 各复杂分析接口应逐步补齐 workflow contract，而不是只定义最终返回字段
- 盯盘接口优先服务 5-10 分钟轮询场景，服务端内部维护 symbol 级内存 baseline，重启后不恢复
- 定时同步任务通过统一 `sync-market-data` 命令执行，支持按市场、scope、symbol 和时间窗口补库
- 公共 HTTP 接口默认先读 SQLite，若最新日线超过 7 个自然日则按需回退外部源并回写，不暴露强制 `refresh`
- A 股列表与日线优先级默认是 `Tushare -> fallback`，URL 与 token 必须通过环境变量读取，不允许硬编码
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
