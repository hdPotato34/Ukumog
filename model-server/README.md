# Ukumog Engine 服务接入说明

Last updated: `2026-04-21`

## 当前定位

`model-server/` 现在的主要职责不是训练流水线，而是给应用端提供一个可直接联调的 `ukumog-engine` HTTP 服务层。

当前应用端 AI 主链路已经收口为：

```text
React / RemoteEngineClient
  -> server.mjs (/api/engine/*)
    -> model-server FastAPI service
      -> ukumog-engine
```

这条链路已经是当前唯一主线。旧的本地 JS 搜索、opening book、worker 搜索逻辑不再是运行时主实现。

## 当前覆盖范围

已提供的能力：

- `GET /health`
- `POST /search`
- `POST /analyze`

当前明确限制：

- 支持 `9 / 11 / 13 / 15`
- 不提供 `/cancel`
- Python 服务层本身不做复杂会话管理
- Node 代理层负责同源转发、超时保护、单活请求策略和错误整形

## 目录说明

当前真正参与联调的目录主要是：

- `model-server/src/serving/`
  FastAPI 服务入口、schema、`ukumog-engine` 适配层
- `model-server/tests/`
  服务层与适配层测试
- `model-server/docs/`
  续接清单与接入路径说明

## 环境要求

- Python `3.11+`
- Node.js `20+`
- npm

`ukumog-engine/pyproject.toml` 当前正式要求是 `requires-python = ">=3.11"`，所以不要把 Python 3.10 当成受支持环境。

## 本地启动

以下步骤默认从仓库根目录 `C:\Fengru Cup\hd` 执行。

### 1. 安装 Node 依赖

```powershell
npm install
```

### 2. 创建并安装 Python 环境

```powershell
py -3.11 -m venv model-server\.venv
model-server\.venv\Scripts\python -m pip install --upgrade pip
model-server\.venv\Scripts\python -m pip install -r model-server\requirements-serving.txt
model-server\.venv\Scripts\python -m pip install -e .\ukumog-engine
```

如果本机没有 `py -3.11`，可以改用你已经安装好的 Python 3.11 可执行文件。

### 3. 启动 Python 引擎服务

```powershell
model-server\.venv\Scripts\python -m uvicorn app:app --app-dir model-server/src/serving --host 127.0.0.1 --port 8011
```

默认服务地址：

```text
http://127.0.0.1:8011
```

### 4. 启动应用端 Node 服务

另开一个终端：

```powershell
npm run build:app
npm run server
```

默认应用地址：

```text
http://127.0.0.1:8787
```

## 端口与环境变量

### Python 服务

默认：

- Host: `127.0.0.1`
- Port: `8011`

### Node 服务

默认：

- `PORT=8787`
- `HOST=0.0.0.0`

### Node -> Python 代理配置

`server.mjs` 当前读取以下环境变量：

- `ENGINE_SERVICE_ORIGIN`
- `MODEL_SERVER_ORIGIN`
- `ENGINE_SERVICE_TIMEOUT_MS`

默认值分别是：

```text
ENGINE_SERVICE_ORIGIN=http://127.0.0.1:8011
ENGINE_SERVICE_TIMEOUT_MS=15000
```

示例：

```powershell
$env:ENGINE_SERVICE_ORIGIN="http://127.0.0.1:8011"
$env:ENGINE_SERVICE_TIMEOUT_MS="20000"
npm run server
```

## 联调自检

### 检查 Python 服务是否正常

```powershell
Invoke-RestMethod http://127.0.0.1:8011/health
```

期望返回字段包括：

- `ok`
- `backend`
- `engineVersion`
- `pythonVersion`

### 检查 Node 代理是否正常

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/engine/health
```

### 检查应用侧回归

```powershell
npm run test:engine-preflight
npm run test:engine-smoke
npm run test:rules-compare
```

其中 `npm run test:engine-preflight` 会串行执行当前发布前的标准检查：

- `npm run build:app`
- `npm run test:rules-compare`
- `npm run test:engine-contract`
- `npm run test:engine-smoke`
- `npm run test:review-smoke`

## 测试

Python 服务层测试：

```powershell
model-server\.venv\Scripts\python -m unittest discover -s model-server/tests -p "test_*.py"
```

当前测试覆盖：

- FastAPI `/health` `/search` `/analyze`
- 请求校验和标准错误码
- `ukumog-engine` 适配层的局面转换与搜索结果标准化

应用侧联调回归：

- `npm run test:engine-preflight`
- `npm run test:engine-contract`
- `npm run test:engine-smoke`
- `npm run test:rules-compare`

其中：

- `test:engine-preflight` 是当前仓库的统一发布前检查入口，也已接入仓库级 CI
- `test:engine-contract` 会校验 `RemoteEngineClient -> Node -> Python` 的真实接口契约，并覆盖 opening center、必防、避毒手、双威胁等关键 spot check

## 常见故障

### `engine_unavailable`

表现：

- Node `/api/engine/*` 返回 `503`
- 前端提示引擎服务不可用

优先检查：

1. Python 服务是否已经启动在 `127.0.0.1:8011`
2. `ENGINE_SERVICE_ORIGIN` 是否指向正确地址
3. 本机防火墙或端口占用是否导致请求失败

### `engine_timeout`

表现：

- Node 代理返回 `504`
- 日志里可见 `code=engine_timeout`

优先检查：

1. Python 服务是否卡死或启动异常
2. `ENGINE_SERVICE_TIMEOUT_MS` 是否过小
3. 当前请求深度或时间预算是否不合理

### `unsupported_board_size`

表现：

- `POST /search` 或 `POST /analyze` 返回 `400`

原因：

- 当前远端引擎支持 `9 / 11 / 13 / 15`

说明：

- 这是当前产品限制，不是临时 bug

### Python 版本不对

表现：

- 安装 `ukumog-engine` 失败
- 运行时出现不受支持的 Python 版本问题

处理：

- 切到 Python `3.11+`
- 重新创建 `model-server/.venv`

## Docker 与交付范围

当前仓库里的远端引擎链路已经可本地联调，但以下部分还没有收口成完整交付说明：

- Linux x86_64 Docker 服务器发布方案
- Electron 发行版如何携带或拉起 Python 服务
- `/cancel` 风格的跨层取消协议

所以当前推荐定位是：

- Web/本地开发联调：已可用
- 生产级部署编排：仍需单独补文档
- Electron 打包分发：仍需单列方案

## 相关文档

- `model-server/docs/UKUMOG_ENGINE_BACKEND_INTEGRATION_PATH.md`
- `model-server/docs/UKUMOG_ENGINE_BACKEND_TASK_LIST.md`
- `model-server/docs/ELECTRON_ENGINE_DELIVERY_PLAN.md`
