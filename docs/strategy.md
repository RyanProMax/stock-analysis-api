# 当前分析策略

更新时间：2026-03-29

## 结论先说

- 当前唯一公共分析入口固定为 `POST /stock/analyze`
- 对外请求只接受：
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

下面示例使用真实的 `300827`，并按当前公共 contract 走 `mode=full`。

```bash
uv run python scripts/stock_analyze.py \
  --market cn \
  --symbols 300827 \
  --mode full \
  --pretty
```

说明：

- CLI 的 stdout 是纯 JSON，方便外部 Agent 直接消费
- 下方代码块使用 `jsonc`，只是为了在 JSON 中直接写注释
- 注释不是实际输出的一部分
- 示例底稿来自 `2026-03-29` 的真实运行结果
- `mode=full` 会加载 CN 市场当前全部公开模块
- 没有数据或没有权限的原始块不会输出空壳 body，而是只在 `item.meta.modules` 里给状态

## `300827 + mode=full` 带注释示例

```jsonc
{
  "status_code": 200, // StandardResponse 业务状态码
  "data": {
    "status": "partial", // 顶层聚合状态
    "computed_at": "2026-03-29T04:52:47.448292+00:00", // 本次分析生成时间（UTC）
    "source": "stock_analyze_dispatcher", // 顶层统一调度器名
    "market": "cn", // 生效市场
    "strategy": "fsp_objective_stock_analyze_v1", // 当前公共策略名
    "request": {
      "market": "cn", // 回显用户请求市场
      "symbols": ["300827"], // 回显生效后的 symbol 列表，去重保序
      "start_date": "20260227", // 生效后的窗口起始日
      "end_date": "20260329", // 生效后的窗口结束日
      "mode": "full" // 当前 mode
    },
    "items": [
      {
        "requested_symbol": "300827", // 当前 item 对应的请求 symbol
        "status": "partial", // 当前 symbol 的综合状态
        "error": null, // item 级错误；failed / not_supported 时才会有对象

        "info": {
          "common": {
            "ts_code": "300827.SZ", // 标准证券代码
            "name": "上能电气", // 证券简称
            "list_date": "20200410", // 上市日期
            "delist_date": null // 退市日期；仍上市时通常为 null
          },
          "cn_specific": {
            "symbol": "300827", // 不带后缀的纯代码
            "exchange": "SZSE", // 交易所
            "list_status": "L", // 上市状态
            "area": "江苏", // 地域
            "industry": "电气设备", // 行业
            "market": "创业板" // 板块口径
          },
          "us_specific": {
            "ts_code": null, // 统一结构预留给 US
            "name": null,
            "enname": null,
            "classify": null,
            "list_date": null,
            "delist_date": null
          }
        },

        "technical": {
          "fear_greed": {
            "index": 65.56441915275643, // 贪恐指数数值
            "label": "🤤 贪婪" // 贪恐指数标签
          },
          "technical_signals": [
            {
              "key": "ma", // 因子标识
              "name": "MA均线", // 因子名称
              "status": "📈 多头趋势 (中期看涨)", // 因子状态说明
              "bullish_signals": ["价格站上 MA20/MA60，趋势排列良好"], // 多头信号
              "bearish_signals": ["价格跌破 MA5"] // 空头信号
            }
          ], // 实际返回会包含全部技术因子，不只一个
          "trend": {
            "code": "300827", // 趋势分析对应代码
            "trend_status": "强势多头", // 趋势状态
            "ma_alignment": "强势多头排列，均线发散上行", // 均线排列说明
            "trend_strength": 90, // 趋势强度
            "current_price": 43.08, // 当前价格
            "buy_signal": "强烈买入", // 当前模型给出的动作标签
            "signal_score": 78, // 综合分数
            "signal_reasons": ["✅ 强势多头，顺势做多"], // 触发该判断的理由
            "risk_factors": [], // 当前识别到的风险项
            "macd_status": "多头", // MACD 状态
            "rsi_status": "中性" // RSI 状态
          } // 实际返回还包含 MA / 偏离率 / 支撑压力 / MACD / RSI 等完整技术细节
        },

        "report_rc": {
          "records": [
            {
              "ts_code": "300827.SZ", // 标准代码
              "name": "上能电气", // 证券简称
              "report_date": "20251105", // 预测发布日期
              "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润", // 标题
              "report_type": "点评", // 报告类型
              "classify": "一般报告", // 源端分类
              "org_name": "华安证券", // 机构
              "author_name": "张志邦", // 作者
              "quarter": "2027Q4", // 预测对应季度
              "op_rt": 939300.0, // 源端原始字段，保持 Tushare 命名
              "op_pr": null,
              "tp": 115800.0,
              "np": 104700.0,
              "eps": 2.08,
              "pe": 16.81,
              "rd": null,
              "roe": 21.1,
              "ev_ebitda": 13.18,
              "rating": "买入", // 机构评级原文保留；接口本身不会再汇总成 recommendation
              "max_price": null,
              "min_price": null
            }
          ]
        }, // 原始块统一只保留 records；其状态/来源放在 meta.modules.report_rc

        "earnings": {
          "fundamentals": {
            "market": "cn", // 财务上下文对应市场
            "status": "partial", // 财务覆盖状态
            "coverage": {
              "valuation": "ok",
              "growth": "ok",
              "earnings": "partial",
              "institution": "partial",
              "capital_flow": "not_supported",
              "dragon_tiger": "not_supported",
              "boards": "not_supported"
            },
            "source_chain": [
              {"provider": "financial_provider", "result": "ok", "duration_ms": 0}
            ], // 财务上下文内部 source chain；这仍属于业务字段
            "errors": ["not implemented"], // 子流程错误摘要
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
            }
          },
          "growth": {
            "revenue_yoy": 16.149949615964154, // 直接给 Agent 用的增长快照
            "roe": 13.5931,
            "debt_to_assets": 73.009,
            "summary": "revenue_yoy=1614.99%"
          },
          "valuation": {
            "pe_ratio": 56.0584, // 直接给 Agent 用的估值快照
            "pb_ratio": 5.9187,
            "price": null
          },
          "coverage": {
            "valuation": "ok", // 当前 earnings 模块各子块覆盖状态
            "growth": "ok",
            "earnings": "partial",
            "institution": "partial",
            "capital_flow": "not_supported",
            "dragon_tiger": "not_supported",
            "boards": "not_supported"
          }
        },

        "catalysts": {
          "event_count": 0 // 当前窗口内没有可公开交付的事件
        },

        "screen": {
          "metrics": {
            "pe_ratio": 56.0584, // 当前筛选使用的指标快照
            "price_to_book": 5.9187,
            "roe": 13.5931,
            "revenue_growth": 16.149949615964154,
            "debt_ratio": 73.009
          },
          "passed": true, // 是否通过当前 filters
          "filter_count": 0 // 实际执行的过滤条件数量
        },

        "model_update": {
          "refreshed_modules": {
            "earnings": "partial" // 刷新摘要，不是完整 revision history
          }
        },

        "summary": {
          "technical": {
            "signal_count": 11, // 技术因子数量
            "fear_greed": {
              "index": 65.56441915275643,
              "label": "🤤 贪婪"
            },
            "trend": {
              "trend_status": "强势多头", // 汇总后的趋势状态
              "trend_strength": 90,
              "buy_signal": "强烈买入",
              "signal_score": 78
            }
          },
          "research": {
            "report_count": 0, // 当前窗口内 stock-specific research_report 数量
            "latest_report_date": null,
            "institution_count": 0,
            "latest_estimate_date": "20251105", // 当前 report_rc 命中的最新日期
            "rating_distribution": {"买入": 3}, // report_rc 内评级分布
            "quarter_distribution": {
              "2027Q4": 1,
              "2026Q4": 1,
              "2025Q4": 1
            }
          },
          "earnings": {
            "reported_available": false, // earnings.reported 是否有值
            "consensus_available": false, // earnings.consensus 是否有值
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
            "event_count": 0,
            "latest_event_time": null,
            "event_type_distribution": {}
          },
          "screen": {
            "passed": true,
            "filter_count": 0,
            "failed_filters": []
          },
          "models": {
            "executed_modules": {
              "model_update": "ok" // 当前 mode 内执行过的模型类模块摘要
            }
          },
          "change_flags": {
            "has_new_report_7d": false, // 最近 7 天是否有新 report
            "has_new_estimate_7d": false, // 最近 7 天是否有新 estimate
            "has_new_catalyst_7d": false // 最近 7 天是否有新 catalyst
          }
        },

        "meta": {
          "mode": "full", // 当前 item 的生效 mode
          "sources": [
            "CN_Tushare",
            "tushare",
            "Tushare",
            "stock_analyze_dispatcher"
          ], // item 级去重后的来源摘要
          "partial_reasons": [
            {
              "module": "anns_d",
              "status": "permission_denied",
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
          ], // 所有非纯 ok 模块的聚合摘要
          "modules": {
            "technical": {
              "status": "ok", // 模块状态
              "source": "CN_Tushare", // 最终命中的主来源
              "error": null, // 模块级错误
              "notes": {
                "as_of": "2026-03-27", // 模块自身观测时间
                "data_completeness": "ok", // 模块数据完整性
                "interface_type": "mixed" // 模块类型
              }
            },
            "research_report": {
              "status": "empty", // 当前窗口没命中数据
              "source": "tushare",
              "error": null,
              "notes": {
                "skip_reason": "no_stock_specific_report_rc_in_requested_window", // 未拉取 research_report 的原因
                "requested_start_date": "20260227",
                "requested_end_date": "20260329"
              }
            },
            "report_rc": {
              "status": "ok",
              "source": "tushare",
              "error": null,
              "notes": {
                "requested_start_date": "20260227",
                "requested_end_date": "20260329",
                "resolved_start_date": "20251105", // 实际命中的窗口
                "resolved_end_date": "20251105",
                "fallback_mode": "latest_stock_specific_report_date" // fallback 说明
              }
            },
            "anns_d": {
              "status": "permission_denied", // 只在 meta 体现，body 不再输出空壳
              "source": "tushare",
              "error": "抱歉，您没有该接口访问权限。",
              "notes": {}
            },
            "news": {
              "status": "permission_denied",
              "source": "tushare",
              "error": "抱歉，您没有该接口访问权限。",
              "notes": {
                "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)" // 命中过滤规则
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
                "data_completeness": "partial",
                "limitations": [
                  "CN earnings module is limited by available provider financial coverage."
                ],
                "interface_type": "mixed"
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
                ],
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
              "source": "stock_analyze_dispatcher",
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
  },
  "err_msg": null // 成功时固定为 null
}
```

## 读法建议

- 大多数 Agent 先看 `summary`
- 需要追溯来源、降级原因或权限问题时看 `meta.modules`
- 需要完整原始记录时看 `report_rc.records` 或其他原始块
- 需要技术面细节时看 `technical`
- 不要再从 payload 里寻找 thesis、recommendation、price target 之类主观字段，它们已经不属于公共 contract
