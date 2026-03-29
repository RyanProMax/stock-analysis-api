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
- 当前公共策略已升级为 `fsp_objective_stock_analyze_v2`
- 当前接口仍然只输出客观、结构化、可追溯结果：
  - 没有 thesis
  - 没有 recommendation
  - 没有 confidence
  - 没有 price target 结论
  - 没有 moat / positioning / conviction
- 本轮的重点变化：
  - `summary` 首位新增 `research_strategy`
  - `item.meta` 新增 `provenance`
  - `technical` 保留，但改成研究辅助确认层
  - `screen` 无 filters 时不再伪装成 `passed=true`

## 使用方式

下面示例使用真实的 `300827`，并按当前公共 contract 走 `mode=base`。

```bash
uv run python scripts/stock_analyze.py \
  --market cn \
  --symbols 300827 \
  --mode base \
  --pretty
```

说明：

- CLI 的 stdout 是纯 JSON，方便外部 Agent 直接消费
- 下方代码块使用 `jsonc`，只是为了在 JSON 中直接写注释
- 注释不是实际输出的一部分
- 示例底稿来自 `2026-03-29` 的真实运行结果

## `300827 + mode=base` 带注释示例

```jsonc
{
  "status_code": 200, // StandardResponse 业务状态码
  "data": {
    "status": "partial", // 顶层聚合状态
    "computed_at": "2026-03-29T06:03:50.016540+00:00", // 本次分析生成时间（UTC）
    "source": "stock_analyze_dispatcher", // 顶层统一调度器名
    "market": "cn", // 生效市场
    "strategy": "fsp_objective_stock_analyze_v2", // 当前公共策略名
    "request": {
      "market": "cn",
      "symbols": ["300827"],
      "start_date": "20260227",
      "end_date": "20260329",
      "mode": "base"
    },
    "items": [
      {
        "requested_symbol": "300827", // 当前 item 对应的请求 symbol
        "status": "partial", // 当前 symbol 的综合状态
        "error": null, // item 级错误；failed / not_supported 时才会有对象

        "info": {
          "common": {
            "ts_code": "300827.SZ",
            "name": "上能电气",
            "list_date": "20200410",
            "delist_date": null
          },
          "cn_specific": {
            "symbol": "300827",
            "exchange": "SZSE",
            "list_status": "L",
            "area": "江苏",
            "industry": "电气设备",
            "market": "创业板"
          },
          "us_specific": {
            "ts_code": null,
            "name": null,
            "enname": null,
            "classify": null,
            "list_date": null,
            "delist_date": null
          }
        },

        "technical": {
          "fear_greed": {
            "index": 65.56441915275643, // 原始指数值
            "label": "greed" // 已收口为标准 band，不再输出 emoji
          },
          "technical_signals": [
            {
              "key": "ma", // 原始因子标识
              "name": "MA均线",
              "family": "trend", // 信号家族：trend / momentum / volume / volatility / sentiment
              "direction": "mixed", // 当前信号方向：bullish / bearish / mixed / neutral
              "status": "多头趋势 (中期看涨)", // 去 emoji 后的简洁状态
              "evidence": ["价格站上 MA20/MA60，趋势排列良好"], // 支撑当前方向的证据
              "limitations": ["价格跌破 MA5"], // 反向或限制条件
              "as_of": "2026-03-27" // 信号观测日期
            }
          ],
          "trend": {
            "trend_status": "强势多头", // 趋势状态
            "trend_strength": 90.0, // 趋势强度
            "stance": "bullish_confirmation", // 公共层 stance，不再输出 buy_signal
            "score": 78, // 公共层 score，不再输出 signal_score
            "horizon": "swing", // 方法默认观察周期
            "methodology_version": "technical_research_v2", // 当前公共技术确认层版本
            "as_of": "2026-03-27",
            "invalidation_levels": {
              "support_levels": [40.0765], // 失效前应重点观察的支撑位
              "resistance_levels": [47.1] // 当前阻力位
            },
            "risk_context": {
              "volume_status": "缩量回调", // 量价风险语境
              "volume_trend": "缩量回调，洗盘特征明显（好）",
              "support_ma5": false,
              "support_ma10": false
            },
            "evidence": {
              "ma_alignment": "强势多头排列，均线发散上行", // 趋势确认依据
              "macd_status": "多头",
              "rsi_status": "中性",
              "macd_signal": "多头排列，持续上涨",
              "rsi_signal": "RSI中性(55.6)，震荡整理中"
            }
          }
        },

        "report_rc": {
          "records": [
            {
              "report_date": "20251105", // 当前命中的 stock-specific 预测日期
              "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润",
              "org_name": "华安证券",
              "quarter": "2027Q4",
              "eps": 2.08,
              "pe": 16.81,
              "roe": 21.1,
              "rating": "买入" // 源端原文保留；系统不会把它升级成 recommendation
            }
          ]
        }, // 原始块统一只保留 records

        "earnings": {
          "fundamentals": {
            "market": "cn",
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
            ],
            "errors": ["not implemented"],
            "growth": {
              "status": "ok",
              "data": {
                "revenue_yoy": 0.16149949615964154, // 统一为 ratio 语义
                "roe": 0.135931,
                "debt_to_assets": 0.73009
              }
            }
          },
          "growth": {
            "revenue_yoy": 0.16149949615964154, // 直接给 Agent 用的增长快照
            "roe": 0.135931,
            "debt_to_assets": 0.73009
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
          "event_count": 0 // 当前窗口内无可交付事件
        },

        "screen": {
          "metrics": {
            "pe_ratio": 56.0584,
            "price_to_book": 5.9187,
            "roe": 0.135931,
            "revenue_growth": 0.16149949615964154,
            "debt_ratio": 0.73009
          },
          "evaluated": false, // 当前没有 filters，说明并未真正执行 pass/fail 筛选
          "passed": null, // 不再把“没筛选”伪装成 true
          "filter_count": 0
        },

        "summary": {
          "research_strategy": {
            "expectations_vs_reported": {
              "state": "expectations_only", // 当前更多是“有预测、缺完整已公布口径”
              "market": "cn",
              "estimate_available": true,
              "reported_available": false,
              "consensus_available": false,
              "latest_estimate_date": "20251105"
            },
            "fundamental_quality": {
              "state": "partial", // 基本面覆盖不是空，但也不完整
              "available_components": ["fundamentals", "growth", "valuation", "coverage"],
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
            "valuation_context": {
              "state": "covered", // 已有基础估值快照
              "valuation_metrics": {
                "pe_ratio": 56.0584,
                "pb_ratio": 5.9187
              }
            },
            "catalyst_path": {
              "state": "not_visible", // 当前窗口里没有可公开交付的 catalyst
              "event_count": 0
            },
            "price_action_confirmation": {
              "state": "supportive", // 技术确认层给出的价格行为确认
              "stance": "bullish_confirmation",
              "trend_status": "强势多头",
              "score": 78,
              "volume_status": "缩量回调",
              "sentiment_band": "greed"
            },
            "cross_signal_alignment": {
              "state": "mixed", // 多模块信号不是完全一致，也不是完全冲突
              "positive_signals": 2,
              "caution_signals": 0
            },
            "risk_flags": [
              "estimate_fallback_used", // report_rc 实际走了窗口外 fallback
              "stale_estimate_window", // 估值/预期日期偏旧
              "partial_earnings_coverage", // 财务覆盖不完整
              "no_visible_catalysts", // 当前无明显催化剂
              "screen_not_evaluated", // screen 未执行真正筛选
              "technical_layer_contains_heuristics" // 技术层仍属启发式确认层
            ],
            "evidence_strength": {
              "level": "low", // 规则生成的总体证据强度，不是主观 confidence
              "dimensions": {
                "source_directness": "high",
                "data_completeness": "medium",
                "recency": "medium",
                "cross_source_consistency": "medium",
                "heuristic_dependency": "low",
                "fallback_dependency": "low"
              }
            }
          },
          "research": {
            "report_count": 0,
            "latest_report_date": null,
            "institution_count": 0,
            "latest_estimate_date": "20251105",
            "rating_distribution": {"买入": 3},
            "quarter_distribution": {
              "2027Q4": 1,
              "2026Q4": 1,
              "2025Q4": 1
            }
          },
          "earnings": {
            "reported_available": false,
            "consensus_available": false
          },
          "catalysts": {
            "event_count": 0,
            "latest_event_time": null,
            "event_type_distribution": {}
          },
          "screen": {
            "evaluated": false,
            "passed": null,
            "filter_count": 0,
            "failed_filters": []
          },
          "change_flags": {
            "has_new_report_7d": false,
            "has_new_estimate_7d": false,
            "has_new_catalyst_7d": false
          },
          "technical": {
            "signal_count": 11,
            "fear_greed": {
              "index": 65.56441915275643,
              "label": "greed"
            },
            "trend": {
              "trend_status": "强势多头",
              "stance": "bullish_confirmation",
              "score": 78
            }
          }
        },

        "meta": {
          "mode": "base",
          "sources": [
            "CN_SQLiteDailyWarehouse",
            "tushare",
            "Tushare"
          ], // item 级去重后的来源摘要
          "partial_reasons": [
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
            "report_rc": {
              "status": "ok",
              "source": "tushare",
              "error": null,
              "notes": {
                "requested_start_date": "20260227",
                "requested_end_date": "20260329",
                "resolved_start_date": "20251105", // 实际命中的 fallback 窗口
                "resolved_end_date": "20251105",
                "fallback_mode": "latest_stock_specific_report_date"
              }
            }
          },
          "provenance": {
            "summary": {
              "research_strategy": {
                "expectations_vs_reported": {
                  "source_modules": ["report_rc", "earnings"], // 这个结论来自哪些模块
                  "field_paths": [
                    "report_rc.records[*].report_date",
                    "earnings.reported",
                    "earnings.consensus"
                  ], // 关键字段路径
                  "fallback_used": true, // 是否用过 fallback
                  "heuristic": false, // 是否含 heuristic
                  "evidence_class": "consensus" // 证据类型
                },
                "price_action_confirmation": {
                  "source_modules": ["technical"],
                  "field_paths": [
                    "technical.trend",
                    "technical.technical_signals",
                    "technical.fear_greed"
                  ],
                  "fallback_used": false,
                  "heuristic": true,
                  "evidence_class": "heuristic"
                },
                "evidence_strength": {
                  "source_modules": [
                    "technical",
                    "research_report",
                    "report_rc",
                    "earnings",
                    "catalysts",
                    "screen"
                  ],
                  "field_paths": [
                    "meta.modules",
                    "summary.research_strategy.expectations_vs_reported"
                  ],
                  "fallback_used": true,
                  "heuristic": true,
                  "evidence_class": "derived"
                }
              }
            }
          }
        }
      }
    ]
  },
  "err_msg": null
}
```

## 读法建议

- 先看 `summary.research_strategy`，这是当前最接近 FSP 研报组织方式的主视图
- 再看 `meta.provenance`，确认每个研究结论具体来自哪些模块、是否用了 fallback、是否包含 heuristic
- 需要完整原始记录时看 `report_rc.records` 或其他原始块
- 需要技术确认细节时看 `technical`
- 不要再从 payload 里寻找 thesis、recommendation、price target 或 confidence，它们已经不属于公共 contract
