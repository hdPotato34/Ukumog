# Ukumog Engine 应用端续接任务清单

Last updated: `2026-04-21`

关联方案文档：

- `model-server/docs/UKUMOG_ENGINE_BACKEND_INTEGRATION_PATH.md`

## 1. 当前结论

应用端已经不该再围绕旧的本地 JS 引擎做续修了，当前唯一应该继续投入的主链路是：

`React -> RemoteEngineClient -> server.mjs -> model-server -> ukumog-engine`

这意味着：

- `ukumog-engine` 是唯一搜索与分析主实现
- 旧 opening 逻辑、opening book、worker 搜索链路已经退出运行主线
- 前端保留 `game-core.mjs` 作为 UI 状态推进和最终落子裁判层
- 第一阶段仍然只支持 `11x11`

## 2. 已完成基线

### 运行链路

- [x] Python 服务层已提供 `/health` `/search` `/analyze`
- [x] Node 同源代理 `/api/engine/*` 已接通
- [x] `RemoteEngineClient` 已成为应用侧统一引擎客户端
- [x] engine-room 已从开局第一手起走远端搜索
- [x] review 当前节点分析已走远端
- [x] review 背景补分析已走远端

### 稳定性与收口

- [x] engine-room 入口已收口到 `11x11`
- [x] 前端已避免 focus/background 无限制重复触发
- [x] Node 代理已补“同一 viewer 同一路由仅保留最新请求”的单活策略
- [x] 客户端断开、超时、被新请求顶掉这三类中断已分流

### 回归与校验

- [x] engine-room smoke 脚本已落地
- [x] JS `game-core.mjs` 与 Python `ukumog-engine` 规则对拍脚本已落地
- [x] 当前规则对拍已通过 271 个 case
- [x] `npm run build:app` 已通过

### 旧逻辑清退

- [x] 旧本地引擎主文件已移除出主线
- [x] `engine/opening-book.mjs` 已删除
- [x] `engine/engine-worker.mjs` 已删除
- [x] `engine/engine-search.mjs` 已删除
- [x] `engine/engine-eval.mjs` 已删除
- [x] `engine/engine-tactics.mjs` 已删除
- [x] `engine/rules-adapter.mjs` 已删除
- [x] 旧回归脚本与旧 MVP 文档已删除

## 3. 明确冻结的决定

以下决定本轮不再摇摆：

- [x] AI 运行时不再回退到旧 JS 搜索/worker/opening 逻辑
- [x] 应用端 AI 主实现只认 `ukumog-engine`
- [x] `game-core.mjs` 继续保留，不在这一轮整体替换成 Python 规则直连
- [x] 不在这一轮扩展 `9x9 / 13x13 / 15x15` 的 AI 支持
- [x] 不把 Electron 打包问题作为当前运行链路切换的前置阻塞

## 4. 现在还剩什么

### WP-1 交付文档补齐

状态：`已完成`

目标：

- 把“远端唯一主线”的真实状态写清楚
- 让新接手的人可以按文档直接启动联调

任务：

- [x] 更新 `model-server/README.md` 与相关说明，明确应用端已是 remote-only 主线
- [x] 补完整本地启动顺序：Node、Python、环境变量、端口关系
- [x] 明确 Python `3.11+` 是正式前置要求
- [x] 补常见故障说明：服务未起、超时、unsupported board size
- [x] 补 Docker 当前覆盖范围与未覆盖范围

验收：

- [x] 新接手同学按文档可独立跑起联调

### WP-2 Electron 交付路线单列

状态：`已完成`

目标：

- 不阻塞 Web/本地开发主线，但把桌面版交付风险显性化

任务：

- [x] 评估 Python runtime 随包分发方案
- [x] 评估独立二进制或服务伴随启动方案
- [x] 明确开发版与发行版的服务拉起差异
- [x] 输出单独的 Electron 交付说明或风险清单

验收：

- [x] Electron 不再是隐藏 TODO

### WP-3 可选的进一步一致性校验

状态：`已完成`

目标：

- 在已经完成规则对拍的基础上，继续补更高层的一致性信心

候选任务：

- [x] 对 `analyzePosition` 的返回结构做跨层契约检查
- [x] 对强制应手/战术提示增加更高层 spot check
- [x] 把规则对拍纳入更完整的 CI 或发布前检查

说明：

- 当前这部分不是切换主线的阻塞项
- 当前仓库已经提供 `npm run test:engine-preflight`，并接入 `.github/workflows/engine-checks.yml`

## 5. 推荐下一步顺序

1. 先按需要做 `WP-3`，继续补高层契约校验
2. 真正进入桌面交付时，按 `ELECTRON_ENGINE_DELIVERY_PLAN.md` 落实现
3. 保持远端 `ukumog-engine` 是唯一 AI 主线

## 6. 一句话执行策略

**不要再修旧开局逻辑，也不要再给旧 JS 引擎续命；从现在开始，应用端只围绕 `ukumog-engine` 这条远端主线继续收尾和交付。**
