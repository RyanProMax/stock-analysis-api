# CLAUDE.md

Stock Analysis API 后端项目。

## 技术栈

- Python 3.12+
- FastAPI + Uvicorn
- Poetry 依赖管理

## 开发命令

```bash
# 安装依赖
poetry install

# 运行服务
poetry run python main.py
# 或
poetry run start

# 运行测试
poetry run pytest

# 代码格式化
poetry run black --line-length 100 .
```

## 项目结构

```
src/
├── agents/           # Agent 分析系统
├── analyzer/         # 因子计算
├── api/              # FastAPI 路由
├── config.py         # 配置
├── core/             # 核心功能
├── data_provider/    # 数据源
├── model/            # 数据模型
├── notification/     # 通知
├── storage/          # 缓存存储
└── utils/           # 工具函数
```

## 环境变量

复制 `.env.example` 为 `.env` 并配置：

| 变量 | 必填 | 说明 |
|------|------|------|
| | 推荐 | AI 分析 |
| TUSHARE_TOKEN | 可选 | Tushare Token |
| PORT | 否 | 端口 (默认 8080) |
| ENV | 否 | development/production |

## 部署

使用 Docker 构建：
```bash
docker build -t stock-analysis-api .
docker run -p 8080:8080 stock-analysis-api
```
