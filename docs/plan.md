# 当前任务计划

更新时间：2026-03-29

## 当前目标

- 维持 `POST /stock/analyze` 作为唯一公共分析入口，并确保 HTTP / CLI / 文档 / 测试持续一致

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

## 下一步计划

- 若后续继续增强 `summary`、`screen`、`catalysts` 或 `model_update`，优先沿用当前 `summary + meta.modules` 模式，不回退到模块内重复状态壳
- 若新增 Agent 脚本能力，继续保证 stdout 纯 JSON，避免日志污染
- 继续保持 `docs/strategy.md` 与真实 `300827 + mode=full` 输出同步

## 已知风险与阻塞

- `research_report`、`anns_d`、`news`、`major_news` 依旧可能受 Tushare 权限限制，因此 `meta.modules` 状态与说明必须保持真实可追溯
- `technical` 模块当前仍复用旧 analyze 的底层分析器；若后续该分析器打印新日志或改 stdout 行为，需要继续保证 CLI 纯 JSON 不被污染
- `cn` 默认 `base` 依赖 `technical / research_report / report_rc / earnings / catalysts / screen` 协同表达，但 A 股财务能力仍弱于美股，需要通过真实降级而不是补写结论来表达
