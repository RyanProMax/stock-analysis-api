# 当前任务计划

更新时间：2026-03-20

## 当前目标

- 继续把当前 HTTP-only 服务向 `daily_stock_analysis` 的工程化数据上下文设计收敛
- 继续把分析输出向 `financial-services-plugins` 的 workflow 化方法收敛
- 在保持 `facts / analysis` 分层的前提下，补强 compact snapshot、workflow contract、evidence 和 quality check

## 最近完成项

- 移除 MCP 能力，项目收敛为纯 HTTP 服务
- 建立统一 contract 层，复杂接口统一返回 `entity / facts / analysis / meta`
- 修复 `earnings` 的季度期别识别与季度事实字段来源
- 修复 `stock/analyze` 股息率归一化与缓存版本问题
- 建立并扩展共享 `fundamental_context`
- 让 `stock/analyze`、`earnings`、`competitive`、`dcf`、`comps`、`lbo`、`three-statement` 都围绕共享事实上下文输出
- 将 `competitive.company_profile` 与 `comps.target.company_profile` 收敛到同一套 builder
- 整理 `docs/`，保留在线审计、字段规范审计和参考仓库对照文档
- 收窄 `README.md`，去除工程进度表述，仅保留架构设计、能力模块和使用说明
- 进一步收窄 `README.md`，移除 `docs/` 和迭代计划相关暴露信息

## 当前状态

- HTTP 服务为唯一对外协议
- 主链路数据结构已基本对齐 `daily_stock_analysis` 的共享 context 设计
- `earnings` 已初步引入 `financial-services-plugins` 风格的 research strategy 结构
- 当前仍缺：
  - compact/detail snapshot 层
  - 更完整的 workflow contract
  - evidence / methodology / quality checks
  - 更细的 source-chain / fallback / provenance 测试

## 下一步计划

### P0

- 为共享 `fundamental_context` 增加 compact/detail snapshot 层
- 为复杂接口补 `methodology / evidence / limitations`
- 增加 source chain、fallback、provenance 的语义测试

### P1

- 为 `competitive`、`dcf`、`three-statement`、`lbo` 补 workflow 文档与结构化 schema
- 增强 cache key、budget bucket 和降级策略
- 引入 evidence refs、quality checks、assumption delta

## 已知风险与阻塞

- `docs/` 默认被 `.gitignore` 忽略，新增文档时需要显式跟踪
- 本地 live 验证依赖服务重启到最新代码，后台 `nohup uv run start` 偶发未成功挂起，需要必要时前台持有进程
- `comps` 仍存在跨市场 peer 单位/币种异常问题，属于后续准确性修复重点
