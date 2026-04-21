# Ukumog Engine 后端替换实现路径

Last updated: `2026-04-20`

## 1. 目标

在尽可能不改动现有前端页面、状态机和交互体验的前提下，用 `ukumog-engine` 替换当前前端内的偏 mock 本地引擎实现。

这里的“尽可能不改前端”具体指：

- 保留现有 React 页面结构和大部分状态流
- 保留 `EngineGameplayRunner` 的调度思路
- 保留 review 页面按节点调用 `analyzePosition` 的方式
- 保留前端最终用 `game-core.mjs` 做落子合法性和结果确认
- 只在“引擎客户端层”与少量能力开关上做必要修改

最终目标是把引擎能力迁到后端，同时让前端仍然消费一个接近现有 `LocalEngineClient` 的 Promise 风格接口。

---

## 2. 现状结论

## 2.1 当前前端真正依赖的不是 JS 搜索逻辑本身，而是它的调用契约

当前前端和引擎的耦合点主要只有两处：

- `anti-gomoku.jsx`
  - 通过 `EngineGameplayRunner` 触发 `searchMove`
  - 用返回的 `bestMove / pv / score / mate` 更新本地 engine-room 会话
- `game-ui.jsx`
  - review 页面通过 `LocalEngineClient.analyzePosition()` 获取单节点分析
  - 通过 `cancel()` 取消过期分析请求

真正被前端消费的引擎契约是：

- `init()`
- `searchMove({ state, config, timeBudgetMs, maxDepth })`
- `analyzePosition({ state, config, timeBudgetMs, maxDepth })`
- `cancel()`

返回值形态也已经比较固定：

```json
{
  "bestMove": { "row": 5, "col": 5 },
  "score": 356,
  "mate": null,
  "pv": [{ "row": 5, "col": 5 }, { "row": 4, "col": 4 }],
  "depth": 3,
  "nodes": 69,
  "timeMs": 53
}
```

因此，最稳的替换策略不是重写前端状态机，而是保住这个契约，替换其后端实现。

## 2.2 `ukumog-engine` 已经具备可直接复用的核心搜索能力

深挖结果：

- 已有完整规则引擎：
  - `Position`
  - `play_move()`
  - `classify_move()`
  - `brute_force_move_result()`
- 已有完整搜索入口：
  - `SearchEngine.search(position, max_depth, max_time_ms, max_nodes)`
- 已有完整战术分析层：
  - `analyze_tactics()`
  - `immediate_winning_moves()`
- 已有增量状态和 lookup eval：
  - `IncrementalState`
  - `eval_lookup`
- 已有结构化搜索结果：
  - `SearchResult`
  - `SearchStats`
  - `to_dict()`
- 已有可选 ML 混合能力，但不是本次替换的阻塞项

简单实测表明它已经能直接返回稳定搜索结果：

- 初始局面 depth=3 会返回中心点 `(5,5)`
- 有一步必胜时能直接命中
- 对手有一步制胜威胁时能返回唯一防点

说明它不是“规划中引擎”，而是已经具备服务化接入价值的现成引擎内核。

## 2.3 当前替换存在 4 个硬约束

### 约束 A：`ukumog-engine` 当前固定为 `11x11`

当前 Python 引擎写死：

- `BOARD_SIZE = 11`
- 特征编码、模型、测试、搜索都默认 `11x11`

而当前前端允许：

- `9 / 11 / 13 / 15`

这意味着第一阶段不能无条件替换全部前端 AI 能力。

建议：

- 第一阶段只支持 `11x11`
- 对非 `11x11`：
  - engine-room 入口置灰或提示“暂不支持”
  - review 分析显示 “Ukumog engine currently supports 11x11 only”

### 约束 B：当前环境与 `pyproject` 的 Python 版本要求不一致

`ukumog-engine/pyproject.toml` 要求：

- `requires-python = ">=3.11"`

当前工作区环境实际是：

- `Python 3.10.11`

虽然本地轻量搜索脚本目前能跑，但部署路径不应建立在“刚好能跑”的偶然兼容上。

建议：

- 后端服务环境统一冻结到 Python 3.11+

### 约束 C：`ukumog-engine` 原生返回格式与前端现有格式不完全一致

原生 `SearchResult.to_dict()` 产物更接近：

```json
{
  "best_move": 60,
  "best_move_coord": { "row": 5, "col": 5 },
  "score": 356,
  "principal_variation": [60, 48, 50],
  "depth": 3,
  "stats": { "...": "..." }
}
```

而前端当前期望：

- `bestMove`
- `mate`
- `pv` 为坐标对象数组
- `nodes`
- `timeMs`

所以必须有一层“结果标准化适配”。

### 约束 D：`ukumog-engine` 目前没有现成的 HTTP 服务层

它现在是一个 Python package + CLI，不是现成服务。

缺的部分包括：

- 请求/响应 schema
- JS `state` 到 `Position` 的转换
- 取消机制
- 超时保护
- 并发策略
- 健康检查与版本暴露

因此本次工作的核心不是“改搜索”，而是“做一层稳定服务化壳”。

---

## 3. 推荐目标架构

推荐采用三层结构：

```text
React / EngineClient
    -> Node server.mjs same-origin API
        -> Python ukomog service
            -> ukumog_engine adapter
                -> SearchEngine
```

即：

1. 前端仍然只依赖一个 `EngineClient`
2. `server.mjs` 增加同源引擎 API
3. Node 不直接实现搜索，只做代理/编排/限流
4. Python 服务内封装 `ukumog-engine`

这样做的原因：

- 前端改动最小
- 浏览器无跨域问题
- Electron、Web、自部署服务端都能走同一条入口
- Node 可以统一做认证、审计、限流和错误整形
- Python 引擎可独立演进，不把服务协议散落到 React 里

不推荐第一阶段直接让浏览器连 Python 服务，原因是：

- 需要新处理跨域和服务发现
- Electron/Web 路径会分叉
- 后续运维和灰度更难统一

---

## 4. 最小前端改动原则

## 4.1 前端冻结的部分

第一阶段建议明确不改这些东西：

- `EngineGameplayRunner` 的调度流程
- `engine-room` session 数据结构
- review 页面逐步分析的节奏
- `game-core.mjs` 的最终裁判权
- `game-record.mjs` 的记录格式

## 4.2 前端允许改的部分

第一阶段建议只改这些地方：

- 把 `LocalEngineClient` 改成“可配置 transport 的 EngineClient”
- 新增远端 transport，默认走 `/api/engine/*`
- 对 `boardSize !== 11` 做能力开关
- 在 engine/review UI 中显示后端不可用或不支持时的友好提示

换句话说：

- 页面和状态流基本不动
- 只替换“引擎怎么被调用”

---

## 5. 后端接口冻结建议

## 5.1 Node 对前端暴露的 API

建议新增：

- `POST /api/engine/init`
- `POST /api/engine/search`
- `POST /api/engine/analyze`
- `POST /api/engine/cancel`
- `GET /api/engine/health`

第一阶段如果想再简单一点，也可以先只做：

- `POST /api/engine/search`
- `POST /api/engine/analyze`
- `GET /api/engine/health`

并把 `cancel()` 在前端实现成 `AbortController` 级别的请求中断。

## 5.2 前端请求体建议

```json
{
  "state": {
    "board": [["B", null], [null, "W"]],
    "turn": "B",
    "result": null,
    "last": [5, 5]
  },
  "config": {
    "boardSize": 11,
    "baseSeconds": 180,
    "incrementSeconds": 2,
    "colorMode": "random"
  },
  "timeBudgetMs": 220,
  "maxDepth": 5
}
```

说明：

- Python 引擎不需要时钟本身，但保留现有调用字段可减少前端改动
- `config` 目前主要用于 `boardSize` 校验

## 5.3 Node/Python 返回体建议

统一成当前前端最容易消费的格式：

```json
{
  "bestMove": { "row": 5, "col": 5, "notation": "F6" },
  "score": 356,
  "mate": null,
  "pv": [
    { "row": 5, "col": 5, "notation": "F6" },
    { "row": 4, "col": 4, "notation": "E5" }
  ],
  "depth": 3,
  "nodes": 69,
  "timeMs": 53,
  "engineVersion": "ukumog-search-r1",
  "backend": "ukumog"
}
```

其中：

- `bestMove` 可为 `null`
- `mate` 若没有 forced mate 语义则为 `null`
- `pv` 永远返回对象数组，不把 int index 暴露给前端

## 5.4 Python 适配层需要负责的格式转换

需要新增一个 adapter 层，把：

- JS board matrix
- JS turn `"B" | "W"`

转成：

- `Position(black_bits, white_bits, side_to_move)`

并把：

- `best_move`
- `principal_variation`
- `stats.total_nodes`
- `stats.elapsed_seconds`

转回前端格式。

还需要额外补齐：

- `notation`
- `nodes`
- `timeMs`
- `mate`

`mate` 可按 `MATE_SCORE - ply` 的现有评分约定推导；若不准备在第一阶段暴露精确 mate ply，也可以先统一返回 `null`，只保留 `score`。

---

## 6. 推荐实现阶段

## Phase 0：冻结边界

目标：

- 先把“替换边界”冻结下来，避免一边接后端一边又改前端体验

输出：

- 明确第一阶段只支持 `11x11`
- 明确前端保留 `EngineGameplayRunner` / review 分析逻辑
- 明确返回契约以当前 `LocalEngineClient` 形态为准

验收：

- 团队对“只换引擎后端，不重做前端 AI 流程”达成一致

## Phase 1：做 Python 适配层，不先碰网络

目标：

- 先证明任意一个现有前端 `state` 都能映射到 `ukumog-engine` 并返回标准化结果

建议新增：

- `model-server/src/serving/ukumog_adapter.py`

核心职责：

- `frontend_state -> Position`
- `SearchResult -> frontend_analysis`
- board size 校验
- 非法状态报错整形

必做测试：

- 空棋盘能返回中心点
- 必胜局面返回 winning move
- 必防局面返回 forced block
- 非 `11x11` 返回明确错误
- 已终局局面不会进入搜索

验收：

- 纯 Python 层可稳定把输入/输出跑通

## Phase 2：把 Python adapter 包成服务

目标：

- 给 Node 代理层提供可调用的本地 HTTP 服务

建议新增：

- `model-server/src/serving/app.py`
- `model-server/src/serving/schemas.py`
- `model-server/src/serving/engine_pool.py`

建议最小能力：

- `/health`
- `/search`
- `/analyze`

建议：

- 服务内默认单进程起步
- 每次请求新建 `SearchEngine` 或使用受控对象池
- 第一阶段先不共享跨请求 TT

并发建议：

- 单请求同步搜索即可
- 若后续并发升高，再增加 worker 进程池

验收：

- 本地 curl 或脚本可调用并返回标准化结果

## Phase 3：Node server.mjs 增加引擎代理 API

目标：

- 让前端仍然只访问同源 `server.mjs`

建议在 `server.mjs` 新增：

- `handleEngineApi()`

建议路径：

- `POST /api/engine/search`
- `POST /api/engine/analyze`
- `GET /api/engine/health`

Node 侧职责：

- 基础鉴权
- 请求体校验
- 转发到 Python 服务
- 错误信息标准化
- 记录基础日志和耗时

第一阶段建议不要让 Node 直接重写任何搜索逻辑。

验收：

- 浏览器同源请求可拿到结果
- Python 服务挂掉时前端能收到明确错误

## Phase 4：替换前端 transport，但不改页面状态机

目标：

- 让前端“以为自己还在用旧引擎客户端”

建议做法：

1. 把 `LocalEngineClient` 重构成通用 `EngineClient`
2. 保留原 worker transport 作为 fallback 或开发选项
3. 新增 remote transport，默认调用：
   - `/api/engine/search`
   - `/api/engine/analyze`

最小改动点：

- `engine/engine-client.mjs`
- `game-ui.jsx`
- `anti-gomoku.jsx`

前端行为保持不变：

- engine-room 仍然本地维护 session
- review 仍然按节点发起分析
- `applyMove` 仍然在前端做最终裁判

验收：

- 页面行为与当前几乎一致
- 只是结果来源从 worker 变为后端

## Phase 5：先打通 engine-room，再打通 review

建议上线顺序不要反过来。

原因：

- engine-room 的调用链更短
- 输入就是当前局面
- 没有多节点分析队列
- 更容易验证“后端返回一步棋是否稳定”

建议顺序：

1. engine-room 先切到后端引擎
2. review 页面保留旧 worker 分析或暂时关闭
3. engine-room 稳定后，再把 review 分析切过去

review 切换时要额外处理：

- 过期请求取消
- 后台补分析队列
- 快速切步下的请求风暴

验收：

- engine-room 对局能完整走完
- review 分析能逐步回填且不阻塞切步

## Phase 6：补齐取消、超时和并发控制

如果第一阶段只是本地中断 fetch，而 Python 仍继续跑搜索，服务器负载会上升。

因此第二阶段应补：

- request id
- server-side cancel token
- Python 搜索中断
- Node 侧超时回收

建议协议：

- `search/analyze` 返回 `requestId`
- `cancel` 按 `requestId` 取消

如果想降低复杂度，也可以先做“每用户单活跃分析任务”：

- 新请求到来时，Node 标记旧任务过期
- Python 服务侧只保留最新任务

---

## 7. 建议目录落点

建议新增文件：

### Python 服务层

- `model-server/src/serving/app.py`
- `model-server/src/serving/ukumog_adapter.py`
- `model-server/src/serving/schemas.py`
- `model-server/src/serving/engine_pool.py`

### Node 代理层

- 直接修改 `server.mjs`

### 前端 transport 层

- `engine/engine-client.mjs`
- 可选新增 `engine/engine-remote-client.mjs`

### 文档与运维

- `model-server/README.md`
- `configs/` 下补服务配置模板

---

## 8. 关键兼容性决策

## 8.1 第一阶段只支持 `11x11`

这是最重要的冻结项。

不建议第一阶段为了兼容 `9/13/15` 去改 `ukumog-engine` 内核，原因是：

- 会扩大规则、掩码、特征、测试、模型四个面
- 会把“接服务”任务膨胀成“改引擎核心”

更稳的路径是：

1. 先用 `11x11` 跑通替换
2. 再评估是否把 Python 引擎泛化到可变棋盘

## 8.2 前端继续保留最终落子校验权

即使后端返回一步棋，前端仍然必须：

- 用 `applyMove()` 再走一次
- 非法则报错并 fallback

原因：

- 避免前后端规则漂移时直接把坏数据写进 UI 会话
- 减少线上出错面

## 8.3 第一阶段不引入 ML 模型作为上线阻塞项

当前 `ukumog-engine` 的 ML 能力可用，但不是接入主路径的阻塞条件。

第一阶段建议：

- 先用 pure search / search-first 版本上线
- 模型路径、权重、registry 留作第二阶段增强

这样风险最低。

---

## 9. 风险与对策

## 风险 1：review 页面会放大后端压力

原因：

- 当前 review 会同时有 focus 和 background 两个分析客户端
- 快速切步会造成频繁取消和重发

对策：

- 第一阶段限制后台分析并发
- 优先分析当前节点
- 背景分析串行化
- 增加服务端 cancel 或过期任务丢弃

## 风险 2：Electron 发行版的 Python 运行时分发

原因：

- 当前 Electron 只会带上 Node server
- 并没有打包 Python runtime 和 `ukumog-engine`

对策：

- 浏览器/开发版先打通
- Electron 打包单独做一阶段
- 评估方案：
  - 附带嵌入式 Python
  - Nuitka / PyInstaller 打成独立服务二进制
  - 安装时检测本机 Python 并提示

推荐：

- 不把 Electron 打包问题混进第一阶段功能替换里

## 风险 3：请求取消如果只停在前端，会浪费后端 CPU

对策：

- 第一阶段接受该限制
- 第二阶段补 server-side cancel

## 风险 4：后端服务与前端 `game-core` 规则漂移

对策：

- 把规则一致性测试列为上线前强制门槛
- 保留前端 `applyMove` 二次校验
- 增加跨实现对拍测试

---

## 10. 上线前最低验收清单

至少应满足：

1. `11x11` engine-room 可完成完整人机对局
2. 必胜、必防、避毒手三类局面都能稳定返回正确决策
3. review 页面当前节点分析稳定返回
4. 快速切步不会导致页面卡死
5. Python 服务不可用时前端能友好报错
6. 前端 `applyMove` 二次校验始终开启
7. Node 与 Python 服务都有健康检查

建议补的自动化验证：

- JS state -> Python Position 转换测试
- Python result -> 前端 analysis payload 转换测试
- `game-core.mjs` 与 `ukumog-engine` 的规则对拍测试
- `/api/engine/search` 集成测试
- `/api/engine/analyze` 集成测试

---

## 11. 推荐实施顺序

推荐顺序如下：

1. 先冻结范围：第一阶段仅支持 `11x11`
2. 先做 Python adapter，把输入输出标准化
3. 再做 Python HTTP 服务
4. 再在 `server.mjs` 增加同源代理
5. 再把前端 `EngineClient` 切到远端 transport
6. 先替换 engine-room
7. 稳定后替换 review 分析
8. 最后再做 cancel 优化、Electron 打包和 ML 接入

一句话总结：

**不要重做前端 AI 流程；要冻结现有前端引擎契约，把 `ukumog-engine` 包进后端服务，通过 Node 同源代理平滑接进来，并把第一阶段范围严格限制在 `11x11`。**
