# Daily Market Pack Implementation Plan

- [x] 1. 固化首批范围与 contract
  - 明确六项指标、截点、fallback、无持久化和非目标。
  - _Requirements: 1–8_

- [x] 2. 实现无状态 market-series provider
  - 新增 FRED、Yahoo、腾讯证券、东方财富读取适配。
  - 统一点位、截点和来源语义。
  - _Requirements: 2–6_

- [x] 3. 实现 daily market pack service 与 CLI
  - 聚合六项指标并输出严格 JSON。
  - 暴露 provider attempts、partial/failed 和机器字段。
  - _Requirements: 1–6_

- [x] 4. 更新 stock-analysis-skill 路由 contract
  - 增加“日报行情数据包”唯一主路由、标准命令和输出说明。
  - _Requirements: 1, 6_

- [x] 5. 接入 Stock Daily
  - 用一次性 API CLI 替换六项行情的 Node.js 外部直连。
  - 保留行业热度、新闻和现有页面 contract。
  - _Requirements: 7–8_

- [x] 6. 验证与交付
  - 运行 API、Skill、Stock Daily 的定向与完整测试。
  - 更新架构、计划和操作文档。
  - _Requirements: 1–8_

- [x] 7. 扩展中国主要指数覆盖
  - 新增深证成指、中证 500、创业板指和科创 50。
  - 同步 Stock Daily contract、数据与响应式行情矩阵。
  - _Requirements: 2, 3, 5, 7, 8_
