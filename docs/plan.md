# 当前任务计划

更新时间：2026-03-29

## 当前目标

- 将 `POST /stock/analyze` 升级为对齐 FSP 研报分析框架的 objective 输出，并提升技术面与摘要层的可信度和可追溯性

## 最近完成项

- 已将公共分析入口彻底收敛到 `POST /stock/analyze`
- 已删除公共：
  - `POST /analysis/research/snapshot`
  - `GET /stock/list`
  - `POST /stock/search`
- 已将 `/stock/analyze` 的 `data` 切换为统一 stock-analyze snapshot payload：
  - `status / computed_at / source / market / strategy / request / items`
- 已加入固定 `technical` 模块，并纳入 `base/full` 两个 mode
- 已提供与 HTTP 能力对齐的 CLI：
  - `scripts/stock_analyze.py`
- 已确保 CLI stdout 为纯 JSON，便于外部 Agent 直接消费
- 已将分析相关测试收敛为 CLI 主入口，删除旧 analyze/snapshot 双轨测试
- 已同步更新：
  - `AGENTS.md`
  - `docs/architecture.md`
  - `docs/api.md`
  - `docs/strategy.md`
  - `README.md`
- 已完成全量回归：`81 passed`
- 已将本轮 FSP 对齐要求并入：
  - `docs/architecture.md`
  - `docs/api.md`
  - `docs/strategy.md`

## 当前状态

- 公共接口仍然只有 HTTP REST API；内部 `scripts/` 允许承载 Agent / skill 调用脚本
- 当前公共分析只保留：
  - `POST /stock/analyze`
  - `POST /watch/poll`
  - `GET /health`
- 当前 `/stock/analyze` 请求固定为：
  - `market / symbols / start_date / end_date / mode`
- 当前 `/stock/analyze` item 固定为：
  - `requested_symbol / status / error / info / summary / 模块业务数据 / meta`
- 当前 `mode` 集合：
  - `cn.base`: `technical / research_report / report_rc / earnings / catalysts / screen`
  - `cn.full`: `technical / research_report / report_rc / anns_d / news / major_news / earnings / catalysts / screen / model_update`
  - `us.base`: `technical / earnings / dcf / comps / three_statement / screen`
  - `us.full`: `technical / earnings / earnings_preview / dcf / comps / three_statement / lbo / three_statement_scenarios / competitive / catalysts / screen / model_update / sector_overview`
- 当前 CLI：
  - `uv run python scripts/stock_analyze.py --market cn --symbols 300827 --mode full --pretty`
  - 输出与 HTTP `StandardResponse` 尽量同构
- 当前待收口的问题：
  - `summary` 仍偏模块汇总，尚未完全体现 FSP 研报分析顺序
  - `technical` 仍包含零售化措辞和启发式动作标签
  - 缺少 `item.meta.provenance` 级别的字段出处
  - 比例/百分比语义仍有历史遗留不一致

## 下一步计划

- 增加 `summary.research_strategy`，按 FSP 研报逻辑组织预期、基本面、估值、催化剂与价格行为确认
- 为 `summary.research_strategy.*` 增加 `item.meta.provenance`
- 将 `technical` 收敛为专业研究确认层，去掉 emoji 和零售化动作口号
- 将公共策略名升级为 `fsp_objective_stock_analyze_v2`
- 更新 CLI 测试、`docs/api.md` 与 `docs/strategy.md`，对齐新的输出结构

## 已知风险与阻塞

- `research_report`、`anns_d`、`news`、`major_news` 依旧可能受 Tushare 权限限制，因此 `meta.modules` 状态与说明必须保持真实可追溯
- `technical` 模块当前仍复用旧 analyze 的底层分析器；本轮主要在公共包装层做语义收口，底层分析方法本身仍可能继续演进
- A 股 `earnings` 的 provider 覆盖仍弱于美股，因此 `research_strategy` 中的 `evidence_strength` 不能高估 CN 场景
- `report_rc` 可能回退到窗口外最近一份 stock-specific estimate；该 fallback 若未在 strategy provenance 中显式暴露，会继续损伤可信度
