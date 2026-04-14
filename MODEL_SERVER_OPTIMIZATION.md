# 模型端对接优化方案（服务端）

Last updated: `2026-04-14`

## 目标

为当前 `server.mjs` 提供一套可落地的模型端对接优化方案，重点解决：

- 在线对局时延与吞吐
- 模型调用稳定性（超时、重试、幂等）
- 房间状态同步效率
- 后续从轮询到推送的演进路径

---

## 当前现状（基于代码）

### 1) 通信模式

- 前端大厅轮询：`4000ms`
- 前端房间轮询：`1000ms`
- 当前是 `HTTP + polling`，无 WebSocket/SSE。

相关代码：

- `anti-gomoku.jsx` 中 `LOBBY_POLL_MS` 与 `ROOM_POLL_MS`
- `server.mjs` 中 `GET /api/rooms/:roomId` 返回房间快照

### 2) 快照策略

服务端 `snapshotFor` 每次返回较完整 payload（`gameState / game / requests / chatMessages / roomSummary`）。

这在加入模型端后会带来：

- 高并发下序列化开销偏高
- 网络重复传输较多
- 客户端 diff 成本增加

### 3) 计时器策略

每个活跃房间有自己的 `setInterval(1000ms)` 进行时钟推进。

当房间数增多时，定时器数量和上下文切换成本会上升。

### 4) 持久化策略

当前 `persistState` 采用整文件 JSON 写入队列。

优点是简单；缺点是写放大明显，不利于频繁状态更新场景。

---

## 优化总览（按优先级）

## P0：先做，收益最大

### P0-1. 引入版本号与条件拉取（低改造高收益）

在 room 增加：

- `stateVersion`（房间状态版本号，每次有效变更 +1）
- `snapshotHash`（可选，ETag 候选）

接口建议：

- `GET /api/rooms/:roomId?since=<version>`
- 如果无变化：返回 `304` 或 `{ unchanged: true, stateVersion }`
- 如果有变化：返回增量或完整快照

收益：

- 显著减少重复 payload
- 降低 CPU 序列化与网络带宽占用

### P0-2. 模型调用保护（timeout + fallback + 幂等）

新增内部调用抽象（服务端发起，不对外暴露）：

- `requestModelMove({ roomId, gameId, requestId, position, legalMoves, clockMs, config })`

必须具备：

- 超时控制（例如 `300~800ms`）
- 幂等键（`requestId`）
- 失败降级（规则引擎或安全随机合法步）
- 结果二次校验（必须再走 `applyMove`）

收益：

- 避免模型偶发超时导致房间卡死
- 网络抖动下不重复落子
- 保证服务端是最终裁决者

### P0-3. 统一模型回合触发点

在 `move` 成功后统一判断：

- 下一手是否为 AI
- 若是，进入模型请求流程
- 返回结果后再次广播 snapshot/delta

建议保持“同一房间单线程串行处理”语义，避免并发落子竞态。

---

## P1：中期演进

### P1-1. 从轮询切到 SSE（优先于 WebSocket）

建议先用 SSE：

- 服务器单向推送足够覆盖对局状态同步
- 代码改造量小于完整 WS 协议
- 可与现有 REST 写接口并存

可保留轮询作为降级通道。

### P1-2. snapshot 拆分为 snapshot + delta

事件类型建议：

- `move_applied`
- `clock_tick`
- `request_state_changed`
- `chat_appended`
- `game_finished`

客户端根据 `stateVersion` 重建状态；如果版本断档再拉完整 snapshot。

### P1-3. 推理缓存

key 建议：

- `positionHash + modelVersion + decodeParams`

用于：

- 复盘/观战重复局面
- 低温度策略下常见重复盘面

---

## P2：规模化与长期

### P2-1. 房间时钟统一调度器

将“每房间一个 interval”改成：

- 全局 tick（例如每 200ms 或 500ms）
- 扫描到期房间并推进时钟

可减少大量 interval 带来的调度开销。

### P2-2. 持久化升级

从整文件 JSON 演进到：

- SQLite（推荐）或 append-only 日志

收益：

- 降低写放大
- 更好的崩溃恢复和查询能力

### P2-3. 多进程/多实例准备

为后续横向扩展预留：

- room actor 路由（同房间请求进入同一执行单元）
- 外部缓存/消息总线（Redis）

---

## 建议的服务端模块边界

可在 `server.mjs` 基础上逐步拆分：

- `room-engine`：房间状态机与动作校验
- `model-gateway`：模型请求、超时、重试、幂等
- `state-sync`：snapshot/delta 组装与版本控制
- `clock-scheduler`：时钟推进

先抽函数，再抽文件，避免一次性重构风险。

---

## 对接模型端的最小接口草案

```json
POST /internal/model/move
{
  "requestId": "uuid",
  "roomId": "ABC123",
  "gameId": "uuid",
  "position": { "board": "...", "turn": "B" },
  "legalMoves": [[5,6],[5,7]],
  "clockMs": { "B": 182000, "W": 176000 },
  "config": { "boardSize": 11, "incrementSeconds": 3 },
  "deadlineMs": 600
}
```

返回：

```json
{
  "requestId": "uuid",
  "modelVersion": "ag-az-2026-04-14",
  "move": [5, 6],
  "latencyMs": 143
}
```

注意：

- 服务端收到后必须再做合法性校验
- 超时或非法落子都走 fallback

---

## 观测指标（上线前必须有）

- `room_snapshot_bytes_avg/p95`
- `room_poll_qps`（或 SSE 连接数）
- `model_latency_ms_p50/p95/p99`
- `model_timeout_rate`
- `fallback_rate`
- `move_end_to_end_latency`（用户提交到局面更新可见）
- `room_state_version_gap_rate`（客户端断档率）

---

## 推荐实施顺序（低风险）

1. 加 `stateVersion` + `since` 参数 + unchanged 返回
2. 上 `model-gateway`（timeout/幂等/fallback）
3. 在回合切换处接入 AI 落子触发
4. snapshot/delta 化
5. 迁移 SSE
6. 时钟调度器与持久化升级

---

## 非目标（本阶段不做）

- 一次性改造成完整微服务
- 立刻移除所有轮询
- 一次性替换全部持久化层

优先保证：**可用、可回滚、可观测**。
