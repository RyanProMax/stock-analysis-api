# Agentic Strategy Loop Roadmap

更新时间：2026-05-16

## 目标

把当前以确定性脚本为主的股票策略分析、自迭代和自验证链路，升级为可审计的 agent 介入闭环：

1. `task-chain` 继续负责 due task、lease、append-only run log、结构化报告和 next task 决策。
2. Agent 只通过明确 handoff queue / CLI contract 接收任务和回写结果，不直接改运行时策略。
3. KOL、新闻、板块、日报等语义分析由 agent 层完成，但必须可追溯输入、输出、模型角色和证据。
4. 策略 proposal 进入人工审核和 registry gate；禁止自动 approve、自动 activate 或真实交易。
5. Researcher、backtester、evaluator / judge 角色必须分离，禁止同一个 agent 既当 researcher 又当最终 judge。

## 当前事实核查

已有事实：

- `docs/plan.md` 已明确：`scripts/task_chain.py` 当前只是 Alpha / 模拟盘自迭代元调度入口，负责 due task、lease、run log、summary 和 next task；真实 subagents review 后续由 Cli Claw / Agent 层接入。
- `src/services/task_chain_service.py` 中 `kol_scan` 调用 `stock-kol-intel` 后，如果返回 `assistant_prompt`，只输出 `status=agent_required`、`prompt_preview` 和 `reason=stock_kol_intel_returns_assistant_prompt`。
- `agent_required` 当前不是 agent 执行结果，不会触发策略迭代；只有 `kol_scan status=collected` 且有正文时才允许后续策略输入。
- `strategy_analysis` / `strategy_iteration` 已能调用 `AlphaResearchLoopService`，但仍是只读 / paper-only，不写 registry、不 approve、不 activate、不触发 broker。
- `strategy_registry.py`、`strategy_judge.py` 和 `alpha_research_loop.py` 已建立候选策略、judge verdict 和人工审批的最小治理链。

当前缺口：

- 没有持久化 agent handoff queue；`agent_required` 结果无法被外部 Cli Claw / scheduled agent 稳定拉取、认领、回写和重放。
- 没有统一 agent CLI contract；不同 agent 的输入、输出、错误、幂等键、证据引用和角色约束还没有固定。
- KOL / news / sector / daily report 的语义 review 尚未真正进入 task-chain 的可审计闭环。
- Agent review 的回写结果还不能被 task-chain 用作 `kol_scan status=collected`、`sector_review` 或 `daily_report` 的可信 evidence。
- watchlist、threshold、factor list、KOL topic 等仍有硬编码和 payload 散落，缺少 registry 化配置和变更审批。
- 缺少 observability、replay、eval dataset 和 agent 输出质量回归。

## 硬约束

- 禁止真实交易。
- 禁止 `unlock_trade`。
- 禁止自动 approve 策略。
- 禁止自动 activate 策略。
- 禁止 agent 直接写 active strategy、broker、OpenD 写入接口或交易 ledger。
- 禁止把同一个 agent 同时作为 researcher 和 evaluator / judge。
- 禁止把 `assistant_prompt` 当作已完成研究正文。
- 禁止在没有 evidence、run id、input hash 和 role id 的情况下接受 agent 回写。
- 第一阶段只做可审计 handoff queue 和 CLI contract，不自动下单、不自动激活。

## 总体架构

```text
Deterministic Task Chain
  ├─ due task / lease / run log
  ├─ news_scan / kol_scan / sector_review / strategy_analysis / daily_report
  └─ emits agent_required handoff item

Agent Handoff Queue
  ├─ pending / leased / completed / failed / superseded
  ├─ input payload + input_hash + source task/run id
  ├─ role policy + allowed tools + forbidden actions
  └─ append-only output / error / audit event

Cli Claw / Scheduled Agent Bridge
  ├─ poll handoff queue
  ├─ run role-specific agent prompt
  ├─ validate JSON output contract
  └─ write back semantic evidence

Semantic Review Layer
  ├─ KOL review
  ├─ news review
  ├─ sector review
  └─ daily report synthesis

Strategy Governance
  ├─ StrategyProposal candidate_only
  ├─ independent judge verdict
  ├─ human review
  ├─ registry approve
  └─ registry activate
```

## 阶段路线

### P0：当前事实核查与状态冻结

状态：当前阶段

输入：

- `docs/plan.md`
- `PLAN/ROADMAP.md`
- `docs/specs/task-chain-worker.md`
- `src/services/task_chain_service.py`
- 已有 `strategy_registry.py`、`strategy_judge.py`、`alpha_research_loop.py` contract

输出：

- 本 roadmap 更新为 agentic strategy loop 主线。
- 新增 `docs/specs/agentic-strategy-loop.md`，作为 handoff queue、agent review、结果回写和安全边界的实现 spec。
- `docs/plan.md` 保持当前状态入口，明确下一步不是“让 task-chain 自动执行 agent”，而是先补可审计 handoff queue 和 CLI contract。

验收：

- 文档明确 `task-chain` 当前不执行 agent。
- 文档明确 `kol_scan status=agent_required` 不是最终情报。
- 文档明确第一阶段只做 handoff queue / CLI contract。
- 文档明确禁止真实交易、自动 approve、自动 activate、同 agent 自研自评。

不可做：

- 不改运行时代码。
- 不新增 broker 写入能力。
- 不把 agent 输出直接写 active strategy。

### P1：Agent Handoff Queue

目标：

把 `agent_required`、语义 review 请求和 strategy proposal review 请求落成可审计队列，让外部 agent 可以稳定消费。

输入：

- `task_chain_runs.output` 中的 `agent_required`、degraded semantic input 或需要 human-review-ready 的 proposal。
- source task id、run id、task type、market、symbols、as_of、prompt preview、原始 prompt hash。
- role policy：`kol_researcher`、`news_researcher`、`sector_reviewer`、`daily_report_writer`、`strategy_researcher`、`strategy_judge`。

P1a 当前交付：

- `task_chain_agent_handoffs` 表保存 pending / claimed / completed / failed handoff。
- `kol_scan status=agent_required` 会创建 pending handoff，并在 task result 中返回 `handoff_id`、`prompt_chars` 和 `prompt_preview`。
- `scripts/task_chain.py handoff list [status]` 可列出 handoff。
- `scripts/task_chain.py handoff claim <handoff_id> --claimed-by <owner>` 可原子认领 pending handoff。
- `scripts/task_chain.py handoff complete <handoff_id> --result-json ...|--result-file ...` 可回写 agent 结果。
- `scripts/task_chain.py handoff fail <handoff_id> --error ...` 可标记失败。
- stdout 严格 JSON。

P1b 目标输出：

- 新 queue 表或独立 SQLite store：
  - `agent_handoff_items`
  - `agent_handoff_events`
  - `agent_handoff_outputs`
- CLI：
  - `scripts/task_chain.py handoff enqueue`
  - `scripts/task_chain.py handoff claim`
  - `scripts/task_chain.py handoff complete`
  - `scripts/task_chain.py handoff fail`
  - `scripts/task_chain.py handoff list`
  - `scripts/task_chain.py handoff replay`
- 每条 handoff item 固定包含 `handoff_id`、`source_task_id`、`source_run_id`、`role`、`status`、`input_hash`、`idempotency_key`、`allowed_actions`、`forbidden_actions`。

验收：

- 同一个 source run 重复 enqueue 必须幂等。
- claim 必须有 lease 和 owner id。
- complete 必须校验 `input_hash`、`role`、JSON schema 和 forbidden action。
- failed / completed / superseded 都要 append-only event。
- `agent_required` KOL item 能被队列表示，但不会被当作 collected content。

不可做：

- 不调用真实 agent。
- 不自动把 handoff output 写成 strategy proposal。
- 不触发下单、审批或激活。

### P2：Cli Claw Scheduled-Agent Bridge

目标：

让 Cli Claw / scheduled agent 通过稳定 CLI 消费 handoff queue，并把结构化结果回写。

输入：

- `agent_handoff.py claim --role ... --owner-id ...`
- handoff item JSON。
- role-specific prompt template。
- allowed tools 和 forbidden actions。

输出：

- `agent_bridge.py run-once` 或等价 scheduled-agent contract。
- agent result JSON：
  - `handoff_id`
  - `agent_role`
  - `agent_id`
  - `model`
  - `input_hash`
  - `evidence_refs`
  - `summary`
  - `findings`
  - `confidence`
  - `limitations`
  - `proposed_next_actions`
  - `forbidden_actions_attempted=false`
- 回写到 handoff output，不直接写 registry 或 active strategy。

验收：

- bridge 可以 `claim -> run -> validate -> complete` 单条任务。
- agent 失败时写 `fail`，保留 stderr / error type / retryable。
- output schema 不合格时不能 complete，只能 fail 或 quarantine。
- scheduled agent 多实例并发不会重复处理同一 handoff item。

不可做：

- 不绕过 queue 直接读写 task-chain DB。
- 不允许 agent 调 `strategy_registry approve/activate`。
- 不允许 bridge 调 broker、OpenD 写入或真实交易接口。

### P3：Agent Semantic Review for KOL / News / Sector / Daily Report

目标：

把 KOL、新闻、板块和日报从“确定性结构化壳”升级为 agent 语义 review，但仍由 task-chain 负责编排和审计。

输入：

- KOL assistant prompt 或 KOL 原文。
- news scan result。
- sector market context。
- alpha research loop summary。
- trading / watch / task-chain run summary。

输出：

- `kol_review`：结构化 KOL 观点、标的、方向、证据、风险、时效性。
- `news_review`：新闻主题、影响链、相关标的、确定性 / 不确定性。
- `sector_review`：板块强弱、可跟踪 ETF / 股票、触发条件和无效条件。
- `daily_report_review`：盘后摘要、已验证事实、待人工动作、不可行动信息。
- task-chain 可引用的 semantic evidence id。

验收：

- KOL / news / sector / daily report output 都必须有 source refs 和 limitations。
- `agent_required` 只有在 agent output validated 后才能变成可消费 evidence。
- `strategy_iteration` 只能消费 validated semantic evidence，不能消费 prompt preview。
- summary-only 默认输出，不泄露过长原文。

不可做：

- 不把 KOL / news 观点直接转为交易信号。
- 不让 report writer 充当 judge。
- 不让语义 review 自动创建 approved / active strategy。

### P4：Strategy Proposal Human Review / Registry Gate

目标：

把 agent 生成的策略建议约束在 candidate proposal 与人工审批链内。

输入：

- validated semantic evidence。
- alpha scan / evaluation / backtest evidence。
- independent judge verdict。
- active champion verdict。
- proposed strategy diff。

输出：

- `StrategyProposal`，固定 `approval_required=true`、`effective_status=candidate_only`、`proposal_not_applied=true`。
- `StrategyJudgeVerdict`，固定 `human_review_ready` 或 `blocked`。
- registry append-only records：proposal、verdict、human approval、activation event。

验收：

- researcher / backtester / evaluator role id 必须互不相同。
- evaluator 未 passed 时不能进入人工审核。
- `approve` 必须由 human reviewer 显式执行。
- `activate` 必须已有 approval record，且仍只能激活一个 active strategy。
- agent 只能写 candidate evidence，不能写 approval / activation。

不可做：

- 不自动 approve。
- 不自动 activate。
- 不把 judge passed 当成 activation。
- 不允许自研 agent 自己给最终 passed verdict。

### P5：De-hardcode Watchlist / Thresholds

目标：

把 watchlist、threshold、factor list、KOL topic、market windows、risk limits 等配置从硬编码和临时 payload 迁移到可审计 registry。

输入：

- 当前脚本默认值。
- task-chain payload。
- active strategy parameters。
- alpha universe seed。
- manual config proposal。

输出：

- versioned config registry：
  - watchlist set
  - market universe seed
  - factor set
  - threshold profile
  - KOL / news topic profile
  - risk limit profile
- config proposal / approval / activation event。
- scripts 只读 active config，不直接写配置。

验收：

- 默认运行路径能说明每个 watchlist / threshold 的来源。
- 配置变更必须 append-only。
- agent 可建议 config proposal，但不能自动 activate。
- active config 支持回滚。

不可做：

- 不把 prompt 中的临时标的直接写入 active watchlist。
- 不让 agent 自动降低风险阈值。
- 不隐藏手工 override 来源。

### P6：Observability / Replay / Eval

目标：

让 agentic loop 可以复盘、重放、评价和回归测试。

输入：

- task-chain runs。
- handoff item / event / output。
- agent result。
- strategy proposal / verdict / registry events。
- simulated ledger / backtest evidence。

输出：

- run timeline：从 task-chain 到 handoff、agent review、proposal、judge、human action 的完整链路。
- replay CLI：按 `handoff_id` 或 `source_run_id` 重放输入，不调用 broker。
- eval dataset：KOL / news / sector / daily report 的 golden samples、schema validation、judge consistency checks。
- metrics：queue latency、agent failure rate、schema failure rate、blocked reason distribution、proposal-to-approval conversion、post-activation drift。

验收：

- 任一 strategy proposal 可追溯到原始输入 hash 和所有 semantic evidence。
- 任一 agent output 可重放 schema validation。
- eval 不依赖真实交易。
- observability 默认脱敏长原文，只保留 hash / summary / refs。

不可做：

- 不用 eval 结果自动 approve / activate。
- 不把模拟盘短期结果包装成真实收益承诺。
- 不绕过人工审核做生产策略更新。

## 第一阶段实现范围

第一阶段分两步交付 P1。P1a 已先落可运行的 handoff queue MVP 和 CLI contract；P1b 再补完整审计字段、append-only event、schema validation 和 replay。

P1a 已包括：

- queue schema。
- claim owner。
- complete / fail。
- `agent_required` KOL item 的 handoff 创建。
- CLI stdout 严格 JSON。

P1b 必须补齐：

- append-only handoff event。
- idempotency key。
- role policy。
- input hash。
- lease TTL / claim expiry。
- output schema validation。
- forbidden actions validation。
- `agent_required` KOL item 的 enqueue 和 replay contract。
- replay CLI。

明确不包括：

- 不自动调用 agent。
- 不自动下单。
- 不自动 approve。
- 不自动 activate。
- 不改 public HTTP API。
- 不把 KOL prompt preview 当最终报告。

## 推荐实施顺序

1. 完成 P0 文档状态冻结。
2. 实现 `agent_handoff` repository / service / CLI P1a。
3. 从 `kol_scan status=agent_required` 生成 handoff item。
4. 增加 P1a queue contract tests：create、list、claim、complete、fail。
5. 补 P1b queue contract：幂等、lease TTL、input hash、role policy、events、schema validation、replay。
6. 增加 bridge contract spec，但先不自动运行 agent。
7. 让 validated KOL review 回写为 semantic evidence。
8. 扩展 news / sector / daily report review。
9. 接入 strategy proposal human review / registry gate。
10. 做 de-hardcode config registry。
11. 做 observability / replay / eval。

## 风险

- Agent 输出可能不稳定，必须用 schema、evidence refs、role policy 和 replay 限制影响面。
- 如果没有 handoff queue，scheduled agent 容易重复消费、丢失任务或把 prompt 误当结果。
- 如果 researcher 和 judge 不分离，策略自迭代会形成宽松反馈回路。
- 如果配置仍硬编码，agent proposal 很难解释“建议改了什么”和“当前生效的是哪一版”。
- 如果没有 replay / eval，后续很难判断 agent review 质量是否退化。
