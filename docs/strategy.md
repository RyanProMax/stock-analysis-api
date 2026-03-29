# 当前分析策略

更新时间：2026-03-29

## 结论先说

- 当前公共研究入口固定为 `POST /analysis/research/snapshot`
- 公共请求只接受：
  - `market`
  - `symbols`
  - `start_date`
  - `end_date`
  - `mode`
- `mode` 固定为：
  - `base`
  - `full`
- 当前接口仍然只输出客观、结构化、可追溯结果：
  - 没有 thesis
  - 没有 recommendation
  - 没有 confidence
  - 没有 price target 结论
  - 没有 moat / positioning / idea pitch / morning note

## 使用方式

下面示例使用 `300827`，并按当前公共 contract 走 `mode=full`。

```bash
uv run python scripts/poll_research_snapshot.py \
  --market cn \
  --symbols 300827 \
  --mode full \
  --pretty
```

说明：

- 下方代码块使用 `jsonc`，只是为了在 JSON 里直接写注释
- 注释不是实际接口输出的一部分
- 示例底稿来自 `2026-03-29` 的真实返回
- `mode=full` 会加载 CN 市场当前全部公开模块，但不会跨市场强行跑 US-only 模块
- `empty` / `permission_denied` / `not_supported` 模块不会再输出空壳 body，而是统一放到 `item.meta.modules`

## `300827 + mode=full` 带注释示例

```jsonc
{
  "status": "partial", // 顶层聚合状态；这里只有一个 symbol，所以与 item.status 一致
  "computed_at": "2026-03-29T02:08:47.218562+00:00", // 本次快照生成时间（UTC）
  "source": "research_snapshot_dispatcher", // 统一调度器名，不代表单一 provider
  "market": "cn", // 请求市场
  "strategy": "fsp_objective_research_snapshot_v1", // 当前 snapshot 策略名
  "request": {
    "market": "cn", // 回显用户请求的市场
    "symbols": ["300827"], // 回显生效后的 symbol 列表，去重保序
    "start_date": "20260227", // 生效后的起始日期；未传时默认为 end_date 往前 30 天
    "end_date": "20260329", // 生效后的结束日期
    "mode": "full" // 当前公共入口只暴露 mode，不再暴露 modules / module_options
  },
  "items": [
    {
      "requested_symbol": "300827", // 当前 item 对应的请求 symbol
      "status": "partial", // 当前 symbol 的综合状态
      "error": null, // item 级错误；failed / not_supported 才会填对象

      "info": {
        "common": {
          "ts_code": "300827.SZ", // 标准证券代码
          "name": "上能电气", // 证券简称
          "list_date": "20200410", // 上市日期
          "delist_date": null // 退市日期；仍上市时通常为 null
        },
        "cn_specific": {
          "symbol": "300827", // 不带交易所后缀的纯代码
          "exchange": "SZSE", // 交易所
          "list_status": "L", // 上市状态；L = listed
          "area": "江苏", // 地域
          "industry": "电气设备", // 行业
          "market": "创业板" // 板块口径
        },
        "us_specific": {
          "ts_code": null, // 统一结构预留给 US；CN 下保持 null
          "name": null,
          "enname": null,
          "classify": null,
          "list_date": null,
          "delist_date": null
        }
      },

      "report_rc": {
        "records": [
          {
            "ts_code": "300827.SZ", // 标准证券代码
            "name": "上能电气", // 股票简称
            "report_date": "20251105", // 预测发布日期
            "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润", // 报告标题
            "report_type": "点评", // 报告类型；这里不是“非个股”
            "classify": "一般报告", // 源端分类字段
            "org_name": "华安证券", // 机构名
            "author_name": "张志邦", // 作者
            "quarter": "2027Q4", // 预测对应季度
            "op_rt": 939300.0, // 源端原始字段，保持 Tushare 命名
            "op_pr": null, // 源端为空时保持 null
            "tp": 115800.0, // 源端原始字段，保持 Tushare 命名
            "np": 104700.0, // 净利润预测值
            "eps": 2.08, // EPS 预测值
            "pe": 16.81, // 对应 PE
            "rd": null, // 源端为空时保持 null
            "roe": 21.1, // ROE 预测值
            "ev_ebitda": 13.18, // EV/EBITDA
            "rating": "买入", // 机构评级
            "max_price": null, // 源端为空时保持 null
            "min_price": null // 源端为空时保持 null
          },
          {
            "ts_code": "300827.SZ",
            "name": "上能电气",
            "report_date": "20251105",
            "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润",
            "report_type": "点评",
            "classify": "一般报告",
            "org_name": "华安证券",
            "author_name": "张志邦",
            "quarter": "2026Q4",
            "op_rt": 816400.0,
            "op_pr": null,
            "tp": 98000.0,
            "np": 88600.0,
            "eps": 1.76,
            "pe": 19.86,
            "rd": null,
            "roe": 22.7,
            "ev_ebitda": 15.11,
            "rating": "买入",
            "max_price": null,
            "min_price": null
          },
          {
            "ts_code": "300827.SZ",
            "name": "上能电气",
            "report_date": "20251105",
            "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润",
            "report_type": "点评",
            "classify": "一般报告",
            "org_name": "华安证券",
            "author_name": "张志邦",
            "quarter": "2025Q4",
            "op_rt": 687900.0,
            "op_pr": null,
            "tp": 81800.0,
            "np": 73900.0,
            "eps": 1.47,
            "pe": 23.81,
            "rd": null,
            "roe": 24.5,
            "ev_ebitda": 17.09,
            "rating": "买入",
            "max_price": null,
            "min_price": null
          }
        ]
      },

      "earnings": {
        "fundamentals": {
          "market": "cn", // 基础上下文对应市场
          "status": "partial", // 这一整块财务上下文的覆盖状态
          "coverage": {
            "valuation": "ok", // 估值子块可用
            "growth": "ok", // 增长子块可用
            "earnings": "partial", // 财报子块只有部分字段
            "institution": "partial", // 机构持仓子块只有部分字段
            "capital_flow": "not_supported", // 当前未实现
            "dragon_tiger": "not_supported", // 当前未实现
            "boards": "not_supported" // 当前未实现
          },
          "source_chain": [
            {"provider": "financial_provider", "result": "ok", "duration_ms": 0},
            {"provider": "tushare.income", "result": "ok", "duration_ms": 0},
            {"provider": "tushare.income", "result": "ok", "duration_ms": 0},
            {"provider": "financial_provider", "result": "partial", "duration_ms": 0},
            {"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0},
            {"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0},
            {"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}
          ], // CN 财务上下文内部 source chain；这是业务字段，不是公共模块状态壳
          "errors": ["not implemented", "not implemented", "not implemented"], // 子流水线级错误摘要
          "valuation": {
            "status": "ok",
            "coverage": {"status": "ok"},
            "source_chain": [{"provider": "financial_provider", "result": "ok", "duration_ms": 0}],
            "errors": [],
            "data": {
              "pe_ratio": 56.0584,
              "pb_ratio": 5.9187,
              "price": null
            }
          },
          "growth": {
            "status": "ok",
            "coverage": {"status": "ok"},
            "source_chain": [{"provider": "tushare.income", "result": "ok", "duration_ms": 0}],
            "errors": [],
            "data": {
              "revenue_yoy": 16.149949615964154,
              "roe": 13.5931,
              "debt_to_assets": 73.009,
              "summary": "revenue_yoy=1614.99%"
            }
          },
          "earnings": {
            "status": "partial",
            "coverage": {"status": "partial"},
            "source_chain": [{"provider": "tushare.income", "result": "ok", "duration_ms": 0}],
            "errors": [],
            "data": {
              "financial_report": {
                "report_date": null,
                "announcement_date": null,
                "revenue_growth_ratio": null,
                "roe": null
              },
              "dividend": {},
              "forecast_summary": "",
              "quick_report_summary": ""
            }
          },
          "institution": {
            "status": "partial",
            "coverage": {"status": "partial"},
            "source_chain": [{"provider": "financial_provider", "result": "partial", "duration_ms": 0}],
            "errors": [],
            "data": {
              "institution_holding_change": null,
              "top10_holder_change": null,
              "summary": ""
            }
          },
          "capital_flow": {
            "status": "not_supported",
            "coverage": {"status": "not_supported"},
            "source_chain": [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
            "errors": ["not implemented"],
            "data": {}
          },
          "dragon_tiger": {
            "status": "not_supported",
            "coverage": {"status": "not_supported"},
            "source_chain": [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
            "errors": ["not implemented"],
            "data": {}
          },
          "boards": {
            "status": "not_supported",
            "coverage": {"status": "not_supported"},
            "source_chain": [{"provider": "fundamental_pipeline", "result": "not_supported", "duration_ms": 0}],
            "errors": ["not implemented"],
            "data": {}
          }
        },
        "growth": {
          "revenue_yoy": 16.149949615964154, // 增长快照
          "roe": 13.5931,
          "debt_to_assets": 73.009,
          "summary": "revenue_yoy=1614.99%"
        },
        "valuation": {
          "pe_ratio": 56.0584, // 估值快照
          "pb_ratio": 5.9187,
          "price": null
        },
        "coverage": {
          "valuation": "ok", // 各财务子块可用性摘要
          "growth": "ok",
          "earnings": "partial",
          "institution": "partial",
          "capital_flow": "not_supported",
          "dragon_tiger": "not_supported",
          "boards": "not_supported"
        }
      },

      "catalysts": {
        "event_count": 0 // 当前公共 body 只保留业务字段；这里没有可公开事件明细，因此只剩数量
      },

      "screen": {
        "metrics": {
          "pe_ratio": 56.0584, // 当前 symbol 的筛选指标快照
          "price_to_book": 5.9187,
          "roe": 13.5931,
          "revenue_growth": 16.149949615964154,
          "debt_ratio": 73.009
        },
        "passed": true, // 当前 mode 下没有公开自定义 filters，默认不拦截
        "filter_count": 0 // 公开 contract 下当前未传自定义筛选器
      },

      "model_update": {
        "refreshed_modules": {
          "earnings": "partial" // 本次模型更新摘要里实际刷新到的模块状态
        }
      },

      "summary": {
        "research": {
          "report_count": 0, // 请求窗口内有效 research_report 条数
          "latest_report_date": null, // 请求窗口内最新研报日期；这里为空
          "institution_count": 0, // 请求窗口内覆盖机构数
          "latest_estimate_date": "20251105", // 当前可用预测块中最新 report_rc 日期
          "rating_distribution": {
            "买入": 3 // 当前可用 report_rc 的评级分布
          },
          "quarter_distribution": {
            "2027Q4": 1,
            "2026Q4": 1,
            "2025Q4": 1
          }
        },
        "earnings": {
          "reported_available": false, // 是否拿到可直接用的 reported 财报事实
          "consensus_available": false, // 是否拿到可直接用的 consensus
          "growth": {
            "revenue_yoy": 16.149949615964154,
            "roe": 13.5931,
            "debt_to_assets": 73.009,
            "summary": "revenue_yoy=1614.99%"
          },
          "valuation": {
            "pe_ratio": 56.0584,
            "pb_ratio": 5.9187,
            "price": null
          },
          "coverage": {
            "valuation": "ok",
            "growth": "ok",
            "earnings": "partial",
            "institution": "partial",
            "capital_flow": "not_supported",
            "dragon_tiger": "not_supported",
            "boards": "not_supported"
          }
        },
        "catalysts": {
          "event_count": 0, // 事件总数
          "latest_event_time": null, // 最近事件时间
          "event_type_distribution": {} // 事件类型分布
        },
        "screen": {
          "passed": true, // screen 摘要：是否通过
          "filter_count": 0, // 条件数
          "failed_filters": [] // 未通过项列表
        },
        "models": {
          "executed_modules": {
            "model_update": "ok" // 当前 mode 下执行到的模型 / 更新类模块状态摘要
          }
        },
        "change_flags": {
          "has_new_report_7d": false, // 最近 7 天是否有新研报
          "has_new_estimate_7d": false, // 最近 7 天是否有新预测
          "has_new_catalyst_7d": false // 最近 7 天是否有新催化
        }
      },

      "meta": {
        "mode": "full", // 当前 item 使用的 mode
        "sources": [
          "tushare", // 原始块主 provider
          "Tushare", // 某些财务上下文内部回填的 source 名大小写不同，当前原样保留
          "research_snapshot_dispatcher" // dispatcher 自身作为来源的模块，如 model_update
        ],
        "partial_reasons": [
          {
            "module": "anns_d", // 被判定为非 ok 的模块名
            "status": "permission_denied", // 该模块状态
            "error": "抱歉，您没有该接口访问权限。"
          },
          {
            "module": "news",
            "status": "permission_denied",
            "error": "抱歉，您没有该接口访问权限。"
          },
          {
            "module": "major_news",
            "status": "permission_denied",
            "error": "抱歉，您没有该接口访问权限。"
          },
          {
            "module": "earnings",
            "status": "partial",
            "error": null
          },
          {
            "module": "catalysts",
            "status": "partial",
            "error": null
          }
        ], // 当前 item 被判为 partial 的直接原因列表
        "modules": {
          "research_report": {
            "status": "empty", // 统一模块状态入口
            "source": "tushare", // 最终命中的 source
            "error": null, // 模块级错误文本
            "notes": {
              "skip_reason": "no_stock_specific_report_rc_in_requested_window", // research_report 为什么被跳过
              "requested_start_date": "20260227",
              "requested_end_date": "20260329"
            }
          },
          "report_rc": {
            "status": "ok",
            "source": "tushare",
            "error": null,
            "notes": {
              "requested_start_date": "20260227", // 原请求窗口
              "requested_end_date": "20260329",
              "resolved_start_date": "20251105", // 实际回退后命中的窗口
              "resolved_end_date": "20251105",
              "fallback_mode": "latest_stock_specific_report_date" // 回退模式
            }
          },
          "anns_d": {
            "status": "permission_denied",
            "source": "tushare",
            "error": "抱歉，您没有该接口访问权限。",
            "notes": {}
          },
          "news": {
            "status": "permission_denied",
            "source": "tushare",
            "error": "抱歉，您没有该接口访问权限。",
            "notes": {
              "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)" // 新闻提及过滤规则
            }
          },
          "major_news": {
            "status": "permission_denied",
            "source": "tushare",
            "error": "抱歉，您没有该接口访问权限。",
            "notes": {
              "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)"
            }
          },
          "earnings": {
            "status": "partial",
            "source": "Tushare",
            "error": null,
            "notes": {
              "data_completeness": "partial", // 结构化模块的覆盖度
              "limitations": [
                "CN earnings module is limited by available provider financial coverage."
              ], // 限制说明统一上收
              "interface_type": "mixed" // 结构化模块类型
            }
          },
          "catalysts": {
            "status": "partial",
            "source": "tushare",
            "error": null,
            "notes": {
              "data_completeness": "partial",
              "limitations": [
                "Underlying CN native blocks unavailable: anns_d, news, major_news"
              ], // catalyst 为什么是 partial
              "interface_type": "fact"
            }
          },
          "screen": {
            "status": "ok",
            "source": "Tushare",
            "error": null,
            "notes": {
              "data_completeness": "partial",
              "limitations": [
                "Screen evaluates only the requested symbols, not a full market universe."
              ],
              "interface_type": "mixed"
            }
          },
          "model_update": {
            "status": "ok",
            "source": "research_snapshot_dispatcher",
            "error": null,
            "notes": {
              "data_completeness": "partial",
              "limitations": [
                "Model update is a deterministic refresh summary, not a stored revision history."
              ],
              "interface_type": "mixed"
            }
          }
        }
      }
    }
  ]
}
```

## 读这个 payload 时要抓住的重点

- 主业务数据看 `summary` 和有实际 body 的模块：
  - `report_rc`
  - `earnings`
  - `catalysts`
  - `screen`
  - `model_update`
- 模块为什么缺失、为什么 partial、为什么回退，不再去模块 body 里找，而是统一看 `item.meta.modules`
- `research_report` / `anns_d` / `news` / `major_news` 即使没有 body，也仍然通过 `meta.modules` 暴露真实状态
- `summary` 是确定性汇总，不是主观结论
