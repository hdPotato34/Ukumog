# Electron 引擎交付路线说明

Last updated: `2026-04-21`

## 1. 结论先说

当前 Electron 桌面版已经能拉起内置 Node 服务，但**还不能自带拉起 `ukumog-engine` Python 服务**。

所以现在的真实状态是：

- Web / 本地浏览器联调：可用
- Docker 双服务部署：可用
- Electron 开发壳：只在你手动先启动 Python 引擎服务时可用 AI
- Electron 发行版：当前不具备完整 AI 能力交付条件

推荐交付路线：

1. 开发阶段继续允许“外部手动启动 Python 服务”
2. 发行阶段改为“随包分发独立引擎服务二进制”
3. Electron 主进程统一负责拉起：
   - `ukumog-engine-service`
   - 内置 `server.cjs`
4. Node 继续只做同源代理，不把搜索逻辑塞回桌面端 JS

## 2. 当前现状

### Electron 现在实际会做什么

`electron/main.cjs` 当前只会：

- 启动 `site/server.cjs` 或打包后的 `resources/server/server.cjs`
- 创建桌面窗口
- 退出时杀掉 Node 子进程

它**不会**：

- 启动 Python
- 检查 `/api/engine/health`
- 检查 `http://127.0.0.1:8011/health`
- 管理 `ukumog-engine` 生命周期

### 打包现在实际会带什么

`package.json` 当前 Electron 打包只额外带上：

- `site/server.cjs`

它**没有**带上：

- Python runtime
- `model-server/src/serving`
- `ukumog-engine`
- Python 依赖环境
- 任意可执行的 engine service binary

### 为什么桌面版 AI 现在会断

`server.mjs` 默认把引擎代理转发到：

```text
http://127.0.0.1:8011
```

但 Electron 当前只启动 Node，不启动该地址上的 Python 服务，所以：

- engine-room 的搜索请求会落到 `engine_unavailable`
- review 的分析请求也会落到 `engine_unavailable`

## 3. 开发版与发行版应如何区分

### 开发版

当前建议保留最小阻力路径：

- Electron 只负责拉起 Node
- 开发者手动启动 Python 引擎服务
- 通过本机 `127.0.0.1:8011` 联调

这条路径的优点：

- 最接近现在已经验证通过的 Web 联调链路
- 不会把 Electron 分发问题混入日常功能开发
- 出问题时更容易拆层排查

开发版启动方式应明确写成：

1. 手动启动 `model-server` FastAPI 服务
2. 再运行 `npm run desktop`

### 发行版

发行版不应该依赖用户本机先装 Python，也不应该要求用户手动起服务。

发行版需要做到：

- 安装后开箱即用
- 不依赖系统 Python
- Electron 打开时自动拉起引擎服务
- Electron 退出时自动回收引擎服务
- 失败时能给出明确诊断，而不是只显示泛化的 `engine_unavailable`

## 4. 候选方案比较

### 方案 A：继续依赖用户本机 Python

做法：

- Electron 不打包引擎
- 安装说明要求用户自行安装 Python 3.11+
- 用户手动运行 FastAPI 服务

优点：

- 实现成本最低
- 几乎不用改 Electron 代码

缺点：

- 普通用户不可接受
- 环境不一致风险极高
- 售后成本高
- 不满足真正的桌面版交付要求

结论：

- 只适合内部开发，不适合发行版

### 方案 B：随包分发嵌入式 Python + 代码目录

做法：

- 打包 Python runtime
- 打包 `model-server/src/serving`
- 打包 `ukumog-engine`
- 打包依赖环境或启动时在本地构建 venv

优点：

- 复用当前 FastAPI 服务形态
- 和现有代码结构最接近

缺点：

- 打包体积较大
- 安装和升级复杂
- Windows 权限、路径、杀软误报风险更高
- 启动脚本和依赖布局更脆弱

结论：

- 可行，但不是首选

### 方案 C：把 Python 引擎服务打成独立二进制

做法：

- 用 PyInstaller / Nuitka 等方式把当前服务入口打成单独可执行文件
- Electron 把该可执行文件作为 `extraResources` 一起带上
- Electron 主进程启动该二进制，再启动 Node

优点：

- 不依赖系统 Python
- 发行版路径更清晰
- 资产边界清楚，便于版本化
- Electron 只需要管理“两个本地进程”

缺点：

- 需要新增打包流水线
- 需要处理签名、体积和 Windows 安全软件问题

结论：

- **这是当前最推荐的发行版方案**

### 方案 D：Electron 直连远端托管引擎服务

做法：

- 桌面版不带本地 Python
- 所有 AI 请求发往远端服务

优点：

- 客户端最轻
- 后端统一升级简单

缺点：

- 离线不可用
- 网络依赖更强
- 与当前本地同源代理架构分叉
- 鉴权、跨域、发现、容灾都会复杂化

结论：

- 适合未来托管版，不适合作为当前桌面发行版首发方案

## 5. 推荐路线

推荐采用两阶段策略。

### 第一阶段：开发版继续外部 Python

目标：

- 不阻塞当前功能开发
- 保持桌面调试路径可用

执行：

- 继续要求开发者手动起 `model-server`
- `npm run desktop` 只负责 Electron + Node
- 文档明确这不是发行版行为

### 第二阶段：发行版切到独立引擎服务二进制

目标：

- 让桌面版具备完整 AI 能力交付条件

执行：

1. 为 `model-server` 增加一个可打包的服务入口
2. 生成 `ukumog-engine-service.exe`
3. Electron 打包时把它放进 `resources/engine/`
4. `electron/main.cjs` 启动顺序改成：
   - 先拉起 engine service
   - 等待 `http://127.0.0.1:<engine-port>/health` 成功
   - 再拉起 `server.cjs`
   - 再创建窗口
5. Node 服务通过环境变量拿到真正的 `ENGINE_SERVICE_ORIGIN`
6. 退出时统一回收两个子进程

## 6. 具体改造点

### 打包资产

需要新增：

- 引擎服务可执行产物
- 可能的模型/配置资源
- Electron `extraResources` 对应条目

### Electron 主进程

`electron/main.cjs` 需要新增：

- `engineProcess`
- `startEngineService()`
- `stopEngineService()`
- `waitForHealth(url, timeoutMs)`
- 更明确的启动失败提示

### Node 服务

`server.mjs` 不需要重新实现搜索逻辑，只需要继续接受：

- `ENGINE_SERVICE_ORIGIN`

推荐由 Electron 主进程显式传入，而不是继续依赖硬编码默认值。

### 构建流水线

需要新增一条桌面专用构建链路，例如：

1. 构建前端与 Node bundle
2. 构建 engine service binary
3. 把两类产物一起交给 `electron-builder`

## 7. 启动与关闭时序建议

推荐时序：

1. Electron 主进程启动
2. 启动 engine service
3. 轮询 `/health`
4. 健康通过后启动 `server.cjs`
5. 打开窗口

关闭时序：

1. 先关闭窗口
2. 停止 Node 服务
3. 停止 engine service
4. 清理临时资源

如果 engine service 启动失败：

- 不要假装应用正常
- 应弹出明确错误，说明是本地引擎服务未启动成功

## 8. 验收标准

Electron 交付路线至少要满足：

- 桌面发行版不依赖系统 Python
- 启动后 engine-room 可直接使用 AI
- review 分析可直接使用 AI
- 本地两个服务进程可被主进程正确拉起和回收
- 启动失败时有明确报错
- 不需要把旧 JS 引擎重新塞回 Electron 兜底

## 9. 现在就该怎么做

当前建议执行顺序：

1. 保持现状不改运行代码
2. 把这份路线文档作为桌面版基线
3. 真正开始做桌面版交付时，优先实现“独立引擎服务二进制 + 主进程健康检查拉起”

一句话总结：

**Electron 现在缺的不是前端页面，而是第二个本地进程的分发与编排；桌面版要交付，就要把 `ukumog-engine` 作为受控本地服务和 Node 一起交给 Electron 主进程管理。**
