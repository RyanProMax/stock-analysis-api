# AGENTS.md

Stock Analysis API 后端项目，当前公共接口仅保留 HTTP REST API。
仓库可以包含供内部 Agent / skill 调用的 `scripts/` 脚本，但这类脚本不属于公共 API。

## 文档治理

- `docs/plan.md` 是当前任务、进展、状态、下一步和风险的唯一复用文档
- `docs/architecture.md` 是架构约束、数据分层约束、模块边界和接口设计原则的唯一权威文档
- `docs/api.md` 是当前 HTTP 接口设计说明的唯一文档，统一维护接口用途、调用方式、入参、出参和字段含义
- `docs/specs/` 是具体需求、审计结论、字段规范、接口整改项和模块级交付要求的唯一目录
- `README.md` 只保留项目使用说明、运行方式、命令入口和必要的使用级注意事项，不承载架构说明、演进计划、风险清单或当前状态快照
- 新需求先落 `docs/specs/`，实施过程中同步更新 `docs/plan.md`
- 架构层面的新增、删除或偏移，必须先更新 `docs/architecture.md`
- 涉及仓表、同步流程、状态模型和字段口径的重构，必须先更新 `AGENTS.md` / `docs/`，再实施代码变更
- 不再新增重复职责的阶段性文档；如需迁移旧文档内容，迁移完成后删除原文档并校正 `docs/plan.md`
- `docs/specs/` 只保留未完成、仍需执行的规格；已完成的迁移说明、审计快照或阶段性治理文档应删除，不作长期归档
- 内部 skill / agent 调用脚本的 contract、状态语义和输入输出说明统一沉淀在 `docs/specs/`，不写入 `docs/api.md`

## 技术栈

- Python 3.12+
- FastAPI + Uvicorn
- uv 依赖管理

## 开发命令

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv run start
black --line-length 100 .
```

## 项目结构

```text
scripts/            # 内部脚本入口（skill / agent 调用），不属于公共 API
src/
├── analyzer/         # 因子计算与标准化适配
├── api/              # FastAPI 路由、schema 与 deps
├── core/             # 兼容层与流程编排
├── data_provider/    # 外部数据源适配
├── model/            # 领域模型与统一 contract
├── repositories/     # SQLite repository
├── services/         # 业务编排服务
├── storage/          # 兼容导入层，不再作为正式业务层
└── utils/            # 工具
```

## HTTP API

- 完整接口设计说明见 `docs/api.md`

| 端点 | 方法 | 描述 |
|------|------|------|
| `/stock/analyze` | POST | 批量分析股票 |
| `/stock/list` | GET | 获取股票列表 |
| `/stock/search` | POST | 搜索股票 |
| `/watch/poll` | POST | 多股票盯盘轮询 |
| `/analysis/research/snapshot` | POST | 统一的客观研究快照入口 |

## 数据标准

- 复杂接口统一返回 `entity`、`facts`、`analysis`、`meta`
- 内部 research snapshot 脚本统一返回 `status`、`computed_at`、`source`、`market`、`strategy`、`request`、`items`
- `facts` 仅允许 `reported` / `consensus`
- `analysis` 仅允许 `derived` / `estimate` / `model_output`
- 比例型机器值统一存 `ratio`
- 缺少可靠原始数据时宁可降级，也不要伪造历史或共识
- SQLite 只保存数据源返回的必要持久信息，不保存分析报告缓存
- 5-10 分钟短线 watch baseline 只保留进程内内存态，不落数据库
- 公共 HTTP 接口不暴露 `refresh` 参数，统一先查 SQLite，缺失再拉外部源并回写
- 本地行情仓主表按市场拆分为 `cn_symbols`、`cn_daily`、`us_symbols`、`us_daily`
- 统一同步入口为 `uv run sync-market-data`
- A 股优先以 `Tushare` 为主数据源，`TUSHARE_TOKEN` / `TUSHARE_HTTP_URL` 只能从环境变量读取
- `cn_symbols` 只保留当前上市 A 股股票 + ETF 最新快照，不保留历史状态
- `cn_symbols.market` 直接承担类型区分：股票保留原板块口径，ETF 统一为 `ETF`
- `cn_symbols.daily_start_date` / `daily_end_date` 只表示本地 `cn_daily` 已落库的最早 / 最晚交易日，是本地覆盖摘要，不是上市区间、交易所日历或 source truth
- `cn_daily` 的全市场补库口径为当前上市 A 股、自 `2026-01-01` 起的日线数据
- 每日首次任意 HTTP 请求都会后台检查一次 `cn_symbols / us_symbols` 是否需要刷新；`cn/us` 按各自市场是否开市独立判断，且不阻塞当前请求
- `sync_runs` 采用 append-only 历史模型，但每条记录都必须表达“本次运行结束后的全局数据状态”
- `cn_daily` 应逐步吸收 Tushare `daily_basic` 的标准事实字段，不把核心市场事实长期塞进 `extra`
- `cn_daily.is_suspended` 是停复牌事件标记，不是持续停牌状态，也不能推导“直到下一条 row 前都停牌”
- Tushare `suspend_d` 当前只在同步阶段作为辅助事实源使用，不单独落表，不生成停牌虚拟日线 row
- `sync-market-data` 需要先用 `cn_symbols` 覆盖摘要做粗筛，再做精确校验；停牌导致的无新日线不能直接算普通 stale

## 文档协作要求

- 每次迭代都必须更新 `docs/plan.md`，不要新建重复的阶段性计划文档
- 每次任务完成后提交一次 commit
- `docs/plan.md` 至少包含：
  - 当前目标
  - 最近完成项
  - 当前状态
  - 下一步计划
  - 已知风险或阻塞
- 具体需求、审计、整改清单统一沉淀在 `docs/specs/`
- 新增或删除 `docs/` 文档时，需要同时检查 `docs/plan.md`、`docs/architecture.md` 和 `docs/specs/` 是否仍反映当前真实状态

## 代码规范

- 公共能力新增优先通过 HTTP 路由、schema、文档和测试交付
- 内部 skill / agent 脚本能力统一放在 `scripts/`，其业务逻辑仍应放在 `src/services/`、`src/data_provider/` 或 `src/analyzer/`
- 业务逻辑优先放在 `src/services/`、`src/repositories/` 或 `src/analyzer/`
- 标准化 contract 放在 `src/model/contracts.py` 和 `src/analyzer/normalizers.py`
- `src/storage/` 只保留兼容导入，不再新增正式实现
