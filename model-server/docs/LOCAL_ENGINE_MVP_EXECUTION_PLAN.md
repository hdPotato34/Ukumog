# 本地推理人机引擎 MVP 执行清单

Last updated: `2026-04-18`

## 1. MVP 冻结范围

本期只做 4 件事：

1. 本地可运行的搜索型引擎
2. 本地人机对局
3. 复盘单点分析与逐步补全评分
4. 训练后参数包可替换

本期明确不做：

- 多档难度
- 服务端 AI 落子
- 神经网络推理
- 云端分析
- 多模型调度
- 复杂搜索优化

---

## 2. 一期完成标准

满足以下条件即算 MVP 完成：

1. 用户可以在本地与 AI 下完整一盘棋。
2. AI 能识别“立即赢”和“明显自杀”。
3. 复盘页能显示当前节点评分、评估条和 PV。
4. 复盘页能逐步补齐主线各步评分，不阻塞切步。
5. 引擎参数可从外部参数包加载，替换后能生效。

---

## 3. 技术决策冻结

以下决策本期不再摇摆：

- 搜索算法：`iterative deepening + negamax + alpha-beta`
- 推理位置：用户本地
- 运行方式：`Web Worker`
- 规则来源：只复用 [game-core.mjs](C:\Fengru Cup\hd\game-core.mjs)
- 评估形式：参数化手工特征
- 复盘分析缓存：先放前端 session，不改 `AntiGomokuPGN/1`
- 人机模式：做本地 `engine-room`，不走线上房间 API

---

## 4. 开发顺序

严格按下面顺序做，避免同时铺太开。

### Phase 1：引擎核心跑通

目标：

- 可对任意局面返回一个合法着
- 支持时间预算
- 支持取消

### Phase 2：本地人机房间

目标：

- 玩家可与本地引擎完整对局
- UI 可见 engine thinking 状态

### Phase 3：复盘分析

目标：

- 当前节点分析
- 评估条
- PV
- 主线逐步补全评分

### Phase 4：参数包与训练骨架

目标：

- 参数包可导出、可加载、可替换
- 训练脚本能产出参数包雏形

---

## 5. 任务拆分

## WP-1 规则适配层

目标：

- 给搜索层提供稳定、纯净、无 UI 的规则接口

新增文件：

- `engine/rules-adapter.mjs`

任务：

- 封装局面复制
- 封装合法手枚举
- 封装落子模拟
- 封装终局判定
- 预留局面哈希接口

验收标准：

- 给定任意合法局面，能枚举合法手
- 枚举结果与 `applyMove` 一致
- 非法手不会被返回

## WP-2 战术过滤层

目标：

- 在正式搜索前做最重要的短手数筛选

新增文件：

- `engine/engine-tactics.mjs`

任务：

- 实现立即赢检测
- 实现立即自杀检测
- 实现对手立即赢威胁检测
- 实现防守着提取
- 输出候选着优先级

验收标准：

- 有立即赢时能优先返回立即赢着
- 明显自杀着不会排在前列
- 对手有一步制胜威胁时，候选集合能包含防守着

## WP-3 静态评估层

目标：

- 给搜索层提供可训练、可替换的评分函数

新增文件：

- `engine/engine-eval.mjs`
- `engine/engine-pack.default.json`

任务：

- 定义特征集合
- 定义权重读取逻辑
- 定义终局评分
- 定义数值评分到 UI 展示值的映射规则

验收标准：

- 同一局面重复评估结果稳定
- 更优局面通常得到更高分
- 参数包替换后评分会变化

## WP-4 搜索层

目标：

- 在预算时间内返回最佳着和 PV

新增文件：

- `engine/engine-search.mjs`

任务：

- 实现 negamax
- 实现 alpha-beta
- 实现 iterative deepening
- 实现 move ordering
- 实现基础 transposition table
- 实现 abort / timeout

验收标准：

- 返回结果始终合法
- 超时时能返回最近一层完整结果
- 返回包含 `bestMove / score / depth / pv / nodes / timeMs`

## WP-5 Worker 运行时

目标：

- 把引擎搬到后台线程

新增文件：

- `engine/engine-worker.mjs`
- `engine/engine-client.mjs`

任务：

- 定义 worker 消息协议
- 实现 `init`
- 实现 `searchMove`
- 实现 `analyzePosition`
- 实现 `cancel`
- 实现 worker 生命周期管理

验收标准：

- UI 主线程不阻塞
- 取消请求能终止旧分析
- worker 崩溃时能回退并重新初始化

## WP-6 本地人机房间

目标：

- 在不改线上房间协议的前提下完成本地 AI 对局

新增文件：

- `engine-room.mjs`

修改文件：

- [anti-gomoku.jsx](C:\Fengru Cup\hd\anti-gomoku.jsx)
- [game-ui.jsx](C:\Fengru Cup\hd\game-ui.jsx)

任务：

- 定义 `engine-room` session 结构
- 实现玩家落子 -> AI 思考 -> AI 落子闭环
- 增加 engine thinking 状态
- 增加 AI 对局入口
- 接入 record 保存

验收标准：

- 玩家可进入 AI 房间
- AI 可连续完成整局
- 结束后可复盘并保存记录

## WP-7 复盘分析

目标：

- 在 review 中显示每一步的分析结果

新增文件：

- `review-analysis.mjs`

修改文件：

- [anti-gomoku.jsx](C:\Fengru Cup\hd\anti-gomoku.jsx)
- [game-ui.jsx](C:\Fengru Cup\hd\game-ui.jsx)
- [game-record.mjs](C:\Fengru Cup\hd\game-record.mjs) `仅在必要时补 helper，不改格式`

任务：

- 增加当前节点分析状态
- 增加评估条组件
- 增加 PV 展示
- 增加主线逐步补分析
- 增加节点分析缓存

验收标准：

- 进入复盘后可看到当前节点评估
- 切步后分析结果会更新
- 主线评分会逐步补齐

## WP-8 构建与打包

目标：

- 把 worker 和参数包一起交付到前端产物

修改文件：

- [scripts/build.mjs](C:\Fengru Cup\hd\scripts\build.mjs)

任务：

- 构建 worker
- 复制默认参数包到 `site/engine/`
- 确认 Electron 与浏览器版本都能加载

验收标准：

- `npm run build:app` 后产物完整
- Electron 和浏览器开发模式都能启动引擎

## WP-9 训练骨架

目标：

- 建立最小可运行的参数训练与导出链路

新增文件：

- `model-server/scripts/build-engine-dataset.py`
- `model-server/scripts/train-engine-weights.py`
- `model-server/scripts/eval-engine-pack.py`
- `model-server/scripts/export-engine-pack.py`
- `model-server/configs/engine_train.template.yaml`
- `model-server/configs/engine_eval.template.yaml`

任务：

- 抽取局面特征
- 生成训练样本
- 训练线性权重或小型 MLP
- 导出参数包 JSON
- 跑最小评测

验收标准：

- 能从样本生成一个参数包
- 前端替换参数包后能成功加载

---

## 6. 每个工作包的输出格式

每完成一个工作包，都需要给出：

1. 改了哪些文件
2. 增加了什么能力
3. 怎么验证
4. 还剩什么风险

---

## 7. 第一周建议目标

第一周只做 `WP-1` 到 `WP-5`。

第一周完成标准：

- 已有可调用的 worker 引擎
- 已有立即赢 / 自杀过滤
- 已有基础 alpha-beta 搜索
- 已有默认参数包
- 已有 `searchMove` 和 `analyzePosition`

第一周明确不碰：

- 复盘 UI
- 训练脚本
- 复杂搜索增强

---

## 8. 第二周建议目标

第二周做 `WP-6` 和 `WP-7`。

第二周完成标准：

- 人机对局可玩
- 复盘可看评分
- 主线节点能逐步补分析

---

## 9. 第三周建议目标

第三周做 `WP-8` 和 `WP-9`。

第三周完成标准：

- 构建产物包含 worker 与参数包
- 训练脚本可生成参数包
- 本地能替换参数包验证生效

---

## 10. 最小测试清单

至少补这些测试或验证脚本：

- 规则适配：合法手枚举与 `applyMove` 一致
- 战术过滤：立即赢、立即自杀、唯一防守手
- 搜索：返回合法着、超时可返回
- worker：取消任务有效
- 人机对局：完整走完一盘
- 复盘分析：切步后评分正确刷新
- 参数包：替换后可加载

---

## 11. 现在就可以开工的第一批文件

第一批建议直接创建：

- `engine/rules-adapter.mjs`
- `engine/engine-tactics.mjs`
- `engine/engine-eval.mjs`
- `engine/engine-search.mjs`
- `engine/engine-worker.mjs`
- `engine/engine-client.mjs`
- `engine/engine-pack.default.json`

---

## 12. 一句话执行策略

**先把“本地 worker 里能稳定返回合法最佳着”做出来，再接 UI，再接训练。**
