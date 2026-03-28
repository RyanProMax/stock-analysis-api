# 当前分析策略

更新时间：2026-03-28

## 结论先说

- 当前仓库没有接入 LLM 主观研判，也没有“读完研报后给投资结论”的自由发挥层
- 当前研报能力不是单纯把 Tushare 原样透传出去，而是：
  - 先按固定规则请求 Tushare
  - 再做确定性的排序、去重、状态判定、降级、提及过滤和结构化衍生
- 因此它属于“硬编码的数据策略与确定性分析”，不属于“主观研究分析”

## 带字段说明的真实返回示例

下面这段不是“抽象 schema”，而是用 `300827` 的真实返回结果改写成的带注释 `jsonc`。

- 真实调用命令：
  - `uv run python scripts/poll_research_snapshot.py --market cn --symbols 300827 --pretty`
- 说明：
  - 代码块使用 `jsonc`，是为了能在 JSON 里直接写注释
  - 注释不是实际接口输出的一部分

```jsonc
{
  "status": "partial", // 顶层状态；只要有 partial / failed / not_supported，顶层就不是 ok
  "computed_at": "2026-03-28T13:52:43.679568+00:00", // 本次快照生成时间
  "source": "tushare", // 当前命中的 provider；现在固定是 tushare
  "market": "cn", // 请求市场
  "strategy": "tushare_first_research_snapshot_v1", // 当前固定策略版本名
  "request": {
    "market": "cn",
    "symbols": [
      "300827" // 原始请求 symbol，保留用户输入顺序
    ],
    "start_date": "20260226", // 生效后的起始日期；默认是 end_date 往前 30 天
    "end_date": "20260328" // 生效后的结束日期
  },
  "items": [
    {
      "requested_symbol": "300827", // 当前 item 对应的请求 symbol
      "status": "partial", // 该 symbol 的状态
      "error": null, // item 级错误；这里只有在 failed / not_supported 等情况下才会填对象

      "info": {
        "common": {
          "ts_code": "300827.SZ", // 标准证券代码
          "name": "上能电气", // 证券简称
          "list_date": "20200410", // 上市日期
          "delist_date": null // 退市日期；仍上市时通常为 null
        },
        "cn_specific": {
          "symbol": "300827", // 不带市场后缀的原始股票代码
          "exchange": "SZSE", // 交易所
          "list_status": "L", // 上市状态；L 表示上市
          "area": "江苏", // 地域
          "industry": "电气设备", // 行业
          "market": "创业板" // 板块 / 市场口径
        },
        "us_specific": {
          "ts_code": null, // 预留给 US 的统一结构，CN 下保持 null
          "name": null,
          "enname": null,
          "classify": null,
          "list_date": null,
          "delist_date": null
        }
      },

      "research_report": {
        "records": [], // 券商研报列表 / 覆盖记录；这里为空
        "source": "tushare",
        "source_status": "empty", // 该块自己的状态，不等于 item 总状态
        "source_error": null,
        "attempted_sources": [
          "tushare"
        ],
        "skip_reason": "no_stock_specific_report_rc_in_requested_window", // 因请求窗口里没有个股 report_rc，所以跳过 research_report 查询
        "requested_start_date": "20260226",
        "requested_end_date": "20260328"
      },

      "report_rc": {
        "records": [
          {
            "ts_code": "300827.SZ",
            "name": "上能电气",
            "report_date": "20251105", // 预测发布日期
            "report_title": "上能电气：营收稳健增长，费用及汇兑短期扰动Q3利润",
            "report_type": "点评", // 个股报告类型；不是“非个股”
            "classify": "一般报告",
            "org_name": "华安证券",
            "author_name": "张志邦",
            "quarter": "2027Q4", // 预测对应季度
            "op_rt": 939300.0,
            "op_pr": null,
            "tp": 115800.0,
            "np": 104700.0, // 预测净利润
            "eps": 2.08, // 预测 EPS
            "pe": 16.81,
            "rd": null,
            "roe": 21.1,
            "ev_ebitda": 13.18,
            "rating": "买入",
            "max_price": null,
            "min_price": null
          }
          // 实际还有 2 条同标题同日期记录，分别对应 2026Q4 与 2025Q4
        ],
        "source": "tushare",
        "source_status": "ok",
        "source_error": null,
        "attempted_sources": [
          "tushare"
        ],
        "requested_start_date": "20260226", // 用户请求窗口
        "requested_end_date": "20260328",
        "resolved_start_date": "20251105", // 实际返回数据的日期窗口
        "resolved_end_date": "20251105",
        "fallback_mode": "latest_stock_specific_report_date" // 说明发生了“回退到最近个股 report_rc 日期”
      },

      "anns_d": {
        "records": [], // 上市公司公告流
        "source": "tushare",
        "source_status": "permission_denied",
        "source_error": "抱歉，您没有该接口访问权限。",
        "attempted_sources": [
          "tushare"
        ]
      },

      "news": {
        "records": [], // 通用新闻源中过滤后的新闻
        "source": "tushare",
        "source_status": "permission_denied",
        "source_error": "抱歉，您没有该接口访问权限。",
        "attempted_sources": [
          "tushare"
        ],
        "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)" // 本地提及过滤规则
      },

      "major_news": {
        "records": [], // 重点媒体 / 长新闻源中过滤后的新闻
        "source": "tushare",
        "source_status": "permission_denied",
        "source_error": "抱歉，您没有该接口访问权限。",
        "attempted_sources": [
          "tushare"
        ],
        "filter_rule": "title_or_content_contains_any(symbol, ts_code, name)"
      },

      "derived": {
        "coverage_snapshot": {
          "report_count": 0, // 来自 research_report.records 的数量
          "latest_trade_date": null, // 最新研报交易日期
          "institution_count": 0, // 研报覆盖机构数
          "report_type_distribution": {} // 研报类型分布
        },

        "estimate_snapshot": {
          "report_count": 3, // 来自 report_rc.records 的预测记录数
          "latest_report_date": "20251105", // 最新预测发布日期
          "latest_records": [
            {
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
            // 实际还有同批次 2 条记录
          ],
          "by_quarter": {
            "2027Q4": {
              "count": 1,
              "latest_report_date": "20251105",
              "rating_distribution": {
                "买入": 1
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
            "买入": 3
          }
        },

        "catalyst_timeline": [], // 公告 / news / major_news 合并后的事件流
        "change_flags": {
          "has_new_report_7d": false, // 最近 7 天是否有新 research_report
          "has_new_estimate_7d": false, // 最近 7 天是否有新 report_rc
          "has_new_catalyst_7d": false // 最近 7 天是否有新公告或新闻催化
        }
      }
    }
  ]
}
```

### 怎么读这个 JSON

- 先看 `status`
  - `ok` 代表全部 item 完整成功
  - `partial` 代表至少一个块降级了，但不一定没有核心数据
- 再看每个 block 的 `source_status`
  - 这是最直观的调试入口
  - 能区分是 `ok`、`empty`、`permission_denied` 还是 `error`
- 再看 block 的 `records`
  - 这里放的是原始 Tushare 行数组
  - 字段名尽量保持 Tushare 原样，不再额外包一层 `items`
- 最后看 `derived`
  - 这是程序做的确定性汇总视图
  - 如果只关心“有没有覆盖、最近日期、评级分布”，优先看这一层

## 总体原则

- 所有分析能力优先区分三层：
  - 原始事实
  - 确定性衍生
  - 主观判断
- 当前仓库只交付前两层，不交付第三层
- “分析”一词在当前项目里主要表示：
  - 固定 workflow 编排
  - 明确可复现的规则计算
  - 可追溯到原始数据的字段转换
- 当前不做：
  - thesis
  - narrative summary
  - rating 建议
  - target price
  - 事件重要性主观排序
  - 跨数据源语义融合

## Research Snapshot 策略

### 能力定位

- 入口：`scripts/poll_research_snapshot.py`
- 用途：内部 Agent / skill 调用
- 范围：当前只交付 `CN` 股票
- 输出：纯 JSON，不输出自由文本结论

### 数据源策略

- 当前只接一个 provider：`tushare`
- 代码结构保留多源 fallback 骨架，但当前不会命中第二数据源
- 各数据块独立调度，不做跨块联表拼接
- 各数据块命中首个可用源后立即停止

### 当前请求的数据块分别是什么

- `research_report`
  - 券商研报列表 / 覆盖记录，偏“研报正文索引”
- `report_rc`
  - 券商盈利预测与评级记录，偏“预测 / 评级快照”
- `anns_d`
  - 上市公司公告流
- `news`
  - 通用新闻源中命中股票提及过滤后的新闻
- `major_news`
  - 重点媒体 / 长新闻源中命中股票提及过滤后的新闻
- `derived`
  - 系统基于上述原始块做的确定性汇总，不是主观结论

### 当前“自有策略”具体做了什么

#### 1. 标的识别与身份结构

- 输入的 `symbol` 先解析成标准 `ts_code`
- 统一输出：
  - `info.common`
  - `info.cn_specific`
  - `info.us_specific`
- `CN` 当前只接受普通股票
- 命中 ETF / 基金时返回 `not_supported`

#### 2. 数据块级状态判定

- 每个数据块都直接输出：
  - `records`
  - `source`
  - `source_status`
  - `source_error`
  - `attempted_sources`
- `source_status` 固定枚举：
  - `ok`
  - `empty`
  - `permission_denied`
  - `not_supported`
  - `error`

#### 3. 排序与去重

- `research_report`
  - 按 `trade_date desc, inst_csname asc, title asc`
  - 只做精确重复行去重
- `report_rc`
  - 按 `report_date desc, quarter desc, org_name asc, report_title asc`
  - 只做精确重复行去重
- `anns_d`
  - 按 `ann_date desc, rec_time desc, title asc`
- `news` / `major_news`
  - 统一按发布时间倒序

#### 4. 可选块权限降级

- `anns_d` / `news` / `major_news` 当前可能被 Tushare 权限限制
- 这些块失败时不会直接让整条 item 失败
- 它们会在各自 block 顶层明确标记：
  - `source_status = permission_denied`
  - `source_error = ...`

#### 5. `news` / `major_news` 的确定性提及过滤

- 这两个接口不能直接按股票代码精准取数
- 当前固定做法是：
  - 先按固定来源拉取时间窗数据
  - 再在本地用“股票代码 / `ts_code` / 股票名命中 `title` 或 `content`”过滤
- 这一步是本项目自己的硬编码规则
- 但它仍然是确定性过滤，不是语义理解或主观归因

#### 6. `report_rc` 的个股回退策略

- `report_rc` 在某些窗口里可能只有 `report_type = 非个股` 的行业或主题报告
- 当前策略不会把这种窗口误当成“真正有个股研究覆盖”
- 如果请求窗口里只有 `非个股`，当前逻辑会：
  - 继续查询该股票历史 `report_rc`
  - 找到最近一个“个股研报日期”
  - 回退到该日期返回一组最新个股预测记录
- `report_rc` block 会直接标记：
  - `fallback_mode`
  - `requested_start_date`
  - `requested_end_date`
  - `resolved_start_date`
  - `resolved_end_date`
- `research_report` 在这种情况下会明确返回：
  - `source_status = empty`
  - `skip_reason = no_stock_specific_report_rc_in_requested_window`

#### 7. `derived` 确定性衍生

- `coverage_snapshot`
  - 统计研报数量
  - 统计最新日期
  - 统计机构数
  - 统计类型分布
- `estimate_snapshot`
  - 统计预测记录数
  - 统计最新预测日期
  - 输出最近一批预测记录
  - 按季度聚合
  - 统计评级分布
- `catalyst_timeline`
  - 合并公告、新闻、长新闻为统一事件流
- `change_flags`
  - 判断最近 7 天是否有新研报 / 新预测 / 新催化

这些都属于程序内的固定计算，不包含主观理解。

## 这是不是“只请求 Tushare 然后汇总”？

答案是：不完全是，但也不是主观分析系统。

更准确地说，当前能力是：

- 原始数据来源上：基本就是 Tushare-first
- 结果加工上：有一层我们自己的确定性 workflow
- 分析深度上：没有主观研究结论层

所以它介于两者之间：

- 不是“原始接口透传”
- 也不是“自主研究员式分析”

## 当前没有哪些“自己的分析”

- 没有对研报正文做观点抽取
- 没有把多份研报总结成 thesis
- 没有自己生成买入/卖出结论
- 没有自己算目标价
- 没有做机构观点冲突分析
- 没有做事件重要性评分
- 没有做跨源证据融合
- 没有用模型推断新闻与股价关系

## 当前策略的边界

- 如果 Tushare 原始接口没有数据，系统不会伪造数据
- 如果 Tushare 接口有权限限制，系统只会结构化降级
- 如果窗口内没有个股研报，系统最多回退到最近一批个股 `report_rc`
- 当前不会把别的数据源拼进来补成“看起来更完整”的结果

## 一句话定义

当前仓库的“分析策略”可以概括为：

`Tushare-first + 硬编码 workflow + 确定性衍生 + 无主观研判`
