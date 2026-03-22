# 当前任务计划

更新时间：2026-03-22

## 当前目标

- 将 `harness` 的 AI Friendly 工程改造持续收敛到稳定文档结构
- 保持当前任务统一收敛到 `docs/plan.md`
- 保持架构约束统一收敛到 `docs/architecture.md`
- 保持未完成需求和整改项统一收敛到 `docs/specs/`

## 最近完成项

- 完成 `docs` 三层结构重组：
  - `docs/plan.md` 承载任务和进展
  - `docs/architecture.md` 承载架构约束
  - `docs/specs/` 承载未完成规格与整改项
- 已删除重复职责的旧文档：
  - `docs/architecture-benchmark-notes.md`
  - `docs/data-source-field-spec-audit.md`
  - `docs/http-api-online-audit.md`
- 已将旧文档中的有效内容迁移为新的权威文档结构
- 明确 `harness` 在本项目中指 AI Friendly 工程改造，而不是独立目录

## 当前状态

- HTTP 服务仍是唯一对外协议
- `facts / analysis / meta` 分层仍是当前输出 contract 基线
- `docs` 结构重组已经完成
- 当前保留的 `docs/specs/` 文件都应代表尚未完成的执行规格
- 当前剩余工作不再是文档迁移，而是按规格继续做 AI Friendly 工程整改

## 下一步计划

### P0

- 继续清理 `docs/specs/`，删除已完成的阶段性规格
- 先推进 `data-source-field-governance` 中的 P0 项
- 先推进 `http-api-accuracy` 中的 P0 项

### P1

- 按 `docs/specs/` 的整改项继续推进 compact/detail snapshot
- 增加 source chain、fallback、provenance 的语义测试
- 为 `competitive`、`dcf`、`three-statement`、`lbo` 补 workflow schema 与 evidence 约束

## 已知风险与阻塞

- `comps` 仍存在跨市场 peer 单位/币种异常问题，属于后续准确性修复重点
- 若后续把“迁移说明”或“已完成审计快照”继续留在 `docs/specs/`，文档会再次膨胀和漂移
