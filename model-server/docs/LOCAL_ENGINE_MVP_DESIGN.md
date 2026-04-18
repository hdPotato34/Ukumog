# 本地推理人机引擎 MVP 设计文档

Last updated: `2026-04-18`

配套执行清单见：

- [LOCAL_ENGINE_MVP_EXECUTION_PLAN.md](C:\Fengru Cup\hd\model-server\docs\LOCAL_ENGINE_MVP_EXECUTION_PLAN.md)

## 1. 目标

为当前反五子棋项目增加一个 **可本地推理、可复盘分析、可后续训练调参** 的人机引擎 MVP。

本期目标同时满足三件事：

1. 玩家在复盘界面可以看到每一步落子后的局势评分，交互风格参考 lichess。
2. 玩家可以与引擎开启“正常房间风格”的人机对局，先不提供难度选择。
3. 推理默认发生在玩家本地，而不是游戏服务器端：
   - Electron 发行版：在本地 renderer 进程启动引擎
   - 自部署服务器版本：在访问网页的浏览器本地启动引擎
   - 线上网页版本：仅当用户选择“和机器对战”或打开复盘分析时，在当前网页启动引擎

同时保留后续演进空间：

- 本地先写好训练/调参代码
- 可把训练任务放到高性能 GPU 服务器上执行
- 训练完成后将参数包导回本地
- 本地推理继续使用同一套引擎接口和参数格式

---

## 2. 核心结论

MVP 采用：

**战术规则过滤 + 迭代加深 Alpha-Beta（Negamax）搜索 + 参数化静态评估**

这是当前阶段在三者之间最平衡的方案：

- 实现复杂度可控
- 不依赖神经网络即可达到可用棋力
- 能直接复用现有规则层
- 可在浏览器和 Electron 中本地运行
- 后续可通过训练优化评估参数与候选着排序，而不必推翻整体架构

---

## 3. 本期范围

### 3.1 做

- 本地推理引擎核心
- 浏览器/Electron 端本地 worker 调度
- 人机对局模式
- 复盘逐步分析与评估条
- 参数包加载与版本管理
- 最小训练/调参流水线

### 3.2 不做

- 多档难度切换
- 服务端集中式 AI 落子
- 多模型在线调度
- 云端复盘分析
- 完整神经网络策略/value 模型
- 完整 MLOps 平台

---

## 4. 产品形态与关键约束

## 4.1 人机对局的产品形态

MVP 中的人机对局应当 **复用在线房间的界面与交互感受**，但底层不走线上房间 API。

建议设计为：

- UI 层尽量复用现有 [game-ui.jsx](C:\Fengru Cup\hd\game-ui.jsx) 的房间视图
- 会话控制层新增一个“本地引擎房间 controller”
- 数据模型尽量复用现有 `room / game / record` 概念
- 但房间状态、AI 决策、分析结果均在本地内存中维护

原因：

- 能满足“服务器版也在用户本地启动引擎”的要求
- 避免把 AI 计算成本放到服务器
- 不需要新增服务端鉴权、超时、幂等等复杂链路
- 后续仍可继续沿用现有 record 存档与复盘能力

### 4.2 复盘分析的产品形态

复盘界面增加：

- 局势评估条
- 当前节点评分
- 主变化（PV）展示
- 每步落子的分析缓存
- 后台渐进式分析

用户打开复盘后：

1. 前端加载 record
2. 本地启动分析 worker
3. 先分析当前节点
4. 再沿主线逐步补全每一步的评分
5. UI 随分析结果逐步更新，不阻塞用户操作

### 4.3 评分表现形式

参考 lichess，但适配本项目：

- 若存在强制胜负：显示 `#n`
  - `#3` 表示当前评估视角下预计 3 个己方回合内强制取胜
  - `#-2` 表示当前评估视角下预计 2 个对手回合内强制失败
- 若不存在短杀：显示数值评分
  - 建议内部用整数 `score`
  - UI 映射为评估条和数值标签

评分统一以“当前分析视角方更优”为正值。

---

## 5. 总体架构

## 5.1 模块划分

建议拆成四层：

### A. 规则层

复用现有 [game-core.mjs](C:\Fengru Cup\hd\game-core.mjs)：

- `createMatchState`
- `applyMove`
- 终局检测
- 计时逻辑

新增一个 engine 适配层，专门给搜索使用：

- 合法手枚举
- 快速局面复制
- 终局快速判断
- 局面哈希

### B. 引擎核心层

纯逻辑、无 UI、可同时运行于浏览器与 Node：

- 战术规则过滤
- 候选着生成
- Negamax / Alpha-Beta 搜索
- 静态评估
- 主变化提取
- 节点统计
- 可中断搜索

### C. 运行时层

负责把引擎放进本地 worker 中运行：

- 浏览器：Web Worker
- Electron：仍优先复用 Web Worker
- Node/CLI：可选 worker thread 或直接同步调用

### D. 训练与参数层

负责离线生成与优化参数包：

- 数据同步
- 特征提取
- 评估权重调优
- 战术题评测
- 导出参数包

---

## 6. 运行时设计

## 6.1 为什么必须本地 worker 化

引擎搜索会消耗较多 CPU 时间。

如果直接在 React 主线程中搜索，会导致：

- 棋盘卡顿
- 输入掉帧
- 复盘切步不流畅

因此必须放入 worker：

- 人机对局的 AI 思考在 worker 中进行
- 复盘分析也在 worker 中进行
- UI 主线程只负责发请求、接结果、渲染状态

## 6.2 启动策略

遵循“按需启动”：

- 普通大厅、资料页、纯在线对局：不启动引擎
- 本地练习：默认不启动引擎
- 人机对局：进入房间时启动引擎 worker
- 复盘分析：进入 review 页面时启动分析 worker

## 6.3 统一消息接口

建议前后都使用同一套消息协议：

### `init`

加载参数包与运行时配置。

### `searchMove`

请求 AI 为当前局面搜索下一步。

### `analyzePosition`

请求对某一局面做定额分析，返回分数、PV、深度、节点数。

### `analyzeRecord`

批量分析一条 record 的多个节点，用于复盘逐步补全结果。

### `cancel`

取消当前搜索或分析。

---

## 7. MVP 引擎算法设计

## 7.1 搜索主干

主搜索使用：

- `iterative deepening`
- `negamax`
- `alpha-beta pruning`

建议搜索流程：

1. 生成候选着
2. 战术过滤与排序
3. 从浅层到深层迭代加深
4. 每层维护当前最好着法与 PV
5. 到达时间预算即返回最近一层完整结果

这样做的优点：

- 随时可中断
- 更适合浏览器环境
- 可以渐进输出更稳定的最佳着

## 7.2 战术规则过滤

这是 MVP 强度的关键。

每轮搜索前先做战术层判断：

1. 若存在“立即赢”的合法着，直接优先
2. 若某着会“立即自杀”，直接剔除或强惩罚
3. 若对手存在“立即赢”威胁，优先搜索唯一或少量防守着
4. 对明显无关的远点大幅降权或剔除

这里要特别注意反五子棋特性：

- 成五为胜
- 成四为负

因此“看起来连子更多”未必更好，必须始终以规则层裁决为准。

## 7.3 候选着生成

MVP 不建议全盘展开。

建议候选着来源：

- 上一步附近
- 已有棋串附近
- 能形成或破坏关键威胁的位置
- 开局可加入中心优先

建议控制在：

- 常规局面：`8 ~ 16` 个候选着
- 战术局面：允许扩到 `20 ~ 24`

## 7.4 静态评估函数

评估函数先用参数化人工特征，不依赖神经网络。

建议至少包含以下特征：

- 当前方是否存在立即赢手
- 对手是否存在立即赢手
- 当前方是否存在高风险“成四即死”诱因
- 当前方安全威胁数量
- 对手安全威胁数量
- 安全合法着数量
- 连型与断点威胁数量
- 局部中心控制
- 最近一步带来的先手压迫

评估函数输出一个整数分值：

- 越大表示当前分析方越优
- 特殊终局值需远高于普通静态特征值

## 7.5 搜索增强

MVP 建议做：

- move ordering
- transposition table
- repetition-safe hashing（如后续需要）
- timeout / abort 支持

MVP 可暂不做或后做：

- null-move pruning
- late move reductions
- aspiration windows
- quiescence search 的复杂版本

原因是本项目先追求稳定、正确、可调试。

---

## 8. 训练与参数策略

## 8.1 重要定位

MVP 的“训练”不是先训练一个完整神经网络引擎。

MVP 的训练目标是：

1. 优化静态评估函数权重
2. 优化候选着排序参数
3. 构建战术题集与回归评测集

也就是说：

- **搜索结构固定**
- **规则层固定**
- **通过训练改善参数**

## 8.2 为什么这条路线适合当前项目

- 推理必须在本地浏览器/Electron 运行，不能依赖 GPU
- JS/worker 中运行参数化评估器很轻量
- 训练可以在高性能 GPU 服务器上做，但推理只吃导出的参数包
- 后续若要接神经网络，也可以把参数包机制沿用下去

## 8.3 训练输入

建议训练数据来源分三类：

### A. 线上 finished games

来自项目已有对局记录。

用途：

- 学习局面优劣趋势
- 统计常见陷阱与开局分布

### B. 自博弈数据

由当前搜索引擎自我对局产生。

用途：

- 扩大数据规模
- 提升中后盘覆盖

### C. 战术题数据

人工或程序生成：

- 立即赢
- 避免自杀
- 唯一防守手
- 多候选陷阱手

用途：

- 做硬门禁
- 防止参数训练后“数值更平滑但战术变差”

## 8.4 训练方式

MVP 推荐两种低风险路线：

### 路线 1：监督式权重拟合

把局面特征抽出来，用结果标签或更深搜索标签拟合：

- logistic regression
- linear model
- 小型 MLP

优势：

- 简单
- 结果可解释
- 便于导出到本地参数包

### 路线 2：基于对战结果的参数搜索

例如：

- CMA-ES
- population based search
- 随机扰动 + arena 对战筛选

优势：

- 不需要显式 value 标签
- 更贴近真实胜率

MVP 建议先做：

**监督式权重拟合 + 小规模 arena 对战复验**

## 8.5 GPU 服务器的作用

虽然 MVP 推理不依赖 GPU，但训练端仍然建议统一用 PyTorch 风格流水线来写，原因是：

- 方便后续升级到小型神经网络评估器
- 训练代码在 CPU / GPU 都能运行
- 数据处理与参数导出流程更统一

训练端输出物应当是一个轻量参数包，而不是浏览器直接加载 `.pt` 文件。

---

## 9. 参数包设计

## 9.1 目标

参数包需要满足：

- 可版本化
- 可本地加载
- 可缓存
- 与运行时代码解耦
- 未来可从“纯权重”演进到“权重 + 小模型”

## 9.2 建议格式

建议先使用 `json` 或压缩后的 `json`：

```json
{
  "enginePackVersion": 1,
  "engineVersion": "ag-local-ab-20260418-r1",
  "search": {
    "defaultMoveTimeMs": 350,
    "maxDepth": 6,
    "candidateLimit": 16
  },
  "evaluation": {
    "weights": {
      "immediateWin": 1000000,
      "opponentImmediateWin": -1000000,
      "safeThreat": 240,
      "opponentSafeThreat": -250
    }
  },
  "featureFlags": {
    "useTranspositionTable": true
  }
}
```

后续如需更小体积，可升级为：

- 压缩 JSON
- 二进制权重数组

## 9.3 本地加载位置

建议打包进前端静态资源：

- `site/engine/engine-pack.json`

开发阶段：

- 源文件放在仓库可编辑目录
- 构建时复制到 `site/engine/`

---

## 10. 复盘分析设计

## 10.1 数据模型

当前 record 节点未存分析结果，可在本地 review session 中增加分析缓存层。

建议不要在第一期就修改导出格式 `AntiGomokuPGN/1`。

MVP 方案：

- record 原始结构不变
- 在前端 review session 中维护：
  - `analysisByNodeId`
  - `analysisStatusByNodeId`
- 仅本地缓存，不进入导出文本

后续如确有需要，再扩展为：

- 本地存档附带分析缓存
- 或新增 `AntiGomokuPGN/2`

## 10.2 单节点分析返回内容

建议格式：

```json
{
  "nodeId": "node-123",
  "depth": 6,
  "score": 184,
  "mate": null,
  "bestMove": { "row": 5, "col": 7, "notation": "H6" },
  "pv": ["H6", "G6", "J7"],
  "nodes": 18234,
  "timeMs": 322
}
```

## 10.3 UI 展示建议

复盘页增加：

- 左侧或右侧评估条
- 当前节点评分
- 最佳着与 PV
- 主线步列表中的评分标记

分析策略：

- 当前节点优先
- 用户切步时优先分析新节点
- 空闲时再回填其余节点

---

## 11. 人机对局设计

## 11.1 会话类型

建议新增一种本地会话类型：

- `engine-room`

它复用“在线房间式”的体验，但不依赖 `server.mjs` 的线上 room API。

建议包含：

- `mode: "engine"`
- `role: "host" | "guest"`
- `engineSide: "B" | "W"`
- `engineStatus: "idle" | "thinking" | "error"`
- `analysis`: 当前局面评分

## 11.2 落子流程

1. 玩家进入人机房间
2. 创建本地 match state
3. 若轮到 AI：
   - 向 worker 发送 `searchMove`
   - UI 展示 “Engine thinking...”
4. worker 返回着法
5. 主线程用规则层再次调用 `applyMove`
6. 更新棋盘、记录、当前局面分析

注意：

- 主线程必须做最终合法性校验
- worker 返回非法着时，应记录错误并走安全 fallback

## 11.3 Fallback

本地人机模式也需要 fallback：

- 超时：返回最近一层完成搜索的最佳着
- worker 异常：退回规则型安全着法
- 参数包加载失败：使用内置默认参数

---

## 12. 建议目录与文件

建议在后续实现中增加以下文件：

### 前端/运行时

- `engine/engine-core.mjs`
- `engine/engine-eval.mjs`
- `engine/engine-search.mjs`
- `engine/engine-tactics.mjs`
- `engine/engine-worker.mjs`
- `engine/engine-client.mjs`
- `engine/engine-pack.default.json`

### React 接入

- `engine-room.mjs`
- `review-analysis.mjs`

### 训练端

- `model-server/src/data_pipeline/`
- `model-server/src/training/`
- `model-server/src/evaluation/`
- `model-server/src/export/`
- `model-server/scripts/build-engine-dataset.py`
- `model-server/scripts/train-engine-weights.py`
- `model-server/scripts/eval-engine-pack.py`
- `model-server/scripts/export-engine-pack.py`

### 配置

- `model-server/configs/engine_train.template.yaml`
- `model-server/configs/engine_eval.template.yaml`

---

## 13. 与现有仓库的接入点

## 13.1 规则层

直接复用 [game-core.mjs](C:\Fengru Cup\hd\game-core.mjs)，保证裁判规则唯一。

## 13.2 复盘与记录

复用 [game-record.mjs](C:\Fengru Cup\hd\game-record.mjs) 的 record 树结构。

复盘分析先以“外部缓存”方式接入，不立即改 record 导出格式。

## 13.3 UI

主要接入点在：

- [anti-gomoku.jsx](C:\Fengru Cup\hd\anti-gomoku.jsx)
- [game-ui.jsx](C:\Fengru Cup\hd\game-ui.jsx)

其中：

- `anti-gomoku.jsx` 负责切换到人机房间与 review 分析模式
- `game-ui.jsx` 负责展示评估、PV、engine thinking 状态

## 13.4 构建

需要在 [scripts/build.mjs](C:\Fengru Cup\hd\scripts\build.mjs) 中加入 worker 与参数包的构建/复制逻辑。

---

## 14. 分阶段实施建议

## Phase 1：规则型本地引擎跑通

目标：

- 实现 worker
- 实现战术过滤
- 实现 Alpha-Beta 搜索
- 实现本地人机对局

交付标准：

- 用户可在本地与引擎完成整盘对局
- AI 能规避明显自杀着
- AI 能发现短手数立即赢

## Phase 2：复盘分析 UI

目标：

- 单节点分析
- 评估条
- PV 展示
- 主线逐步补分析

交付标准：

- 用户在复盘中可看到每步评分
- 切步不会卡死 UI

## Phase 3：参数化评估与训练流水线

目标：

- 抽取特征
- 建立训练脚本
- 导出参数包
- 本地加载训练后参数

交付标准：

- 训练机可产出新参数包
- 本地替换参数包即可提升评估器表现

## Phase 4：门禁与回归

目标：

- 建立战术题集
- 建立 arena 对战评测
- 建立参数包注册与回滚流程

交付标准：

- 参数包有可比较的胜率与战术指标
- 不会因“调参”破坏基础战术能力

---

## 15. 风险与对策

### 风险 1：浏览器中搜索过慢

对策：

- 候选着裁剪
- 迭代加深 + 时间预算
- worker 化
- 默认固定思考时长

### 风险 2：评估函数方向错，导致会搜不会判

对策：

- 强化战术过滤层
- 建立战术题硬门禁
- 用更深搜索结果做监督标签

### 风险 3：复盘分析拖慢页面

对策：

- 当前节点优先
- 分析任务队列化
- 空闲时补全
- 支持取消过期任务

### 风险 4：服务端与客户端规则不一致

对策：

- 始终复用 [game-core.mjs](C:\Fengru Cup\hd\game-core.mjs)
- 任何 AI 返回结果都要再次走 `applyMove`

---

## 16. 最终建议

当前最合适的 MVP 路线不是先做“训练型强 AI”，而是：

1. 先实现 **本地搜索引擎**
2. 再把 **复盘分析 UI** 接上
3. 最后通过 **离线训练/调参** 持续提升参数包

一句话总结：

**先把本地可运行、可分析、可替换参数的 Alpha-Beta 引擎做出来，再让训练服务器持续为它产出更好的参数包。**
