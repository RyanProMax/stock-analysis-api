# Agentic Strategy Loop Spec

更新时间：2026-05-16

## 背景

当前 `task-chain` 已经能做 due task、lease、防重入、append-only run log、小时汇报、盘后研究、KOL / news 扫描、sector review、strategy analysis 和 daily report 的结构化调度。

但它仍是确定性脚本层：

- `task-chain` 只负责元调度和结构化报告。
- KOL skill 返回 `assistant_prompt` 时，`kol_scan` 只标记 `status=agent_required`。
- `agent_required` 不是 agent 执行结果，不能作为策略输入。
- 真实 subagents review 后续由 Cli Claw / Agent 层接入。

本 spec 定义从确定性脚本升级到 agent 介入闭环的最小可审计 contract。

## 目标

- 将需要 agent 处理的任务落入持久化 handoff queue。
- 让 Cli Claw / scheduled agent 通过 CLI claim / complete / fail。
- 将 agent 语义 review 回写为可验证 evidence，而不是直接改策略。
- 将策略建议限制在 candidate proposal、independent judge、human review、registry gate 内。
- 保持禁止真实交易、禁止自动 approve、禁止自动 activate。

## 非目标

- 不实现真实交易。
- 不新增公共 HTTP API。
- 不让 agent 直接执行 broker、OpenD 写入、`unlock_trade` 或订阅。
- 不让 agent 自动 approve / activate 策略。
- 不把同一个 agent 同时作为 researcher 和 judge。
- 不把 `assistant_prompt` 当作已完成报告。

## 核心对象

### AgentHandoffItem

```json
{
  "handoff_id": "ah_20260516_000001",
  "source": "task_chain",
  "source_task_id": "task_...",
  "source_run_id": "run_...",
  "source_task_type": "kol_scan",
  "role": "kol_researcher",
  "status": "pending",
  "priority": 50,
  "market": "cn",
  "symbols": ["HK.00700"],
  "as_of": "2026-05-16",
  "input_payload": {},
  "input_hash": "sha256:...",
  "idempotency_key": "task_run:run_...:kol_researcher",
  "allowed_actions": ["semantic_review", "evidence_summary"],
  "forbidden_actions": ["live_trade", "unlock_trade", "approve_strategy", "activate_strategy"],
  "created_at": "2026-05-16T00:00:00+00:00",
  "leased_by": null,
  "lease_expires_at": null
}
```

状态：

- `pending`
- `leased`
- `completed`
- `failed`
- `superseded`
- `quarantined`

### AgentHandoffEvent

Append-only 审计事件：

```json
{
  "event_id": "ahe_...",
  "handoff_id": "ah_...",
  "event_type": "claimed",
  "owner_id": "cli-claw-daily-1",
  "created_at": "2026-05-16T00:01:00+00:00",
  "payload": {
    "lease_ttl_seconds": 900
  }
}
```

### AgentHandoffOutput

```json
{
  "handoff_id": "ah_...",
  "agent_role": "kol_researcher",
  "agent_id": "kol-agent-v1",
  "model": "agent-runtime-model",
  "input_hash": "sha256:...",
  "status": "completed",
  "evidence_refs": [
    {
      "type": "task_chain_run",
      "id": "run_..."
    }
  ],
  "summary": "结构化摘要",
  "findings": [],
  "confidence": "medium",
  "limitations": [],
  "proposed_next_actions": [],
  "forbidden_actions_attempted": false,
  "created_at": "2026-05-16T00:03:00+00:00"
}
```

## Role Policy

允许的 role：

- `kol_researcher`：只做 KOL 情报抽取、归因、风险和时效性判断。
- `news_researcher`：只做新闻主题、影响链和不确定性判断。
- `sector_reviewer`：只做板块方向、可跟踪标的和 invalidation 条件。
- `daily_report_writer`：只做报告综合，不做最终策略评估。
- `strategy_researcher`：只提出候选策略或参数调整方向。
- `strategy_backtester`：只做验证、回测和失败归因。
- `strategy_judge`：只做独立 gate verdict，不能提出策略。

强制约束：

- `strategy_researcher.agent_id != strategy_judge.agent_id`
- `strategy_backtester.agent_id != strategy_judge.agent_id`
- `daily_report_writer` 不能输出 judge verdict。
- `kol_researcher` / `news_researcher` / `sector_reviewer` 不能输出 approval 或 activation。

## CLI Contract

第一阶段新增 CLI 只做 handoff queue，不自动运行 agent。P1a 先复用现有 `scripts/task_chain.py handoff ...` 子命令；P1b 已补最小 role、hash、event、lease、replay 和 schema validation contract。

### P1a implemented contract

```bash
uv run python scripts/task_chain.py --task-db .cache/task_chain.sqlite handoff list pending
uv run python scripts/task_chain.py --task-db .cache/task_chain.sqlite handoff claim <handoff_id> --claimed-by cli-claw-bridge
uv run python scripts/task_chain.py --task-db .cache/task_chain.sqlite handoff complete <handoff_id> --result-json '{"final_markdown":"..."}'
uv run python scripts/task_chain.py --task-db .cache/task_chain.sqlite handoff fail <handoff_id> --error "agent unavailable"
```

P1a output shape:

```json
{
  "status": "ok",
  "source": "task_chain_handoff",
  "handoff": {
    "id": "uuid",
    "source_task_id": "task_...",
    "source_run_id": "run_...",
    "task_type": "kol_scan",
    "status": "pending",
    "prompt_json": {},
    "prompt_text": "...",
    "result_json": {},
    "error": null,
    "claimed_by": null,
    "claimed_at": null
  }
}
```

P1a list / claim compatibility commands remain available. P1a-style `complete/fail` without owner is restricted to legacy migrated rows; newly enqueued P1b handoffs must use `claim-next` and owner-scoped `complete/fail` so owner、lease、hash、role、schema 和 policy validation cannot be bypassed.

### P1b implemented contract

### enqueue

```bash
uv run python scripts/task_chain.py handoff enqueue \
  --source-task-id task_... \
  --source-run-id run_... \
  --source-task-type kol_scan \
  --role kol_researcher \
  --input-json input.json \
  --pretty
```

输出：

```json
{
  "status": "ok",
  "source": "agent_handoff_enqueue",
  "handoff": {},
  "idempotent": false
}
```

### claim

```bash
uv run python scripts/task_chain.py handoff claim-next \
  --role kol_researcher \
  --owner-id cli-claw-kol-1 \
  --lease-ttl-seconds 900 \
  --pretty
```

输出：

```json
{
  "status": "ok",
  "source": "agent_handoff_claim",
  "handoff": {}
}
```

没有任务时：

```json
{
  "status": "skipped",
  "reason": "no_pending_handoff"
}
```

### complete

```bash
uv run python scripts/task_chain.py handoff complete \
  ah_... \
  --owner-id cli-claw-kol-1 \
  --output-file output.json \
  --pretty
```

complete 必须校验：

- handoff 仍被同一 owner lease。
- lease 未过期。
- `output.input_hash == handoff.input_hash`。
- `output.agent_role == handoff.role`。
- `forbidden_actions_attempted == false`。
- output schema 合格。

### fail

```bash
uv run python scripts/task_chain.py handoff fail \
  ah_... \
  --owner-id cli-claw-kol-1 \
  --error-type schema_validation_failed \
  --error-message "missing evidence_refs" \
  --retryable true \
  --pretty
```

### replay

```bash
uv run python scripts/task_chain.py handoff replay --handoff-id ah_... --pretty
```

P1b 当前刻意保留的限制：

- `claim-next` 内部状态仍沿用 P1a 的 `claimed`，但必须携带 owner 和 `lease_expires_at`。
- 对新 handoff，`complete/fail` 必须带 `--owner-id`；无 owner 只允许处理旧 P1a schema 迁移出来的 legacy handoff。
- handoff item JSON 同时包含 `id` 和 `handoff_id`，用于兼容现有内部调用和 P1b 外部 agent contract。
- P1b 只落 handoff output 和 audit event，不把 output 自动升级为 KOL 正文、策略 proposal、registry approval 或 active strategy。

replay 只返回原始 input、hash、role policy 和 source refs，不调用 agent、不改状态。

## Task-Chain 接入点

### KOL

当前事实：

- `kol_scan` 调用 `stock-kol-intel`。
- 如果 reply type 是 `assistant_prompt`，输出 `status=agent_required`。
- 当前不会执行 agent。

P1 行为：

- `kol_scan status=agent_required` 时 enqueue `role=kol_researcher` handoff item。
- item input 包含 prompt、ack、days、market、source run id、prompt hash。
- task-chain result 继续保留 `agent_required`，不能改成 `collected`。

P3 行为：

- agent output validated 后，新增 semantic evidence。
- 后续 `strategy_iteration` 只能消费 semantic evidence，不消费 prompt preview。

### News

- `news_scan status=collected` 可 enqueue `role=news_researcher`。
- provider unavailable 或 degraded 时可 enqueue degraded review，但 output 必须保留 limitation。
- 新闻 review 不能直接产生交易动作。

### Sector

- `sector_review` 可从 KOL / news semantic evidence 和 market context 生成 handoff。
- output 只描述板块方向、相关标的、触发条件和失效条件。

### Daily Report

- `daily_report_writer` 汇总 task-chain、semantic evidence、alpha research loop、watch worker 和 ledger summary。
- output 只能生成报告和人工待办，不生成 approval / activation。

## Strategy Gate

Agent 可以输出 `StrategyProposal`，但必须满足：

- `approval_required=true`
- `effective_status=candidate_only`
- `proposal_not_applied=true`
- evidence refs 完整。
- independent `strategy_judge` verdict passed 后才可进入 human review。

Registry gate：

- `strategy_registry.py propose` 只写 candidate。
- `strategy_registry.py record-verdict` 只 append verdict。
- `strategy_registry.py approve` 必须由 human reviewer 显式执行。
- `strategy_registry.py activate` 必须已有 approval record。

禁止：

- agent 调 `approve`。
- agent 调 `activate`。
- judge passed 自动变 active。

## Validation Rules

通用校验：

- stdout 严格 JSON。
- 不允许 `NaN` / `Infinity`。
- 必须有 `input_hash`。
- 必须有 `agent_role` 和 `agent_id`。
- 必须有 `evidence_refs`。
- 必须有 `limitations`。
- 必须声明 `forbidden_actions_attempted=false`。

策略相关校验：

- researcher / backtester / judge role id 不能相同。
- proposal 缺 backtest / evaluation evidence 时不能进入 judge passed。
- verdict 缺 evaluator id 时 blocked。
- data gaps 未解释时 blocked。

## 第一阶段验收

第一阶段分 P1a / P1b。

P1a 已实现：

- `task_chain_agent_handoffs` 表。
- `scripts/task_chain.py handoff list|claim|complete|fail`。
- KOL `agent_required` 创建 pending handoff。
- handoff 保存完整 prompt，不只存 preview。
- completed handoff 不会被二次 claim。
- CLI stdout 严格 JSON。

P1b 已实现：

- `scripts/task_chain.py handoff enqueue` 幂等。
- `scripts/task_chain.py handoff claim-next` 支持 lease、防重入、owner id。
- `scripts/task_chain.py handoff complete` 校验 owner、lease、input hash、role、schema 和 forbidden actions。
- `scripts/task_chain.py handoff fail` 支持 owner、error type、message、retryable，并写 append-only event。
- `scripts/task_chain.py handoff replay` 可重放输入、events 和 outputs。
- `task_chain_agent_handoff_events` 保存 enqueued / claimed / reclaimed / completed / failed 事件。
- `task_chain_agent_handoff_outputs` 保存完成后的结构化 agent output。
- `complete` 会拒绝 wrong owner、expired lease、wrong hash、wrong role、schema 缺字段、forbidden actions 和非 allowed actions。
- KOL `agent_required` 可以被表示为 handoff item，但不会自动变成 collected content。

P1b 后续可增强：

- `superseded` / `quarantined` 状态和事件。
- 更严格的 role separation 校验。
- completed output 转 validated semantic evidence 的 P3 消费入口。

不验收：

- 不要求真实 agent 已接入。
- 不要求 scheduled agent 自动运行。
- 不要求 strategy proposal 自动进入 registry。
- 不允许任何真实交易、自动 approve 或自动 activate。

## 风险

- prompt 被误当最终报告：必须保持 `agent_required` 和 `validated_evidence` 两种状态分离。
- agent 重复消费：必须用 idempotency key、lease 和 source run id。
- 输出不可追溯：必须记录 input hash、source refs 和 append-only events。
- 自研自评：必须用 role policy 阻断 researcher / judge 同 agent。
- 权限扩散：必须把 forbidden actions 写入 handoff item 并在 complete 时校验。
