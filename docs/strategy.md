# 当前分析策略

更新时间：2026-03-28

## 结论先说

- 当前仓库已经把 FSP 的客观能力统一收敛到单一入口：`POST /analysis/research/snapshot`
- 这个入口不是“单纯请求一个 Tushare API 然后透传”，而是：
  - 先解析 `market / symbols / modules / module_options`
  - 再按模块调度原始数据块、结构化分析块和模型块
  - 最后统一输出结构化、可追溯、严格客观的 payload
- 当前仍然**没有主观研究层**：
  - 没有 thesis
  - 没有 recommendation
  - 没有 confidence
  - 没有 target price 结论
  - 没有 moat / positioning / idea pitch / morning note

## 真实调用

下面示例使用 `300827`，并显式加载当前所有模块。

- 真实命令：

```bash
uv run python scripts/poll_research_snapshot.py \
  --market cn \
  --symbols 300827 \
  --modules research_report,report_rc,anns_d,news,major_news,earnings,earnings_preview,dcf,comps,three_statement,lbo,three_statement_scenarios,competitive,catalysts,model_update,sector_overview,screen \
  --module-options '{"screen":{"filters":{"pe_ratio":{"lte":20}}},"catalysts":{"horizon_days":30},"dcf":{"risk_free_rate":0.04},"three_statement":{"scenario":"base","projection_years":3}}' \
  --pretty
```

- 说明：
  - 代码块用 `jsonc`，是为了直接在 JSON 里写注释
  - 注释不是实际接口输出的一部分
  - 下面示例以这次 `300827` 的真实返回为底稿，只对重复结构做了少量压缩说明

## 带注释的完整示例

```jsonc
{
  "status": "partial", // 顶层状态：汇总所有 requested symbol 后得到；这里只请求了 1 个 symbol
  "computed_at": "2026-03-28T15:37:25.519245+00:00", // 本次快照生成时间（UTC）
  "source": "research_snapshot_dispatcher", // 统一调度器名，不是单个 provider 名
  "market": "cn", // 请求市场
  "strategy": "fsp_objective_research_snapshot_v1", // 当前统一 research snapshot 策略名

  "request": {
    "market": "cn", // 用户请求市场
    "symbols": [
      "300827" // 用户请求的原始 symbol，顶层顺序会保留到 items[]
    ],
    "start_date": "20260226", // 生效后的起始日期；不传时默认 end_date 往前 30 天
    "end_date": "20260328", // 生效后的结束日期
    "modules": [
      "research_report", // 券商研报列表 / 覆盖记录
      "report_rc", // 盈利预测与评级快照
      "anns_d", // 公告流
      "news", // 通用新闻提及过滤
      "major_news", // 重点媒体新闻提及过滤
      "earnings", // 财务 / 财报客观汇总
      "earnings_preview", // US-only 业绩前瞻模块；在 CN 下会返回 not_supported
      "dcf", // US-only DCF 模型
      "comps", // US-only 可比公司分析
      "three_statement", // US-only 三表预测
      "lbo", // US-only LBO 模型
      "three_statement_scenarios", // US-only 三表情景比较
      "competitive", // US-only 竞争格局
      "catalysts", // 事件日历 / 催化汇总
      "model_update", // 模型更新摘要
      "sector_overview", // US-only 行业概览
      "screen" // 量化筛选
    ],
    "module_options": {
      "screen": {
        "filters": {
          "pe_ratio": {
            "lte": 20 // 筛选条件：pe_ratio <= 20
          }
        }
      },
      "catalysts": {
        "horizon_days": 30 // 催化观察窗口
      },
      "dcf": {
        "risk_free_rate": 0.04 // DCF 参数；CN 下不会实际执行，只会原样记录到 request 和 model_update
      },
      "three_statement": {
        "scenario": "base", // 三表场景参数；CN 下不会实际执行
        "projection_years": 3 // 三表预测年数；CN 下不会实际执行
      }
    }
  },

  "items": [
    {
      "requested_symbol": "300827", // 当前 item 对应的请求 symbol
      "status": "partial", // 当前 symbol 的综合状态
      "error": null, // item 级错误；只有 failed / not_supported 等场景才会填对象

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
          "market": "创业板" // 板块 / 市场口径
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

      "research_report": {
        "records": [], // 原始记录数组；这里为空，表示当前窗口没有成功拿到券商研报正文索引
        "source": "tushare", // 实际 provider
        "source_status": "empty", // block 级状态：ok / empty / permission_denied / error / not_supported
        "source_error": null, // block 级错误文本
        "attempted_sources": [
          "tushare" // 本 block 的 source chain
        ],
        "skip_reason": "no_stock_specific_report_rc_in_requested_window", // 跳过原因：请求窗口里没有个股 report_rc，因此不查 research_report
        "requested_start_date": "20260226", // research_report 使用的原始请求窗口起点
        "requested_end_date": "20260328" // research_report 使用的原始请求窗口终点
      },

      "report_rc": {
        "records": [
          {
            "ts_code": "300827.SZ", // 标准证券代码
            "name": "上能电气", // 股票名称
            "report_date": "20251105", // 研报 / 预测发布日期
            "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润", // 报告标题
            "report_type": "点评", // 报告类型；这里是个股报告，不是“非个股”
            "classify": "一般报告", // 分类口径
            "org_name": "华安证券", // 机构名
            "author_name": "张志邦", // 作者
            "quarter": "2027Q4", // 预测对应季度
            "op_rt": 939300.0, // 营业收入预测值
            "op_pr": null, // 营业收入增速或相关扩展字段；源端为空时保留 null
            "tp": 115800.0, // 营业利润 / 税前利润类字段；保持源端命名
            "np": 104700.0, // 净利润预测值
            "eps": 2.08, // EPS 预测值
            "pe": 16.81, // 对应 PE
            "rd": null, // 研发费用相关字段；源端为空
            "roe": 21.1, // ROE 预测值
            "ev_ebitda": 13.18, // EV/EBITDA
            "rating": "买入", // 机构评级
            "max_price": null, // 价格区间上限；源端为空
            "min_price": null // 价格区间下限；源端为空
          },
          {
            // 第二条记录字段结构完全相同，只是 quarter / eps / pe / np 等值不同
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
            // 第三条记录字段结构完全相同，只是对应 2025Q4
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
        ],
        "source": "tushare",
        "source_status": "ok",
        "source_error": null,
        "attempted_sources": [
          "tushare"
        ],
        "requested_start_date": "20260226", // 用户请求窗口起点
        "requested_end_date": "20260328", // 用户请求窗口终点
        "resolved_start_date": "20251105", // 实际数据返回窗口起点；说明触发了回退
        "resolved_end_date": "20251105", // 实际数据返回窗口终点
        "fallback_mode": "latest_stock_specific_report_date" // 回退模式：请求窗口只有“非个股”时，回退到最近个股 report_rc 日期
      },

      "anns_d": {
        "records": [], // 公告记录数组；这里为空不是“没有公告”，而是无权限
        "source": "tushare",
        "source_status": "permission_denied", // 公告接口未开权限
        "source_error": "抱歉，您没有该接口访问权限。", // 源端原文
        "attempted_sources": [
          "tushare"
        ]
      },

      "news": {
        "records": [], // 新闻记录数组；这里为空是权限问题
        "source": "tushare",
        "source_status": "permission_denied",
        "source_error": "抱歉，您没有该接口访问权限。",
        "attempted_sources": [
          "tushare"
        ],
        "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)" // 本地提及过滤规则：标题或正文命中 symbol / ts_code / name 任一即可
      },

      "major_news": {
        "records": [], // 重点媒体新闻记录数组；这里也因权限为空
        "source": "tushare",
        "source_status": "permission_denied",
        "source_error": "抱歉，您没有该接口访问权限。",
        "attempted_sources": [
          "tushare"
        ],
        "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)" // 和 news 使用相同的本地过滤规则
      },

      "earnings": {
        "entity": {
          "symbol": "300827", // 标的代码
          "name": "上能电气", // 标的名称
          "market": "cn" // 模块内部的市场标识
        },
        "facts": {
          "reported": {
            "financial_report": {
              "report_date": null, // 财报期末日期；当前 provider 未补到
              "announcement_date": null, // 公告日期；当前 provider 未补到
              "revenue_growth_ratio": null, // 财报口径收入增速；当前 provider 未补到
              "roe": null // 财报口径 ROE；当前 provider 未补到
            },
            "dividend": {}, // 分红事实；当前为空
            "forecast_summary": "", // 业绩预告摘要；当前为空字符串
            "quick_report_summary": "" // 快报摘要；当前为空字符串
          },
          "consensus": {} // 当前 CN earnings 模块不提供 Street consensus，因此为空对象
        },
        "analysis": {
          "derived": {
            "fundamentals": {
              "market": "cn", // fundamental context 对应市场
              "status": "partial", // fundamental context 的整体状态
              "coverage": {
                "valuation": "ok", // 估值子能力覆盖可用
                "growth": "ok", // 成长子能力覆盖可用
                "earnings": "partial", // 财报子能力部分可用
                "institution": "partial", // 机构持仓子能力部分可用
                "capital_flow": "not_supported", // 资金流子能力未实现
                "dragon_tiger": "not_supported", // 龙虎榜子能力未实现
                "boards": "not_supported" // 板块子能力未实现
              },
              "source_chain": [
                {
                  "provider": "financial_provider", // 统一财务 provider 抽象层
                  "result": "ok",
                  "duration_ms": 0 // 当前调用耗时占位
                },
                {
                  "provider": "tushare.income", // Tushare 收益表相关源
                  "result": "ok",
                  "duration_ms": 0
                },
                {
                  "provider": "tushare.income",
                  "result": "ok",
                  "duration_ms": 0
                },
                {
                  "provider": "financial_provider",
                  "result": "partial",
                  "duration_ms": 0
                },
                {
                  "provider": "fundamental_pipeline", // 下面几条说明若干子能力当前未实现
                  "result": "not_supported",
                  "duration_ms": 0
                },
                {
                  "provider": "fundamental_pipeline",
                  "result": "not_supported",
                  "duration_ms": 0
                },
                {
                  "provider": "fundamental_pipeline",
                  "result": "not_supported",
                  "duration_ms": 0
                }
              ],
              "errors": [
                "not implemented", // capital_flow 的原因
                "not implemented", // dragon_tiger 的原因
                "not implemented" // boards 的原因
              ],
              "valuation": {
                "status": "ok",
                "coverage": {
                  "status": "ok" // valuation 子块自己的覆盖状态
                },
                "source_chain": [
                  {
                    "provider": "financial_provider",
                    "result": "ok",
                    "duration_ms": 0
                  }
                ],
                "errors": [],
                "data": {
                  "pe_ratio": 56.0584, // PE
                  "pb_ratio": 5.9187, // PB
                  "price": null // 当前价格；当前 provider 未补到
                }
              },
              "growth": {
                "status": "ok",
                "coverage": {
                  "status": "ok"
                },
                "source_chain": [
                  {
                    "provider": "tushare.income",
                    "result": "ok",
                    "duration_ms": 0
                  }
                ],
                "errors": [],
                "data": {
                  "revenue_yoy": 16.149949615964154, // 收入同比；当前数值来自 provider 结果，按源端口径保留
                  "roe": 13.5931, // ROE
                  "debt_to_assets": 73.009, // 资产负债率
                  "summary": "revenue_yoy=1614.99%" // 简短确定性摘要，不是主观分析
                }
              },
              "earnings": {
                "status": "partial",
                "coverage": {
                  "status": "partial"
                },
                "source_chain": [
                  {
                    "provider": "tushare.income",
                    "result": "ok",
                    "duration_ms": 0
                  }
                ],
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
                "coverage": {
                  "status": "partial"
                },
                "source_chain": [
                  {
                    "provider": "financial_provider",
                    "result": "partial",
                    "duration_ms": 0
                  }
                ],
                "errors": [],
                "data": {
                  "institution_holding_change": null, // 机构持仓变化
                  "top10_holder_change": null, // 前十大股东变化
                  "summary": "" // 简短摘要；当前为空
                }
              },
              "capital_flow": {
                "status": "not_supported",
                "coverage": {
                  "status": "not_supported"
                },
                "source_chain": [
                  {
                    "provider": "fundamental_pipeline",
                    "result": "not_supported",
                    "duration_ms": 0
                  }
                ],
                "errors": [
                  "not implemented"
                ],
                "data": {} // 未实现时返回空对象
              },
              "dragon_tiger": {
                "status": "not_supported",
                "coverage": {
                  "status": "not_supported"
                },
                "source_chain": [
                  {
                    "provider": "fundamental_pipeline",
                    "result": "not_supported",
                    "duration_ms": 0
                  }
                ],
                "errors": [
                  "not implemented"
                ],
                "data": {}
              },
              "boards": {
                "status": "not_supported",
                "coverage": {
                  "status": "not_supported"
                },
                "source_chain": [
                  {
                    "provider": "fundamental_pipeline",
                    "result": "not_supported",
                    "duration_ms": 0
                  }
                ],
                "errors": [
                  "not implemented"
                ],
                "data": {}
              }
            },
            "growth": {
              "revenue_yoy": 16.149949615964154, // 从 fundamentals.growth.data 摘出的便捷视图
              "roe": 13.5931,
              "debt_to_assets": 73.009,
              "summary": "revenue_yoy=1614.99%"
            },
            "valuation": {
              "pe_ratio": 56.0584, // 从 fundamentals.valuation.data 摘出的便捷视图
              "pb_ratio": 5.9187,
              "price": null
            },
            "coverage": {
              "valuation": "ok", // 便捷覆盖摘要
              "growth": "ok",
              "earnings": "partial",
              "institution": "partial",
              "capital_flow": "not_supported",
              "dragon_tiger": "not_supported",
              "boards": "not_supported"
            }
          }
        },
        "meta": {
          "as_of": null, // 当前模块没有明确 as_of
          "sources": [
            "Tushare" // 对外展示的模块来源
          ],
          "data_completeness": "partial", // 模块完整度
          "limitations": [
            "CN earnings module is limited by available provider financial coverage." // 模块局限性说明
          ],
          "schema_version": "2.0.0", // 统一结构化 schema 版本
          "interface_type": "mixed" // 模块接口类型：fact / mixed / model
        },
        "module_status": "partial", // 模块状态
        "module_error": null, // 模块错误文本
        "attempted_sources": [
          "Tushare" // 模块级 source chain
        ]
      },

      "earnings_preview": {
        "entity": {}, // 未执行时结构化模块仍返回空壳结构
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty", // 说明模块没有数据内容
          "limitations": [
            "Earnings preview is only supported for US market." // not_supported 的原因写在 limitations 里
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported", // 当前 market 不支持
        "module_error": "Earnings preview is only supported for US market.", // 模块级错误文本
        "attempted_sources": [
          "tushare" // 这里仍记录当前 market 的默认 source chain
        ]
      },

      "dcf": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "DCF is only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "DCF is only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "comps": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "Comps is only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "Comps is only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "three_statement": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "Three-statement is only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "Three-statement is only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "lbo": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "LBO is only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "LBO is only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "three_statement_scenarios": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "Three-statement scenarios are only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "Three-statement scenarios are only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "competitive": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "Competitive module is only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "Competitive module is only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "catalysts": {
        "entity": {
          "symbol": "300827", // 标的代码
          "name": "上能电气" // 标的名称
        },
        "facts": {
          "reported": {
            "events": [] // 合并后的事件数组；公告 / news / major_news 都没有可用记录时为空
          },
          "consensus": {}
        },
        "analysis": {
          "derived": {
            "event_type_distribution": {}, // 按事件类型统计
            "event_count": 0, // 事件数量
            "horizon_days": 30 // 透传 module_options.catalysts.horizon_days
          }
        },
        "meta": {
          "as_of": null,
          "sources": [
            "tushare"
          ],
          "data_completeness": "ok", // 这里是 ok，因为模块自身成功执行，只是结果为空
          "limitations": [],
          "schema_version": "2.0.0",
          "interface_type": "fact"
        },
        "module_status": "ok",
        "module_error": null,
        "attempted_sources": [
          "tushare"
        ]
      },

      "model_update": {
        "entity": {
          "symbol": "300827",
          "name": "上能电气"
        },
        "facts": {
          "reported": {
            "input_overrides": {
              "screen": {
                "filters": {
                  "pe_ratio": {
                    "lte": 20 // 本次请求的 screen 参数原样记录
                  }
                }
              },
              "catalysts": {
                "horizon_days": 30 // 本次请求的 catalysts 参数原样记录
              },
              "dcf": {
                "risk_free_rate": 0.04 // 即使未执行，也会记录本次输入覆盖
              },
              "three_statement": {
                "scenario": "base",
                "projection_years": 3
              }
            }
          },
          "consensus": {}
        },
        "analysis": {
          "derived": {
            "refreshed_modules": {
              "earnings": "partial" // 当前 model_update 实际刷新过的模块及其状态
            },
            "available_actuals": {
              "financial_report": {
                "report_date": null, // 当前可用的 earnings actuals 快照
                "announcement_date": null,
                "revenue_growth_ratio": null,
                "roe": null
              },
              "dividend": {},
              "forecast_summary": "",
              "quick_report_summary": ""
            }
          }
        },
        "meta": {
          "as_of": null,
          "sources": [
            "research_snapshot_dispatcher" // 这个模块是 dispatcher 内部汇总出来的
          ],
          "data_completeness": "partial",
          "limitations": [
            "Model update is a deterministic refresh summary, not a stored revision history."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "ok",
        "module_error": null,
        "attempted_sources": [
          "research_snapshot_dispatcher"
        ]
      },

      "sector_overview": {
        "entity": {},
        "facts": {},
        "analysis": {},
        "meta": {
          "as_of": null,
          "sources": [],
          "data_completeness": "empty",
          "limitations": [
            "Sector overview is only supported for US market."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "not_supported",
        "module_error": "Sector overview is only supported for US market.",
        "attempted_sources": [
          "tushare"
        ]
      },

      "screen": {
        "entity": {
          "symbol": "300827",
          "name": "上能电气"
        },
        "facts": {
          "reported": {
            "metrics": {
              "_source": "Tushare", // screen 使用的指标来源
              "pe_ratio": 56.0584, // PE
              "price_to_book": 5.9187, // PB
              "roe": 13.5931, // ROE
              "revenue_growth": 16.149949615964154, // 收入增长
              "debt_ratio": 73.009 // 负债率
            }
          },
          "consensus": {}
        },
        "analysis": {
          "derived": {
            "filters": {
              "pe_ratio": {
                "actual": 56.0584, // 实际值
                "condition": {
                  "lte": 20 // 用户传入条件
                },
                "passed": false // 是否通过
              }
            },
            "passed": false, // 所有筛选条件是否整体通过
            "filter_count": 1 // 本次条件数量
          }
        },
        "meta": {
          "as_of": null,
          "sources": [
            "Tushare"
          ],
          "data_completeness": "partial",
          "limitations": [
            "Screen evaluates only the requested symbols, not a full market universe."
          ],
          "schema_version": "2.0.0",
          "interface_type": "mixed"
        },
        "module_status": "ok",
        "module_error": null,
        "attempted_sources": [
          "Tushare"
        ]
      },

      "derived": {
        "coverage_snapshot": {
          "report_count": 0, // research_report.records 数量
          "latest_trade_date": null, // research_report 中最新 trade_date
          "institution_count": 0, // research_report 涉及的机构数
          "report_type_distribution": {} // research_report 的 report_type 分布
        },
        "estimate_snapshot": {
          "report_count": 3, // report_rc.records 数量
          "latest_report_date": "20251105", // 最新 report_rc 日期
          "latest_records": [
            {
              // 字段结构和 report_rc.records 中的单条记录完全一致
              "ts_code": "300827.SZ",
              "name": "上能电气",
              "report_date": "20251105",
              "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润",
              "report_type": "点评",
              "classify": "一般报告",
              "org_name": "华安证券",
              "author_name": "张志邦",
              "quarter": "2027Q4",
              "op_rt": 939300.0,
              "op_pr": null,
              "tp": 115800.0,
              "np": 104700.0,
              "eps": 2.08,
              "pe": 16.81,
              "rd": null,
              "roe": 21.1,
              "ev_ebitda": 13.18,
              "rating": "买入",
              "max_price": null,
              "min_price": null
            }
            // 其余 2 条 latest_records 结构相同，对应 2026Q4 / 2025Q4
          ],
          "by_quarter": {
            "2027Q4": {
              "count": 1, // 该季度记录数
              "latest_report_date": "20251105", // 该季度内最新 report_date
              "rating_distribution": {
                "买入": 1 // 该季度评级分布
              }
            },
            "2026Q4": {
              "count": 1,
              "latest_report_date": "20251105",
              "rating_distribution": {
                "买入": 1
              }
            },
            "2025Q4": {
              "count": 1,
              "latest_report_date": "20251105",
              "rating_distribution": {
                "买入": 1
              }
            }
          },
          "rating_distribution": {
            "买入": 3 // 全部 report_rc 的评级分布
          }
        },
        "catalyst_timeline": [], // 由 anns_d / news / major_news 合成的时间线；无权限时为空
        "change_flags": {
          "has_new_report_7d": false, // 最近 7 天是否有新的 research_report
          "has_new_estimate_7d": false, // 最近 7 天是否有新的 report_rc
          "has_new_catalyst_7d": false // 最近 7 天是否有新的公告 / 新闻催化
        }
      }
    }
  ]
}
```

## 怎么读这个 JSON

- 先看顶层 `status`
  - 这是对所有 `items[].status` 的汇总
  - `partial` 不代表所有模块都失败，只代表有模块降级或不支持
- 再看每个 block / module 自己的状态字段
  - 原始块看 `source_status`
  - 结构化模块看 `module_status`
- 再看 `info`
  - 这是统一身份层
  - 不管后面加载了哪些模块，这层都应该先看
- 最后看三类内容
  - 原始记录看 `research_report / report_rc / anns_d / news / major_news`
  - 结构化分析看 `earnings / catalysts / model_update / screen`
  - CN 的确定性汇总看 `derived`

## 当前这份示例说明了什么

- 当前系统确实有自己的客观策略层
  - 模块调度
  - fallback
  - 排序去重
  - source chain
  - partial / permission_denied / not_supported 状态表达
  - deterministic derived
- 但它仍然不是主观研究 agent
  - 没有 thesis
  - 没有 narrative summary
  - 没有投资建议
  - 没有目标价结论

接口 contract 以 [docs/api.md](/Users/ryan/projects/stock-analysis-api/docs/api.md) 为准，架构边界以 [docs/architecture.md](/Users/ryan/projects/stock-analysis-api/docs/architecture.md) 为准。
