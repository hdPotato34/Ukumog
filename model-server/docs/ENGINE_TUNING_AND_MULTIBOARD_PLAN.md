# 引擎深度 / 思考时间可调与多棋盘支持计划

Last updated: `2026-04-21`

## 1. 目标

在当前 `React -> RemoteEngineClient -> server.mjs -> model-server -> ukumog-engine` 主链路不回退的前提下，补齐三类能力：

1. engine-room 的搜索深度可调
2. engine-room / review 的思考时间可调
3. 远端引擎从当前 `11x11 only` 逐步扩展到多棋盘支持

这里需要先明确：

- “深度 / 思考时间可调”是已有请求参数的产品化和配置化
- “多棋盘支持”不是简单放开前端限制，而是一个会深入到 `ukumog-engine` 内核的中型改造

## 2. 当前逻辑盘点

## 2.1 深度和思考时间的参数链其实已经存在

当前链路里，`timeBudgetMs` 和 `maxDepth` 不是新概念，而是已经贯穿前后端：

- 前端客户端透传
  - `engine/engine-client.mjs`
  - `searchMove({ state, config, timeBudgetMs, maxDepth })`
  - `analyzePosition({ state, config, timeBudgetMs, maxDepth })`
- Node 代理校验并转发
  - `server.mjs`
  - `validateEngineRequestBody()` 要求两者都是正整数
- Python schema 接收
  - `model-server/src/serving/schemas.py`
  - `EngineRequest.timeBudgetMs`
  - `EngineRequest.maxDepth`
- Python adapter 真正下发到引擎
  - `model-server/src/serving/ukumog_adapter.py`
  - `engine.search(..., max_depth=request.maxDepth, max_time_ms=request.timeBudgetMs)`

结论：

- 参数通路已经打通
- 当前缺的不是协议层，而是“谁来决定这两个参数”和“用户如何修改它们”

## 2.2 当前真正的问题是前端调用值大多写死

### engine-room

`engine/engine-gameplay-runner.mjs` 当前仍然使用固定策略：

- 有时钟对局：固定 `GAMEPLAY_TIMED_SEARCH_BUDGET_MS`
- 无时钟对局：固定 `GAMEPLAY_UNTIMED_SEARCH_BUDGET_MS`
- 搜索深度：固定 `GAMEPLAY_SEARCH_MAX_DEPTH`

也就是说：

- engine-room 已经能传 `timeBudgetMs / maxDepth`
- 但实际取值来自代码常量，而不是用户配置

### review

`game-ui.jsx` 里 review 分析也还是硬编码：

- 当前节点 focus 分析：`timeBudgetMs: 220`，`maxDepth: 5`
- 后台预取 background 分析：`timeBudgetMs: 140`，`maxDepth: 4`

这意味着：

- review 现在已经能用远端参数
- 但没有任何 UI 或状态层让用户调整

## 2.3 当前配置模型里没有“引擎参数位”

当前大厅和开局配置主要走：

- `game-core.mjs`
  - `DEFAULT_MATCH_CONFIG`
  - `sanitizeConfig()`
- `hub-ui.jsx`
  - `MatchConfigFields`

但现在的配置只有：

- `boardSize`
- `baseSeconds`
- `incrementSeconds`
- `colorMode`

没有：

- `engineMaxDepth`
- `engineTimeBudgetMs`
- `reviewMaxDepth`
- `reviewTimeBudgetMs`

所以如果要加这个功能，不能只在某个按钮旁边塞两个输入框，必须先决定“引擎配置放在哪一层”。

## 2.4 当前多棋盘支持是被前后端双层硬限制住的

### 前端限制

- `anti-gomoku.jsx`
  - `handleStartEngine()` 直接拒绝非 `11x11`
- `hub-ui.jsx`
  - `CreateRoomModal` 中 “Player vs hd” 按钮只有 `11x11` 可用
- `game-ui.jsx`
  - review 远端分析仅在 `record.config.boardSize === 11` 时启用

### Node 限制

- `server.mjs`
  - `validateEngineRequestBody()` 中直接要求 `boardSize === SUPPORTED_ENGINE_BOARD_SIZE`

### Python 服务限制

- `model-server/src/serving/schemas.py`
  - `EngineState.validate_shape()` 直接要求棋盘是 `11 x 11`
- `model-server/src/serving/ukumog_adapter.py`
  - `frontend_state_to_position()` 直接拒绝非 `11x11`

## 2.5 `ukumog-engine` 内核本身也大量绑定 `11x11`

这一步最关键。当前仓库里并不是只有接入层写死了 `11x11`，引擎本体也有大量尺寸耦合：

- `ukumog-engine/ukumog_engine/board.py`
  - `BOARD_SIZE = 11`
- `ukumog-engine/ukumog_engine/position.py`
  - `Position.from_rows()` 按固定 `BOARD_SIZE` 校验
- `ukumog-engine/ukumog_engine/search.py`
  - 多处直接使用 `BOARD_SIZE`
- `ukumog-engine/ukumog_engine/tactics.py`
  - 中心点和相关逻辑使用 `BOARD_SIZE`
- `ukumog-engine/ukumog_engine/ml/*`
  - 特征尺寸、模型尺寸、对称变换大量默认 `11`

结论：

- “支持不同棋盘”不能被当成接入层小改
- 它至少会影响：
  - board / position / search / tactics
  - adapter / schema / tests
  - 可能还会影响 ML 特征与模型路径

## 3. 设计决策建议

## 3.1 深度 / 思考时间不要直接塞进通用对局配置

当前 `createConfig` 同时服务于：

- 在线房间
- 本地练习
- 本地人机

如果把引擎参数直接并入通用 `config`，会带来几个问题：

- 在线房间也会带上与服务端房间逻辑无关的字段
- 本地练习会携带完全无意义的引擎字段
- review 分析参数和 engine-room 对局参数不一定相同

建议：

- 保留当前 `MatchConfig` 只表示“棋局配置”
- 新增独立的“引擎设置”模型，例如：

```json
{
  "engineSettings": {
    "play": {
      "timeBudgetMs": 400,
      "maxDepth": 6
    },
    "reviewFocus": {
      "timeBudgetMs": 300,
      "maxDepth": 6
    },
    "reviewBackground": {
      "timeBudgetMs": 160,
      "maxDepth": 4
    }
  }
}
```

## 3.2 多棋盘支持要先做“能力发现”，不要再在前端硬编码 `11`

当前 UI 直接写死：

- “engine only supports 11x11”
- `boardSize === 11`

建议先把支持范围从“硬编码常量”改成“后端能力声明”，例如让 `/api/engine/health` 返回：

```json
{
  "ok": true,
  "backend": "ukumog",
  "engineVersion": "x.y.z",
  "pythonVersion": "3.11.x",
  "capabilities": {
    "supportedBoardSizes": [11],
    "timeBudgetMs": { "min": 50, "max": 5000 },
    "maxDepth": { "min": 1, "max": 12 }
  }
}
```

这样做的价值是：

- 在引擎仍然只支持 `11x11` 时，前端也不需要继续写死
- 将来扩到 `9 / 13 / 15` 时，前端不必再次做一轮分叉改造

## 3.3 多棋盘支持优先走 search-first，不把 ML 作为第一阶段阻塞项

当前 `ukumog-engine` 的 ML 侧尺寸耦合明显比纯搜索路径更重。

建议：

- 第一阶段多棋盘能力先保证：
  - 规则正确
  - 搜索可跑
  - 服务契约稳定
- 如果 ML 路径暂时只适用于 `11x11`，则：
  - 非 `11x11` 先切到 pure search / search-first
  - 不因为 ML 未泛化而阻塞多棋盘主链路

## 4. 分阶段计划

## WP-1 补齐深度 / 思考时间可调

状态：`已完成`

目标：

- 不改动远端协议形状
- 把当前硬编码的搜索参数变成用户可调配置

任务：

- [x] 新增前端引擎设置模型与默认值
  - 建议新建 `engine/engine-settings.mjs`
  - 提供：
    - `DEFAULT_ENGINE_SETTINGS`
    - `sanitizeEngineSettings()`
    - `clampTimeBudgetMs()`
    - `clampMaxDepth()`
- [x] 在 `anti-gomoku.jsx` 中为 engine-room 增加独立设置状态
  - 不并入 `DEFAULT_MATCH_CONFIG`
  - 在开始人机局时，把当前设置写入 `engineSession`
- [x] 在 `hub-ui.jsx` 的 `CreateRoomModal` 中增加 engine-only 设置区
  - 只对 “Player vs hd” 生效
  - 不影响在线房间 / 本地练习的配置结构
- [x] 在 `engine/engine-gameplay-runner.mjs` 中移除对固定搜索常量的依赖
  - 优先读取 `session.engineSettings.play`
  - 若不存在，再回退默认值
- [x] 在 `game-ui.jsx` 的 review 页增加分析参数设置
  - focus 分析参数可调
  - background 分析参数可调，且建议保留单独默认值
- [x] review 请求不再写死 `220/5` 与 `140/4`
- [x] 可选：把用户最近一次使用的引擎设置落到本地存储

验收：

- [x] engine-room 可以在 UI 中修改搜索深度和思考时间
- [x] review 可以在 UI 中修改分析深度和思考时间
- [x] 实际请求中的 `timeBudgetMs / maxDepth` 与 UI 选择一致
- [x] 默认行为与当前版本兼容，不配置时仍能稳定运行

测试：

- [ ] 前端设置 sanitize 测试
- [x] `engine-smoke` 增加“自定义参数仍能走通”的覆盖
- [ ] `engine-contract-smoke` 可增加“请求参数被真实消费”的 spot check

## WP-2 把棋盘支持从硬编码改成能力声明

状态：`已完成`

目标：

- 先去掉“前端手写 11x11 常量绑定”
- 让 UI 根据后端能力决定是否可用

任务：

- [x] 扩展 Python `/health` 返回 `capabilities`
- [x] Node `/api/engine/health` 原样透传该能力信息
- [x] 前端增加 engine capabilities 拉取与缓存
- [x] `CreateRoomModal` 不再用本地常量判断是否支持某尺寸
- [x] review 页是否可分析，改为依据 capabilities
- [x] 文案从“当前只支持 11x11”改为“当前引擎支持这些棋盘尺寸”

验收：

- [x] 在引擎仍只支持 `11x11` 时，UI 行为与现在一致
- [x] 当后端未来放开新尺寸时，前端无需再改一轮硬编码逻辑

## WP-3 评估并改造 `ukumog-engine` 为可变棋盘

状态：`进行中（search-first 首段已落地）`

目标：

- 让远端引擎真正支持 `9 / 11 / 13 / 15`

任务拆分：

- [~] 审计并改造核心尺寸常量传播路径
  - `board.py`
  - `position.py`
  - `search.py`
  - `tactics.py`
  - 相关辅助模块
- [x] 让 `Position` 和搜索入口明确携带 `board_size`
- [x] 让 adapter 按请求尺寸生成位置对象，而不是固定 `11`
- [x] 让 schema 校验“棋盘矩阵尺寸必须等于 `config.boardSize`”
- [x] 让 Node 端从“只允许 11”改成“校验是否在后端声明能力集合中”
- [ ] 重新审计中心点、坐标换算、PV 输出、notation、rules compare
- [ ] 决定非 `11x11` 下的 ML 策略
  - 方案 A：先禁用 ML，走纯搜索
  - 方案 B：补齐可变尺寸特征与模型

风险说明：

- 这不是单纯的服务层工作
- 这会影响引擎规则、搜索、评估、测试数据和可能的模型工件
- 如果不先分离 ML 依赖，工作量会继续膨胀

验收：

- [ ] `9 / 11 / 13 / 15` 都能通过基础 schema 校验
- [ ] engine-room 对支持尺寸都能开局并完成完整对局
- [ ] review 对支持尺寸都能稳定分析
- [ ] 非法尺寸返回明确错误

测试：

- [x] `model-server/tests/test_app.py` 增加多尺寸 case
- [x] `model-server/tests/test_ukumog_adapter.py` 增加多尺寸 case
- [x] `scripts/compare_rules.mjs` 扩展到多棋盘对拍
- [x] `scripts/engine-contract-smoke.mjs` 增加多棋盘 spot check
- [x] `scripts/review-smoke.mjs` 增加 `9x9` review 分析与分支 smoke

当前进展：

- 已打通 `9 / 11 / 13 / 15` 的后端 capabilities 声明
- 已让 Python adapter / Node proxy / contract smoke 接受多棋盘请求
- 已让 `ukumog-engine` 的 `Position / Search / Tactics` 主链路按请求尺寸运行
- 已新增 `9x9` 的 adapter / app / contract smoke 覆盖
- 已新增 `9x9` 的 engine-room smoke 覆盖，以及 `9 / 11 / 13 / 15` 的 rules compare 对拍
- 已新增 `9x9` 的 review smoke，覆盖 record 回放、主节点分析、后台节点分析、分支分析
- 仍未处理 ML 特征、模型输入输出、对称变换等 `11x11` 耦合模块

## 5. 推荐实施顺序

1. 先做 `WP-1`
   先把已有参数链真正开放给用户，这部分收益大、风险低
2. 再做 `WP-2`
   先把前端从“硬编码 11”升级为“能力驱动”
3. 最后做 `WP-3`
   真正改 `ukumog-engine` 内核，扩尺寸支持

## 6. 本轮明确不建议的做法

- 不建议为了做“深度 / 时间可调”去重构远端协议
- 不建议把引擎参数粗暴塞进通用房间配置，污染在线房间模型
- 不建议只放开前端棋盘按钮，而不改 Node / Python / `ukumog-engine`
- 不建议为了多棋盘支持先把旧 JS 引擎捡回来兜底

## 7. 一句话执行策略

**先把已经打通但仍写死的 `timeBudgetMs / maxDepth` 产品化，再把棋盘支持从“硬编码 11x11”升级为“能力发现 + 引擎内核改造”；不要把多棋盘问题误判成一个只改 UI 的小需求。**
