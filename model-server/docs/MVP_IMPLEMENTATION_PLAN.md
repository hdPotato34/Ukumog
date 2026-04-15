# Model Server MVP 实施规划（可直接开工）

Last updated: 2026-04-15

## 1) MVP 目标

在不影响现有线上对局稳定性的前提下，完成一个**可调用、可观测、可回退**的模型端最小闭环：

1. 训练端服务器可启动独立推理服务（HTTP）
2. 游戏服务端可通过内网调用该推理服务拿到落子
3. 推理失败可自动回退（不阻塞对局）
4. 具备最小日志与评估产物落盘能力

---

## 2) MVP 范围（做 / 不做）

### 做
- 单模型在线推理接口（先不做多模型动态调度）
- 单机部署（3090 训练机）
- 游戏服 -> 模型服内网 HTTP 调用
- timeout / 幂等 requestId / fallback
- 最小数据同步与离线评估脚本

### 不做
- 复杂分布式训练调度
- 多实例负载均衡
- WebSocket 推流改造
- 完整 MLOps 平台化

---

## 3) 目录与文件清单（按实现顺序）

## Phase A: 推理服务最小可用

1. `model-server/src/server.mjs`
   - 提供 `/health`、`/v1/move`
   - 入参校验、requestId 记录、超时控制

2. `model-server/src/policy/mvp_policy.mjs`
   - 先实现 MVP 策略：
     - 优先立即赢（成五）
     - 避免立即自杀（成四）
     - 其余走轻量启发式/随机合法步

3. `model-server/src/rules/rules-adapter.mjs`
   - 复用主仓库规则（以 `game-core.mjs` 为准）
   - 提供：合法手枚举、applyMove 校验、终局检测

4. `model-server/configs/inference.mvp.json`
   - 超时、回退策略、日志级别

5. `model-server/scripts/run-model-server.sh`
   - 启动脚本（含环境变量示例）

## Phase B: 游戏服接入（最小侵入）

1. `server.mjs`（现有文件小改）
   - 新增模型网关调用函数（如 `requestModelMove`）
   - 在落子后判断是否轮到 AI，触发模型调用
   - 保留服务端最终合法性校验（仍由 `applyMove` 决定）

2. `configs/model_gateway.example.json`（可放根目录或 model-server/configs）
   - 模型服 URL、token、timeout、fallback 开关

## Phase C: 数据与评估最小闭环

1. `model-server/scripts/sync-games.sh`
   - 从线上导入 finished games 到 `data/raw/`

2. `model-server/scripts/build-dataset.py`（或 `.mjs`）
   - raw -> processed

3. `model-server/scripts/eval-mvp.py`（或 `.mjs`）
   - 跑固定局数对战，产出 `artifacts/eval/mvp_report.json`

---

## 4) API 约定（MVP）

## `POST /v1/move`

请求：

```json
{
  "requestId": "uuid",
  "gameId": "uuid",
  "position": {
    "board": [["B",null],[null,"W"]],
    "turn": "B",
    "lastMove": [5,6]
  },
  "config": {
    "boardSize": 11,
    "incrementSeconds": 3
  },
  "deadlineMs": 600
}
```

响应：

```json
{
  "requestId": "uuid",
  "move": [5,7],
  "modelVersion": "mvp-rule-20260415",
  "latencyMs": 42,
  "fallback": false
}
```

错误响应需明确可降级：

```json
{
  "type": "timeout_or_internal_error",
  "message": "..."
}
```

---

## 5) 配置与环境变量（MVP）

模型服：
- `MODEL_SERVER_PORT`（默认 19090）
- `MODEL_SERVER_HOST`（默认 0.0.0.0）
- `MODEL_SERVER_TOKEN`（内网调用鉴权）
- `MODEL_MOVE_TIMEOUT_MS`（默认 600）

游戏服（调用模型服）：
- `MODEL_GATEWAY_URL`
- `MODEL_GATEWAY_TOKEN`
- `MODEL_GATEWAY_TIMEOUT_MS`
- `MODEL_GATEWAY_ENABLED=true|false`

---

## 6) 验收标准（Definition of Done）

### DoD-A 推理服务
- `/health` 返回 200
- `/v1/move` 在 100 次请求内成功率 >= 99%
- 非法输入返回 4xx，不崩溃

### DoD-B 游戏服接入
- AI 对局可正常走子
- 模型服宕机时对局仍可继续（fallback 生效）
- 无“重复落子 / 非法落子”问题

### DoD-C 最小评估
- 产出 `artifacts/eval/mvp_report.json`
- 报告包含：胜率、平均时延、超时率、fallback 率

---

## 7) 风险与回滚

风险：
- 模型服超时导致回合卡住
- 模型返回非法落子
- 网络波动导致重复请求

措施：
- 统一 deadline + requestId
- 服务端二次合法性校验
- 失败立即 fallback
- 一键关闭模型网关：`MODEL_GATEWAY_ENABLED=false`

---

## 8) 里程碑（建议 5 天节奏）

- Day 1: 完成 Phase A（推理服务 + mvp_policy）
- Day 2: 完成 Phase B（游戏服接入 + fallback）
- Day 3: 联调与压测（1000 局模拟）
- Day 4: 完成 Phase C（最小数据同步 + 评估脚本）
- Day 5: 修复问题并冻结 MVP 版本

---

## 9) 下一步（MVP 后）

1. 用真实模型替换 `mvp_policy`
2. 接入 `registry/model_registry.json` 做候选/生产切换
3. 加入灰度发布与自动回滚
4. 推理缓存（positionHash + modelVersion）

---

## 10) 关键原则

**先把调用链跑通（可回退），再追求模型强度。**
