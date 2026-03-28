# 当前分析策略

更新时间：2026-03-28

## 结论先说

- 当前仓库已经把 FSP 的客观能力统一收敛到单一 HTTP 入口：`POST /analysis/research/snapshot`
- 这不是“调用单个 Tushare 接口然后原样返回”，而是：
  - 先按市场和 `modules` 做模块调度
  - 再分别执行原始数据块、结构化分析模块和模型模块
  - 最后统一输出结构化、可追溯、严格客观的 payload
- 当前仍然**不做主观研究层**：
  - 不输出 thesis
  - 不输出 recommendation
  - 不输出 confidence
  - 不输出 price target 结论
  - 不输出 moat / positioning / idea pitch / morning note

## 当前策略是什么

当前策略可以概括成：

- `dispatcher-first`
  - 统一入口先解析 `market`、`symbols`、`modules`、`module_options`
  - 不传 `modules` 时按市场加载默认模块
- `provider-aware`
  - `cn` 原生研究块优先复用 Tushare
  - `us` 模型/分析模块优先复用 yfinance + 本地 analyzer
- `objective-only`
  - 原始块保留事实
  - 结构化块只保留 `reported` / `consensus` / `derived` / `model_output`
  - 所有模块统一经过出口清洗，移除主观字段

## 模块分层

- 原始 / 事件型模块
  - `research_report`: 券商研报列表 / 覆盖记录
  - `report_rc`: 盈利预测与评级快照
  - `anns_d`: 公告流
  - `news`: 通用新闻命中过滤结果
  - `major_news`: 重点媒体新闻命中过滤结果
- 结构化分析 / 模型模块
  - `earnings`
  - `earnings_preview`
  - `dcf`
  - `comps`
  - `three_statement`
  - `three_statement_scenarios`
  - `lbo`
  - `competitive`
  - `catalysts`
  - `model_update`
  - `sector_overview`
  - `screen`
- `cn` 衍生汇总
  - 当执行 CN 原生研究块时，额外生成 `derived`
  - 它是对 `research_report / report_rc / anns_d / news / major_news` 的确定性汇总，不是主观判断

## 带字段说明的示例

下面这段是当前统一入口的带注释 `jsonc` 示例，说明注释不是实际接口返回的一部分。

```jsonc
{
  "status": "ok", // 顶层状态，汇总所有 requested symbol
  "computed_at": "2026-03-28T16:20:00+00:00", // 本次快照生成时间
  "source": "research_snapshot_dispatcher", // 统一调度器，不是单个 provider 名
  "market": "us",
  "strategy": "fsp_objective_research_snapshot_v1", // 当前统一策略版本名
  "request": {
    "market": "us",
    "symbols": ["NVDA"],
    "start_date": "20260301",
    "end_date": "20260328",
    "modules": ["earnings", "dcf"], // 本次实际执行的模块
    "module_options": {
      "dcf": {
        "risk_free_rate": 0.04
      }
    }
  },
  "items": [
    {
      "requested_symbol": "NVDA",
      "status": "ok", // 当前 symbol 的状态
      "error": null,
      "info": {
        "common": {
          "ts_code": null,
          "name": "NVIDIA",
          "list_date": null,
          "delist_date": null
        },
        "cn_specific": {
          "symbol": null,
          "exchange": null,
          "list_status": null,
          "area": null,
          "industry": null,
          "market": null
        },
        "us_specific": {
          "ts_code": "NVDA", // US 侧统一身份字段
          "name": "NVIDIA",
          "enname": null,
          "classify": "stock",
          "list_date": null,
          "delist_date": null
        }
      },

      "earnings": {
        "entity": {}, // 标的身份信息
        "facts": {
          "reported": {}, // 已披露事实
          "consensus": {} // 一致预期或共识对比
        },
        "analysis": {
          "derived": {} // 确定性衍生，不是主观解读
        },
        "meta": {
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "ok",
        "module_error": null,
        "attempted_sources": ["yfinance"]
      },

      "dcf": {
        "entity": {},
        "facts": {
          "reported": {},
          "consensus": {}
        },
        "analysis": {
          "model_output": {} // 模型输出
        },
        "meta": {
          "schema_version": "2.0.0",
          "interface_type": "model"
        },
        "module_status": "ok",
        "module_error": null,
        "attempted_sources": ["yfinance"]
      }
    }
  ]
}
```

## 怎么判断它有没有“自己的分析”

有，但只在客观层：

- 有自己的模块调度策略
- 有自己的状态语义
- 有自己的排序、去重、降级、过滤和 fallback 规则
- 有自己的确定性 `derived` / `model_output`

没有主观层：

- 没有“这家公司值得买”的结论
- 没有“研报观点总结”
- 没有“我认为市场错杀/高估”的 narrative
- 没有 analyst-style text generation

所以当前系统更准确的描述是：

- “统一的客观研究快照与模型分发器”
- 不是“主观研究分析 agent”

接口 contract 以 [docs/api.md](/Users/ryan/projects/stock-analysis-api/docs/api.md) 为准，架构边界以 [docs/architecture.md](/Users/ryan/projects/stock-analysis-api/docs/architecture.md) 为准。
