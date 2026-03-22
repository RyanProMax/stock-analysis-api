# AGENTS.md

Stock Analysis API 后端项目，当前仅保留 HTTP REST API。

## 文档治理

- `docs/plan.md` 是当前任务、进展、状态、下一步和风险的唯一复用文档
- `docs/architecture.md` 是架构约束、数据分层约束、模块边界和接口设计原则的唯一权威文档
- `docs/specs/` 是具体需求、审计结论、字段规范、接口整改项和模块级交付要求的唯一目录
- 新需求先落 `docs/specs/`，实施过程中同步更新 `docs/plan.md`
- 架构层面的新增、删除或偏移，必须先更新 `docs/architecture.md`
- 不再新增重复职责的阶段性文档；如需迁移旧文档内容，迁移完成后删除原文档并校正 `docs/plan.md`
- `docs/specs/` 只保留未完成、仍需执行的规格；已完成的迁移说明、审计快照或阶段性治理文档应删除，不作长期归档

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
src/
├── analyzer/         # 因子计算与标准化适配
├── api/              # FastAPI 路由与 schema
├── core/             # 核心服务
├── data_provider/    # 数据源
├── model/            # 领域模型与统一 contract
├── storage/          # 本地 SQLite 持久层
└── utils/            # 工具
```

## HTTP API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/stock/analyze` | POST | 批量分析股票 |
| `/stock/list` | GET | 获取股票列表 |
| `/stock/search` | POST | 搜索股票 |
| `/watch/poll` | POST | 多股票盯盘轮询 |
| `/valuation/dcf` | GET | DCF 估值模型 |
| `/valuation/comps` | GET | 可比公司分析 |
| `/model/lbo` | GET | LBO 情景模型 |
| `/model/three-statement` | GET | 三表预测模型 |
| `/model/three-statement/scenarios` | GET | 三表情景对比 |
| `/analysis/competitive/competitive` | GET | 竞争格局分析 |
| `/analysis/earnings/earnings` | GET | 季报分析 |

## 数据标准

- 复杂接口统一返回 `entity`、`facts`、`analysis`、`meta`
- `facts` 仅允许 `reported` / `consensus`
- `analysis` 仅允许 `derived` / `estimate` / `model_output`
- 比例型机器值统一存 `ratio`
- 缺少可靠原始数据时宁可降级，也不要伪造历史或共识
- SQLite 只保存数据源返回的必要持久信息，不保存分析报告缓存
- 5-10 分钟短线 watch baseline 只保留进程内内存态，不落数据库
- 公共 HTTP 接口不暴露 `refresh` 参数，统一先查 SQLite，缺失再拉外部源并回写

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

- 新增能力时只更新 HTTP 路由、schema、文档和测试
- 业务逻辑放在 `src/core/` 或 `src/analyzer/`
- 标准化 contract 放在 `src/model/contracts.py` 和 `src/analyzer/normalizers.py`
