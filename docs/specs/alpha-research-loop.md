# Alpha Research Loop

更新时间：2026-05-09

## 目标

建设自动盯盘、Alpha 挖掘、因子评估、策略 proposal 和人工批准的闭环。系统可以自动发现候选信号和生成迭代建议，但不能在未经人工批准时改变运行中策略，更不能触发真实交易。

## 边界

- 公共接口仍只通过 HTTP REST 暴露；新增 research 能力先走内部 CLI。
- Agent 不进入日内下单路径，只能在盘后或离线阶段生成结构化建议。
- 默认只读或 dry-run；Futu broker 仅允许显式 opt-in 的 `SIMULATE`。
- 禁止真实交易、交易解锁、订阅推送、OpenD 写入配置和任何绕过 broker adapter 的交易调用。
- 所有 JSON contract 必须可被 `json.dumps(..., allow_nan=False)` 序列化。

## 数据契约

### AlphaCandidate

用于表达一次扫描产出的候选信号。

- `candidate_id`：候选唯一 ID。
- `universe_id`：股票池 ID。
- `as_of`：信号日期或时间。
- `market` / `symbol`：市场与标的。
- `factor_values`：原始因子值。
- `score` / `rank`：综合分与排名，数据不足时允许为空。
- `reasons`：入选原因。
- `data_quality` / `data_gaps`：数据质量和缺口。

### AlphaEvaluation

用于表达候选或因子的评估结果。

- `evaluation_id` / `candidate_id` / `method`：评估标识。
- `forward_windows`：前瞻窗口，例如 1D / 5D / 20D。
- `metrics`：IC、RankIC、分组收益、换手、命中率、回撤等指标。
- `sample_split`：必须包含 `train`、`validation`、`out_of_sample`。
- `cost_model`：交易成本假设。
- `status` / `data_gaps`：评估状态和数据缺口。

### StrategyProposal

用于表达 Agent 或 research service 生成的策略调整建议。

- 默认 `approval_required=true`。
- 默认 `effective_status=candidate_only`。
- 默认约束包含：
  - `proposal_not_applied_to_runtime`
  - `requires_human_approval`
  - `agent_not_in_intraday_order_path`

### StrategyVersion

用于表达策略版本治理状态。

- 合法状态：`draft`、`candidate`、`approved`、`active`、`retired`、`rejected`。
- `approved` 或 `active` 必须有 `approved_by`。
- 不允许出现 `auto_applied` 这类绕过审批的状态。

## 模块分工

- `src/model/alpha.py`：Alpha 候选与评估 contract。
- `src/model/strategy.py`：策略 proposal 与版本治理 contract。
- `src/model/serialization.py`：跨 contract 复用的 JSON 安全序列化。
- `src/services/alpha_universe_service.py`：只读构建 Alpha 扫描股票池，支持 `all` / `stock` / `etf` / 显式 `symbols`，`watchlist` 在未提供 symbols 时返回空集合。
- `src/services/alpha_feature_service.py`：从本地 SQLite 日线仓提取首批因子，不访问 broker，不拉外部实时行情。
- `src/services/alpha_scan_service.py`：将 universe 与 feature 转换为 `AlphaCandidate`，数据不足时只标记 `partial`，不伪造分数。
- `src/services/alpha_scan_cli.py`：内部 CLI 参数解析与纯 JSON 输出。
- `src/services/*`：后续继续承载 evaluate、registry 等业务逻辑。
- `scripts/*`：只做 CLI 参数解析和 service 调用，不沉淀正式业务逻辑。

## P1 Alpha Scan CLI

内部入口：

```bash
uv run python scripts/alpha_scan.py --market cn --universe all --top 20 --pretty
uv run python scripts/alpha_scan.py --market cn --symbols 300827,300274 --top 10
```

输出 contract：

- 顶层固定为 `status`、`source=alpha_scan`、`computed_at`、`request`、`summary`、`items`。
- `status=empty`：股票池为空，`items=[]`。
- `status=partial`：至少一个候选缺少足够日线；该候选 `score=null`、`data_quality=partial`、`data_gaps` 说明缺口。
- `items` 中每项必须符合 `AlphaCandidate.to_dict()` contract。
- 该 CLI 只读本地行情仓，不写 trading ledger，不触发 broker，不调用 Futu `SIMULATE`。

## 验收

- `uv run pytest tests/test_alpha_contracts.py -q`
- `uv run pytest tests/test_alpha_scan_cli.py -q`
- contract 输出不包含 `NaN` / `Infinity`。
- proposal 默认需要人工批准。
- P1 开始前不得新增交易写入能力。
