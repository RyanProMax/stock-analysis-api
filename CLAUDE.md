# CLAUDE.md

Stock Analysis API 后端项目，当前为 HTTP-only 服务。

## 开发命令

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv run start
```

## 关键约束

- 复杂接口统一返回 `entity/facts/analysis/meta`
- `facts` 只放事实值，`analysis` 只放推导、估算和模型输出
- 缺少可靠源数据时返回 `partial` 或 `unavailable`

## 当前 HTTP 能力

- `/stock/analyze`
- `/stock/list`
- `/stock/search`
- `/valuation/dcf`
- `/valuation/comps`
- `/model/lbo`
- `/model/three-statement`
- `/model/three-statement/scenarios`
- `/analysis/competitive/competitive`
- `/analysis/earnings/earnings`
