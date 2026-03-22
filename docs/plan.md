# 当前任务计划

更新时间：2026-03-22

## 当前目标

- 稳定首版单接口盯盘轮询 API
- 持续提升美股降级质量、alert 语义和 polling contract
- 保持任务、架构和规格三层文档结构稳定

## 最近完成项

- 完成盯盘 API 方案设计，确定对外只保留 `POST /watch/poll`
- 确认服务端内部按 `symbol` 维护 baseline，不使用 cursor / monitor_id
- 确认首版范围覆盖 A 股和美股，US 链路允许降级为 latest available snapshot
- 实现 `/watch/poll` route、request schema、watch polling service 和 symbol 级 baseline cache
- 输出 compact snapshot、delta、alerts 的统一 contract
- 删除旧 specs，新增唯一规格文档 `docs/specs/watch-polling-api.md`
- 补齐 watch contract 测试、HTTP route 测试和轮询逻辑单测
- 明确 `quote.mode` 与 `meta.degradation` 语义，区分 realtime / daily_fallback / unavailable
- 将美股日线降级统一标记为 `partial`，避免将 fallback 结果误判为 realtime `ok`
- 补充 `source_chain`、降级信息和 watch contract 语义测试

## 当前状态

- HTTP 服务仍是唯一对外协议
- `facts / analysis / meta` 分层仍是当前输出 contract 基线
- 当前唯一对外盯盘能力应收敛为单一轮询接口
- 旧的字段治理与 API 审计 specs 已不再代表当前主任务
- 首版已完成的实现包括：
  - compact snapshot
  - delta / alerts
  - symbol 级 baseline cache
  - A 股实时优先、美股降级可用
  - quote 降级模式显式暴露
  - US daily fallback 不再伪装为 realtime `ok`

## 下一步计划

### P0

- 增强美股 next earnings date 和 quote 降级质量
- 继续补充 source chain / partial / failure 语义测试
- 细化 alert 阈值和 evidence 说明，减少误报

### P1

- 继续压缩轮询 payload，控制 token 与重复字段
- 评估是否需要引入更稳定的 US realtime quote 链路
- 评估是否需要将 baseline 存储从本地文件缓存升级为更显式的状态存储

## 已知风险与阻塞

- 美股缺少与 A 股同等级的统一 realtime quote，首版需要接受 partial 降级
- symbol 级 baseline 为全局共享，不区分调用方，会影响多 Agent 并发观测语义
- 如果继续往 `docs/specs/` 保留旧整改规划，会再次偏离当前主任务
