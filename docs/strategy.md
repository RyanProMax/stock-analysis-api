# 当前分析策略

更新时间：2026-03-28

## 结论先说

- 当前仓库没有接入 LLM 主观研判，也没有“读完研报后给投资结论”的自由发挥层
- 当前研报能力不是单纯把 Tushare 原样透传出去，而是：
  - 先按固定规则请求 Tushare
  - 再做确定性的排序、去重、状态判定、降级、提及过滤和结构化衍生
- 因此它属于“硬编码的数据策略与确定性分析”，不属于“主观研究分析”

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

### 当前请求的数据块

- 核心块：
  - `research_report`
  - `report_rc`
- 可选块：
  - `anns_d`
  - `news`
  - `major_news`

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

- 每个数据块都单独输出：
  - `items`
  - `source_meta`
- `source_meta` 固定包含：
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

- `research_report`：
  - 按 `trade_date desc, inst_csname asc, title asc`
  - 只做精确重复行去重
- `report_rc`：
  - 按 `report_date desc, quarter desc, org_name asc, report_title asc`
  - 只做精确重复行去重
- `anns_d`：
  - 按 `ann_date desc, rec_time desc, title asc`
- `news` / `major_news`：
  - 统一按发布时间倒序

#### 4. 可选块权限降级

- `anns_d` / `news` / `major_news` 当前可能被 Tushare 权限限制
- 这些块失败时不会直接让整条 item 失败
- 它们会在：
  - `capabilities`
  - `source_meta`
  中明确标记为 `permission_denied`

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
- 这是当前代码里的硬编码补救策略，目的是避免把“只有行业报告”误呈现成“个股研究为空”
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

## 当前哪些接口仍有“确定性分析”

### `/analysis/earnings/earnings`

- 当前只保留确定性字段
- 不再返回旧的 `analysis.research_strategy` 叙事结构
- 仍然会做固定规则下的字段归一、口径整理和分析块输出

### 估值与模型类接口

- `DCF` / `LBO` / `three-statement` 这类接口仍然包含模型计算
- 但它们的“分析”也是模型参数和公式驱动的确定性结果
- 不属于主观文本分析

## 当前策略的边界

- 如果 Tushare 原始接口没有数据，系统不会伪造数据
- 如果 Tushare 接口有权限限制，系统只会结构化降级
- 如果窗口内没有个股研报，系统最多回退到最近一批个股 `report_rc`
- 当前不会把别的数据源拼进来补成“看起来更完整”的结果

## 一句话定义

当前仓库的“分析策略”可以概括为：

`Tushare-first + 硬编码 workflow + 确定性衍生 + 无主观研判`
