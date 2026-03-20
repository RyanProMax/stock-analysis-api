# AGENTS.md

Stock Analysis API 后端项目，当前仅保留 HTTP REST API。

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
├── storage/          # 缓存
└── utils/            # 工具
```

## HTTP API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/stock/analyze` | POST | 批量分析股票 |
| `/stock/list` | GET | 获取股票列表 |
| `/stock/search` | POST | 搜索股票 |
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

## 文档协作要求

- `docs/plan.md` 是当前任务进展与后续计划的唯一复用文档
- 每次迭代都必须更新 `docs/plan.md`，不要新建重复的阶段性计划文档
- `docs/plan.md` 至少包含：
  - 当前目标
  - 最近完成项
  - 当前状态
  - 下一步计划
  - 已知风险或阻塞
- 新增或删除其他 `docs/` 文档时，需要同步检查 `docs/plan.md` 是否仍反映当前真实状态

## 代码规范

- 新增能力时只更新 HTTP 路由、schema、文档和测试
- 业务逻辑放在 `src/core/` 或 `src/analyzer/`
- 标准化 contract 放在 `src/model/contracts.py` 和 `src/analyzer/normalizers.py`
