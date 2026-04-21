# Ukumog Engine 后端替换任务清单

Last updated: `2026-04-20`

关联方案文档：

- `model-server/docs/UKUMOG_ENGINE_BACKEND_INTEGRATION_PATH.md`

## 1. 任务目标

把当前前端使用的本地 JS 引擎能力切换到后端 `ukumog-engine`，同时尽量不改前端页面、状态流和交互体验。

本任务清单默认采用以下冻结决策：

- 第一阶段只支持 `11x11`
- 前端继续保留 `EngineGameplayRunner`、review 分析流程和 `game-core.mjs` 的最终裁判权
- 通过同源 `server.mjs` 代理 Python 引擎服务
- 前端只替换引擎 transport，不重做页面状态机

---

## 2. 里程碑

### M0：范围冻结

完成标准：

- 团队确认第一阶段仅支持 `11x11`
- 团队确认前端保留现有引擎调用契约
- 团队确认采用 `Node API -> Python service -> ukumog-engine` 路线

### M1：Python 适配层跑通

完成标准：

- 能把前端 `state/config` 转成 `ukumog-engine.Position`
- 能把 `SearchResult` 转成前端当前可直接消费的结果结构
- 纯 Python 测试通过

### M2：Python 服务跑通

完成标准：

- 本地可调用 `/health` `/search` `/analyze`
- 可返回标准化分析结果
- 错误和不支持场景可稳定返回

### M3：Node 代理 API 跑通

完成标准：

- `server.mjs` 可同源代理 Python 服务
- 前端可通过 `/api/engine/*` 拿到结果
- Python 服务异常时前端能收到明确错误

### M4：engine-room 切换完成

完成标准：

- `11x11` 人机对局完整可玩
- 必胜、必防、避毒手场景正确
- 非 `11x11` 有明确限制提示

### M5：review 分析切换完成

完成标准：

- 当前节点分析可用
- 背景补分析可用
- 快速切步不阻塞 UI

### M6：稳定性和交付补齐

完成标准：

- 取消和超时策略明确
- 健康检查和日志可用
- Electron 路线有单独交付方案

---

## 3. 工作包拆分

## WP-0 范围冻结与对齐

目标：

- 把不再摇摆的决策冻结下来，避免实施过程中边做边改方向

任务：

- [ ] 确认第一阶段只支持 `11x11`
- [ ] 确认第一阶段不引入 ML 模型作为阻塞条件
- [ ] 确认前端保留 `EngineGameplayRunner`
- [ ] 确认前端保留 review 页面当前的分析交互模式
- [ ] 确认前端继续用 `applyMove()` 做最终校验
- [ ] 确认对外 API 走 `server.mjs` 同源代理
- [ ] 确认 Python 服务运行时目标为 `Python 3.11+`

输出物：

- 冻结后的决策记录
- 如有需要，补充到方案文档

验收：

- 不再存在“前端重做”或“浏览器直连 Python”这类未决路径

---

## WP-1 定义引擎请求/响应契约

目标：

- 明确前端、Node、Python 三层之间统一使用的数据结构

任务：

- [ ] 定义 `search` 请求体 schema
- [ ] 定义 `analyze` 请求体 schema
- [ ] 定义成功响应体 schema
- [ ] 定义错误响应体 schema
- [ ] 明确 `boardSize !== 11` 的错误码和消息
- [ ] 明确终局局面的返回策略
- [ ] 明确 `mate` 字段第一阶段是否始终返回 `null`
- [ ] 明确 `pv` 使用对象数组格式而不是 int index

建议文件：

- `model-server/src/serving/schemas.py`
- 文档可补充到 `model-server/README.md`

验收：

- 前后端都可按同一份契约实现

依赖：

- `WP-0`

---

## WP-2 实现 Python 状态适配层

目标：

- 把当前前端传来的 `state/config` 可靠映射为 `ukumog-engine` 可用输入

任务：

- [ ] 实现前端棋盘矩阵到 bitboard 的转换
- [ ] 实现 `"B" | "W"` 到 `Color.BLACK | Color.WHITE` 的转换
- [ ] 实现前端状态合法性校验
- [ ] 实现已终局状态的拒绝或短路处理
- [ ] 实现 `boardSize` 校验
- [ ] 实现 `SearchResult` 到前端分析结构的标准化
- [ ] 实现 `notation` 生成
- [ ] 实现 `nodes`、`timeMs` 字段填充
- [ ] 实现 `principal_variation` 到前端 `pv` 的转换

建议文件：

- `model-server/src/serving/ukumog_adapter.py`

验收：

- 给定一份前端 `state`，可稳定得到标准化结果

依赖：

- `WP-1`

---

## WP-3 编写 Python 适配层单元测试

目标：

- 确保适配层不是“看起来能跑”，而是覆盖关键边界

任务：

- [ ] 测试空棋盘能返回中心点
- [ ] 测试一步必胜局面返回 winning move
- [ ] 测试一步必防局面返回 forced block
- [ ] 测试 poison 场景不会返回明显毒手
- [ ] 测试非 `11x11` 返回明确错误
- [ ] 测试非法棋盘状态返回明确错误
- [ ] 测试终局局面不会继续搜索
- [ ] 测试 `pv`、`nodes`、`timeMs` 字段存在且格式正确

建议文件：

- `ukumog-engine/tests/` 下补适配相关测试，或
- `model-server/tests/` 新增服务适配层测试

验收：

- 适配层测试可独立运行并通过

依赖：

- `WP-2`

---

## WP-4 实现 Python 引擎 HTTP 服务

目标：

- 给 Node 提供一个稳定的本地引擎服务入口

任务：

- [ ] 新建 Python 服务入口
- [ ] 实现 `/health`
- [ ] 实现 `/search`
- [ ] 实现 `/analyze`
- [ ] 加入请求体校验
- [ ] 加入错误处理和统一返回格式
- [ ] 加入基础日志
- [ ] 暴露 `engineVersion`
- [ ] 明确第一阶段是否单进程单 worker

建议文件：

- `model-server/src/serving/app.py`
- `model-server/src/serving/engine_pool.py`

验收：

- 本地 HTTP 请求可稳定返回结果

依赖：

- `WP-2`
- `WP-3`

---

## WP-5 增加 Python 服务集成测试

目标：

- 验证服务层而不仅仅是适配层

任务：

- [ ] `/health` 正常返回
- [ ] `/search` 可返回合法 best move
- [ ] `/analyze` 可返回标准化 analysis payload
- [ ] 非法请求体返回 4xx
- [ ] 非 `11x11` 返回明确错误
- [ ] Python 引擎内部异常时返回 5xx 且不泄露脏堆栈

验收：

- 集成测试通过

依赖：

- `WP-4`

---

## WP-6 在 Node server.mjs 中新增引擎代理 API

目标：

- 保持前端同源访问，不让浏览器直接面对 Python 服务

任务：

- [ ] 在 `server.mjs` 增加 `handleEngineApi()` 或等价分支
- [ ] 新增 `GET /api/engine/health`
- [ ] 新增 `POST /api/engine/search`
- [ ] 新增 `POST /api/engine/analyze`
- [ ] 实现 Node 到 Python 服务的转发
- [ ] 增加超时控制
- [ ] 统一错误格式
- [ ] 增加最小日志与耗时统计

验收：

- 浏览器通过同源接口可调用引擎

依赖：

- `WP-4`
- `WP-5`

---

## WP-7 封装前端远端引擎 transport

目标：

- 保住前端现有 `LocalEngineClient` 风格接口，只替换其背后 transport

任务：

- [ ] 把当前 `engine-client.mjs` 抽象为可替换 transport
- [ ] 新增 remote transport
- [ ] remote transport 对接 `/api/engine/search`
- [ ] remote transport 对接 `/api/engine/analyze`
- [ ] remote transport 支持 `AbortController`
- [ ] 保留旧 worker transport 作为 fallback 或开发开关
- [ ] 明确初始化行为是否仍保留 `init()`

建议文件：

- `engine/engine-client.mjs`
- 可选 `engine/engine-remote-client.mjs`

验收：

- 前端业务层不需要知道底层是 worker 还是远端服务

依赖：

- `WP-6`

---

## WP-8 切换 engine-room 到后端引擎

目标：

- 在不重做 engine-room 状态机的前提下完成人机对局切换

任务：

- [ ] 让 `EngineGameplayRunner` 走新的 remote transport
- [ ] 保留前端 `applyMove()` 二次校验
- [ ] 对 `boardSize !== 11` 加入口限制
- [ ] 对后端不可用时增加友好提示
- [ ] 确保对局结束后存档和复盘不受影响
- [ ] 确保 thinking/error/idle 状态仍可正确展示

涉及文件：

- `anti-gomoku.jsx`
- `game-ui.jsx`
- `engine/engine-gameplay-runner.mjs`
- `engine-room.mjs`

验收：

- `11x11` 完整人机对局可玩

依赖：

- `WP-7`

---

## WP-9 增加 engine-room 回归验证

目标：

- 确认切换到后端后，核心玩法没有回归

任务：

- [ ] 空棋盘开局能正常启动
- [ ] 玩家先手、后手都能正常对局
- [ ] 必胜局面 AI 能直接收胜
- [ ] 必防局面 AI 能做防守
- [ ] AI 返回非法着时前端能报错并安全处理
- [ ] 一局结束后 record 可保存
- [ ] 保存后可正常进入 review

建议：

- 复用或新增 `scripts/engine-smoke.mjs`
- 补端到端 smoke 脚本

验收：

- 核心对局链路无回归

依赖：

- `WP-8`

---

## WP-10 切换 review 当前节点分析

目标：

- 先只切当前节点分析，不先做背景补分析优化

任务：

- [ ] review 页面 focus analysis 改走远端 transport
- [ ] 保持当前 analysis 卡片渲染逻辑不变
- [ ] 失败时保持现有 error 状态展示
- [ ] 切步时支持前端级别请求取消
- [ ] 确保 `formatAnalysisScore()` 等辅助函数不需要大改

涉及文件：

- `game-ui.jsx`
- `review-analysis.mjs`

验收：

- 当前节点分析可稳定显示

依赖：

- `WP-7`

---

## WP-11 切换 review 背景补分析

目标：

- 在 review 页面恢复当前已有的“当前节点优先，后台补主线”体验

任务：

- [ ] 背景分析客户端切到远端 transport
- [ ] 串行化背景分析请求
- [ ] 避免 focus/background 同时打爆后端
- [ ] 快速切步时正确取消过期请求
- [ ] 为后端不可用场景增加降级策略

验收：

- 主线分析可逐步回填
- 快速切步不明显卡顿

依赖：

- `WP-10`

---

## WP-12 增加跨实现规则对拍测试

目标：

- 确保前端 `game-core.mjs` 与 `ukumog-engine` 不会出现规则漂移

任务：

- [ ] 随机生成一批局面
- [ ] 对同一落子同时跑 `game-core.mjs.applyMove()` 和 `ukumog-engine.play_move()`
- [ ] 对比终局结果
- [ ] 对比毒手/必赢手关键场景
- [ ] 固化几组手工构造的边界局面

建议：

- 新增一个跨语言对拍脚本
- 或由 Node 驱动 Python 子进程完成对拍

验收：

- 关键规则对拍通过

依赖：

- `WP-2`

---

## WP-13 增加取消、超时和单活跃任务策略

目标：

- 控制 review 快速切步和多任务情况下的后端资源浪费

任务：

- [ ] 设计 request id
- [ ] 明确 Node 层的任务登记结构
- [ ] 明确 Python 层的取消策略
- [ ] 实现 `POST /api/engine/cancel` 或等价单活跃策略
- [ ] 增加超时兜底
- [ ] 增加取消场景日志

验收：

- 连续切步时后端不会持续堆积旧任务

依赖：

- `WP-10`
- `WP-11`

---

## WP-14 运维与配置补齐

目标：

- 让服务不只是“本地能跑”，而是具备基本可维护性

任务：

- [ ] 补 Python 服务启动说明
- [ ] 补服务配置模板
- [ ] 补本地开发启动方式
- [ ] 补健康检查说明
- [ ] 补错误定位说明
- [ ] 补日志字段说明
- [ ] 说明 Python 3.11+ 前置要求

建议文件：

- `model-server/README.md`
- `configs/` 下新增模板

验收：

- 新同学可以按文档把服务启动起来

依赖：

- `WP-4`
- `WP-6`

---

## WP-15 Electron 交付路线单列

目标：

- 不阻塞第一阶段功能替换，但尽早把桌面版风险显性化

任务：

- [ ] 评估是否随安装包分发 Python runtime
- [ ] 评估是否把 Python 服务打成独立二进制
- [ ] 评估 Electron 启动时如何拉起 Python 服务
- [ ] 评估打包体积和升级路径
- [ ] 产出桌面版专用实施建议

验收：

- Electron 路线不再是隐性风险

依赖：

- 无阻塞，可并行

---

## 4. 推荐执行顺序

建议严格按这个顺序推进：

1. `WP-0`
2. `WP-1`
3. `WP-2`
4. `WP-3`
5. `WP-4`
6. `WP-5`
7. `WP-6`
8. `WP-7`
9. `WP-8`
10. `WP-9`
11. `WP-10`
12. `WP-11`
13. `WP-12`
14. `WP-13`
15. `WP-14`
16. `WP-15`

---

## 5. 第一周建议范围

如果要控制节奏，第一周建议只做这些：

- [ ] `WP-0`
- [ ] `WP-1`
- [ ] `WP-2`
- [ ] `WP-3`
- [ ] `WP-4`
- [ ] `WP-5`

第一周结束标志：

- Python adapter 已完成
- Python 服务已完成
- `/health` `/search` `/analyze` 可本地调用
- 关键局面测试通过

---

## 6. 第二周建议范围

- [ ] `WP-6`
- [ ] `WP-7`
- [ ] `WP-8`
- [ ] `WP-9`

第二周结束标志：

- 前端 engine-room 已接到后端引擎
- `11x11` 人机对局可用

---

## 7. 第三周建议范围

- [ ] `WP-10`
- [ ] `WP-11`
- [ ] `WP-12`
- [ ] `WP-13`
- [ ] `WP-14`

第三周结束标志：

- review 分析切换完成
- 取消、超时、规则对拍、文档都补齐

---

## 8. 当前最推荐立刻开工的文件

如果现在就开始实现，建议第一批直接创建或修改：

- `model-server/src/serving/schemas.py`
- `model-server/src/serving/ukumog_adapter.py`
- `model-server/src/serving/app.py`
- `server.mjs`
- `engine/engine-client.mjs`

---

## 9. 一句话执行策略

**先把 Python 适配层和服务层做对，再让 Node 代理接进来，最后只替换前端 transport，不重做前端 AI 流程。**
