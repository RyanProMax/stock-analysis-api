# Stock Analysis API

股票分析系统后端 API 服务。

## 功能

- 股票技术分析 (MA, MACD, RSI, KDJ 等)
- 股票基本面分析 (PE, PB, ROE, 营收增长等)
- DCF 估值模型
- AI 智能分析 (LLM)
- SSE 流式响应

## 快速开始

```bash
# 安装依赖
poetry install

# 复制环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 运行服务
poetry run python main.py
```

服务启动后访问 http://localhost:8080/docs 查看 API 文档。

## 环境变量

- `DEEPSEEK_API_KEY`: (推荐)
- `TUSHARE_TOKEN`: Tushare Token (可选)
- `PORT`: 服务端口，默认 8080

## 部署

支持 Docker 部署到 Google Cloud Run。
